"""Rebuild the Code: Terraform Python documentation bundle from a game install.

    python tools/build_docs.py "E:/SteamLibrary/steamapps/common/Code Terraform" docs

Everything the game ships lives inside the single Tauri executable as brotli-compressed
embedded assets. This script locates that asset table in the PE, decompresses it, then
reconstructs the documentation from two sources:

  * `/stubs/*.pyi` — type stubs the game ships verbatim.
  * `/assets/index-*.js` — the API registries the in-game DOCS panel and autocomplete
    read from, joined against the English locale table.

Every registry is found by *content* (a known English id or string), never by minified
variable name or byte offset, so this survives a rebuild of the game.
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
ASSET_PATH = re.compile(r"^/[A-Za-z0-9 _.,'()/-]{1,120}\.[A-Za-z0-9]{1,5}$")
TEXT_EXT = (".pyi", ".md", ".js", ".css", ".html", ".json", ".svg", ".txt", ".py")


# --------------------------------------------------------------------- assets
def read_assets(exe_path):
    """Return {asset path: bytes} from the Tauri embedded-asset table.

    The table is an array of 32-byte `(key_ptr, key_len, value_ptr, value_len)`
    records. We anchor on a path string that any Tauri frontend has, find the
    pointer to it, then walk the table around that record.
    """
    pe = PE(exe_path)
    d = pe.data

    def entry(off):
        if off < 0 or off + 32 > len(d):
            return None
        kp, kl, vp, vl = struct.unpack_from("<4Q", d, off)
        if not (1 <= kl <= 130) or not (0 < vl <= 200 * 1024 * 1024):
            return None
        ko, vo = pe.va_to_off(kp), pe.va_to_off(vp)
        if ko is None or vo is None or vo + vl > len(d):
            return None
        try:
            key = d[ko:ko + kl].decode("utf-8")
        except UnicodeDecodeError:
            return None
        return (key, vo, vl) if ASSET_PATH.match(key) else None

    found = {}
    for anchor in (b"/index.html", b"/stubs/README.md", b"/icon.svg"):
        for m in re.finditer(re.escape(anchor), d):
            va = pe.off_to_va(m.start())
            if va is None:
                continue
            for p in re.finditer(re.escape(struct.pack("<Q", va)), d):
                lo, hi = p.start() - 8192, p.start() + 8192
                for off in range(max(0, lo), hi, 8):
                    e = entry(off)
                    if e:
                        found[e[0]] = (e[1], e[2])
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
class Bundle:
    """Content-addressed lookups into the minified frontend bundle."""

    def __init__(self, text):
        self.s = text
        assign = {}
        for m in re.finditer(r"(?<![A-Za-z0-9_$.])([A-Za-z_$][A-Za-z0-9_$]{0,3})="
                             + BT + r"([a-z0-9_]{2,40})" + BT, text):
            assign.setdefault(m.group(1), set()).add(m.group(2))
        # Minified names are reused across scopes; only trust unambiguous ones.
        self.refs = {k: next(iter(v)) for k, v in assign.items() if len(v) == 1}

    def deref(self, v):
        if isinstance(v, dict) and set(v) == {"__ref__"}:
            return self.refs.get(v["__ref__"], v["__ref__"])
        return v

    def registry(self, label, pattern):
        """Parse the literal whose opening bracket is capture group 1."""
        m = re.search(pattern, self.s)
        if not m:
            sys.exit("registry %r not found — the bundle's shape changed" % label)
        return parse_at(self.s, m.start(1))[0]

    def by_name(self, name):
        m = re.search(r"(?<![A-Za-z0-9_$.])" + re.escape(name) + r"=(\[)", self.s)
        return parse_at(self.s, m.start(1))[0] if m else None

    def resolve(self, ref, before, window=200000):
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


def q(text):
    """Regex-escaped backtick-quoted literal."""
    return BT + re.escape(text) + BT


PATTERNS = {
    # label:           regex whose group 1 is the literal's opening bracket
    "locale":          r"=(\{en:\{app:\{)",
    "components":      r"=(\[\{id:[^,]{1,6},nameKey:" + q("components.commander.name") + r")",
    "types":           r"=(\[\{typeName:" + q("Component") + r",docsGroup:)",
    "builtin_types":   r"=(\[\{typeName:" + q("list") + r",docsGroup:)",
    "globals":         r"=(\[\{name:" + q("boot") + r",signature:)",
    "lang":            r"=(\[\{id:" + q("variables") + r",titleKey:)",
    "builtins":        r"=(\[\{name:" + q("print") + r",signature:)",
    "docs_pages":      r"=(\[\{id:" + q("getting_started") + r",categoryKey:)",
    "seed_scripts":    r"=(\{[a-z0-9_]+:\{name:" + BT + r"[a-z0-9_]+\.py" + BT + r",source:)",
}


def subst(node, token, value):
    if isinstance(node, str):
        return node.replace(token, value)
    if isinstance(node, list):
        return [subst(x, token, value) for x in node]
    if isinstance(node, dict):
        return {k: subst(v, token, value) for k, v in node.items()}
    return node


def expand_spreads(entries, bundle):
    """`...[a,b,c].map(e=>({...}))` yields one entry per id, templated on ${e}."""
    out = []
    for e in entries:
        if "__spread__" not in e:
            out.append(e)
            continue
        text = e["__spread__"]
        m = re.match(r"\.\.\.\[([^\]]+)\]\.map\(\s*(\w+)\s*=>\s*\(", text)
        if not m:
            continue
        ids = [bundle.refs.get(t.strip(), t.strip()) for t in m.group(1).split(",")]
        tmpl = parse_at(text, text.index("{", m.end() - 1))[0]
        for cid in ids:
            item = subst(tmpl, "${%s}" % m.group(2), cid)
            item["id"] = cid
            out.append(item)
    return out


# --------------------------------------------------------------------- output
class Writer:
    def __init__(self, root):
        self.root = root

    def __call__(self, rel, text):
        dest = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        io.open(dest, "w", encoding="utf-8", newline="\n").write(text)


def slug(x):
    return re.sub(r"[^a-z0-9]+", "-", x.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir", help="game install folder (contains the .exe)")
    ap.add_argument("out_dir", help="where to write the documentation bundle")
    ap.add_argument("--dump-assets", metavar="DIR",
                    help="also write every decompressed asset here")
    args = ap.parse_args()

    exes = [f for f in os.listdir(args.game_dir) if f.lower().endswith(".exe")]
    if not exes:
        sys.exit("no .exe found in %s" % args.game_dir)
    exe = os.path.join(args.game_dir, exes[0])

    print("reading %s" % exe)
    assets = read_assets(exe)
    print("  %d embedded assets" % len(assets))

    if args.dump_assets:
        for key, blob in assets.items():
            p = os.path.join(args.dump_assets, key.lstrip("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "wb").write(blob)
        print("  dumped to %s" % args.dump_assets)

    js_keys = [k for k in assets
               if re.match(r"^/assets/index-.*\.js$", k) and len(assets[k]) > 500000]
    if not js_keys:
        sys.exit("could not identify the main frontend bundle")
    bundle = Bundle(assets[max(js_keys, key=lambda k: len(assets[k]))].decode("utf-8"))
    print("  bundle: %s" % max(js_keys, key=lambda k: len(assets[k])))

    release = "unknown"
    rel_file = os.path.join(args.game_dir, ".from-release")
    if os.path.exists(rel_file):
        m = re.search(r"tag:\s*(\S+)", open(rel_file, encoding="utf-8").read())
        if m:
            release = m.group(1)

    write = Writer(args.out_dir)
    reg = {k: bundle.registry(k, p) for k, p in PATTERNS.items()}
    LOCALE = reg["locale"]["en"]
    COMPONENTS = expand_spreads(reg["components"], bundle)
    for bt in reg["builtin_types"]:                       # methods live in a side var
        if isinstance(bt["methods"], dict):
            bt["methods"] = bundle.by_name(bt["methods"]["__ref__"]) or []

    def tr(key, default=None):
        """Resolve a dotted locale key; the table nests some levels and flattens others."""
        parts = key.split(".")
        for cut in range(1, len(parts)):
            node = LOCALE
            for p in parts[:cut]:
                if not isinstance(node, dict) or p not in node:
                    node = None
                    break
                node = node[p]
            if isinstance(node, dict) and ".".join(parts[cut:]) in node:
                return node[".".join(parts[cut:])]
        return default

    def desc_of(e):
        d = e.get("description")
        if d is None and e.get("descriptionKey"):
            d = tr(e["descriptionKey"])
        return d or ""

    def render_method(mth, prefix=""):
        sig = mth.get("signature") or (prefix + mth.get("name", ""))
        ret = mth.get("returnType") or mth.get("returns") or ""
        out = ["### `%s`%s" % (sig, "  \u2192  `%s`" % ret if ret else ""), ""]
        if desc_of(mth):
            out += [desc_of(mth), ""]
        if mth.get("params"):
            out += ["| Parameter | Type | Description |", "| --- | --- | --- |"]
            for p in mth["params"]:
                nm = p.get("name", "") + (" *(optional)*" if p.get("optional") else "")
                out.append("| `%s` | `%s` | %s |"
                           % (nm, p.get("type", ""), desc_of(p).replace("|", "\\|")))
            out.append("")
        if mth.get("returns") and mth["returns"] != ret:
            out += ["**Returns:** %s" % mth["returns"], ""]
        if mth.get("example"):
            out += ["```python", mth["example"], "```", ""]
        return "\n".join(out)

    def group_by(entries, key, default="Other"):
        g = {}
        for e in entries:
            g.setdefault(bundle.deref(e.get(key)) or default, []).append(e)
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
            utype = bundle.deref((page.get("unlockCondition") or {}).get("type"))
            if utype and utype != "always":
                meta += "  \u00b7  *Unlocks: `%s`*" % utype
            write("manual/" + fname, "\n".join(
                ["# %s" % tr(page["titleKey"], page["id"]), "", meta, "", "---", "",
                 tr(page["contentKey"], ""), ""]))
            index.append("- [%s](%s) \u2014 `%s`" % (tr(page["titleKey"], page["id"]),
                                                     fname, page["id"]))
        index.append("")
    write("manual/README.md", "\n".join(index))
    counts["manual"] = n

    # -- global functions ---------------------------------------------------
    doc = ["# Global Functions", "",
           "Functions callable directly from any script (no component needed).",
           "Each is gated behind an *API group* the game unlocks as you progress.", ""]
    for cat, fns in group_by(reg["globals"], "category").items():
        doc += ["## %s" % cat, ""]
        for fn in fns:
            doc.append(render_method(fn))
            if bundle.deref(fn.get("apiGroup")):
                doc += ["*API group: `%s`*" % bundle.deref(fn["apiGroup"]), ""]
    write("reference/global-functions.md", "\n".join(doc))
    counts["globals"] = len(reg["globals"])

    # -- builtins -----------------------------------------------------------
    doc = ["# Built-in Functions", "",
           "The interpreter's builtins. This is a bespoke Python-like runtime, so the set",
           "is smaller than CPython's and some semantics differ (every number is a float).", ""]
    for cat, fns in group_by(reg["builtins"], "category").items():
        doc += ["## %s" % cat, ""] + [render_method(f) for f in fns]
    write("reference/builtins.md", "\n".join(doc))
    counts["builtins"] = len(reg["builtins"])

    # -- builtin types ------------------------------------------------------
    doc = ["# Built-in Type Methods", "",
           "Methods and properties available on the interpreter's core data types.", ""]
    for t in reg["builtin_types"]:
        doc += ["## `%s`" % t["typeName"], ""]
        if t.get("returnedBy"):
            doc += ["*Produced by: %s*" % t["returnedBy"], ""]
        doc += [render_method(m) for m in t["methods"]]
    write("reference/builtin-types.md", "\n".join(doc))

    # -- language features --------------------------------------------------
    doc = ["# Language Features", "",
           "The Python subset the interpreter supports, as presented in the in-game",
           "reference. Features unlock progressively \u2014 `id` is the unlock flag.", ""]
    for catkey, feats in group_by(reg["lang"], "categoryKey").items():
        doc += ["## %s" % tr(catkey, catkey), ""]
        for f in feats:
            doc += ["### %s" % tr(f.get("titleKey", ""), f.get("id", "")), "",
                    "`id: %s`" % f.get("id", ""), "",
                    tr(f.get("descriptionKey", ""), ""), ""]
            if f.get("example"):
                doc += ["```python", f["example"], "```", ""]
    write("reference/language-features.md", "\n".join(doc))
    counts["lang"] = len(reg["lang"])

    # -- components ---------------------------------------------------------
    index = ["# Components", "",
             'Everything reachable through `get_component("...")` or as `self` inside a',
             "machine script.", ""]
    for grp, comps in group_by(COMPONENTS, "docsGroup").items():
        fname = "reference/components/%s.md" % slug(grp)
        doc = ["# %s" % grp, ""]
        index += ["## %s" % grp, ""]
        for c in comps:
            cid = bundle.deref(c.get("id"))
            if not (isinstance(cid, str) and re.match(r"^[a-z0-9_]+$", cid)):
                cid = c.get("descriptionKey", ".x.").split(".")[1]
            doc += ["## %s" % tr(c.get("nameKey", ""), cid), "",
                    "```python", 'c = get_component("%s")' % cid, "```", ""]
            if desc_of(c):
                doc += [desc_of(c), ""]
            meta = ["`%s: %s`" % (k, bundle.deref(c[k]))
                    for k in ("type", "shared", "scriptSlots", "allowsRemoteWrites") if k in c]
            if meta:
                doc += [" \u00b7 ".join(meta), ""]
            doc += [render_method(m, ".") for m in (c.get("methods") or [])]
            doc.append("---\n")
            index.append("- **%s** \u2014 `%s` (%s)"
                         % (tr(c.get("nameKey", ""), cid), cid, os.path.basename(fname)))
        index.append("")
        write(fname, "\n".join(doc))
    write("reference/components/README.md", "\n".join(index))
    counts["components"] = len(COMPONENTS)

    # -- object types -------------------------------------------------------
    index = ["# Object Types", "",
             "Objects returned by component methods \u2014 their properties and methods.", ""]
    for grp, types in group_by(reg["types"], "docsGroup").items():
        fname = "reference/types/%s.md" % slug(grp)
        doc = ["# %s" % grp, ""]
        index += ["## %s" % grp, ""]
        for t in types:
            doc += ["## `%s`" % t["typeName"], ""]
            if t.get("returnedBy"):
                doc += ["*Returned by: %s*" % t["returnedBy"], ""]
            doc += [render_method(m, ".") for m in (t.get("methods") or [])]
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
            if str(v).strip():
                counts["guides"] += 1
                doc += ["## `%s.%s`" % (section, k), "", str(v), "", "---", ""]
    write("machine-guides.md", "\n".join(doc))

    # -- seeded + example scripts -------------------------------------------
    seed_at = re.search(PATTERNS["seed_scripts"], bundle.s).start(1)
    rows = []
    for slot, entry in reg["seed_scripts"].items():
        if not isinstance(entry, dict):
            continue
        src = entry.get("source")
        if isinstance(src, dict) and "__ref__" in src:
            src = bundle.resolve(src["__ref__"], seed_at)
        rows.append((slot, entry.get("name"), src))

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
        "The Python source the game seeds into each machine's script slot \u2014 the\n"
        "working examples the tutorials build on.", normal))
    write("starter-scripts/CONTRACT-SOLUTIONS.md", render_scripts(
        "Contract Scripts \u2014 SPOILERS",
        "> **Spoiler warning.** These are the contract scaffolds shipped in the binary,\n"
        "> several of which contain the puzzle answers outright.", spoiler))
    counts["seeded"], counts["contracts"] = len(normal), len(spoiler)

    doc = ["# Example Script Library", "",
           "Ready-made example scripts the game offers inside each machine's editor,",
           "grouped by the machine type they are attached to.", ""]
    counts["examples"] = 0
    seen = set()
    for m in re.finditer(r"[\w$]+\(([\w$]+),(\[\{name:" + BT + r"[^" + BT + r"]+" + BT
                         + r",description:)", bundle.s):
        if m.start(2) in seen:
            continue
        seen.add(m.start(2))
        arr = parse_at(bundle.s, m.start(2))[0]
        if not all(isinstance(e, dict) and "source" in e for e in arr):
            continue
        doc += ["## `%s`" % bundle.refs.get(m.group(1), m.group(1)), ""]
        for e in arr:
            counts["examples"] += 1
            src = e.get("source")
            if isinstance(src, dict) and "__ref__" in src:
                src = bundle.resolve(src["__ref__"], m.start())
            doc += ["### %s" % e.get("name"), ""]
            if e.get("description"):
                doc += [e["description"], ""]
            doc += ["```python", (src or "").rstrip(), "```", ""]
    write("starter-scripts/example-library.md", "\n".join(doc))

    # -- stubs --------------------------------------------------------------
    stub_count = 0
    for key, blob in sorted(assets.items()):
        if key.startswith("/stubs/"):
            stub_count += 1
            write("stubs/" + key[len("/stubs/"):].replace("/", "_"), blob.decode("utf-8"))

    # -- index --------------------------------------------------------------
    write("README.md", """# Code: Terraform \u2014 Python Documentation

