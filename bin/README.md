# ct_sync — fill the game's script slots from this repo

When you add a script slot to a machine in Code: Terraform, the game creates an empty
`.py` file in the save's external-editor directory. `ct_sync.py` watches that directory
and fills each such file with the matching script from [`scripts/`](../scripts/), so the
repo stays the source of truth and the game just receives copies.

```bash
python bin/ct_sync.py phases     # the phases in the tree, and what each one covers
python bin/ct_sync.py use p3     # play phase 3 from now on
python bin/ct_sync.py status     # what maps to what, and what each save file would do
python bin/ct_sync.py once       # fill everything fillable right now, then exit
python bin/ct_sync.py watch      # keep running; fill files as the game creates them
```

## Where it looks

| | Default | Override |
| --- | --- | --- |
| Save directory | newest `%APPDATA%\io.codeterraform.game\save_*_scripts` | `--save-dir` / `CT_SAVE_DIR` |
| Script tree | `scripts/` in this repo | `--scripts-dir` / `CT_SCRIPTS_DIR` |
| Phase being played | `scripts/.current`, else the highest phase present | `--phase` / `CT_PHASE` |

The active save changes with each playthrough, so auto-detection picks the most recently
modified one and prints which it chose. `watch` resolves this once at startup — if you
switch saves mid-session, restart it.

## Matching

A save file matches a repo script when their names agree **after dropping a trailing
`_<number>`**. So `phase02/power/solar_1.py` fills `solar_1.py`, `solar_2.py` … `solar_6.py`,
and `phase02/bio/bio_lab_1.py` fills `bio_lab_3.py`. Below the phase directory, the
grouping (`power/`, `bio/`, `atmos/`) is purely for organisation; only the file name matters.

If two repo files in the *same phase* reduce to the same base name, neither is used and
`status` flags the ambiguity rather than guessing. One file per base per phase.

## Phases

The game is played in stages, and each stage wants different scripts — the solar script
that was right with three panels and no battery bank is not the one you want later. The
top level of `scripts/` is therefore the **phase**:

```
scripts/
├── .current              ← "phase02"  (git-ignored; per-playthrough state)
├── common/               ← phase-independent: contract solutions, one-offs
│   └── contract/
├── phase01/
│   └── bio/              ← the first biology loop, superseded
└── phase02/
    ├── lib/              ← libraries are phase-scoped too
    ├── atmos/  bio/  control_room/  factory/
    └── harvesting/  power/  rover/  sensor/
```

A phase directory is anything matching `phaseNN` (`phase2`, `p2` and `phase02-orbital`
also parse; the number is what orders them). Which phase is in force is decided by, most
specific first:

1. **The marker in the game file** — `xyz p1` (also `xyz-p1`, `xyz:phase01`) fills that
   one slot from that one phase. It is exact: if the phase has no version of the script
   it says so rather than quietly serving another, because you asked for a specific one.
2. **`scripts/.current`** — one line naming the phase, written by `ct_sync.py use p3`.
   Editing it while `watch` runs re-resolves and re-sweeps immediately. Git-ignored:
   it is where *you* are in *this* playthrough, not part of the scripts.
3. **`--phase p3`** / `CT_PHASE`.
4. **The highest phase present**, so a fresh clone with no `.current` works. Every
   command prints the phase it chose and the chain behind it.

### Falling back

A script the active phase does not have comes from the newest earlier phase that does,
and then from `common/`:

```
Phase    phase03 (scripts\.current)  falling back to phase02 -> phase01 -> common
```

That is what makes a rewrite incremental. Create `scripts/phase03/`, put the one script
you have rewritten in it, and the other eighteen keep coming from `phase02` until you
get to them. `phases` is the checklist:

```
phase03 resolves 39 of 39 script(s): 1 its own, 23 inherited, 15 shared from common/.
  inherit  bio_collector            from phase02  (not rewritten for phase03 yet)
  ...
```

`common/` is not a fallback so much as a decision: a contract puzzle has one right
answer and no phase owns it. `phases` counts those separately from inherited scripts for
that reason.

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
  pull  solar_3.py   -> scripts\phase02\power\solar_1.py  [zyx, phase02, solar_3 -> solar_1]
```

It is the mirror of a fill: the slot id is rewritten the other way (`solar_3` → `solar_1`),
`zyx p1` targets one phase and `.current` / `--phase` decide otherwise, and an
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

## Libraries (`lib/`)

Shared code lives in `scripts/<phase>/lib/*.py` and is **mirrored** into the save's
`lib/`, not slot-matched: the game never creates an empty library for us and there is no
instance number to renumber, so the repo is simply the source of truth.

```
  lib   lib/store.py   <- scripts\phase02\lib\store.py   (new: Import as Game Library)
```

Libraries are phase-scoped and resolved **per file** along the same chain as scripts, so
a new phase can rewrite one helper and inherit the rest. A library the active phase does
not provide but the save still holds is reported and left alone — the game tracks it in
`libraryScripts` and an older script may still import it:

```
  lib   lib/orbital.py   in the save but not in phase02 (only phase03); left alone
```

A file new to the save needs one in-game step, as that note says: the editor offers
**Import as Game Library** for an unregistered file under `lib/`. After that the game
tracks it in `libraryScripts` and picks up later edits automatically.

A save copy that has diverged, because you edited it in game, is reported and **not**
clobbered. Mark it with `xyz` to let the repo win. `build_index` skips `lib/`
entirely, so a library is never mistaken for a machine script.

Libraries cannot see a caller's globals — the game docs are explicit that "caller-local
names are not" in scope. `get_component()` and the other top-level game functions *are*
available, so a helper should resolve shared components itself rather than expect the
importing script's variables. `self` and `panel` do not exist in a library; pass the
machine in when a helper needs to act for the caller.

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
--phase            Phase being played (phase03, p3, 3); overrides scripts/.current
--poll             Poll instead of filesystem events (watch only)
```
