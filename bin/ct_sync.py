#!/usr/bin/env python
"""Sync repo scripts into a Code: Terraform save's external-editor directory.

The game creates a script file the moment you add a script slot to a machine, but
leaves it empty. This watches the save directory and, whenever such an empty `.py`
appears, fills it with the matching script from this repo's `scripts/` tree.

    python bin/ct_sync.py status          # show what maps to what
    python bin/ct_sync.py once            # one pass over what is there now
    python bin/ct_sync.py watch           # keep running and fill files as they appear

`watch` watches both sides: the save directory for files the game creates, and this
repo's `scripts/` tree for scripts you add, edit or rename. A repo change re-reads the
tree and re-sweeps the save, so a script you add now can fill an empty file that was
already waiting for it.

Matching ignores a trailing `_<number>`, so `scripts/bio/bio_lab_1.py` fills the
save's `bio_lab_1.py`, `bio_lab_2.py`, and so on.

Variants live in subdirectories: `bio/early/bio_lab_1.py` and `bio/mid/bio_lab_1.py`.
Which one is used is decided by, most specific first: the marker (`xyz mid`), a
`.current` file in the group directory naming a default (git-ignored), `--variant`,
then a plain file beside the variant directories. Otherwise the slot is skipped and
`status` lists the choices. A base with a single file is never ambiguous, so a
variant directory can be partial.

An empty game file with no match is copied into `scripts/_unmatched/` (untracked) so
it is in front of you: write it, drag it into the right folder, and the watcher fills
the game's copy. Delete it if the slot is not worth a script. `_unmatched/` is never
used as a source, and a blank staged file is removed once a real match exists.

When the slot number differs, the script's *own* id is rewritten to match the slot
(`oxygen_gen_1` -> `oxygen_gen_2`). Other numbered ids are left alone and reported,
because they name different machines with their own numbering, and comments that
enumerate ids would be mangled by a blanket rename. Use `--no-renumber` to disable.

The game does not always create that empty file. When it does not, make the file
yourself with `xyz` on the first line and it becomes fillable whatever else it holds
— bare, commented or quoted all count. That marker is an explicit request, so it also
overrides the "already has code" guard; the old contents are copied to
`.ct-sync-backups/` first. `--magic` changes the word, `--magic ""` turns it off.

`zyx` on the first line goes the other way: the game file is copied back into the
matching repo script (slot id rewritten to the repo file's, previous content backed up),
and the marker is removed from the game file. `zyx mid` targets a variant. With no
matching repo script the content lands in `_unmatched/`. A marked file holding no code
is refused, since that is the one way a pull could wipe a script.

Only top-level `.py` files are touched. `.pyi` stubs, `.json`, `user_stubs.py`, the
`lib/` subdirectory and the game's own scratch files are left alone, and an unmarked
file that already contains code is never overwritten.
"""
import ast
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SCRIPTS = REPO / "scripts"
BACKUP_DIR = REPO / ".ct-sync-backups"
UNMATCHED = "_unmatched"            # under scripts/; staged, never a source
CURRENT = ".current"                # per-directory variant pointer; git-ignored
SAVE_GLOB = "save_*_scripts"
GAME_DIR = "io.codeterraform.game"

# The game owns these; never write to them.
RESERVED = {"user_stubs.py"}
SKIP_DIRS = {"lib"}
SKIP_SUFFIXES = (".codeterraform-write.bak",)
SKIP_PATTERNS = (re.compile(r"\.codeterraform-retired-"),)
TRAILING_INDEX = re.compile(r"_\d+$")
DEFAULT_MAGIC = "xyz"               # game file -> filled from the repo
DEFAULT_PULL = "zyx"                # game file -> copied back into the repo

app = typer.Typer(add_completion=False, help=__doc__)


@dataclass
class Options:
    save_dir: Path
    scripts_dir: Path
    strict: bool = False
    dry_run: bool = False
    verbose: bool = False
    renumber: bool = True
    magic: str = DEFAULT_MAGIC
    pull: str = DEFAULT_PULL
    variant: str = ""

    @property
    def unmatched_dir(self) -> Path:
        return self.scripts_dir / UNMATCHED


