// Render a Quicker easy-template-x template with sample data the way Quicker does, and report problems.
//
// Usage: node render_check.mjs <template.docx> <data.json> <out.docx>
// Exit codes: 0 = rendered, 2 = engine error (template is broken), 3 = rendered but tags left over
//
// Mirrors Quicker's word.js: angular-expressions resolver, the Quicker filter set (units as documented
// by the product owner), delimiters { } # / with tag options [% %] (v8 branch), maxXmlDepth 1000,
// curly quotes normalised, and - on engine 7+ - Quicker's own image plugins (word-image-plugin.cjs) when
// that file sits next to this script. The public plugin does not ship it: without it, multi-image values
// and grids render their first image through the stock image plugin (tag syntax is checked, layout is not).
// Resolver: v3 uses easy-template-x-angular-expressions 0.1.0 (as production); v8 uses angular-expressions
// 1.5.2 directly (as the v8 branch). Both emulate Quicker's image-loop fix: inside a loop over an image
// field `{image}` is the current image, and a loop over a single-image field (an object) runs once.
// Differences from production, by design:
//   * a tag whose expression fails makes the render FAIL here (production prints it empty) - stricter;
//   * Quicker's html plugin is not bundled: `| html` renders as plain text;
//   * on engine v3 a multi-image value renders its first image only (Quicker's v3 code is not bundled).
import fs from 'fs';
import path from 'path';
import { createRequire } from 'module';
import JSZip from 'jszip';
import { TemplateHandler, ScopeData } from 'easy-template-x';

const require = createRequire(import.meta.url);
const HERE = path.dirname(new URL(import.meta.url).pathname);
const [, , tplPath, dataPath, outPath] = process.argv;
if (!tplPath || !dataPath || !outPath) {
  console.error('usage: node render_check.mjs <template.docx> <data.json> <out.docx>');
  process.exit(1);
}

let engineVersion = 'unknown';
try {
  engineVersion = JSON.parse(fs.readFileSync(path.join(HERE, 'node_modules', 'easy-template-x', 'package.json'), 'utf8')).version;
} catch (e) { /* ignore */ }
const ENGINE_MAJOR = parseInt(engineVersion, 10) || 0;

// ---------------- data -----------------
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
const baseDir = path.dirname(path.resolve(dataPath));
// Quicker's loop plugin gives every item of a loop _idx (from 0), _isFirst and _isLast - emulated here for
// every array of plain objects (form groups, customers), unless the data already carries them.
function hydrate(node) {
  if (Array.isArray(node)) {
    const out = node.map(hydrate);
    out.forEach((it, i) => {
      if (it && typeof it === 'object' && !Array.isArray(it) && it._type !== 'image' && !Buffer.isBuffer(it)) {
        if (it._idx === undefined) it._idx = i;
        if (it._isFirst === undefined) it._isFirst = i === 0;
        if (it._isLast === undefined) it._isLast = i === out.length - 1;
      }
    });
    return out;
  }
  if (node && typeof node === 'object') {
    if (node._type === 'image' && node.path) {
      const p = path.isAbsolute(node.path) ? node.path : path.join(baseDir, node.path);
      return { _type: 'image', source: fs.readFileSync(p), format: 'image/png',
               width: node.width || 590, height: node.height || 435 };
    }
    for (const k of Object.keys(node)) node[k] = hydrate(node[k]);
  }
  return node;
}
hydrate(data);
if (data.p) { data.project = data.p; if (data.p.ad) data.p.additionalDetails = data.p.ad; }

// ---------------- Quicker filters (word.js) -----------------
const pad = n => String(n).padStart(2, '0');
// Dates are stored as ISO timestamps (UTC). Quicker formats them with moment; we render them in Israel
// time (assumption - see quicker-contract.md open points) so a value saved as Israeli midnight
// ("2026-03-14T22:00:00.000Z") prints as 15/03/2026.
const IL = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Jerusalem', year: 'numeric', month: '2-digit',
  day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
