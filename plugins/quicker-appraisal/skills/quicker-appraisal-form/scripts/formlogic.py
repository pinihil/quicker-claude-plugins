#!/usr/bin/env python3
"""
Display-condition logic of a Quicker appraisal form.

- Reads a field's `if` the way the browser does: a string is an Angular expression over
  `project.additionalDetails` (the grammar the server allows - see form-template-conditions.js); a
  structured `{logic, conditions}` follows the client's condition-evaluator.js. Fields that are not
  under test are UNKNOWN (three-valued logic), so "shown when the gate is X" is only claimed when it
  holds whatever the other fields say.
- Finds "gates": choice questions whose answers include "no" / "not checked" (or a checkbox), and
  the details that hang on them.
- Audits a form for the mistakes that make a form feel unprofessional: a detail shown for every
  answer (the antiquities map shown when the property was never checked), a condition that compares
  to an option that doesn't exist, a negated condition that shows details before anyone answered,
  a chain that reopens when its gate changes, a gate hidden for good.

Used by audit_form.py and check_ops.py. No Quicker code is copied here - the rules are re-stated.
"""
import re

from formlib import label_of, norm, options_of, org_list_of, section_keys, similarity, walk, _PREFIXES, _same_word, _stems


# =========================================================================== values
class _Unknown:
    def __repr__(self):
        return "UNKNOWN"


UNKNOWN = _Unknown()


class UDict(dict):
    """additionalDetails where a field that isn't set explicitly is UNKNOWN (not empty)."""
    def __missing__(self, key):
        return UNKNOWN


def truthy(v):
    if v is UNKNOWN:
        return UNKNOWN
    if v is None or v is False or v == "" or (isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0):
        return False
    return True                      # [] and {} are truthy in JavaScript


def js_string(v):
    if v is None:
        return ""
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, list):
        return ",".join(js_string(x) for x in v)
    return str(v)


def _num(v):
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if v is None:
        return float("nan")
    if isinstance(v, str):
        try:
            return float(v.strip()) if v.strip() else 0.0
        except ValueError:
            return float("nan")
    return float("nan")


def loose_eq(a, b):
    if a is UNKNOWN or b is UNKNOWN:
        return UNKNOWN
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        if isinstance(a, bool) and isinstance(b, bool):
            return a == b
        return _num(a) == _num(b)
    if isinstance(a, (int, float)) and isinstance(b, str) or isinstance(b, (int, float)) and isinstance(a, str):
        return _num(a) == _num(b)
    if isinstance(a, list) or isinstance(b, list):
        if isinstance(a, list) and isinstance(b, list):
            return a is b
        return js_string(a) == js_string(b)
    return a == b


def strict_eq(a, b):
    if a is UNKNOWN or b is UNKNOWN:
        return UNKNOWN
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    if type(a) is not type(b):
        return False
    return a == b if not isinstance(a, list) else a is b


def _not(v):
    t = truthy(v)
    return UNKNOWN if t is UNKNOWN else (not t)


# =========================================================================== parser
_TOKEN = re.compile(r"""
    \s*(?:
      (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
    | (?P<num>\d+(?:\.\d+)?)
    | (?P<id>[A-Za-z_$֐-׿][\w$֐-׿-]*)
    | (?P<op>===|!==|==|!=|<=|>=|&&|\|\||[-+*/%<>!?:.,()\[\]{}|])
    )""", re.X)


class CondError(ValueError):
    pass


def _tokens(src):
    pos, out = 0, []
    src = src or ""
    while pos < len(src):
        if src[pos:].strip() == "":
            break
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise CondError(f"cannot read the condition near: {src[pos:pos + 20]!r}")
        pos = m.end()
        if m.group("str") is not None:
            s = m.group("str")[1:-1]
            out.append(("str", re.sub(r"\\(.)", r"\1", s)))
        elif m.group("num") is not None:
            out.append(("num", float(m.group("num"))))
        elif m.group("id") is not None:
            out.append(("id", m.group("id")))
        else:
            out.append(("op", m.group("op")))
    out.append(("end", None))
    return out