def show(path: Path) -> str:
    """Repo-relative when inside the repo, absolute otherwise (--scripts-dir may point anywhere)."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def err(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)


def warn(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.YELLOW)


def ok(msg: str) -> None:
    typer.secho(msg, fg=typer.colors.GREEN)


# ------------------------------------------------------------------ discovery
def appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def discover_save() -> Optional[Path]:
    """Newest `save_*_scripts` directory, since the active save changes per playthrough."""
    root = appdata() / GAME_DIR
    if not root.is_dir():
        return None
    saves = [p for p in root.glob(SAVE_GLOB) if p.is_dir()]
    return max(saves, key=lambda p: p.stat().st_mtime) if saves else None


def resolve_save(save_dir: Optional[Path]) -> Path:
    if save_dir is None:
        save_dir = discover_save()
        if save_dir is None:
            err("No save directory found under %s." % (appdata() / GAME_DIR))
            err("Pass --save-dir, or set CT_SAVE_DIR.")
            raise typer.Exit(2)
        typer.echo("Save (auto-detected): %s" % save_dir)
    if not save_dir.is_dir():
        err("Not a directory: %s" % save_dir)
        raise typer.Exit(2)
    return save_dir


# -------------------------------------------------------------------- mapping
def base_name(stem: str) -> str:
    """`bio_lab_1` -> `bio_lab`. Slot numbers differ between repo and save."""
    return TRAILING_INDEX.sub("", stem)


def split_index(stem: str):
    """`bio_lab_1` -> ('bio_lab', '1');  `boot` -> ('boot', None)."""
    m = re.search(r"_(\d+)$", stem)
    return (stem[:m.start()], m.group(1)) if m else (stem, None)


def renumber(text: str, src_stem: str, dst_stem: str):
    """Point the script's *own* instance id at the slot it is being filled into.

    Only the source's exact self id is rewritten — `oxygen_gen_1` -> `oxygen_gen_2`
    when `oxygen_gen_1.py` fills `oxygen_gen_2.py`. Every other numbered id is left
    alone on purpose: ids like `bio_exchange_1` name a *different* machine with its
    own numbering, and comments that enumerate ids ("bio_exchange_1, bio_exchange_2,
    ...") would be turned into nonsense by a blanket rename.

    A source with no number is never rewritten: its base is a bare word like `boot`
    or `power`, which collides with real API names.
    """
    src_base, src_num = split_index(src_stem)
    if src_num is None or src_base != base_name(dst_stem) or src_stem == dst_stem:
        return text, 0, None
    old = "%s_%s" % (src_base, src_num)
    pattern = re.compile(r"(?<![0-9A-Za-z_])" + re.escape(old) + r"(?![0-9A-Za-z_])")
    new_text, count = pattern.subn(dst_stem, text)
    return new_text, count, ("%s -> %s" % (old, dst_stem) if count else None)


NUMBERED_ID = re.compile(r"(?<![0-9A-Za-z_])([a-z][a-z0-9]*(?:_[a-z0-9]+)*_\d+)(?![0-9A-Za-z_])")


def other_numbered_ids(text: str, own_base: str):
    """Numbered ids that are not the script's own — the tool deliberately leaves these."""
    return sorted({t for t in NUMBERED_ID.findall(text) if base_name(t) != own_base})


@dataclass
class Group:
    """Every repo script sharing one base name, keyed by variant.

    Variants are subdirectories: `bio/early/bio_lab_1.py` and `bio/mid/bio_lab_1.py`
    are variants `early` and `mid` of `bio_lab`, rooted at `bio/`. A file sitting
    directly in the root (`bio/bio_lab_1.py`) has the empty tag and is the implicit
    default. A base with a single candidate is never ambiguous, whatever its path —
    so a variant directory can start with one file and grow.
    """
    base: str
    root: Path
    candidates: dict                 # tag -> path

    @property
    def tags(self):
        return sorted(t for t in self.candidates if t)

    @property
    def only(self):
        return next(iter(self.candidates.values())) if len(self.candidates) == 1 else None

    def current(self) -> str:
        """The tag named by `<root>/.current`, if any."""
        try:
            return (self.root / CURRENT).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def select(self, want: Optional[str], default: str):
        """Pick a path. Returns (path, how) or (None, why)."""
        if self.only is not None:
            return self.only, ""
        if want:
            if want in self.candidates:
                return self.candidates[want], "variant %s (marker)" % want
            return None, "no variant %r (have: %s)" % (want, ", ".join(self.tags))
        cur = self.current()
        if cur:
            if cur in self.candidates:
                return self.candidates[cur], "variant %s (.current)" % cur
            return None, ".current says %r, but %s has only: %s" % (cur, self.base, ", ".join(self.tags))
        if default and default in self.candidates:
            return self.candidates[default], "variant %s (--variant)" % default
        if "" in self.candidates:
            return self.candidates[""], "untagged default"
        return None, "variants: %s (set %s or use %s)" % (
            ", ".join(self.tags), show(self.root / CURRENT), "the marker")


def build_index(scripts_dir: Path):
    """Map base name -> Group. Returns (index, conflicts).

    `_unmatched/` is skipped: it holds files staged *for* writing, and treating them
    as sources would fill an empty game file with an empty repo file.
    """
    by_base = {}
    for path in sorted(scripts_dir.rglob("*.py")):
        if UNMATCHED in path.relative_to(scripts_dir).parts:
            continue
        by_base.setdefault(base_name(path.stem), []).append(path)

    index, conflicts = {}, {}
    for base, paths in by_base.items():
        root = Path(os.path.commonpath([str(p.parent) for p in paths]))
        candidates, clash = {}, []
        for p in paths:
            rel = p.parent.relative_to(root).parts
            tag = rel[0] if rel else ""
            if tag in candidates:
                clash.append(p)             # two files, same variant, same base
            else:
                candidates[tag] = p
        if clash:
            conflicts[base] = sorted(list(candidates.values()) + clash)
        else:
            index[base] = Group(base, root, candidates)
    return index, conflicts


def report_conflicts(conflicts) -> None:
    for key, paths in sorted(conflicts.items()):
        warn("ambiguous base name %r, skipped: %s" % (key, ", ".join(show(p) for p in paths)))


def is_candidate(path: Path, save_dir: Path) -> bool:
    """Top-level `.py` files the game made for us — nothing else."""
    if path.suffix != ".py" or path.name in RESERVED:
        return False
    if path.name.endswith(SKIP_SUFFIXES) or any(p.search(path.name) for p in SKIP_PATTERNS):
        return False
    try:
        rel = path.resolve().relative_to(save_dir.resolve())
    except ValueError:
        return False
    return len(rel.parts) == 1 and not (set(rel.parts[:-1]) & SKIP_DIRS)


def is_empty(text: str, strict: bool) -> bool:
    """Empty means 'holds no code'.

    Blank and whitespace-only always count. Unless --strict, a file holding only
    comments and/or a single docstring counts too: that is what the game leaves in a
    fresh slot, and it is not work worth keeping.
    """
    if not text.strip():
        return True
    if strict:
        return False
    try:
        body = ast.parse(text).body
    except SyntaxError:
        return False                      # unparseable: assume it is someone's work
    if not body:
        return True                       # comments only
    return (len(body) == 1
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str))