function parseDate(v) {
  if (v instanceof Date) return v;
  const s = String(v).trim();
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/.test(s)) {
    const d = new Date(s);
    if (isNaN(d)) return null;
    const parts = Object.fromEntries(IL.formatToParts(d).map(x => [x.type, x.value]));
    return new Date(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute);
  }
  let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?/);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0));
  m = s.match(/^(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?:\s+(\d{1,2}):(\d{2}))?$/);
  if (m) return new Date(+m[3], +m[2] - 1, +m[1], +(m[4] || 0), +(m[5] || 0));
  return null;
}
function fmtDate(v, fmt = 'DD/MM/YYYY') {
  if (v === undefined || v === null || v === '') return '';
  const d = parseDate(v);
  if (!d || isNaN(d)) return String(v);                     // not a date -> printed as is
  const tok = { YYYY: d.getFullYear(), YY: String(d.getFullYear()).slice(-2), MM: pad(d.getMonth() + 1),
                M: d.getMonth() + 1, DD: pad(d.getDate()), D: d.getDate(), HH: pad(d.getHours()), mm: pad(d.getMinutes()) };
  return String(fmt).replace(/YYYY|YY|MM|M|DD|D|HH|mm/g, t => tok[t]);
}
const empty = v => v === undefined || v === null || v === '' ||
  (Array.isArray(v) && v.length === 0) ||
  (typeof v === 'object' && !Array.isArray(v) && !Buffer.isBuffer(v) && Object.keys(v).length === 0);

// images: maxSize (px, shrink only, keeps ratio) -> frame/rounded/gap/align -> grid (last)
const scaleImg = (img, w, h) => {
  if (!img || img._type !== 'image') return img;
  w = Number(w) || img.width; h = Number(h) || img.height;
  const r = Math.min(w / img.width, h / img.height, 1);
  return { ...img, width: Math.round(img.width * r), height: Math.round(img.height * r) };
};
const imgsOf = v => Array.isArray(v) ? v : (v && Array.isArray(v._images) ? v._images : (v && v._type === 'image' ? [v] : []));
const eachImg = (v, fn) => {
  if (Array.isArray(v)) return v.map(fn);
  if (v && Array.isArray(v._images)) return { ...v, _images: v._images.map(fn) };
  return v && v._type === 'image' ? fn(v) : v;
};
const lenEmu = (x, defUnit) => {            // '1.5pt' | '2px' | 1.5 (defUnit) -> EMU
  const m = String(x ?? '').trim().match(/^(-?\d+(?:\.\d+)?)\s*(pt|px)?$/i);
  if (!m) return null;
  const n = parseFloat(m[1]); const u = (m[2] || defUnit).toLowerCase();
  return Math.round(n * (u === 'pt' ? 12700 : 9525));
};
const hex6 = c => {
  const s = String(c || '000000').replace('#', '');
  return /^[0-9a-f]{3}$/i.test(s) ? s.split('').map(ch => ch + ch).join('') : (/^[0-9a-f]{6}$/i.test(s) ? s : '000000');
};
const ALIGN = { right: 'right', center: 'center', left: 'left', justify: 'both', 'ימין': 'right', 'אמצע': 'center', 'שמאל': 'left' };
const v3Images = v => {                                      // v3 harness: first image only
  if (Array.isArray(v)) return v[0];
  if (v && Array.isArray(v._images)) return v._images[0];
  return v;
};
// multi-image values / grids need Quicker's image plugin (engine 7+); otherwise first image only
const fullImages = () => ENGINE_MAJOR >= 7 && quickerImages;
const imageFilters = {
  maxSize: (v, w, h) => {
    const out = Array.isArray(v) ? { _type: 'image', _images: v.map(x => scaleImg(x, w, h)) } : eachImg(v, x => scaleImg(x, w, h));
    return fullImages() ? out : v3Images(out);
  },
  frame: (v, width, color) => eachImg(v, x => ({ ...x, border: { width: lenEmu(width ?? 1, 'pt') || 12700, color: hex6(color) } })),
  rounded: (v, p) => eachImg(v, x => ({ ...x, rounded: Math.min(50000, Math.max(0, (p === undefined ? 10 : Number(p)) * 1000)) })),
  gap: (v, n) => eachImg(v, x => ({ ...x, gap: lenEmu(n ?? 8, 'px') ?? 76200 })),
  align: (v, a) => (v && typeof v === 'object' && !Array.isArray(v)) ? { ...v, align: ALIGN[String(a || 'center').trim()] || 'center' } : v,
  grid: (v, cols, width, color) => {
    if (!fullImages()) return v3Images(v);
    const border = width !== undefined ? { sz: Math.round(parseFloat(width) * 8) || 0, color: hex6(color) } : undefined;
    return { _type: 'imageGrid', _images: imgsOf(v), columns: Math.max(1, Math.min(12, Number(cols) || 3)), tableBorder: border };
  },
};
const LOOP_SEP = { comma: ', ', pipe: ' | ', dash: ' - ', space: ' ', semicolon: '; ', newline: '\n' };
const filters = {
  date: (v, f) => fmtDate(v, f),
  currency: v => empty(v) || isNaN(Number(v)) ? (empty(v) ? '' : String(v)) : Number(v).toLocaleString('en-US', { maximumFractionDigits: 3 }),
  fixed: v => empty(v) || isNaN(Number(v)) ? (empty(v) ? '' : String(v)) : Number(v).toFixed(2),
  list: (v, sep = ', ') => Array.isArray(v) ? v.filter(x => !empty(x)).join(sep) : (v ?? ''),
  includes: (v, x) => Array.isArray(v) ? v.includes(x) : (typeof v === 'string' ? v.includes(x) : false),
  isEmpty: v => empty(v),
  stripTag: v => String(v ?? '').replace(/<[^>]*>/g, ''),
  html: v => String(v ?? '').replace(/<\/(p|div|li|h\d)>/gi, '\n').replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]*>/g, '').trim(),
  lower: v => String(v ?? '').toLowerCase(),
  inc: (v, n) => (isNaN(Number(v)) ? v : Number(v) + (n === undefined ? 1 : Number(n))),
  // {_idx | loopSep:'comma'} -> the separator before every item except the first (_idx counts from 0)
  loopSep: (v, kind = 'comma') => (Number(v) > 0 ? (LOOP_SEP[kind] ?? String(kind)) : ''),
  ...imageFilters,
};

