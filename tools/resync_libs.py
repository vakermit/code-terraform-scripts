#!/usr/bin/env python
"""Rewrite each registered Library's source in a Code: Terraform save from disk.

    python tools/resync_libs.py            # newest save, report and fix
    python tools/resync_libs.py --dry-run  # report only

WHY THIS EXISTS. `ct_sync` mirrors `scripts/<phase>/lib/*.py` into the save's
`lib/` directory, and that is enough for the editor to show the new text. It is
not enough for the game to RUN it: a registered Library's source is also stored
inside the save, and that stored copy is what executes.

The failure is silent until it isn't. Edit a library, sync the file, reload, and
the game runs the old text. If a function's signature changed, every caller dies
with an argument-count error naming a signature that matches the file you are
looking at — which is a genuinely confusing hour. If only a body changed, the old
behaviour simply persists.

So: run this after changing any library, with the game closed. It is idempotent,
touches only libraries whose stored copy differs from disk, and backs the save up
before writing. It never creates a registration — use the game's **Import as Game
Library** for a new file, because only the game can allocate an incarnation id.

The game must not be running. A save written underneath us would be lost.
"""
import argparse
import glob
import json
import os
import shutil
import sys
from datetime import datetime


def game_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        sys.exit("no APPDATA; this tool is Windows-only, like the game")
    return os.path.join(appdata, "io.codeterraform.game")


def live_save(game):
    """The save the game would load: highest writeSequence, not newest mtime.

    The game keeps a ring of history buffers (.h0 through .h9) beside the real
    save, and picking by filename or mtime lands on a stale snapshot. That
    mistake cost an hour once; writeSequence is the only honest discriminator.
    """
    best = None
    for path in glob.glob(os.path.join(game, "save_*.json")):
        name = os.path.basename(path)
        if ".claude-bak-" in name or ".bak-" in name or "pre-migration" in name:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        seq = data.get("writeSequence")
        if not isinstance(seq, int):
            continue
        if best is None or seq > best[1]:
            best = (path, seq, data)
    return best


def lib_dir(game, save_path):
    """The external-editor lib/ directory belonging to this save."""
    slot = os.path.basename(save_path)
    for suffix in (".json",):
        if slot.endswith(suffix):
            slot = slot[: -len(suffix)]
    slot = slot.split(".")[0]              # drop .hN and any other qualifier
    return os.path.join(game, slot + "_scripts", "lib")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", "-n", action="store_true",
                    help="report what differs and write nothing")
    args = ap.parse_args()

    game = game_dir()
    found = live_save(game)
    if found is None:
        sys.exit("no save found under %s" % game)
    save_path, seq, save = found
    libs = save.get("state", {}).get("libraryScripts") or {}
    if not libs:
        sys.exit("no registered libraries in %s" % os.path.basename(save_path))

    libs_path = lib_dir(game, save_path)
    print("save     %s  (writeSequence %d)" % (os.path.basename(save_path), seq))
    print("libs     %s" % libs_path)
    print()

    stale = []
    for name in sorted(libs):
        path = os.path.join(libs_path, name + ".py")
        if not os.path.exists(path):
            print("  %-14s no file on disk, left alone" % name)
            continue
        with open(path, encoding="utf-8") as f:
            source = f.read()
        entry = libs[name]
        if entry.get("source") == source and entry.get("deployedSource") == source:
            print("  %-14s current" % name)
            continue
        print("  %-14s STALE: registered %d B, disk %d B"
              % (name, len(entry.get("source") or ""), len(source)))
        stale.append((name, entry, source))

    if not stale:
        print("\nevery registered library matches its file.")
        return 0
    if args.dry_run:
        print("\n%d stale; re-run without --dry-run to rewrite." % len(stale))
        return 1

    for name, entry, source in stale:
        entry["source"] = source
        entry["deployedSource"] = source
        variants = entry.get("variants")
        if isinstance(variants, list) and variants and isinstance(variants[0], dict):
            variants[0]["source"] = source
        else:
            entry["variants"] = [{"name": "Main", "description": "", "source": source}]
        entry["activeVariantName"] = "Main"

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = save_path.replace(".json", ".claude-bak-%s.json" % stamp)
    shutil.copy2(save_path, backup)
    tmp = save_path + ".resync-tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(save, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, save_path)

    print("\nbackup   %s" % os.path.basename(backup))
    print("resynced %s" % ", ".join(n for n, _, _ in stale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
