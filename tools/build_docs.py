"""Rebuild the Code: Terraform Python documentation bundle from a game install.

    python tools/build_docs.py "E:/SteamLibrary/steamapps/common/CodeTerraform" docs

Everything the game ships lives inside the single Tauri executable as brotli-compressed
embedded assets. This script locates that asset table in the PE, decompresses it, then
reconstructs the documentation from the frontend JavaScript, which holds the same API
registries the in-game DOCS panel and editor autocomplete read from, joined against the
English locale table.

Every registry is found by *content* (a known English id or string), never by minified
variable name or byte offset. The frontend may be a single bundle (demo builds) or many
chunks (retail builds), so each registry is searched for across all of them.
"""
import argparse
import io
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jsparse import parse_at
from pe import PE

try:
    import brotli
except ImportError:
    sys.exit("brotli is required:  python -m pip install brotli")

BT = chr(96)                       # backtick, so this file stays paste-safe
# Asset keys are URL-ish paths and DO include non-ASCII (e.g. "/audio/music/Maré Serena.mp3"),
# so reject only control characters rather than allow-listing ASCII.
ASSET_PATH = re.compile("^/[^" + chr(0) + "-" + chr(31) + "]{1,200}[.][A-Za-z0-9]{1,5}$")


# --------------------------------------------------------------------- assets
def read_assets(exe_path):
    """Return {asset path: bytes} from the Tauri embedded-asset table.

    The table is an array of 32-byte `(key_ptr, key_len, value_ptr, value_len)`
    records. We anchor on a path string any Tauri frontend has, find the pointer
    to it, then collect every record around it.
    """
    pe = PE(exe_path)
    d = pe.data

    def entry(off):
        if off < 0 or off + 32 > len(d):
            return None
        kp, kl, vp, vl = struct.unpack_from("<4Q", d, off)
        if not (1 <= kl <= 200) or not (0 < vl <= 200 * 1024 * 1024):
            return None
        ko, vo = pe.va_to_off(kp), pe.va_to_off(vp)
        if ko is None or vo is None or vo + vl > len(d):
            return None
        try:
            key = d[ko:ko + kl].decode("utf-8")
        except UnicodeDecodeError:
            return None
        return (key, vo, vl) if ASSET_PATH.match(key) else None

    def scan(centre, radius):
        hits = {}
        for off in range(max(0, centre - radius), min(len(d), centre + radius), 8):
            e = entry(off)
            if e:
                hits[off] = e
        return hits

    found = {}
    for anchor in (b"/index.html", b"/icon.svg"):
        for m in re.finditer(re.escape(anchor), d):
            va = pe.off_to_va(m.start())
            if va is None:
                continue
            for p in re.finditer(re.escape(struct.pack("<Q", va)), d):
                # The table's size is unknown up front, so grow the window until records
                # stop appearing near its edges — a fixed window silently truncates.
                radius, hits = 1 << 16, {}
                while radius <= (1 << 24):
                    hits = scan(p.start(), radius)
                    if not hits:
                        break
                    if (min(hits) > p.start() - radius + 4096
                            and max(hits) < p.start() + radius - 4096):
                        break
                    radius *= 2
                for _, (key, vo, vl) in hits.items():
                    found[key] = (vo, vl)
            if found:
                break
        if found:
            break
    if not found:
        sys.exit("could not locate the embedded asset table in %s" % exe_path)

    out = {}
    for key, (vo, vl) in found.items():
        raw = d[vo:vo + vl]
        try:
            out[key] = brotli.decompress(raw)
        except brotli.error:
            out[key] = raw
    return out


# ----------------------------------------------------------------- registries
def q(text):
    return BT + re.escape(text) + BT