_BIN = {"||": 1, "&&": 2, "==": 3, "!=": 3, "===": 3, "!==": 3, "<": 4, ">": 4, "<=": 4, ">=": 4,
        "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}


class _Parser:
    def __init__(self, src):
        self.t = _tokens(src)
        self.i = 0

    def peek(self, kind=None, val=None):
        k, v = self.t[self.i]
        return (kind is None or k == kind) and (val is None or v == val)

    def take(self, kind=None, val=None):
        k, v = self.t[self.i]
        if (kind and k != kind) or (val is not None and v != val):
            raise CondError(f"expected {val or kind}, found {v!r}")
        self.i += 1
        return v

    def parse(self):
        node = self.filters()
        if not self.peek("end"):
            raise CondError(f"unexpected {self.t[self.i][1]!r}")
        return node

    def filters(self):
        node = self.ternary()
        while self.peek("op", "|"):
            self.take()
            name = self.take("id")
            args = []
            while self.peek("op", ":"):
                self.take()
                args.append(self.ternary())
            node = ("filter", node, name, args)
        return node

    def ternary(self):
        cond = self.binary(1)
        if self.peek("op", "?"):
            self.take()
            a = self.ternary()
            self.take("op", ":")
            b = self.ternary()
            return ("cond", cond, a, b)
        return cond

    def binary(self, level):
        left = self.unary()
        while True:
            k, v = self.t[self.i]
            if k != "op" or v not in _BIN or _BIN[v] < level:
                return left
            self.i += 1
            right = self.binary(_BIN[v] + 1)
            left = ("bin", v, left, right)

    def unary(self):
        if self.peek("op", "!") or self.peek("op", "-") or self.peek("op", "+"):
            op = self.take()
            return ("un", op, self.unary())
        return self.postfix(self.primary())

    def primary(self):
        k, v = self.t[self.i]
        if k == "str" or k == "num":
            self.i += 1
            return ("lit", v)
        if k == "id":
            self.i += 1
            lits = {"true": True, "false": False, "null": None, "undefined": None}
            if v in lits:
                return ("lit", lits[v])
            return ("id", v)
        if self.peek("op", "("):
            self.take()
            node = self.filters()
            self.take("op", ")")
            return node
        if self.peek("op", "["):
            self.take()
            items = []
            while not self.peek("op", "]"):
                items.append(self.ternary())
                if self.peek("op", ","):
                    self.take()
            self.take("op", "]")
            return ("arr", items)
        if self.peek("op", "{"):
            self.take()
            items = {}
            while not self.peek("op", "}"):
                kk, kv = self.t[self.i]
                self.i += 1
                self.take("op", ":")
                items[kv] = self.ternary()
                if self.peek("op", ","):
                    self.take()
            self.take("op", "}")
            return ("obj", items)
        raise CondError(f"unexpected {v!r}")

    def postfix(self, node):
        while True:
            if self.peek("op", "."):
                self.take()
                name = self.take("id")
                if self.peek("op", "("):
                    self.take()
                    args = []
                    while not self.peek("op", ")"):
                        args.append(self.ternary())
                        if self.peek("op", ","):
                            self.take()
                    self.take("op", ")")
                    node = ("call", node, name, args)
                else:
                    node = ("mem", node, name)
            elif self.peek("op", "["):
                self.take()
                idx = self.ternary()
                self.take("op", "]")
                node = ("idx", node, idx)
            else:
                return node


_CACHE = {}


def parse(expr):
    if expr not in _CACHE:
        _CACHE[expr] = _Parser(expr).parse()
    return _CACHE[expr]


# =========================================================================== evaluator
def _get(obj, key):
    if obj is UNKNOWN:
        return UNKNOWN
    if obj is None:
        return None                                   # Angular: a member of undefined is undefined
    if isinstance(obj, dict):
        return obj[key] if (key in obj or isinstance(obj, UDict)) else None
    if isinstance(obj, (list, str)):
        if key == "length":
            return len(obj)
        if isinstance(key, (int, float)) and not isinstance(key, bool):
            i = int(key)
            return obj[i] if 0 <= i < len(obj) else None
    return None


def evaluate(node, scope):
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "id":
        name = node[1]
        if name in scope:
            return scope[name]
        return UNKNOWN if name in ("x", "y", "z") else None
    if kind == "arr":
        vals = [evaluate(n, scope) for n in node[1]]
        return UNKNOWN if any(v is UNKNOWN for v in vals) else vals
    if kind == "obj":
        return {k: evaluate(v, scope) for k, v in node[1].items()}
    if kind == "mem":
        return _get(evaluate(node[1], scope), node[2])
    if kind == "idx":
        obj, key = evaluate(node[1], scope), evaluate(node[2], scope)
        if key is UNKNOWN:
            return UNKNOWN
        return _get(obj, key)
    if kind == "call":
        obj = evaluate(node[1], scope)
        args = [evaluate(a, scope) for a in node[3]]
        if obj is UNKNOWN or any(a is UNKNOWN for a in args):
            return UNKNOWN
        if obj is None or not isinstance(obj, (list, str)) or not args:
            return None
        if node[2] == "includes":
            if isinstance(obj, str):
                return js_string(args[0]) in obj
            return any(strict_eq(x, args[0]) is True for x in obj)
        if node[2] == "indexOf":
            if isinstance(obj, str):
                return obj.find(js_string(args[0]))
            for i, x in enumerate(obj):
                if strict_eq(x, args[0]) is True:
                    return i
            return -1
        return None
    if kind == "un":
        v = evaluate(node[2], scope)
        if node[1] == "!":
            return _not(v)
        if v is UNKNOWN:
            return UNKNOWN
        n = _num(v)
        return -n if node[1] == "-" else n
    if kind == "bin":
        op = node[1]
        if op == "&&":
            a = evaluate(node[2], scope)
            ta = truthy(a)
            if ta is False:
                return a
            b = evaluate(node[3], scope)
            tb = truthy(b)
            if ta is True:
                return b
            return False if tb is False else UNKNOWN
        if op == "||":
            a = evaluate(node[2], scope)
            ta = truthy(a)
            if ta is True:
                return a
            b = evaluate(node[3], scope)
            tb = truthy(b)
            if ta is False:
                return b
            return True if tb is True else UNKNOWN
        a, b = evaluate(node[2], scope), evaluate(node[3], scope)
        if op in ("==", "!="):
            r = loose_eq(a, b)
            return r if op == "==" or r is UNKNOWN else not r
        if op in ("===", "!=="):
            r = strict_eq(a, b)
            return r if op == "===" or r is UNKNOWN else not r
        if a is UNKNOWN or b is UNKNOWN:
            return UNKNOWN
        if op in ("<", ">", "<=", ">="):
            if isinstance(a, str) and isinstance(b, str):
                x, y = a, b
            else:
                x, y = _num(a), _num(b)
            return {"<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
        if op == "+":
            if isinstance(a, str) or isinstance(b, str):
                return js_string(a) + js_string(b)
            return _num(a) + _num(b)
        x, y = _num(a), _num(b)
        try:
            return {"-": x - y, "*": x * y, "/": x / y, "%": x % y}[op]
        except ZeroDivisionError:
            return float("nan")
    if kind == "cond":
        t = truthy(evaluate(node[1], scope))
        if t is UNKNOWN:
            return UNKNOWN
        return evaluate(node[2] if t else node[3], scope)
    if kind == "filter":
        return UNKNOWN
    return UNKNOWN


def _single(c, model):
    val = model[c.get("field")] if isinstance(model, dict) else None
    cmp = c.get("value")
    op = c.get("operator")
    if val is UNKNOWN:
        return UNKNOWN
    if op == "equals":
        return loose_eq(val, cmp)
    if op == "notEquals":
        return not loose_eq(val, cmp)
    if op in ("greaterThan", "lessThan", "greaterOrEqual", "lessOrEqual"):
        x, y = _num(val), _num(cmp)
        return {"greaterThan": x > y, "lessThan": x < y, "greaterOrEqual": x >= y, "lessOrEqual": x <= y}[op]
    if op in ("contains", "notContains"):
        r = js_string(cmp) in js_string(val if truthy(val) else "")
        return r if op == "contains" else not r
    if op == "isEmpty":
        return val is None or val == "" or (isinstance(val, list) and not val)
    if op == "isNotEmpty":
        return not (val is None or val == "" or (isinstance(val, list) and not val))
    if op == "isTrue":
        return val is True
    if op == "isFalse":
        return not truthy(val) or val is False
    return True


def condition_value(cond, model, x=None, y=None):
    """True / False / UNKNOWN: is a field with this `if` shown, for additionalDetails `model`?"""
    if cond in (None, "", {}):
        return True
    if isinstance(cond, dict):
        conds = cond.get("conditions") or []
        if not conds:
            return True
        vals = [_single(c, model) for c in conds]
        if (cond.get("logic") or "and") == "and":
            if any(v is False for v in vals):
                return False
            return True if all(v is True for v in vals) else UNKNOWN
        if any(v is True for v in vals):
            return True
        return False if all(v is False for v in vals) else UNKNOWN
    try:
        node = parse(cond)
    except CondError:
        return UNKNOWN
    scope = {"project": {"additionalDetails": model}}
    if x is not None:
        scope["x"] = x
    if y is not None:
        scope["y"] = y
    return truthy(evaluate(node, scope))


def all_true(values):
    if any(v is False for v in values):
        return False
    return True if all(v is True for v in values) else UNKNOWN


# =========================================================================== reading conditions
_PATH = re.compile(r"project\s*\.\s*additionalDetails\s*(?:\.\s*([A-Za-z_$][\w$]*)|\[\s*['\"]([^'\"]+)['\"]\s*\])")


def reads(cond):
    """Top-level fields a condition reads."""
    if not cond:
        return set()
    if isinstance(cond, dict):
        return {c.get("field") for c in cond.get("conditions") or [] if isinstance(c, dict) and c.get("field")}
    return {a or b for a, b in _PATH.findall(str(cond))}


def _path_of(node):
    """'field' for project.additionalDetails.field (top-level), 'g.sub' for g[x].sub, else None."""
    parts = []
    while True:
        if node[0] == "mem":
            parts.append(node[2])
            node = node[1]
        elif node[0] == "idx":
            node = node[1]
        else:
            break
    if node == ("id", "project") and parts and parts[-1] == "additionalDetails" and len(parts) >= 2:
        return ".".join(reversed(parts[:-1]))
    return None


def value_tests(cond):
    """Comparisons of a field with literal values: [(path, value, kind)] - kind 'eq' | 'ne' | 'has'."""
    out = []
    if not cond:
        return out
    if isinstance(cond, dict):
        for c in cond.get("conditions") or []:
            op = c.get("operator")
            if op in ("equals", "notEquals", "contains", "notContains") and isinstance(c.get("value"), str):
                out.append((c.get("field"), c["value"], {"equals": "eq", "notEquals": "ne"}.get(op, "has")))
        return out
    try:
        root = parse(cond)
    except CondError:
        return out

    def visit(n):
        if not isinstance(n, tuple):
            return
        if n[0] == "bin" and n[1] in ("==", "===", "!=", "!=="):
            for a, b in ((n[2], n[3]), (n[3], n[2])):
                p = _path_of(a)
                if p and b[0] == "lit" and isinstance(b[1], str):
                    out.append((p, b[1], "eq" if n[1] in ("==", "===") else "ne"))
        if n[0] == "call" and n[2] in ("includes", "indexOf") and n[3]:
            p = _path_of(n[1])
            arg = n[3][0]
            if p and arg[0] == "lit" and isinstance(arg[1], str):
                out.append((p, arg[1], "has"))
            if n[1][0] == "arr":
                q = _path_of(arg)
                if q:
                    for item in n[1][1]:
                        if item[0] == "lit" and isinstance(item[1], str):
                            out.append((q, item[1], "eq"))
        for part in n[1:]:
            if isinstance(part, tuple):
                visit(part)
            elif isinstance(part, list):
                for p in part:
                    visit(p)
            elif isinstance(part, dict):
                for p in part.values():
                    visit(p)

    visit(root)
    return out


# =========================================================================== gates
def _words_re(words, prefix=r"(^|\s)", suffix=r"(\s|$)"):
    """A regex over norm()-ed text (final letters folded) for these words/phrases."""
    return re.compile(prefix + "(" + "|".join(re.escape(norm(w)) for w in words) + ")" + suffix)


_UNKNOWN_ANSWER = _words_re([f"{a} {b}" for a in ("לא", "טרם") for b in (
    "נבדק", "נבדקה", "נבדקו", "ידוע", "ידועה", "ידועים", "נמסר", "נמסרה", "הומצא", "הומצאה", "הוצג", "הוצגה",
    "אומת", "אומתה", "נמצא מידע")], suffix="")
_NEGATIVE_ANSWER = _words_re(["לא", "אין", "ללא", "אינו", "אינה", "אינם", "אינן", "לא קיים", "לא קיימת", "לא קיימים",
                              "לא רלוונטי"])


_QUALIFIED = _words_re(["אך", "אבל", "למעט", "פרט ל", "אולם", "חלקית"])


def classify(option):
    """'unknown' (לא נבדק / לא ידוע), 'negative' (לא / אין / אינו...), or 'positive'.
    A qualified negative ("אינו מוגדר כמבנה מסוכן, אך מבנה סמוך מוגדר") reports a finding: positive."""
    n = " " + norm(option) + " "
    if _UNKNOWN_ANSWER.search(n):
        return "unknown"
    if _NEGATIVE_ANSWER.search(n) and not _QUALIFIED.search(n):
        return "negative"
    return "positive"


CHOICE_TYPES = {"radio", "select", "selectOther", "checkbox", "checkboxList"}


def is_gate(node):
    t = node.get("type")
    if t == "checkbox":
        return True
    if t not in CHOICE_TYPES:
        return False
    kinds = {classify(o) for o in options_of(node)}
    return "positive" in kinds and bool(kinds & {"negative", "unknown"})


def positive_options(node):
    if node.get("type") == "checkbox":
        return [True]
    return [o for o in options_of(node) if classify(o) == "positive"]


def _lit(v):
    return "'" + v + "'" if "'" not in v else '"' + v + '"'


def cond_for(path_expr, node, opts):
    """A condition that opens on `opts` of the gate at `path_expr` (project.additionalDetails...)."""
    if node.get("type") == "checkbox":
        return f"{path_expr} === true"
    if node.get("type") == "checkboxList":
        return " || ".join(f"{path_expr}.includes({_lit(o)})" for o in opts)
    if len(opts) == 1:
        return f"{path_expr} == {_lit(opts[0])}"
    return f"[{', '.join(_lit(o) for o in opts)}].includes({path_expr})"


def expr_path(info):
    """project.additionalDetails path of a node, with x / y for the rows of its groups."""
    parts = info["path"].split(".")
    idx = ["x", "y", "z"]
    out = "project.additionalDetails"
    for i, p in enumerate(parts):
        out += f".{p}" if re.match(r"^[A-Za-z_$][\w$]*$", p) else f"[{_lit(p)}]"
        if i < len(parts) - 1:
            out += f"[{idx[i]}]"
    return out


# Words that say what a label is about. Generic words (a detail's kind, yes/no wording) are not topics.
_GENERIC_WORDS = {
    "האם", "קיים", "קיימת", "קיימים", "קיימות", "יש", "אין", "לא", "כן", "סטטוס", "מצב", "סוג", "סוגי",
    "פירוט", "פרטי", "פרט", "בקרבת", "קרבה", "בסביבה", "סביבה", "סביבת", "בתחום", "תחום", "אינו", "אינה",
    "נבדק", "בדיקה", "מבנה", "צילום", "צילומי", "מפה", "מפת", "תמונה", "תמונות", "מסמך", "מסמכים", "הערות",
    "הערה", "תיאור", "הסבר", "תאריך", "שטח", "מספר", "סכום", "שיעור", "השפעה", "השפעת", "על", "השווי",
    "שווי", "לנכס", "בנכס", "הנכס", "נכס", "אחר", "אחרים", "govmap", "גוש", "חלקה", "ככל", "שהוא",
    "שומה", "השומה", "שומת", "לשומה", "תקן", "דוח", "הדוח", "פרויקט", "הפרויקט", "נדרש", "לבנק", "הבנק", "בנק",
    "תיק", "התיק", "כללי", "כללית", "סיכום", "ממצאי", "נוספים", "נוספות",
}
TYPE_QUESTION = re.compile(r"^(" + "|".join(norm(w) for w in ("סוג", "סוגי", "מהות", "אופן", "שיטת", "צורת", "תרחיש")) + r")(\s|$)")
_GENERIC = {norm(w) for w in _GENERIC_WORDS}
DETAIL_WORDS = _words_re(["פירוט", "פרט", "פרטי", "הסבר", "תיאור", "מפה", "מפת", "צילום", "צילומי", "תמונה", "תמונות",
                          "תשריט", "מסמך", "אסמכתא", "תאריך", "מרחק", "השפעה", "השפעת", "היקף", "סכום", "צו",
                          "הכרזה", "מספר"])


def _bare(t):
    """A word and the word without one leading prefix letter(s) - no synonym folding."""
    return {t} | {t[len(p):] for p in _PREFIXES if t.startswith(p) and len(t) - len(p) >= 3}


def topic_words(text):
    return [t for t in norm(text).split() if len(t) >= 3 and not (_bare(t) & _GENERIC)]


def _topic_match(a, b):
    if _same_word(a, b):
        return True
    for x in _stems(a):
        for y in _stems(b):
            short, long_ = sorted((x, y), key=len)
            if len(short) >= 3 and long_.startswith(short) and len(long_) - len(short) <= 2:
                return True                           # אתר / אתרי, מסוכן / המסוכנים, חריגה / חריגות
            if len(x) == len(y) >= 4 and x[:-1] == y[:-1] and {x[-1], y[-1]} <= {"ה", "ת"}:
                return True                           # מפה / מפת, סביבה / סביבת (not בנייה / בניין)
    return False


def shares_topic(a_words, b_text):
    bw = topic_words(b_text)
    return [w for w in a_words if any(_topic_match(w, x) for x in bw)]


# =========================================================================== form helpers
def nodes_in_order(schema):
    """Top-level fields and groups of each section in reading order, with their row condition."""
    out = {}
    for info in walk(schema):
        if info["top"]:
            out.setdefault(info["section"], []).append(info)
    return out


def visibility_conds(info, index):
    """Every condition that must hold for a node to show: its card's, its groups', its own."""
    conds = []
    if info.get("row_if"):
        conds.append(info["row_if"])
    parent = info.get("parent")
    chain = []
    while parent:
        p = index.get(parent)
        if not p:
            break
        chain.append(p)
        parent = p.get("parent")
    for p in reversed(chain):
        if p.get("row_if"):
            conds.append(p["row_if"])
        if p["node"].get("if"):
            conds.append(p["node"]["if"])
    if info["node"].get("if"):
        conds.append(info["node"]["if"])
    return conds


def answers_of(node):
    if node.get("type") == "checkbox":
        return [True, False]
    return options_of(node)


def _model_for(gate_info, value):
    """additionalDetails where only the gate is known (= value); x = y = 0 for gates in groups."""
    parts = gate_info["path"].split(".")
    model = UDict()
    cur = model
    for p in parts[:-1]:
        row = UDict()
        cur[p] = [row]
        cur = row
    cur[parts[-1]] = value
    return model


def visible_for(info, index, gate_info, value):
    model = _model_for(gate_info, value)
    vals = [condition_value(c, model, x=0, y=0) for c in visibility_conds(info, index)]
    return all_true(vals)


def dependents(gate_info, infos, index):
    """Nodes whose visibility reads the gate (same group row for gates inside groups)."""
    out = []
    gkey, gparent = gate_info["key"], gate_info.get("parent")
    for info in infos:
        if info["path"] == gate_info["path"]:
            continue
        if gparent is None:
            if any(gkey in reads(c) for c in visibility_conds(info, index)):
                out.append(info)
        else:
            if not info["path"].startswith(gparent + "."):
                continue
            pat = re.compile(r"\]\s*\.\s*" + re.escape(gkey) + r"\b")
            if any(isinstance(c, str) and pat.search(c) for c in visibility_conds(info, index)):
                out.append(info)
    return out


def matrix(gate_info, infos, index):
    """{dependent path: {answer: True/False/UNKNOWN}} incl. answer None = not answered yet."""
    answers = answers_of(gate_info["node"]) + [None]
    out = {}
    for d in dependents(gate_info, infos, index):
        out[d["path"]] = {a: visible_for(d, index, gate_info, a) for a in answers}
    return out


EXTERNAL_CHECKS = _words_re(["עתיק", "זיהום", "מסוכן", "הפקע", "היטל השבחה", "חריג", "מתח", "אנטנ", "הריסה", "שימור",
                             "הערת אזהרה", "הערות אזהרה", "קרינה", "הצפה", "מטרד", "תמא", "פינוי", "עיקול", "שעבוד",
                             "משכנת", "רכבת", "תוואי", "תחבורה", "מתען", "הפקדה", "קו מתח"],
                            prefix=r"(^|\s|[והבלמשכ])", suffix="")
ABOUT_THE_CHECK = _words_re(["בדיקה", "בדיקת", "נבדק", "נבדקה", "מקור", "מקור המידע", "מועד הבדיקה"],
                            prefix=r"(^|\s|[והבלמשכ])", suffix="")
DETAIL_START = re.compile(r"^(" + "|".join(norm(w) for w in ("פירוט", "פרטי", "פרט")) + r")(\s|$)")
YES_NO_NEGATIVES = {norm(w) for w in ("לא", "אין", "ללא", "לא קיים", "לא קיימת", "לא קיימים", "לא קיימות",
                                     "לא נמצא", "לא נמצאו", "לא ידוע")}
NARRATIVE = _words_re(["תיאור", "פירוט", "סקירה", "ניתוח", "הסבר", "הסברים", "הערות", "הסתייגויות", "עקרונות",
                       "גורמים", "שיקולים", "מצב תכנוני", "מצב משפטי", "השפעה", "השפעת", "סקירת", "ניתוח", "תחשיב",
                       "דיון", "נימוקים", "הנחות",
                       "מסקנות"], prefix=r"(^|\s|[והבלמשכ])")


# =========================================================================== audit
def audit(form, only=None):
    """
    Findings: dicts {kind, level ('fix'|'check'|'advice'), path, gate?, message, suggest?}.
    `only` (a set of paths) limits findings to those nodes or gates (check_ops uses it for the plan).
    """
    schema = form["schema"]
    md = form.get("metadata") or {}
    infos = list(walk(schema))
    index = {i["path"]: i for i in infos}
    top = {i["key"]: i for i in infos if i["top"]}
    findings = []

    def add(kind, level, path, message, gate=None, suggest=None):
        if only is not None and path not in only and (gate is None or gate not in only):
            return
        f = {"kind": kind, "level": level, "path": path, "message": message}
        if gate:
            f["gate"] = gate
        if suggest:
            f["suggest"] = suggest
        findings.append(f)

    def lab(info):
        return label_of(info["node"]) or info["key"]

    # -- conditions that read missing or hidden fields, and values that aren't options
    for info in infos:
        if info["node"].get("hidden"):
            continue                                  # nobody sees it - its condition doesn't matter
        own = [info["node"].get("if")] if info["node"].get("if") else []
        if info["top"] and info.get("row_if"):
            own.append(info["row_if"])
        for cond in own:
            if info["top"] or isinstance(cond, dict):
                for f in sorted(reads(cond)):
                    if f not in top:
                        add("missing-field", "fix", info["path"],
                            f'התנאי של "{lab(info)}" קורא שדה שלא קיים בטופס ({f}) - הוא לא ייפתח לעולם')
                    elif top[f]["node"].get("hidden"):
                        add("hidden-gate", "fix", info["path"],
                            f'התנאי של "{lab(info)}" תלוי ב"{lab(top[f])}" שמוסתר בטופס - אי אפשר לשנות אותו, '
                            "והשדה נשאר תקוע במצב הנוכחי", gate=f)
            for path, value, how in value_tests(cond):
                g = index.get(path)
                if g is None:
                    continue
                gnode = g["node"]
                if gnode.get("type") not in CHOICE_TYPES or gnode.get("type") == "checkbox":
                    continue
                if org_list_of(g, md):
                    continue                        # the options live in the settings
                opts = options_of(gnode)
                if not opts or value in opts or norm(value) in {norm(o) for o in opts}:
                    continue
                if how == "has" and any(value in o for o in opts):
                    continue
                level = "check" if gnode.get("type") == "selectOther" else "fix"
                effect = {"eq": "התנאי לא יתקיים לעולם", "ne": "התנאי מתקיים תמיד",
                          "has": "התנאי לא יתקיים לעולם"}[how]
                best = max(opts, key=lambda o: (similarity(value, o), -abs(len(o) - len(value))))
                fixed = None
                if isinstance(cond, str) and similarity(value, best) >= 0.5 and cond is info["node"].get("if"):
                    fixed = cond.replace(_lit(value), _lit(best))
                add("dead-value", level, info["path"],
                    f'התנאי של "{lab(info)}" משווה את "{lab(g)}" ל-"{value}" - אין אפשרות כזו '
                    f'({" / ".join(opts)}). {effect}' + (f'. כנראה התכוונו ל-"{best}"' if fixed else ""),
                    gate=g["path"], suggest=fixed)

    # -- gates: what each answer shows, and details that ignore the gate
    by_section = nodes_in_order(schema)
    bound = {str(t).split("[")[0] for t in (md.get("projectFieldsMap") or {}).values() if isinstance(t, str)}
    group_rows = []                                  # (group info, [child infos in order])
    for info in infos:
        if info["kind"] == "group":
            kids = [i for i in infos if i.get("parent") == info["path"]]
            group_rows.append((info, kids))

    def scan(sequence, exclude_words=()):
        for pos, g in enumerate(sequence):
            gnode = g["node"]
            if g["kind"] != "field" or not is_gate(gnode) or gnode.get("hidden"):
                continue
            opts = positive_options(gnode)
            answers = answers_of(gnode)
            kinds = {classify(o) for o in options_of(gnode)}
            checked = [o for o in options_of(gnode) if classify(o) != "unknown"]
            open_cond = cond_for(expr_path(g), gnode, opts) if opts else None
            # "סוג ההלוואה: מכוונת / לא מכוונת" chooses a kind - the loan's other fields aren't its details
            kind_question = bool(TYPE_QUESTION.search(norm(lab(g))))
            gwords = [] if kind_question else topic_words(lab(g))
            if gnode.get("type") != "checkbox" and len(opts) == 1:
                gwords += topic_words(opts[0])      # one answer that reports the finding: its words count too
            gwords = [w for w in dict.fromkeys(gwords) if not any(_topic_match(w, x) for x in exclude_words)]
            g_conds = [c for c in visibility_conds(g, index)]
            deps = matrix(g, infos, index)

            # what each answer opens
            for dpath, row in deps.items():
                d = index[dpath]
                if d["node"].get("hidden"):
                    continue
                own = d["node"].get("if")
                replace = open_cond if (own and reads(own) <= {g["key"]} and g["parent"] is None) else None
                shown = [a for a, v in row.items() if v is True and a is not None]
                bad = [a for a in shown if isinstance(a, str) and classify(a) != "positive"]
                pos_shown = [a for a in shown if a is True or (isinstance(a, str) and classify(a) == "positive")]
                if replace and ABOUT_THE_CHECK.search(" " + norm(lab(d)) + " ") and kinds & {"unknown"}:
                    replace = cond_for(expr_path(g), gnode, checked)
                if row.get(None) is True and bad:
                    add("opens-unanswered", "fix", dpath,
                        f'"{lab(d)}" מוצג כבר כשהשאלה "{lab(g)}" עוד לא נענתה, וגם בתשובה "{bad[0]}". '
                        "תנאי בשלילה (!=) פותח פרטים לפני שמישהו ענה - עדיף תנאי על התשובות שפותחות אותם",
                        gate=g["path"], suggest=replace)
                    continue
                unk = [a for a in bad if classify(a) == "unknown"]
                if unk and pos_shown:
                    add("opens-unchecked", "fix", dpath,
                        f'"{lab(d)}" מוצג גם כש"{lab(g)}" = "{unk[0]}" - כשלא נבדק אין מה לפרט',
                        gate=g["path"], suggest=replace)
                if row and all(v is False for v in row.values()) and not any(
                        x["kind"] == "dead-value" and x["path"] == dpath for x in findings):
                    add("never-shown", "fix", dpath,
                        f'"{lab(d)}" לא מוצג באף תשובה של "{lab(g)}" - כנראה ערך שגוי בתנאי', gate=g["path"])

            # details near the gate that ignore it (after it; a shared topic also a little before it)
            window = []
            for k, c in enumerate(sequence[pos + 1:pos + 7]):
                if c["kind"] == "field" and is_gate(c["node"]) and not c["node"].get("hidden"):
                    break                           # the next question starts its own details
                window.append((k, c, "after"))
            window += [(k, c, "before") for k, c in enumerate(reversed(sequence[max(0, pos - 8):pos]))]
            for k, cand, side in window:
                cnode = cand["node"]
                if cand["kind"] == "field" and is_gate(cnode) and not cnode.get("hidden"):
                    continue
                if cand["path"] in deps or cnode.get("hidden") or not open_cond:
                    continue
                extra = [c for c in visibility_conds(cand, index) if c not in g_conds]
                if any(reads(c) for c in extra) or (cnode.get("if") and g["parent"]):
                    continue                        # conditioned on something else - see "chain"
                if cand["top"] and (org_list_of(cand, md) or cnode.get("systemPath") or cand["key"] in bound):
                    continue                        # a project column every report needs - not a detail
                clabel = " " + norm(lab(cand)) + " "
                shared = shares_topic(gwords, lab(cand)) if gwords else []
                detail = bool(DETAIL_WORDS.search(clabel)) or cnode.get("type") == "image" or cand["kind"] == "group"
                starts_as_detail = bool(DETAIL_START.search(norm(lab(cand))))
                if side == "before" and not (shared and (detail or starts_as_detail)):
                    continue                        # before its question: only a clear detail of it
                if not shared and not (k == 0 and ((detail and not topic_words(lab(cand))) or starts_as_detail)):
                    continue
                about_check = bool(ABOUT_THE_CHECK.search(clabel)) and "unknown" in kinds
                cond = cond_for(expr_path(g), gnode, checked if about_check else opts)
                closed = [a for a in answers if isinstance(a, str) and
                          (classify(a) == "unknown" if about_check else classify(a) != "positive")]
                when = " / ".join(f'"{a}"' for a in closed) if closed else '"לא מסומן"'
                open_on = checked if about_check else opts
                opens = "כשמסומן" if gnode.get("type") == "checkbox" else "רק כש-" + " / ".join(f'"{o}"' for o in open_on)
                why = f'נושא משותף: {", ".join(shared)}' if shared else "מיד אחרי השאלה"
                where = " הוא גם מופיע לפני השאלה - להעביר אותו אחריה." if side == "before" else ""
                add("ungated", "fix" if shared and side == "after" else "check", cand["path"],
                    f'"{lab(cand)}" מוצג לכל תשובה של "{lab(g)}", גם {when} ({why}). להציג {opens}.{where}',
                    gate=g["path"], suggest=cond)

            # a check from an outside source with no "not checked" answer
            if gnode.get("type") in ("radio", "select") and "negative" in kinds and "unknown" not in kinds and \
                    EXTERNAL_CHECKS.search(norm(lab(g)) + " " + " ".join(norm(o) for o in options_of(gnode))):
                add("no-unchecked-answer", "advice", g["path"],
                    f'"{lab(g)}": אין תשובה "לא נבדק" - כשהשמאי לא בדק, הטופס מכריח לבחור תשובה שלילית, '
                    'והדוח יקבע עובדה שלא נבדקה. מומלץ add_options "לא נבדק"', gate=g["path"])
            prompt = ((gnode.get("aiConfig") or {}).get("prompt") or "")
            negs = [o for o in options_of(gnode) if classify(o) == "negative"]
            yes_no = any(norm(o) in YES_NO_NEGATIVES for o in negs) or EXTERNAL_CHECKS.search(norm(lab(g)))
            if negs and yes_no and not re.search(r"השאר ריק|לא נבדק|אל תסיק|אם לא|אם אין|רק אם|רק לפי", prompt):
                add("gate-prompt", "advice", g["path"],
                    f'"{lab(g)}": בלי הנחיה, AI Fill עלול לבחור "{negs[0]}" רק כי המסמכים שותקים. '
                    'כדאי aiConfig.prompt: "בחר רק לפי מסמך או בדיקה שקובעים זאת; אם אין - השאר ריק"',
                    gate=g["path"])

    for sec in section_keys(schema):
        scan(by_section.get(sec, []))
    for ginfo, kids in group_rows:
        scan(kids, exclude_words=topic_words(lab(ginfo)))     # "היתר" is the table's subject, not a topic

    # evidence of an outside check with no question to open it
    gate_words = {}
    for i in infos:
        if i["kind"] == "field" and is_gate(i["node"]) and not i["node"].get("hidden"):
            gate_words.setdefault(i["section"], []).extend(topic_words(lab(i)))
    for info in infos:
        node = info["node"]
        if not info["top"] or node.get("hidden") or node.get("type") not in ("image", "textarea", "richtext"):
            continue
        text = norm(lab(info))
        if not EXTERNAL_CHECKS.search(text) or any(reads(c) for c in visibility_conds(info, index)):
            continue
        if shares_topic(gate_words.get(info["section"], []), lab(info)):
            continue                                  # there is a question about it (ungated covers it)
        add("check-without-question", "advice", info["path"],
            f'"{lab(info)}" מתעד בדיקה בלי שאלה שפותחת אותו - הוא יופיע גם כשאין ממצא או כשלא נבדק. '
            'כדאי שאלה (קיים / לא קיים / לא נבדק) ולהציג אותו רק בתשובה שמתארת ממצא')

    # -- chains: a detail of a detail must carry the first gate too
    for info in infos:
        conds = visibility_conds(info, index)
        all_reads = set().union(*[reads(c) for c in conds]) if conds else set()
        own_conds = [c for c in (info.get("row_if") if info["top"] else None, info["node"].get("if")) if c]
        own_reads = set().union(*[reads(c) for c in own_conds]) if own_conds else set()
        for b in sorted(own_reads):
            if b not in top:
                continue
            b_conds = visibility_conds(top[b], index)
            b_reads = set().union(*[reads(c) for c in b_conds]) if b_conds else set()
            missing = b_reads - all_reads - {info["key"]}
            if missing and b_conds:
                add("chain", "fix", info["path"],
                    f'"{lab(info)}" תלוי ב"{lab(top[b])}", שמוצג רק לפי '
                    f'{" ו".join(chr(34) + (lab(top[m]) if m in top else m) + chr(34) for m in sorted(missing))}. '
                    f'שדה מוסתר שומר את הערך שלו, אז כשהתשובה שם משתנה "{lab(info)}" נשאר פתוח. '
                    "להוסיף לתנאי גם את התנאי של השדה שהוא תלוי בו",
                    gate=b, suggest=" && ".join(f"({c})" for c in b_conds + [info['node'].get('if')]
                                               if isinstance(c, str) and c))

    # -- long text and rich text
    for info in infos:
        node = info["node"]
        if info["kind"] != "field":
            continue
        t = node.get("type")
        text = " " + norm(lab(info)) + " "
        if t == "textarea" and NARRATIVE.search(text):
            add("richtext-candidate", "advice", info["path"],
                f'"{lab(info)}" הוא טקסט מפורט - בשדה חדש עדיף richtext (פסקאות, הדגשות, רשימות; בתבנית '
                "{p.ad.x | html}). בשדה קיים: המרה משנה את התבניות שקוראות אותו - ראו form-design.md §3")
    return findings


def suggested_ops(findings):
    """update_field ops for findings that carry a ready condition (fix level), one per path."""
    ops, seen = [], set()
    for f in findings:
        if f.get("suggest") and f["kind"] in ("ungated", "opens-unanswered", "opens-unchecked", "chain", "dead-value") \
                and f["path"] not in seen:
            seen.add(f["path"])
            ops.append({"op": "update_field", "path": f["path"], "set": {"if": f["suggest"]},
                        "why": f["message"]})
    return ops


def combine(existing, new):
    if not existing:
        return new
    if isinstance(existing, dict):
        return None
    return f"({existing}) && ({new})"
