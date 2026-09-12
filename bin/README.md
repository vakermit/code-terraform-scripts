# ct_sync — fill the game's script slots from this repo

When you add a script slot to a machine in Code: Terraform, the game creates an empty
`.py` file in the save's external-editor directory. `ct_sync.py` watches that directory
and fills each such file with the matching script from [`scripts/`](../scripts/), so the
repo stays the source of truth and the game just receives copies.

```bash
python bin/ct_sync.py status     # what maps to what, and what each save file would do
python bin/ct_sync.py once       # fill everything fillable right now, then exit
python bin/ct_sync.py watch      # keep running; fill files as the game creates them
```

## Where it looks

| | Default | Override |
| --- | --- | --- |
| Save directory | newest `%APPDATA%\io.codeterraform.game\save_*_scripts` | `--save-dir` / `CT_SAVE_DIR` |
| Script tree | `scripts/` in this repo | `--scripts-dir` / `CT_SCRIPTS_DIR` |

The active save changes with each playthrough, so auto-detection picks the most recently
modified one and prints which it chose. `watch` resolves this once at startup — if you
switch saves mid-session, restart it.

## Matching

A save file matches a repo script when their names agree **after dropping a trailing
`_<number>`**. So `scripts/power/solar_1.py` fills `solar_1.py`, `solar_2.py` … `solar_6.py`,
and `scripts/bio/bio_lab_1.py` fills `bio_lab_3.py`. Subdirectories under `scripts/` are
purely for organisation; only the file name matters.

If two repo files reduce to the same base name, neither is used and `status` flags the
ambiguity rather than guessing.

## Variants: early / mid / late, v1 / v2

Put alternative versions of a script in **subdirectories** of its group:

```
scripts/bio/
├── .current              ← "mid"   (git-ignored; per-playthrough state)
├── early/
│   ├── bio_collector_1.py
│   ├── bio_exchange_1.py
│   └── bio_lab_1.py
└── mid/
    └── bio_lab_1.py      ← only the lab has a mid version so far
```

The directory name is the variant tag. Which one fills a slot is decided by, most
specific first:

1. **The marker in the game file** — `xyz mid` (also `xyz-mid`, `xyz:mid`) pulls that
   variant into that one slot. Useful for trying the new version on a single machine.
2. **`.current` in the group directory** — a one-line text file naming the default for
   everything under it. `echo mid > scripts/bio/.current`. Changing it while `watch`
   runs re-sweeps immediately. It is git-ignored because it is where *you* are in *this*
   playthrough, not part of the scripts.
3. **`--variant NAME`** / `CT_VARIANT` — a global default for groups with no `.current`.
4. **A plain file beside the variant dirs** (`bio/bio_lab_1.py` next to `bio/mid/`) is
   the implicit default when nothing else chooses.

If none of those resolve it, the slot is skipped and `status` says which variants exist.

**A variant directory can be partial.** Above, `bio_collector` has only one version, so
it resolves to `early/` no matter what `.current` says — you can start `mid/` with a
single file and grow it. `status` shows every group's variants with the chosen one in
brackets and the reason.

Why a text file rather than a symlink: symlinks need Developer Mode or admin on
Windows and git's symlink support there is opt-in; a one-line file does the same job
with none of that.

## What counts as fillable

A file is filled when it holds **no code**: blank, whitespace, comments only, or a single
docstring — which is what the game leaves in a fresh slot. A file with real statements is
never overwritten. `--strict` narrows this to truly blank files.

The game does not always create the empty file. When it doesn't, create it yourself with
**`xyz`** on the first line (`xyz`, `# xyz`, `"xyz"` all work) and it becomes fillable
regardless of content. The marker is an explicit request, so it also overrides the
"already has code" guard — drop `# xyz` on top of a stale script to force a re-sync. The
old contents are copied to `.ct-sync-backups/` first. `--magic WORD` changes the marker,
`--magic ""` disables it.

## The other direction: `zyx` pulls a game file into the repo

Tuned a script in the game's editor and want to keep it? Put **`zyx`** on its first line.
The next sweep copies it into the matching repo script and removes the marker:

```
  pull  solar_3.py   -> scripts\power\solar_1.py  [zyx, solar_3 -> solar_1]
```

It is the mirror of a fill: the slot id is rewritten the other way (`solar_3` → `solar_1`),
`zyx mid` targets a variant and `.current` / `--variant` decide otherwise, and an
ambiguous target is refused rather than guessed. The repo file's previous contents go
to `.ct-sync-backups/` first, though the repo is git — `git diff` is the real safety net.

With no matching repo script the content lands in `scripts/_unmatched/`, so "write it
in the game, then `zyx` it" is a valid way to author a new script. A marked file that
holds no code is refused, because that is the one way a pull could wipe a script.

`--pull-magic WORD` / `CT_PULL_MAGIC` changes the marker; empty disables it.

## Slot numbers inside the script

When `solar_1.py` fills `solar_3.py`, the script's **own** id is rewritten to match the
slot: `solar_1` → `solar_3`, wherever it appears. Nothing else is touched. Other numbered
ids (`bio_exchange_1`, `rover_2`) name *different* machines with their own numbering, and
comments that enumerate ids ("bio_exchange_1, bio_exchange_2, …") would be mangled by a
blanket rename. Instead they are listed after the fill so you can check them:

```
  fill  bio_collector_3.py  <- scripts\bio\bio_collector_1.py  [bio_collector_1 -> bio_collector_3]
        left as-is (check these): bio_exchange_1, bio_exchange_2
```

A source with no number (`boot.py`) is never rewritten — its base is a bare word that
collides with real API names. `--no-renumber` copies verbatim.

The robust fix is to not hard-code ids at all: use `self` for the machine the script
runs on, and probe for siblings by type (see `find_machine()` in the `bio/` scripts).

## Unmatched files

A game file with no match is copied into **`scripts/_unmatched/`** (git-ignored) so it is
in front of you. Write it there, then drag it into the right folder; the watcher sees it
arrive and fills the game's copy. Delete it if the slot isn't worth a script.

`_unmatched/` is never used as a source, staged files are never overwritten (you may be
mid-edit), and only a *truly blank* staged file is removed once a real match appears.

## The repo side is watched too

`watch` also watches `scripts/` recursively. Adding, editing, renaming or deleting a
script re-reads the tree and re-sweeps the save, so a script you add can fill an empty
file that was already waiting for it. Edits don't reach already-filled game files (they
have code); use the `xyz` marker for that.

## What it never touches

- Anything that isn't a top-level `.py` — so `.pyi` stubs, `codeterraform-scripts.json`,
  `pyrightconfig.json`, `typeshed-LICENSE.txt`
- `user_stubs.py` (the game promises never to overwrite it either)
- the `lib/` subdirectory
- the game's own `.codeterraform-retired-*` and `.codeterraform-write.bak` files

Writes go to a temp file in the same directory and are then atomically replaced, so the
game never observes a half-written script.

## Options

```
--save-dir, -s     Save scripts directory (auto-detects the newest save)
--scripts-dir      Repo script tree to sync from
--dry-run, -n      Report what would change without writing
--verbose, -v      Also report files that were skipped
--strict           Only fill truly blank files
--no-renumber      Copy verbatim; do not rewrite the script's own id
--magic            Fill marker (default xyz); empty string disables
--pull-magic       Pull marker (default zyx); empty string disables
--variant          Default variant for groups with no .current file
--poll             Poll instead of filesystem events (watch only)
```