def _first_real_line(text: str):
    for i, line in enumerate(text.splitlines()):
        if line.strip():
            return i, line
    return None, None


def _unquote_marker(line: str) -> str:
    line = line.strip().lstrip("#").strip()
    for quote in ('"""', "'''", '"', "'"):
        if line.startswith(quote) and line.endswith(quote) and len(line) > 2 * len(quote):
            return line[len(quote):-len(quote)].strip()
    return line


def parse_magic(text: str, magic: str):
    """(marked, variant) from the file's first real line.

    The game does not always create the empty file, so this is the manual way in:
    make the file yourself with `xyz` at the top and it becomes fillable. Accepted
    bare, commented, or quoted — `xyz`, `# xyz`, `"xyz"`, `\"\"\"xyz\"\"\"` — because
    which one you type should not matter. `xyz mid` (also `xyz-mid`, `xyz:mid`)
    additionally asks for the `mid` variant of the script.
    """
    if not magic:
        return False, None
    _, line = _first_real_line(text)
    if line is None:
        return False, None
    token = _unquote_marker(line)
    if token.lower() == magic.lower():
        return True, None
    m = re.match(re.escape(magic) + r"[\s\-:/]+([A-Za-z0-9_][\w-]*)$", token, re.IGNORECASE)
    return (True, m.group(1)) if m else (False, None)


def has_magic(text: str, magic: str) -> bool:
    return parse_magic(text, magic)[0]


def strip_magic(text: str, magic: str) -> str:
    """Drop the marker line so a staged copy starts clean."""
    if not has_magic(text, magic):
        return text
    i, _ = _first_real_line(text)
    lines = text.splitlines(keepends=True)
    return "".join(lines[:i] + lines[i + 1:])


