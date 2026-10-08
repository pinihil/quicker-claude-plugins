#!/usr/bin/env python3
"""
Pre-release checks for the plugins in this marketplace - the directory's blocking rules plus our own.

Usage:
    python3 tools/check_plugin.py                       # check everything
    python3 tools/check_plugin.py --base origin/main    # also require a version bump when a plugin changed
    python3 tools/check_plugin.py --allow-placeholders  # local work before the real URLs are filled in

Exit code 0 = OK, 1 = at least one error. Warnings never fail the run.
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ttf", ".otf", ".woff", ".woff2"}
FORBIDDEN_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", "__MACOSX", "__pycache__", "node_modules"}
# Quicker-internal code that must never reach the public repository
PRIVATE_FILES = {"word-image-plugin.cjs", "word-image-plugin.js", "word-loop-plugin.js", "word-expressions.js"}
MAX_FILE = 256 * 1024
MAX_FILES = 512

errors, warnings = [], []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        err(f"{rel(path)}: missing")
    except json.JSONDecodeError as e:
        err(f"{rel(path)}: invalid JSON - {e}")
    return None


def rel(path):
    return os.path.relpath(path, ROOT)


def one_script(text):
    """True when the text uses a single writing system (Latin or Hebrew), ignoring digits/punctuation."""
    latin = bool(re.search(r"[A-Za-z]", text))
    hebrew = bool(re.search(r"[֐-׿]", text))
    other = bool(re.search(r"[^\x00-\x7F֐-׿]", text))
    return not (latin and hebrew) and not other


def readme_words(path):
    text = open(path, encoding="utf-8").read()
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    return len(re.findall(r"\w+", text))


def frontmatter(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    if not m:
        return None
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip() and not line.startswith(" "):
            out[k.strip()] = v.strip()
    return out


def git_show(ref, path):
    try:
        return subprocess.run(["git", "-C", ROOT, "show", f"{ref}:{path}"], capture_output=True,
                              text=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None


def changed_files(ref):
    try:
        out = subprocess.run(["git", "-C", ROOT, "diff", "--name-only", f"{ref}...HEAD"], capture_output=True,
                             text=True, check=True).stdout
        return [x for x in out.splitlines() if x]
    except subprocess.CalledProcessError as e:
        err(f"git diff against {ref} failed: {e.stderr.strip()}")
        return []


def plugin_files(pdir):
    try:
        out = subprocess.run(["git", "-C", pdir, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "."],
                             capture_output=True, text=True, check=True).stdout
        return [os.path.join(pdir, x) for x in out.split("\0") if x and os.path.exists(os.path.join(pdir, x))]
    except (subprocess.CalledProcessError, FileNotFoundError):
        found = []
        for dirpath, _, filenames in os.walk(pdir):
            found += [os.path.join(dirpath, fn) for fn in filenames]
        return found


def check_plugin(entry, args):
    name = entry.get("name", "")
    src = entry.get("source")
    if not isinstance(src, str) or not src.startswith("./") or ".." in src:
        err(f"marketplace entry {name!r}: source must be a relative path from the repo root without '..'")
        return
    pdir = os.path.normpath(os.path.join(ROOT, src))
    manifest = load_json(os.path.join(pdir, ".claude-plugin", "plugin.json"))
    if manifest is None:
        return

    # manifest
    pname = manifest.get("name", "")
    if not NAME_RE.match(pname):
        err(f"{rel(pdir)}: plugin name {pname!r} must be lowercase letters, digits and hyphens (max 64)")
    if pname != name:
        err(f"marketplace entry name {name!r} differs from plugin.json name {pname!r}")
    version = manifest.get("version", "")
    if not SEMVER_RE.match(str(version)):
        err(f"{rel(pdir)}: version {version!r} is not x.y.z - every release must bump it")
    for key in ("description", "author", "version"):
        if not manifest.get(key):
            warn(f"{rel(pdir)}: plugin.json has no {key}")
    for label, value in (("displayName", manifest.get("displayName", "")),
                         ("author.name", (manifest.get("author") or {}).get("name", ""))):
        if value and not one_script(value):
            err(f"{rel(pdir)}: {label} {value!r} mixes writing systems - the directory blocks it")

    # changelog entry for this version
    cl = os.path.join(pdir, "CHANGELOG.md")
    if not os.path.exists(cl):
        warn(f"{rel(pdir)}: no CHANGELOG.md")
    elif not re.search(rf"^##\s+{re.escape(str(version))}\b", open(cl, encoding="utf-8").read(), flags=re.M):
        err(f"{rel(cl)}: no '## {version}' section - describe the release before publishing it")

    # README / LICENSE
    readme = os.path.join(pdir, "README.md")
    if not os.path.exists(readme):
        err(f"{rel(pdir)}: README.md missing")
    elif readme_words(readme) < 40:
        err(f"{rel(readme)}: shorter than 40 words outside code blocks")
    if not os.path.exists(os.path.join(pdir, "LICENSE")) and not manifest.get("license"):
        err(f"{rel(pdir)}: no LICENSE file and no license in plugin.json")

    # .mcp.json
    mcp_path = os.path.join(pdir, ".mcp.json")
    if os.path.exists(mcp_path):
        mcp = load_json(mcp_path) or {}
        for sname, s in (mcp.get("mcpServers") or {}).items():
            url = s.get("url", "")
            if s.get("type") not in ("http", "sse", "ws"):
                err(f"{rel(mcp_path)}: server {sname!r} needs type http/sse/ws")
            if url and not re.match(r"^(https|wss)://", url):
                err(f"{rel(mcp_path)}: server {sname!r} url must be https:// or wss://")
            if s.get("headers"):
                warn(f"{rel(mcp_path)}: server {sname!r} has headers - never commit credentials")

    # skills
    sdir = os.path.join(pdir, "skills")
    for sk in sorted(os.listdir(sdir)) if os.path.isdir(sdir) else []:
        smd = os.path.join(sdir, sk, "SKILL.md")
        if not os.path.exists(smd):
            err(f"{rel(os.path.join(sdir, sk))}: no SKILL.md")
            continue
        fm = frontmatter(smd)
        if not fm:
            err(f"{rel(smd)}: no YAML front matter")
            continue
        if fm.get("name") != sk:
            err(f"{rel(smd)}: name {fm.get('name')!r} must match its folder {sk!r}")
        if not fm.get("description"):
            err(f"{rel(smd)}: description missing")
        elif len(fm["description"]) > 1024:
            err(f"{rel(smd)}: description longer than 1024 characters")
        if "<this skill dir>" in open(smd, encoding="utf-8").read():
            err(f"{rel(smd)}: use ${{CLAUDE_SKILL_DIR}} for script paths")

    # files (what git would commit: tracked + untracked-not-ignored; plain walk outside a git checkout)
    if os.path.isdir(os.path.join(pdir, "bin")):
        err(f"{rel(pdir)}: a top-level bin/ stops claude.ai and Cowork from installing the plugin")
    files = plugin_files(pdir)
    for fp in files:
        fn = os.path.basename(fp)
        parts = set(os.path.relpath(fp, pdir).split(os.sep))
        if parts & FORBIDDEN_NAMES or fn.endswith(".pyc"):
            err(f"{rel(fp)}: must not be committed")
        if fn in PRIVATE_FILES:
            err(f"{rel(fp)}: Quicker-internal code - keep it out of the public repository")
        if fn in ("package-lock.json", "npm-shrinkwrap.json", "bun.lock", "bun.lockb") and os.path.dirname(fp) == pdir:
            warn(f"{rel(fp)}: a lockfile at the plugin root triggers an install and a reviewer hold")
        if os.path.islink(fp):
            err(f"{rel(fp)}: symbolic links are not allowed")
        ext = os.path.splitext(fn)[1].lower()
        if ext not in IMAGE_EXT and os.path.getsize(fp) > MAX_FILE:
            warn(f"{rel(fp)}: over 256 KiB - the directory holds it for a reviewer")
        if not args.allow_placeholders and ext in (".json", ".md", ".sh", ".py", ".mjs") and \
                "REPLACE_ME" in open(fp, encoding="utf-8", errors="ignore").read():
            err(f"{rel(fp)}: still has a REPLACE_ME placeholder")
    if len(files) > MAX_FILES:
        warn(f"{rel(pdir)}: {len(files)} files - over 512 is held for a reviewer")

    # version bump
    if args.base:
        prefix = os.path.relpath(pdir, ROOT).replace(os.sep, "/") + "/"
        touched = [f for f in changed_files(args.base) if f.startswith(prefix)]
        if touched:
            old = git_show(args.base, prefix + ".claude-plugin/plugin.json")
            old_version = json.loads(old).get("version") if old else None
            if old_version == version:
                err(f"{name}: {len(touched)} file(s) changed but version is still {version} - customers "
                    f"won't receive the update. Bump version in plugin.json and add a CHANGELOG section.")
            else:
                print(f"{name}: version {old_version} -> {version} ({len(touched)} file(s) changed)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="git ref to compare with (e.g. origin/main) for the version-bump check")
    ap.add_argument("--allow-placeholders", action="store_true", help="don't fail on REPLACE_ME placeholders")
    args = ap.parse_args()

    mp_path = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
    mp = load_json(mp_path)
    if mp:
        if not NAME_RE.match(mp.get("name", "")):
            err(f"{rel(mp_path)}: marketplace name must be lowercase letters, digits and hyphens")
        if not (mp.get("owner") or {}).get("name"):
            err(f"{rel(mp_path)}: owner.name is required")
        names = [p.get("name") for p in mp.get("plugins", [])]
        if len(names) != len(set(names)):
            err(f"{rel(mp_path)}: duplicate plugin names")
        for entry in mp.get("plugins", []):
            check_plugin(entry, args)

    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("ERROR:", e)
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
