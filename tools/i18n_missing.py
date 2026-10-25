r"""Ad Factory interface text not in the Portuguese dictionary yet (adeditor/i18n-pt.js):
    .venv\Scripts\python.exe tools/i18n_missing.py
A small JS tokenizer separates code from strings and whole template literals, the markup is
parsed as HTML, and text + title/placeholder hints are listed. Add missing ones to "exact"."""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1] / "adeditor"
NUL = chr(0)
BS = chr(92)
out = {}
ATTRS = ("title", "placeholder", "aria-label", "alt", "data-tip")
CODEY = re.compile(r"^[\w$.#\[\]=>:/?&%-]+$")


def keep(s, where):
    s = s.replace(BS + "n", " ").replace(BS + "'", "'").replace(BS + '"', '"')
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 2 or not re.search(r"[A-Za-z]{2}", s):
        return
    if CODEY.match(s) and not re.match(r"^[A-Z][a-z]+$", s):
        return  # identifiers, selectors, paths, keys (a lone Capitalized word stays)
    if re.search(r"(^|\s)(function|=>|const |let |return |\.map\(|\.join\(|===|!==|&&|\|\|)", s):
        return
    if re.match(r"^(/api|https?:|data:|#[a-z]|\.[a-z]|var\(|rgba?\(|url\()", s):
        return
    out.setdefault(s, where)


def keep_parts(s, where):
    for part in s.split(NUL):
        keep(part, where)


class P(HTMLParser):
    def __init__(self, where):
        super().__init__(convert_charrefs=True)
        self.where, self.skip = where, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ATTRS and v:
                keep_parts(v, self.where)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            keep_parts(data, self.where)


def tokens(src):
    """('q', text) quoted strings, ('t', text) whole template literals with each ${...} as NUL."""
    i, n, res, stack, prev = 0, len(src), [], [], ""
    while i < n:
        c = src[i]
        if stack and stack[-1][0] == "tpl":
            pieces, buf = stack[-1][1], stack[-1][2]
            if c == BS:
                buf.append(src[i:i + 2]); i += 2; continue
            if c == "`":
                pieces.append("".join(buf)); stack.pop(); res.append(("t", NUL.join(pieces))); i += 1; prev = "x"; continue
            if c == "$" and src[i + 1:i + 2] == "{":
                pieces.append("".join(buf)); stack[-1][2] = []; stack.append(["expr", 0]); i += 2; prev = "{"; continue
            buf.append(c); i += 1; continue
        if c in "\"'":
            j, b = i + 1, []
            while j < n and src[j] != c and src[j] != "\n":
                if src[j] == BS:
                    b.append(src[j:j + 2]); j += 2; continue
                b.append(src[j]); j += 1
            res.append(("q", "".join(b))); i = j + 1; prev = "x"; continue
        if c == "`":
            stack.append(["tpl", [], []]); i += 1; continue
        if c == "/" and src[i + 1:i + 2] == "/":
            i = src.find("\n", i); i = n if i < 0 else i; continue
        if c == "/" and src[i + 1:i + 2] == "*":
            i = src.find("*/", i); i = n if i < 0 else i + 2; continue
        if c == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^"):
            j, cls = i + 1, False  # a regex literal
            while j < n and src[j] != "\n":
                if src[j] == BS:
                    j += 2; continue
                if src[j] == "[":
                    cls = True
                elif src[j] == "]":
                    cls = False
                elif src[j] == "/" and not cls:
                    break
                j += 1
            i = j + 1; prev = "x"; continue
        if stack and stack[-1][0] == "expr":
            if c == "{":
                stack[-1][1] += 1
            elif c == "}":
                if stack[-1][1] == 0:
                    stack.pop(); i += 1; continue
                stack[-1][1] -= 1
        if not c.isspace():
            prev = c
        i += 1
    return res


P("index.html").feed((ROOT / "index.html").read_text(encoding="utf-8"))
for name in ("app.js", "shop.js", "scriptbuilder.js"):
    for kind, text in tokens((ROOT / name).read_text(encoding="utf-8")):
        if "<" in text or ">" in text:
            p = P(name)
            p.feed(text)
            p.close()
        else:
            keep_parts(text, name)


js = (ROOT / "i18n-pt.js").read_text(encoding="utf-8")
have = json.loads(js[js.index("{"):js.rindex("}") + 1])["exact"]
missing = [(k, w) for k, w in out.items() if k not in have]
for k, w in missing:
    print(f"{w}: {k}")
print(f"{len(missing)} of {len(out)} not translated (some are code, not text)")
