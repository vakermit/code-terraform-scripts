# build_docs — extract the game's Python documentation

Code: Terraform ships as a single Tauri executable with every asset embedded inside it,
brotli-compressed. Among those assets is the frontend JavaScript, and inside *that* are
the registries the in-game DOCS panel and editor autocomplete read from: every component,
method, parameter, return value, raised exception, manual page and training lesson.
`build_docs.py` pulls them out and writes a browsable Markdown bundle.

```bash
python tools/build_docs.py "<game install folder>" <output folder>
python tools/build_docs.py "E:/SteamLibrary/steamapps/common/CodeTerraform" docs
```

Takes about a minute. Add `--dump-assets DIR` to also write every decompressed asset
(large — includes all audio and fonts).

## What you get

```
<output>/
├── README.md                 index, with the "Built from" fingerprint
├── .extracted-from.json      the same fingerprint, for tooling
├── manual/                   every page of the in-game DOCS panel, in game order
├── reference/
│   ├── global-functions.md   boot(), get_component(), …
│   ├── builtins.md           the interpreter's builtins
│   ├── builtin-types.md      methods on list / str / dict / set / tuple / …
│   ├── language-features.md  the supported Python subset and its unlock flags
│   ├── components/           everything get_component() can return, by group
│   └── types/                objects returned by component methods, by group
├── machine-guides.md         per-machine tutorial text shown beside the editor
├── training-lessons.md       the guided lesson course, with solutions   (retail)
├── starter-scripts/          seeded scripts and example library          (demo only)
└── stubs/                    .pyi stubs shipped verbatim                  (demo only)
```

The reference sections carry more than the game's own generated stubs do: parameter
descriptions, examples, raised exceptions and unlock gating.

## Provenance

The output is derived from a binary you don't own, so each bundle records exactly which
one. `.extracted-from.json` holds the executable's SHA-256, size, modification time,
release tag (when the install has a `.from-release` file), the extraction time, and the
section counts; the README shows the same table. On a rerun the tool hashes the installed
exe first and says so if it hasn't changed since the last extract — so you can tell
whether a game update is worth a new commit in your docs repo.

## Keeping it out of the public repo

`docs/` and `demo_docs/` are git-ignored here. Keep your extracts in a separate private
repository per game build:

```bash
python tools/build_docs.py "<install>" docs
cd docs && git init -b main && git add -A && git commit -m "Extract from <build>"
```

Nested independent repos rather than submodules, so the public repo has no reference to
the private one and clones cleanly for anyone.

## How it survives game updates

Everything is located by **content**, never by file name, minified variable name or byte
offset — all of which change on every rebuild of the game:

- The embedded-asset table is found by anchoring on a path every Tauri frontend has
  (`/index.html`), locating the pointer to it, and growing a window around that record
  until no more records appear at the edges.
- Each registry is found by a stable English id in its first entry — `{typeName:'Component'}`,
  `{id:'getting_started'}`, `{name:'print'}` — searched across every JS chunk, since the
  retail build splits the frontend into ~40 of them.
- The locale table is found as the object containing `app:{title:…}`, then flattened into
  one key → string map, because it mixes nested sections, partially-dotted keys, and
  fully-qualified keys stored under unrelated sections.

If a registry can't be found the tool exits naming it, rather than emitting a partial
bundle.

`jsparse.py` is a small parser for the subset of JavaScript the bundler emits for these
literals: object and array literals, template strings, `!0`/`!1`, spreads, accessor
getters (`get description(){return L("key")}` → recovered as `descriptionKey`), and
helper calls whose arguments matter (`nI("line", "line")` line-joiners). `pe.py` walks
PE sections to map virtual addresses to file offsets.

## Known limits

- Method groups spliced in by a factory *call* (`...j0(v0, "gas", …)`) can't be evaluated
  and are skipped; in the retail build this affects a handful of fluid-tank methods.
- Exception constructors get their description from a conditional getter that fills in a
  parent class at runtime; the tool emits the base template ("Built-in exception.")
  rather than an unfilled placeholder.
- The retail build vendors real CPython typeshed stubs for external-editor support.
  They are standard library typing data, not game documentation, and are not extracted.