Extracted from `{exe}` (Tauri app, release `{release}`). All game content lives inside
the executable as brotli-compressed embedded assets; this bundle is everything in there
that documents the in-game Python API and language.

Regenerate with:

```bash
python tools/build_docs.py "<game install folder>" <output folder>
```

## Contents

| Path | What it is |
| --- | --- |
| [`stubs/`](stubs/) | The type stubs the game ships verbatim, for editor autocomplete |
| [`manual/`](manual/README.md) | The {manual} pages of the in-game DOCS panel |
| [`reference/global-functions.md`](reference/global-functions.md) | {globals} functions callable from any script |
| [`reference/builtins.md`](reference/builtins.md) | {builtins} interpreter builtins |
| [`reference/builtin-types.md`](reference/builtin-types.md) | Methods on `list`, `str`, `dict`, `set`, `tuple` |
| [`reference/language-features.md`](reference/language-features.md) | {lang} supported language features and unlock flags |
| [`reference/components/`](reference/components/README.md) | {components} components addressable via `get_component()` |
| [`reference/types/`](reference/types/README.md) | {types} object types returned by component methods |
| [`machine-guides.md`](machine-guides.md) | {guides} per-machine tutorial write-ups shown beside the editor |
| [`starter-scripts/`](starter-scripts/README.md) | The {seeded} scripts the game seeds into machines |
| [`starter-scripts/example-library.md`](starter-scripts/example-library.md) | {examples} ready-made examples offered in the machine editors |
| [`starter-scripts/CONTRACT-SOLUTIONS.md`](starter-scripts/CONTRACT-SOLUTIONS.md) | {contracts} contract scaffolds \u2014 **contains puzzle answers** |