def read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------- sync
def stage_unmatched(path: Path, text: str, opts: Options) -> bool:
    """Copy an unmatched game file into `scripts/_unmatched/` to be written.

    Never overwrites: a file already there may be mid-edit.
    """
    dest = opts.unmatched_dir / path.name
    if dest.exists():
        return False
    if opts.dry_run:
        ok("  would stage %-23s -> %s" % (path.name, show(dest)))
        return True
    try:
        opts.unmatched_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(strip_magic(text, opts.magic), encoding="utf-8", newline="\n")
    except OSError as exc:
        err("  fail  %-28s %s" % (path.name, exc))
        return False
    ok("  stage %-28s -> %s   (write it, then move it into place)"
       % (path.name, show(dest)))
    return True


def tidy_unmatched(index, opts: Options) -> None:
    """Remove *blank* staged files once a real match exists for them.

    Only truly blank files go — anything with so much as a comment is someone's
    start on a script and stays.
    """
    if not opts.unmatched_dir.is_dir():
        return
    for path in sorted(opts.unmatched_dir.glob("*.py")):
        group = index.get(base_name(path.stem))
        if group is None:
            continue
        matched, _ = group.select(None, opts.variant)
        if matched is None:
            continue                      # exists but unresolved: leave the stage copy
        text = read(path)
        if text is None or text.strip():
            continue
        if opts.dry_run:
            typer.echo("  would drop %-24s (blank, now matched by %s)"
                       % (show(path), show(matched)))
            continue
        try:
            path.unlink()
            typer.echo("  drop  %-28s blank, now matched by %s" % (show(path), show(matched)))
        except OSError:
            pass


def backup(path: Path) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, BACKUP_DIR / ("%s.%s.py" % (path.stem, stamp)))