PATTERNS = {
    # label:         regex whose group 1 is the literal's opening bracket
    "components":    r"=(\[\{id:[^,]{1,8},nameKey:" + q("components.commander.name") + r")",
    "types":         r"=(\[\{typeName:" + q("Component") + r",docsGroup:)",
    "builtin_types": r"=(\[\{typeName:" + q("list") + r",docsGroup:)",
    "globals":       r"=(\[\{name:" + q("boot") + r",signature:)",
    "lang":          r"=(\[\{id:" + q("variables") + r",titleKey:)",
    "builtins":      r"=(\[\{name:" + q("print") + r",signature:)",
    "docs_pages":    r"=(\[\{id:" + q("getting_started") + r",categoryKey:)",
}
OPTIONAL = {
    # Demo builds seed machine scripts from a table; retail replaced it with lessons.
    "seed_scripts": r"=(\{[a-z0-9_]+:\{name:" + BT + r"[a-z0-9_]+\.py" + BT + r",source:)",
    "lessons":      r"=(\[\{id:" + q("print-console") + r",title:)",
}


class Chunk:
    def __init__(self, name, text):
        self.name, self.s = name, text
        assign = {}
        for m in re.finditer(r"(?<![A-Za-z0-9_$.])([A-Za-z_$][A-Za-z0-9_$]{0,3})="
                             + BT + r"([a-z0-9_]{2,40})" + BT, text):
            assign.setdefault(m.group(1), set()).add(m.group(2))
        # Minified names are reused across scopes; only trust unambiguous ones.
        self.refs = {k: next(iter(v)) for k, v in assign.items() if len(v) == 1}
        self._joiners = {}

    def deref(self, v):
        if isinstance(v, dict) and set(v) == {"__ref__"}:
            return self.refs.get(v["__ref__"], v["__ref__"])
        return v

    def var(self, name):
        """Parse `name=<literal>`, seeing through `Object.freeze` / `Object.keys`."""
        m = re.search(r"(?<![A-Za-z0-9_$.])" + re.escape(name) + r"=(?=[\[\{" + BT + "\"'])",
                      self.s)
        if m:
            return parse_at(self.s, m.end())[0]
        m = re.search(r"(?<![A-Za-z0-9_$.])" + re.escape(name)
                      + r"=Object\.freeze\((Object\.keys\()?([\w$]+|\[)", self.s)
        if not m:
            return None
        if m.group(1):                                   # Object.freeze(Object.keys(x))
            got = self.var(m.group(2))
            return list(got) if isinstance(got, dict) else None
        if m.group(2) == "[":                            # Object.freeze([...])
            return parse_at(self.s, m.end() - 1)[0]
        return self.var(m.group(2))

    def is_line_joiner(self, fn):
        """True for helpers like `function nI(...e){return e.join('\\n')}`."""
        if fn not in self._joiners:
            self._joiners[fn] = bool(re.search(
                r"function\s+" + re.escape(fn) + r"\(\.\.\.[\w$]+\)\{return\s+[\w$]+\.join\(",
                self.s))
        return self._joiners[fn]

    def call_value(self, v):
        """Resolve `nI(`a`,`b`)` line-joiner calls into their joined text."""
        if not (isinstance(v, dict) and "__call__" in v):
            return None
        if not self.is_line_joiner(v["__call__"]):
            return None
        try:
            args = parse_at("[" + v["__args__"][1:-1] + "]", 0)[0]
        except Exception:
            return None
        return "\n".join(x for x in args if isinstance(x, str))

    def var_map(self, name):
        """`Pj=cm.map(e=>({...}))` — a registry generated from a list of ids."""
        m = re.search(r"(?<![A-Za-z0-9_$.])" + re.escape(name)
                      + r"=([\w$]+)\.map\(\s*(\w+)\s*=>\s*\(", self.s)
        if not m:
            return None
        ids = self.var(m.group(1))
        if not isinstance(ids, list):
            return None
        tmpl = parse_at(self.s, self.s.index("{", m.end() - 1))[0]
        return [subst(tmpl, m.group(2), i) for i in ids if isinstance(i, str)]

    def lookup(self, name):
        return self.var(name) or self.var_map(name)

    def expand_spread(self, text):
        """Resolve one `...X` element into the entries it contributes."""
        m = MAP_LITERAL.match(text)
        if m:                                        # `...[a,b].map(e=>({...}))`
            ids = [self.refs.get(t.strip(), t.strip()) for t in m.group(1).split(",")]
            tmpl = parse_at(text, text.index("{", m.end() - 1))[0]
            out = []
            for cid in ids:
                item = subst(tmpl, m.group(2), cid)
                if isinstance(item, dict):
                    item["id"] = cid
                out.append(item)
            return out
        m = MAP_VAR.match(text)
        if m:                                        # `...names.map(e=>({...}))`
            ids = self.var(m.group(1))
            if isinstance(ids, list):
                tmpl = parse_at(text, text.index("{", m.end() - 1))[0]
                return [subst(tmpl, m.group(2), i) for i in ids if isinstance(i, str)]
            return []
        m = PLAIN_SPREAD.match(text)
        if m:                                        # `...Pj`
            got = self.lookup(m.group(1))
            return got if isinstance(got, list) else [got] if isinstance(got, dict) else []
        return []                                    # factory call we cannot evaluate

    def resolve(self, ref, before, window=250000):
        """Value of `ref=<literal>` from the nearest assignment before an offset."""
        lo = max(0, before - window)
        best = None
        for m in re.finditer(r"(?<![A-Za-z0-9_$.])" + re.escape(ref) + r"=(?=[\[" + BT + "\"'])",
                             self.s[lo:before]):
            best = lo + m.start()
        if best is None:
            return None
        val = parse_at(self.s, best + len(ref) + 1)[0]
        return "\n".join(str(x) for x in val) if isinstance(val, list) else val