// ---------------- handler -----------------
const plugins = [];
let quickerImages = false;
if (ENGINE_MAJOR >= 7) {
  try {
    const qip = require(path.join(HERE, 'word-image-plugin.cjs'));
    const etx = await import('easy-template-x');
    const base = etx.createDefaultPlugins().filter(p => !(p instanceof etx.ImagePlugin));
    plugins.push(...base, new qip.StyledImagePlugin(), new qip.ImageGridPlugin());
    quickerImages = true;
  } catch (e) { /* plugin file not present - stock image plugin */ }
}
const isImg = v => v && typeof v === 'object' && v._type === 'image';
const normQuotes = x => x.replace(/[‘’]/g, "'").replace(/[“”]/g, '"');
const SIMPLE_PATH = /^\s*([A-Za-z_]\w*|\[("[^"]+"|'[^']+'|\d+)\])(\.[A-Za-z_]\w*|\[("[^"]+"|'[^']+'|\d+)\])*\s*$/;
const getPath = (obj, p) => String(p).replace(/\[(\d+)\]/g, '.$1').split('.').filter(Boolean)
  .reduce((o, k) => (o == null ? undefined : o[k]), obj);
// Values traversed along the scope path (loop collections and their current items), innermost last.
function scopeChain(args) {
  const chain = [];
  let cur = args.data;
  for (const part of args.path.slice(0, -1)) {
    const key = typeof part === 'number' ? part : part.name;
    if (typeof key !== 'number' && !SIMPLE_PATH.test(key)) continue;
    cur = getPath(cur, key);
    chain.push(cur);
    if (!cur || typeof cur !== 'object') break;
  }
  return chain;
}
let baseResolver;
if (ENGINE_MAJOR >= 7) {
  // port of easy-template-x-angular-expressions' AngularResolver on top of angular-expressions 1.5.2
  const expressions = require('angular-expressions');
  for (const k of Object.keys(filters)) expressions.filters[k] = filters[k];
  const simple = SIMPLE_PATH;
  const getProp = getPath;
  const cache = new Map();
  baseResolver = (args) => {
    if (!args.path.length) return ScopeData.defaultResolver(args);
    const lastPart = args.path[args.path.length - 1];
    if (typeof lastPart === 'number') return ScopeData.defaultResolver(args);
    const exp = normQuotes((lastPart?.name || '').trim());
    const scope = Object.assign({}, args.data);
    let cur = scope;
    for (const part of args.path) {
      const key = typeof part === 'number' ? part : part.name;
      if (typeof key !== 'number' && !simple.test(key)) continue;
      cur = getProp(cur, key);
      if (!cur || typeof cur !== 'object') break;
      Object.assign(scope, cur);
    }
    let fn = cache.get(exp);
    if (!fn) { fn = expressions.compile(exp); cache.set(exp, fn); }
    return fn(scope);
  };
} else {
  const { createResolver } = await import('easy-template-x-angular-expressions');
  baseResolver = createResolver({ angularFilters: filters });
}
const resolver = (args) => {
  const last = args.path && args.path[args.path.length - 1];
  if (last && typeof last === 'object' && typeof last.name === 'string') last.name = normQuotes(last.name);
  // Quicker fix (word-expressions.js): inside a loop whose item is an image, {image} is that image
  if (last && typeof last === 'object' && /^\s*image\b/.test(last.name || '')) {
    const item = scopeChain(args).reverse().find(isImg);
    if (item) {
      const expressions = require('angular-expressions');
      for (const k of Object.keys(filters)) expressions.filters[k] = filters[k];
      return expressions.compile(last.name.trim())({ ...args.data, image: item });
    }
  }
  const val = baseResolver(args);
  // Quicker fix (word-loop-plugin.js): a loop over a single-image field runs as a one-item list
  if (last && typeof last === 'object' && last.disposition === 'Open' && isImg(val)) return [val];
  return val;
};
const opts = { scopeDataResolver: resolver, maxXmlDepth: 1000 };
if (ENGINE_MAJOR >= 7) opts.delimiters = { tagOptionsStart: '[%', tagOptionsEnd: '%]' };
if (plugins.length) opts.plugins = plugins;
const handler = new TemplateHandler(opts);

const HINTS = {
  UnclosedTagError: 'An opening tag {#...} has no matching closing tag {/...} in the same scope.',
  UnopenedTagError: 'A closing tag {/...} has no matching opening tag - check nesting order.',
  MissingCloseDelimiterError: 'A "{" was opened but its "}" is missing (or split oddly across runs).',
  MissingStartDelimiterError: 'A "}" appears without a matching "{".',
  TagOptionsParseError: 'The text inside [% ... %] is not valid tag options.',
  ResolveError: 'The angular expression inside a tag is invalid. Production would print this tag EMPTY instead of failing.',
};

const tplBuf = fs.readFileSync(tplPath);
let out;
try {
  out = await handler.process(tplBuf, data);
} catch (e) {
  const name = e?.constructor?.name || 'Error';
  console.log(JSON.stringify({ ok: false, engine: engineVersion, error: name, message: e?.message, hint: HINTS[name] || '' }, null, 1));
  process.exit(2);
}
fs.writeFileSync(outPath, out);

// ---------------- post-checks -----------------
const zip = await JSZip.loadAsync(out);
const leftovers = [];
for (const name of Object.keys(zip.files)) {
  if (!/^word\/(document|header\d*|footer\d*)\.xml$/.test(name)) continue;
  const xml = await zip.file(name).async('string');
  for (const p of xml.split(/<\/w:p>/)) {
    const text = (p.match(/<w:t[^>]*>[^<]*<\/w:t>/g) || []).map(t => t.replace(/<[^>]+>/g, '')).join('');
    const m = text.match(/\{[^{}]{1,120}\}/g);
    if (m) leftovers.push({ part: name, tags: m.slice(0, 5), context: text.slice(0, 120) });
  }
  for (const t of xml.matchAll(/<w:tbl>[\s\S]*?<\/w:tbl>/g)) {
    if (!/<w:tr[ >]/.test(t[0])) leftovers.push({ part: name, tags: ['(table with no rows)'],
      context: 'a table lost all its rows - Word reports such a file as damaged. Wrap the table in a .length condition.' });
  }
  // values that rendered as JavaScript artefacts: an object/array printed as text, a failed number
  for (const p of xml.split(/<\/w:p>/)) {
    const text = (p.match(/<w:t[^>]*>[^<]*<\/w:t>/g) || []).map(t => t.replace(/<[^>]+>/g, '')).join('');
    const m = text.match(/\[object Object\]|\bundefined\b|\bNaN\b|\bInvalid date\b/);
    if (m) leftovers.push({ part: name, tags: [m[0]], context: 'a value printed as "' + m[0] + '" - wrong filter or a list/object printed as text: ' + text.slice(0, 100) });
  }
  for (const d of xml.matchAll(/<wp:docPr\b[^>]*\bdescr="([^"]*\{[^"]*\}[^"]*)"/g)) {
    leftovers.push({ part: name, tags: [d[1]], context: 'picture alt text (placeholder not processed - needs engine 7+)' });
  }
}
const result = { ok: leftovers.length === 0, engine: engineVersion, out: outPath, quickerImagePlugin: quickerImages,
                 notes: ['| html renders as plain text here (Quicker html plugin not bundled)'].concat(
                   ENGINE_MAJOR < 7 ? ['v3 harness: multi-image values render their first image only'] : [],
                   ENGINE_MAJOR >= 7 && !quickerImages ? ['Quicker image plugin not present: multi-image values and grids render their first image only'] : []),
                 leftovers };
console.log(JSON.stringify(result, null, 1));
process.exit(leftovers.length ? 3 : 0);