def write_atomic(path: Path, body: str) -> bool:
    """Temp file in the same directory, then replace: no reader sees a half-written file."""
    tmp = path.with_name(path.name + ".ct-sync-tmp")
    try:
        tmp.write_text(body, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        err("  fail  %-28s %s" % (path.name, exc))
        tmp.unlink(missing_ok=True)
        return False


def pull_file(path: Path, text: str, want: Optional[str], index, opts: Options) -> bool:
    """Copy a game file marked `zyx` back into the repo, then drop the marker.

    The reverse of a fill: the game's slot id is rewritten to the repo file's
    (`bio_lab_3` -> `bio_lab_1`), the repo file is backed up before being replaced,
    and the marker is removed from the game file so it is not pulled again. With no
    matching repo script the content lands in `_unmatched/`, ready to drag into place.
    """
    body = strip_magic(text, opts.pull)
    if is_empty(body, strict=False):
        warn("  skip  %-28s marked %r but holds no code; nothing to pull" % (path.name, opts.pull))
        return False

    group = index.get(base_name(path.stem))
    if group is not None:
        target, how = group.select(want, opts.variant)
        if target is None:
            warn("  skip  %-28s %s" % (path.name, how))
            return False
    else:
        target, how = opts.unmatched_dir / path.name, "new, staged"

    note = None
    if opts.renumber:
        body, _, note = renumber(body, path.stem, target.stem)
    parts = [opts.pull] + ([how] if how else []) + ([note] if note else [])
    suffix = "  [%s]" % ", ".join(parts)

    if opts.dry_run:
        ok("  would pull %-24s -> %s%s" % (path.name, show(target), suffix))
        return True

    existing = read(target) if target.exists() else None
    if existing != body:
        if existing is not None and existing.strip():
            backup(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not write_atomic(target, body):
            return False
        ok("  pull  %-28s -> %s%s" % (path.name, show(target), suffix))
        if note:
            others = other_numbered_ids(body, base_name(target.stem))
            if others:
                warn("        left as-is (check these): %s" % ", ".join(others))
    else:
        typer.echo("  pull  %-28s -> %s   already identical" % (path.name, show(target)))

    # Drop the marker so the next sweep treats this as an ordinary script with code.
    write_atomic(path, strip_magic(text, opts.pull))
    return True


def sync_file(path: Path, index, opts: Options, quiet_skips: bool = True) -> bool:
    """Fill one save script from the repo. True if it was written."""
    if not is_candidate(path, opts.save_dir):
        return False
    text = read(path)
    if text is None:
        return False
    pulled, want = parse_magic(text, opts.pull)
    if pulled:
        return pull_file(path, text, want, index, opts)
    marked, want = parse_magic(text, opts.magic)
    if not marked and not is_empty(text, opts.strict):
        if not quiet_skips:
            typer.echo("  skip  %-28s already has code" % path.name)
        return False

    group = index.get(base_name(path.stem))
    if group is None:
        # A marked file is an explicit request, so say so — but once, when it is
        # first staged, not on every sweep for as long as it stays unmatched.
        first_time = not (opts.unmatched_dir / path.name).exists()
        if marked and (first_time or not quiet_skips):
            warn("  skip  %-28s marked %r but no match in scripts/" % (path.name, opts.magic))
        elif not marked and not quiet_skips:
            typer.echo("  skip  %-28s no match in scripts/" % path.name)
        stage_unmatched(path, text, opts)
        return False

    source, how = group.select(want, opts.variant)
    if source is None:
        # Several variants and nothing chose between them. A marked file asked
        # explicitly, so always say why; otherwise only when verbose.
        if marked or not quiet_skips:
            warn("  skip  %-28s %s" % (path.name, how))
        return False

    body = read(source)
    if body is None:
        err("  fail  %-28s cannot read %s" % (path.name, source))
        return False

    note = None
    if opts.renumber:
        body, _, note = renumber(body, source.stem, path.stem)
    parts = ([opts.magic] if marked else []) + ([how] if how else []) + ([note] if note else [])
    suffix = "  [%s]" % ", ".join(parts) if parts else ""

    # Idempotence guard. A repo script that is itself only comments still counts
    # as "empty" after it is copied in, and our own write fires a save event — so
    # without this, `watch` would rewrite such a file forever.
    if text == body:
        return False

    if opts.dry_run:
        ok("  would fill %-24s <- %s%s" % (path.name, show(source), suffix))
        return True

    if text.strip():                      # had a stub worth keeping a copy of
        backup(path)
    if not write_atomic(path, body):
        return False
    ok("  fill  %-28s <- %s%s" % (path.name, show(source), suffix))
    if note:
        # Renumbering happened, so sibling machine ids are the thing most likely
        # to be wrong for this slot. Surface them rather than guessing.
        others = other_numbered_ids(body, base_name(path.stem))
        if others:
            warn("        left as-is (check these): %s" % ", ".join(others))
    return True


def sync_all(index, opts: Options) -> int:
    written = 0
    for path in sorted(opts.save_dir.glob("*.py")):
        written += sync_file(path, index, opts, quiet_skips=not opts.verbose)
    tidy_unmatched(index, opts)
    return written


# ------------------------------------------------------------------- options
SaveOpt = typer.Option(None, "--save-dir", "-s", envvar="CT_SAVE_DIR",
                       help="Save scripts directory. Auto-detects the newest save.")
ScriptsOpt = typer.Option(DEFAULT_SCRIPTS, "--scripts-dir", envvar="CT_SCRIPTS_DIR",
                          help="Repo script tree to sync from.")
StrictOpt = typer.Option(False, "--strict",
                         help="Only fill truly blank files (not comment/docstring stubs).")
DryOpt = typer.Option(False, "--dry-run", "-n", help="Report what would change.")
VerboseOpt = typer.Option(False, "--verbose", "-v", help="Also report files that were skipped.")
NoRenumberOpt = typer.Option(False, "--no-renumber",
                             help="Copy verbatim; do not point the script's own id at the slot.")
MagicOpt = typer.Option(DEFAULT_MAGIC, "--magic", envvar="CT_MAGIC",
                        help="Marker that makes a file fillable whatever it holds. "
                             "Empty string disables it.")
PullOpt = typer.Option(DEFAULT_PULL, "--pull-magic", envvar="CT_PULL_MAGIC",
                       help="Marker that copies a game file back into the repo. "
                            "Empty string disables it.")
VariantOpt = typer.Option("", "--variant", envvar="CT_VARIANT",
                          help="Default variant (subdirectory) when a script has several "
                               "and no .current file or marker chooses.")


def make_opts(save_dir, scripts_dir, strict, dry_run, verbose, no_renumber, magic,
              variant="", pull=DEFAULT_PULL) -> Options:
    save = resolve_save(save_dir)
    if not scripts_dir.is_dir():
        err("Not a directory: %s" % scripts_dir)
        raise typer.Exit(2)
    return Options(save, scripts_dir, strict, dry_run, verbose, not no_renumber, magic, pull, variant)


@app.command()
def status(save_dir: Optional[Path] = SaveOpt, scripts_dir: Path = ScriptsOpt,
           strict: bool = StrictOpt, no_renumber: bool = NoRenumberOpt,
           magic: str = MagicOpt, variant: str = VariantOpt, pull: str = PullOpt):
    """Show the repo-to-save mapping and what each save script would do."""
    opts = make_opts(save_dir, scripts_dir, strict, False, False, no_renumber, magic, variant, pull)
    index, conflicts = build_index(opts.scripts_dir)

    typer.echo("\nRepo scripts (%d):" % len(index))
    for key, group in sorted(index.items()):
        if group.only is not None:
            typer.echo("  %-24s %s" % (key, show(group.only)))
            continue
        chosen, how = group.select(None, opts.variant)
        chosen_tag = next((t for t, p in group.candidates.items() if p == chosen), None)
        labels = []
        for tag in sorted(group.candidates):
            name = tag or "(untagged)"
            labels.append("[%s]" % name if tag == chosen_tag else name)
        typer.echo("  %-24s variants: %s" % (key, ", ".join(labels)))
        typer.echo("  %-24s   -> %s" % ("", "%s  (%s)" % (show(chosen), how) if chosen else how))
    report_conflicts(conflicts)

    staged = sorted(opts.unmatched_dir.glob("*.py")) if opts.unmatched_dir.is_dir() else []
    if staged:
        typer.echo("\nStaged in %s (%d), waiting to be written and moved:"
                   % (show(opts.unmatched_dir), len(staged)))
        for path in staged:
            text = read(path) or ""
            typer.echo("  %-24s %s" % (path.name, "blank" if not text.strip() else "in progress"))

    files = sorted(p for p in opts.save_dir.glob("*.py") if is_candidate(p, opts.save_dir))
    typer.echo("\nSave scripts (%d):" % len(files))
    for path in files:
        text = read(path) or ""
        group = index.get(base_name(path.stem))
        pulled, pull_want = parse_magic(text, opts.pull)
        marked, want = parse_magic(text, opts.magic)
        fillable = marked or is_empty(text, opts.strict)
        source, how = group.select(want, opts.variant) if group else (None, None)
        if pulled:
            if is_empty(strip_magic(text, opts.pull), False):
                state = "marked %r but holds no code; nothing to pull" % opts.pull
            elif group is None:
                state = "marked %r -> would pull to %s" % (opts.pull, show(opts.unmatched_dir / path.name))
            else:
                target, phow = group.select(pull_want, opts.variant)
                state = ("marked %r -> would pull to %s%s" % (opts.pull, show(target), "  [%s]" % phow if phow else "")
                         if target else "marked %r, unresolved: %s" % (opts.pull, phow))
        elif not fillable:
            state = "has code, left alone"
        elif group is None:
            state = ("marked %r, " % opts.magic if marked else "empty, ") + "no match -> would stage"
        elif source is None:
            state = "empty, unresolved: %s" % how
        else:
            state = ("marked %r -> " % opts.magic if marked else "empty -> ")
            state += "would fill from %s" % show(source)
            if how:
                state += "  [%s]" % how
            if opts.renumber:
                _, _, note = renumber(read(source) or "", source.stem, path.stem)
                if note:
                    state += "  [%s]" % note
        typer.echo("  %-28s %s" % (path.name, state))
    typer.echo("")


@app.command()
def once(save_dir: Optional[Path] = SaveOpt, scripts_dir: Path = ScriptsOpt,
         strict: bool = StrictOpt, dry_run: bool = DryOpt, verbose: bool = VerboseOpt,
         no_renumber: bool = NoRenumberOpt, magic: str = MagicOpt,
         variant: str = VariantOpt, pull: str = PullOpt):
    """Fill every empty script that is already in the save directory."""
    opts = make_opts(save_dir, scripts_dir, strict, dry_run, verbose, no_renumber, magic, variant, pull)
    index, conflicts = build_index(opts.scripts_dir)
    report_conflicts(conflicts)
    typer.echo("Syncing %s" % opts.save_dir)
    n = sync_all(index, opts)
    typer.echo("%s %d file(s)." % ("Would sync" if dry_run else "Synced", n))


class Watcher:
    """Shared state for the two watched trees.

    Both feed the same sync. A file the game creates needs a source to fill it, and
    a source added, edited or renamed in the repo may be exactly what an empty file
    that was already sitting there had been missing — so any repo change re-sweeps.
    """

    def __init__(self, opts: Options, delay: float = 0.4):
        self.opts, self.delay = opts, delay
        self.index, self.conflicts = build_index(opts.scripts_dir)
        report_conflicts(self.conflicts)
        self.pending = {}
        self.repo_due = None

    def note_save(self, raw_path):
        path = Path(str(raw_path))
        if is_candidate(path, self.opts.save_dir):
            self.pending[path] = time.monotonic() + self.delay

    def note_repo(self, raw_path):
        path = Path(str(raw_path))
        if path.suffix != ".py" and path.name != CURRENT:
            return
        try:
            if UNMATCHED in path.relative_to(self.opts.scripts_dir).parts:
                return                      # staging area: our own writes, and yours
        except ValueError:
            pass
        self.repo_due = time.monotonic() + self.delay

    def rebuild(self):
        """Re-read the repo tree, report what moved, and re-sweep."""
        before = self.index
        self.index, self.conflicts = build_index(self.opts.scripts_dir)

        def paths(group):
            return ", ".join(show(p) for p in sorted(group.candidates.values()))

        for key in sorted(set(self.index) - set(before)):
            ok("  repo  + %-22s %s" % (key, paths(self.index[key])))
        for key in sorted(set(before) - set(self.index)):
            warn("  repo  - %-22s (was %s)" % (key, paths(before[key])))
        for key in sorted(k for k in set(self.index) & set(before)
                          if self.index[k].candidates != before[k].candidates):
            typer.echo("  repo  ~ %-22s %s" % (key, paths(self.index[key])))
        report_conflicts(self.conflicts)
        # Always sweep: a content edit changes no keys but may be the script an
        # empty game file (or a marked one) is waiting for.
        self.sweep()

    def sweep(self):
        sync_all(self.index, self.opts)

    def drain(self):
        now = time.monotonic()
        if self.repo_due is not None and self.repo_due <= now:
            self.repo_due = None
            self.rebuild()
        for path, due in [(p, d) for p, d in self.pending.items() if d <= now]:
            del self.pending[path]
            if path.exists():
                sync_file(path, self.index, self.opts)


class Events(FileSystemEventHandler):
    """Forwards paths to a callback. Debounced there: writes arrive in several steps."""

    def __init__(self, note):
        self.note = note

    def on_created(self, event):
        if not event.is_directory:
            self.note(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.note(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.note(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.note(event.src_path)       # a rename is a removal here...
            self.note(event.dest_path)      # ...and an addition there


@app.command()
def watch(save_dir: Optional[Path] = SaveOpt, scripts_dir: Path = ScriptsOpt,
          strict: bool = StrictOpt, dry_run: bool = DryOpt, verbose: bool = VerboseOpt,
          no_renumber: bool = NoRenumberOpt, magic: str = MagicOpt,
          variant: str = VariantOpt, pull: str = PullOpt,
          poll: bool = typer.Option(False, "--poll",
                                    help="Poll instead of using filesystem events.")):
    """Watch the save directory, and the repo scripts, and fill as things appear."""
    opts = make_opts(save_dir, scripts_dir, strict, dry_run, verbose, no_renumber, magic, variant, pull)
    watcher = Watcher(opts)
    if not watcher.index:
        err("No scripts found under %s." % opts.scripts_dir)
        raise typer.Exit(2)

    typer.echo("Save     %s" % opts.save_dir)
    typer.echo("Scripts  %s (%d, watched for adds, edits and renames)"
               % (opts.scripts_dir, len(watcher.index)))
    typer.echo("Staging  %s for game files with no match" % show(opts.unmatched_dir))
    if magic:
        typer.echo("Marker   %r at the top of a game file fills it from the repo" % magic)
    if pull:
        typer.echo("Marker   %r at the top of a game file copies it back into the repo" % pull)
    if dry_run:
        warn("Dry run: nothing will be written.")
    watcher.sweep()                                   # catch up on both sides

    observer = (PollingObserver if poll else Observer)()
    observer.schedule(Events(watcher.note_save), str(opts.save_dir), recursive=False)
    observer.schedule(Events(watcher.note_repo), str(opts.scripts_dir), recursive=True)
    observer.start()
    typer.echo("Ready. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(0.2)
            watcher.drain()
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    app()