## Where each part came from

- `stubs/` are real files embedded at `/stubs/*` in the binary. The game ships several
  copies of the same stub for different editor setups.
- Everything under `reference/` and `manual/` is reconstructed from the frontend
  JavaScript bundle, which holds the same API registries the in-game DOCS panel and
  autocomplete read from, joined against the game's English locale table.

The reference sections carry more than the stubs do: parameter names, parameter
descriptions, per-method examples, unlock gating, and prose descriptions that the stub
generator flattens away.

## About the runtime

There is no CPython here. The game implements its own Python-like tokenizer, parser and
evaluator in TypeScript, running in the app's webview (the Rust/Tauri side is just the
shell). So the language is a deliberate subset: every number is a float, the builtin set
is reduced, and `import` is limited. See
[`reference/language-features.md`](reference/language-features.md) for exactly what the
parser accepts, and [`reference/builtins.md`](reference/builtins.md) for what it gives you.
""".format(exe=os.path.basename(exe), release=release, **counts))

    print("\nwrote %s" % args.out_dir)
    for k in ("manual", "globals", "builtins", "lang", "components", "types",
              "guides", "seeded", "contracts", "examples"):
        print("  %-12s %d" % (k, counts[k]))
    print("  %-12s %d" % ("stubs", stub_count))


if __name__ == "__main__":
    main()
