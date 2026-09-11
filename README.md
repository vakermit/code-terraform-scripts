# code-terraform-game

Scripts and tooling for [Code: Terraform](https://store.steampowered.com/app/868160/Code_Terraform/),
a game where you terraform a planet by writing Python.

Three things live here:

| Path | What it is |
| --- | --- |
| [`scripts/`](scripts/) | My machine scripts, grouped by system (`power/`, `atmos/`, `bio/`, `sensor/`, `contract/`) |
| [`bin/ct_sync.py`](bin/README.md) | Watches the game's save directory and fills newly created script slots from `scripts/` |
| [`tools/build_docs.py`](tools/README.md) | Extracts the in-game Python documentation from the game executable into Markdown |

## Setup

With [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

Or with pip into an environment of your own:

```bash
python -m pip install -r requirements.txt
```

Python 3.11+ on Windows. The tools read the game's install folder and its save
directory under `%APPDATA%`; nothing here modifies the game.

## Everyday use

Start the watcher once, then play:

```bash
uv run bin/ct_sync.py watch        # or: python bin/ct_sync.py watch
```

Whenever the game creates an empty script file for a machine, the watcher fills it with
the matching script from `scripts/`. Add a script to `scripts/` and it is picked up
immediately. Details, matching rules and the safety guards are in
[`bin/README.md`](bin/README.md).

## The game documentation

The game ships its API reference, manual pages and training lessons inside its
executable. `tools/build_docs.py` pulls them out as a browsable Markdown bundle:

```bash
uv run tools/build_docs.py "E:/SteamLibrary/steamapps/common/CodeTerraform" docs
```

That content belongs to the game's authors, so **it is not in this repository** — `docs/`
and `demo_docs/` are git-ignored, and I keep my own extracts in separate private repos.
Run the extractor against your own install to get your own copy; each bundle records
exactly which binary it was built from in `.extracted-from.json`. See
[`tools/README.md`](tools/README.md).

## Layout

```
.
├── bin/
│   └── ct_sync.py          save-directory sync watcher
├── scripts/                machine scripts, by system
│   └── _unmatched/         (ignored) staging area the watcher fills — see bin/README.md
├── tools/
│   ├── build_docs.py       documentation extractor
│   ├── jsparse.py          parser for the minified JS object literals the game bundles
│   └── pe.py               minimal PE section walker
├── docs/                   (ignored) extracted full-game docs — separate private repo
└── demo_docs/              (ignored) extracted demo docs      — separate private repo
```