class Corpus:
    """All frontend JS chunks; registries are looked up across every one of them."""

    def __init__(self, assets):
        self.chunks = []
        for key in sorted(assets, key=lambda k: -len(assets[k])):
            if key.endswith(".js"):
                self.chunks.append(Chunk(key, assets[key].decode("utf-8", "replace")))
        if not self.chunks:
            sys.exit("no JavaScript assets found")

    def registry(self, label, pattern, required=True):
        for c in self.chunks:
            m = re.search(pattern, c.s)
            if m:
                return c, parse_at(c.s, m.start(1))[0]
        if required:
            sys.exit("registry %r not found — the bundle's shape changed" % label)
        return None, None

    def locale(self):
        """The English locale object: the one containing `app:{title:...}`.

        Keyed off content rather than a wrapper, because retail reordered the sections
        and moved several of them behind variable references.
        """
        for c in self.chunks:
            i = c.s.find("app:{title:")
            if i < 0:
                continue
            depth, j = 0, i
            while j > 0:
                ch = c.s[j]
                if ch == "}":
                    depth += 1
                elif ch == "{":
                    if depth == 0:
                        break
                    depth -= 1
                j -= 1
            loc = parse_at(c.s, j)[0]
            for k, v in list(loc.items()):          # sections held behind refs
                if isinstance(v, dict) and set(v) == {"__ref__"}:
                    got = c.var(v["__ref__"])
                    if isinstance(got, dict):
                        loc[k] = got
            return c, loc
        sys.exit("locale table not found")


def subst(node, param, value):
    """Substitute a `.map(param => ...)` parameter: `${param}` in strings, bare refs."""
    if isinstance(node, str):
        return node.replace("${%s}" % param, value)
    if isinstance(node, list):
        return [subst(x, param, value) for x in node]
    if isinstance(node, dict):
        if set(node) == {"__ref__"} and node["__ref__"] == param:
            return value
        return {k: subst(v, param, value) for k, v in node.items()}
    return node


MAP_LITERAL = re.compile(r"\.\.\.\[([^\]]+)\]\.map\(\s*(\w+)\s*=>\s*\(")
MAP_VAR = re.compile(r"\.\.\.([\w$]+)\.map\(\s*(\w+)\s*=>\s*\(")
PLAIN_SPREAD = re.compile(r"\.\.\.([\w$]+)$")


def expand_list(entries, chunk):
    """Flatten a registry or `methods:` array.

    Entries can be spliced in by reference (`...L0`, a bare `L0`) or generated by a
    `.map` over a list of ids, so resolve those against the chunk they came from.
    """
    out = []
    for e in entries:
        if not isinstance(e, dict):
            out.append(e)
            continue
        if set(e) == {"__ref__"}:                     # `methods:[..., L0, ...]`
            got = chunk.lookup(e["__ref__"])
            out.extend(got if isinstance(got, list) else [got] if isinstance(got, dict) else [])
            continue
        if "__spread__" in e:
            out.extend(chunk.expand_spread(e["__spread__"]))
            continue
        out.append(e)
    return out


def slug(x):
    return re.sub(r"[^a-z0-9]+", "-", str(x).lower()).strip("-")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--dump-assets", metavar="DIR",
                    help="also write every decompressed asset here (large: includes audio)")
    args = ap.parse_args()

    exes = [f for f in os.listdir(args.game_dir) if f.lower().endswith(".exe")]
    if not exes:
        sys.exit("no .exe found in %s" % args.game_dir)
    exe = os.path.join(args.game_dir, max(
        exes, key=lambda f: os.path.getsize(os.path.join(args.game_dir, f))))

    print("reading %s" % exe)
    assets = read_assets(exe)
    print("  %d embedded assets" % len(assets))
    if args.dump_assets:
        for key, blob in assets.items():
            p = os.path.join(args.dump_assets, key.lstrip("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(blob)
        print("  dumped to %s" % args.dump_assets)

    corpus = Corpus(assets)
    print("  %d JS chunks" % len(corpus.chunks))

    def write(rel, text):
        dest = os.path.join(args.out_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        io.open(dest, "w", encoding="utf-8", newline="\n").write(text)

    reg, home = {}, {}
    for label, pat in PATTERNS.items():
        home[label], reg[label] = corpus.registry(label, pat)
    for label, pat in OPTIONAL.items():
        home[label], reg[label] = corpus.registry(label, pat, required=False)
    loc_chunk, LOCALE = corpus.locale()

    print("  locale: %s (%d sections)" % (loc_chunk.name, len(LOCALE)))
    for label in list(PATTERNS) + list(OPTIONAL):
        if reg[label] is None:
            print("    %-14s absent in this build" % label)
        else:
            print("    %-14s %-4d  %s" % (label, len(reg[label]), home[label].name))

    # Flatten every registry, then every `methods:` array inside it, so entries
    # spliced in by reference are not silently dropped.
    for label in ("components", "types", "builtin_types", "globals", "builtins", "lang"):
        ch = home[label]
        reg[label] = expand_list(reg[label], ch)
        for e in reg[label]:
            ms = e.get("methods") if isinstance(e, dict) else None
            if isinstance(ms, dict) and "__ref__" in ms:      # methods held in a side var
                ms = ch.lookup(ms["__ref__"]) or []
            if isinstance(ms, list):
                e["methods"] = expand_list(ms, ch)
    COMPONENTS = reg["components"]

    # The locale mixes three shapes: nested sections (`app: {title: ...}`), sections
    # holding partially-dotted keys (`lang_features: {"variables.title": ...}`), and
    # sections holding fully-qualified keys that name a *different* section
    # (`diagnostics: {"api.api_object_types.component.id.description": ...}`).
    # Index all three into one flat map rather than guessing where a key lives.
    FLAT = {}

    def _index(node, prefix):
        for k, v in node.items():
            if k == "__spreads__":
                continue
            path = "%s.%s" % (prefix, k) if prefix else k
            if isinstance(v, str):
                FLAT.setdefault(path, v)
                if "." in k:                    # already fully qualified on its own
                    FLAT.setdefault(k, v)
            elif isinstance(v, dict):
                _index(v, path)

    _index(LOCALE, "")

    def tr(key, default=None):
        return FLAT.get(key, default) if key else default

    def field(entry, name, chunk=None):
        """A field that may be a literal, a `<name>Key` translation, or a helper call."""
        v = entry.get(name)
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and "__call__" in v and chunk is not None:
            joined = chunk.call_value(v)
            if joined:
                return joined
        return tr(entry.get(name + "Key"), "") or ""

    def render_method(mth, prefix="", chunk=None):
        sig = mth.get("signature") or (prefix + str(mth.get("name", "")))
        ret = mth.get("returnType") or ""
        head = "### `%s`" % sig
        if isinstance(ret, str) and ret:
            head += "  \u2192  `%s`" % ret
        out = [head, ""]
        desc = field(mth, "description", chunk)
        if desc:
            out += [desc, ""]
        if mth.get("params"):
            out += ["| Parameter | Type | Description |", "| --- | --- | --- |"]
            for p in mth["params"]:
                nm = str(p.get("name", "")) + (" *(optional)*" if p.get("optional") else "")
                out.append("| `%s` | `%s` | %s |"
                           % (nm, p.get("type", ""),
                              field(p, "description", chunk).replace("|", "\\|")))
            out.append("")
        rv = field(mth, "returns", chunk)
        if rv and rv != ret:
            out += ["**Returns:** %s" % rv, ""]
        exc = mth.get("exceptions") or []
        if exc:
            out += ["**Raises:**", ""]
            for e in exc:
                if not isinstance(e, dict):
                    continue
                cond = field(e, "condition", chunk)
                out.append("- `%s`%s" % (e.get("type", "?"), " \u2014 %s" % cond if cond else ""))
            out.append("")
        if isinstance(mth.get("example"), str):
            out += ["```python", mth["example"], "```", ""]
        return "\n".join(out)

    def group_by(entries, key, chunk, default="Other"):
        g = {}
        for e in entries:
            g.setdefault(chunk.deref(e.get(key)) or default, []).append(e)
        return g

    counts = {}

    # -- manual -------------------------------------------------------------
    cats = {}
    for page in reg["docs_pages"]:
        cats.setdefault(page["categoryKey"], []).append(page)
    index = ["# The In-Game Manual (DOCS)", "",
             "Every page of the in-game DOCS panel, in the order the game lists them.", ""]
    n = 0
    for catkey, pages in cats.items():
        catname = tr(catkey, catkey)
        index += ["## %s" % catname, ""]
        for page in pages:
            n += 1
            fname = "%02d-%s.md" % (n, slug(page["id"]))
            meta = "*Category: %s*  \u00b7  *Page id: `%s`*" % (catname, page["id"])
            utype = home["docs_pages"].deref((page.get("unlockCondition") or {}).get("type"))
            if isinstance(utype, str) and utype != "always":
                meta += "  \u00b7  *Unlocks: `%s`*" % utype
            write("manual/" + fname, "\n".join(
                ["# %s" % tr(page.get("titleKey"), page["id"]), "", meta, "", "---", "",
                 tr(page.get("contentKey"), ""), ""]))
            index.append("- [%s](%s) \u2014 `%s`"
                         % (tr(page.get("titleKey"), page["id"]), fname, page["id"]))
        index.append("")
    write("manual/README.md", "\n".join(index))
    counts["manual"] = n

    # -- global functions ---------------------------------------------------
    ch = home["globals"]
    doc = ["# Global Functions", "",
           "Functions callable directly from any script (no component needed).",
           "Each is gated behind an *API group* the game unlocks as you progress.", ""]
    for cat, fns in group_by(reg["globals"], "category", ch).items():
        doc += ["## %s" % cat, ""]
        for fn in fns:
            doc.append(render_method(fn, "", ch))
            grp = ch.deref(fn.get("apiGroup"))
            if isinstance(grp, str):
                doc += ["*API group: `%s`*" % grp, ""]
    write("reference/global-functions.md", "\n".join(doc))
    counts["globals"] = len(reg["globals"])

    # -- builtins -----------------------------------------------------------
    ch = home["builtins"]
    doc = ["# Built-in Functions", "",
           "The interpreter's builtins, grouped as the in-game reference groups them.", ""]
    for cat, fns in group_by(reg["builtins"], "category", ch).items():
        doc += ["## %s" % cat, ""] + [render_method(f, "", ch) for f in fns]
    write("reference/builtins.md", "\n".join(doc))
    counts["builtins"] = len(reg["builtins"])

    # -- builtin types ------------------------------------------------------
    ch = home["builtin_types"]
    doc = ["# Built-in Type Methods", "",
           "Methods and properties available on the interpreter's core data types.", ""]
    for t in reg["builtin_types"]:
        doc += ["## `%s`" % t["typeName"], ""]
        prov = field(t, "returnedBy", ch)
        if prov:
            doc += ["*Produced by: %s*" % prov, ""]
        doc += [render_method(m, "", ch) for m in (t.get("methods") or [])]
    write("reference/builtin-types.md", "\n".join(doc))
    counts["builtin_types"] = len(reg["builtin_types"])

    # -- language features --------------------------------------------------
    ch = home["lang"]
    doc = ["# Language Features", "",
           "The Python subset the interpreter supports, as presented in the in-game",
           "reference. Features unlock progressively \u2014 `id` is the unlock flag.", ""]
    for catkey, feats in group_by(reg["lang"], "categoryKey", ch).items():
        doc += ["## %s" % tr(catkey, catkey), ""]
        for f in feats:
            doc += ["### %s" % tr(f.get("titleKey"), f.get("id", "")), "",
                    "`id: %s`" % f.get("id", ""), "", tr(f.get("descriptionKey"), ""), ""]
            if isinstance(f.get("example"), str):
                doc += ["```python", f["example"], "```", ""]
    write("reference/language-features.md", "\n".join(doc))
    counts["lang"] = len(reg["lang"])

    # -- components ---------------------------------------------------------
    ch = home["components"]
    index = ["# Components", "",
             'Everything reachable through `get_component("...")` or as `self` inside a',
             "machine script.", ""]
    for grp, comps in group_by(COMPONENTS, "docsGroup", ch).items():
        fname = "reference/components/%s.md" % slug(grp)
        doc = ["# %s" % grp, ""]
        index += ["## %s" % grp, ""]
        for c in comps:
            cid = ch.deref(c.get("id"))
            if not (isinstance(cid, str) and re.match(r"^[a-z0-9_]+$", cid)):
                cid = str(c.get("descriptionKey", ".x.")).split(".")[1]
            name = tr(c.get("nameKey"), cid)
            doc += ["## %s" % name, "", "```python", 'c = get_component("%s")' % cid, "```", ""]
            desc = field(c, "description", ch)
            if desc:
                doc += [desc, ""]
            meta = ["`%s: %s`" % (k, ch.deref(c[k]))
                    for k in ("type", "shared", "scriptSlots", "allowsRemoteWrites") if k in c]
            if meta:
                doc += [" \u00b7 ".join(meta), ""]
            doc += [render_method(m, ".", ch) for m in (c.get("methods") or [])]
            doc.append("---\n")
            index.append("- **%s** \u2014 `%s` (%s)" % (name, cid, os.path.basename(fname)))
        index.append("")
        write(fname, "\n".join(doc))
    write("reference/components/README.md", "\n".join(index))
    counts["components"] = len(COMPONENTS)

    # -- object types -------------------------------------------------------
    ch = home["types"]
    index = ["# Object Types", "",
             "Objects returned by component methods \u2014 their properties and methods.", ""]
    for grp, types in group_by(reg["types"], "docsGroup", ch).items():
        fname = "reference/types/%s.md" % slug(grp)
        doc = ["# %s" % grp, ""]
        index += ["## %s" % grp, ""]
        for t in types:
            doc += ["## `%s`" % t["typeName"], ""]
            prov = field(t, "returnedBy", ch)
            if prov:
                doc += ["*Returned by: %s*" % prov, ""]
            doc += [render_method(m, ".", ch) for m in (t.get("methods") or [])]
            doc.append("---\n")
            index.append("- `%s` (%s)" % (t["typeName"], os.path.basename(fname)))
        index.append("")
        write(fname, "\n".join(doc))
    write("reference/types/README.md", "\n".join(index))
    counts["types"] = len(reg["types"])

    # -- machine guides -----------------------------------------------------
    doc = ["# Per-Machine Guides", "",
           "The tutorial text the game shows beside each machine's script editor \u2014",
           "what the machine does, and how a script is meant to drive it.", ""]
    counts["guides"] = 0
    for section in sorted(LOCALE):
        body = LOCALE[section]
        if not isinstance(body, dict):
            continue
        if not (section.endswith("_script") or section == "tutorial_scripts"
                or section in ("solar_tracker", "oxygen_gen", "temp_heater", "pressure_gen")):
            continue
        for k, v in body.items():
            if isinstance(v, str) and v.strip():
                counts["guides"] += 1
                doc += ["## `%s.%s`" % (section, k), "", v, "", "---", ""]
    write("machine-guides.md", "\n".join(doc))

    # -- training lessons (retail) ------------------------------------------
    counts["lessons"] = 0
    if reg["lessons"]:
        ch = home["lessons"]
        doc = ["# Training Lessons", "",
               "The guided Python course built into the game. Each lesson states a task,",
               "explains the concept, and ships hints plus a reference solution.", "",
               "> Reference solutions are included below.", ""]
        for i, les in enumerate(reg["lessons"], 1):
            counts["lessons"] += 1
            doc += ["## %d. %s" % (i, les.get("title", les.get("id"))), "",
                    "*`%s`*" % les.get("id", ""), ""]
            for label, key in (("Objective", "objective"), ("Task", "task")):
                if isinstance(les.get(key), str):
                    doc += ["**%s.** %s" % (label, les[key]), ""]
            if les.get("concepts"):
                doc += ["**Concepts:** %s"
                        % ", ".join("`%s`" % c for c in les["concepts"]), ""]
            for para in les.get("explanation") or []:
                if isinstance(para, str):
                    doc += [para, ""]
            starter = ch.call_value(les.get("starterSource")) or les.get("starterSource")
            if isinstance(starter, str) and starter.strip():
                doc += ["**Starter code**", "", "```python", starter.rstrip(), "```", ""]
            hints = [h for h in (les.get("hints") or []) if isinstance(h, str)]
            if hints:
                doc += ["- *Hint:* %s" % h for h in hints] + [""]
            sol = ch.call_value(les.get("solution")) or les.get("solution")
            if isinstance(sol, str) and sol.strip():
                doc += ["**Solution**", "", "```python", sol.rstrip(), "```", ""]
            doc += ["---", ""]
        write("training-lessons.md", "\n".join(doc))

    # -- seeded scripts (demo) ----------------------------------------------
    counts["seeded"] = counts["contracts"] = counts["examples"] = 0
    if reg["seed_scripts"]:
        ch = home["seed_scripts"]
        at = re.search(OPTIONAL["seed_scripts"], ch.s).start(1)
        rows = []
        for slot, e in reg["seed_scripts"].items():
            if not isinstance(e, dict):
                continue
            src = e.get("source")
            if isinstance(src, dict) and "__ref__" in src:
                src = ch.resolve(src["__ref__"], at)
            rows.append((slot, e.get("name"), src))

        def render_scripts(title, blurb, items):
            out = ["# %s" % title, "", blurb, ""]
            for slot, name, src in items:
                out += ["## `%s`" % (name or slot), "", "*Script slot: `%s`*" % slot, "",
                        "```python", (src or "").rstrip(), "```", ""]
            return "\n".join(out)

        normal = [r for r in rows if not r[0].startswith("contract_")]
        spoiler = [r for r in rows if r[0].startswith("contract_")]
        write("starter-scripts/README.md", render_scripts(
            "Starter Scripts",
            "The Python source the game seeds into each machine's script slot.", normal))
        if spoiler:
            write("starter-scripts/CONTRACT-SOLUTIONS.md", render_scripts(
                "Contract Scripts \u2014 SPOILERS",
                "> **Spoiler warning.** These contract scaffolds contain puzzle answers.",
                spoiler))
        counts["seeded"], counts["contracts"] = len(normal), len(spoiler)

        doc = ["# Example Script Library", "",
               "Ready-made example scripts offered inside each machine's editor.", ""]
        seen = set()
        for m in re.finditer(r"[\w$]+\(([\w$]+),(\[\{name:" + BT + r"[^" + BT + r"]+" + BT
                             + r",description:)", ch.s):
            if m.start(2) in seen:
                continue
            seen.add(m.start(2))
            arr = parse_at(ch.s, m.start(2))[0]
            if not all(isinstance(e, dict) and "source" in e for e in arr):
                continue
            doc += ["## `%s`" % ch.refs.get(m.group(1), m.group(1)), ""]
            for e in arr:
                counts["examples"] += 1
                src = e.get("source")
                if isinstance(src, dict) and "__ref__" in src:
                    src = ch.resolve(src["__ref__"], m.start())
                doc += ["### %s" % e.get("name"), ""]
                if isinstance(e.get("description"), str):
                    doc += [e["description"], ""]
                doc += ["```python", (src or "").rstrip(), "```", ""]
        if counts["examples"]:
            write("starter-scripts/example-library.md", "\n".join(doc))

    # -- verbatim stub assets (demo shipped these; retail generates them) ----
    counts["stubs"] = 0
    for key, blob in sorted(assets.items()):
        if key.startswith("/stubs/"):
            counts["stubs"] += 1
            write("stubs/" + key[len("/stubs/"):].replace("/", "_"), blob.decode("utf-8"))

    # -- index --------------------------------------------------------------
    rows = [("[`manual/`](manual/README.md)",
             "%d pages of the in-game DOCS panel" % counts["manual"]),
            ("[`reference/global-functions.md`](reference/global-functions.md)",
             "%d functions callable from any script" % counts["globals"]),
            ("[`reference/builtins.md`](reference/builtins.md)",
             "%d interpreter builtins" % counts["builtins"]),
            ("[`reference/builtin-types.md`](reference/builtin-types.md)",
             "Methods on the %d core data types" % counts["builtin_types"]),
            ("[`reference/language-features.md`](reference/language-features.md)",
             "%d language features and their unlock flags" % counts["lang"]),
            ("[`reference/components/`](reference/components/README.md)",
             "%d components addressable via `get_component()`" % counts["components"]),
            ("[`reference/types/`](reference/types/README.md)",
             "%d object types returned by component methods" % counts["types"]),
            ("[`machine-guides.md`](machine-guides.md)",
             "%d per-machine tutorial write-ups" % counts["guides"])]
    if counts["lessons"]:
        rows.append(("[`training-lessons.md`](training-lessons.md)",
                     "%d guided Python lessons, with solutions" % counts["lessons"]))
    if counts["seeded"]:
        rows.append(("[`starter-scripts/`](starter-scripts/README.md)",
                     "%d seeded machine scripts" % counts["seeded"]))
    if counts["examples"]:
        rows.append(("[`starter-scripts/example-library.md`](starter-scripts/example-library.md)",
                     "%d ready-made editor examples" % counts["examples"]))
    if counts["contracts"]:
        rows.append(("[`starter-scripts/CONTRACT-SOLUTIONS.md`]"
                     "(starter-scripts/CONTRACT-SOLUTIONS.md)",
                     "%d contract scaffolds \u2014 **contains puzzle answers**"
                     % counts["contracts"]))
    if counts["stubs"]:
        rows.append(("[`stubs/`](stubs/)",
                     "%d type stubs shipped verbatim" % counts["stubs"]))

    write("README.md",
          "# Code: Terraform \u2014 Python Documentation\n\n"
          "Extracted from `%s`. All game content lives inside the executable as\n"
          "brotli-compressed embedded assets; this bundle is everything in there that\n"
          "documents the in-game Python API and language.\n\n"
          "Regenerate with:\n\n```bash\n"
          "python tools/build_docs.py \"<game install folder>\" <output folder>\n```\n\n"
          "## Contents\n\n| Path | What it is |\n| --- | --- |\n%s\n\n"
          "## Where this came from\n\n"
          "Everything here is reconstructed from the frontend JavaScript, which holds the\n"
          "same API registries the in-game DOCS panel and editor autocomplete read from,\n"
          "joined against the game's English locale table. Descriptions, parameter docs,\n"
          "examples, raised exceptions and unlock gating all come from those registries.\n"
          % (os.path.basename(exe), "\n".join("| %s | %s |" % r for r in rows)))

    print("\nwrote %s" % args.out_dir)
    for k, v in counts.items():
        if v:
            print("  %-14s %d" % (k, v))


if __name__ == "__main__":
    main()
