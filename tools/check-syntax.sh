#!/usr/bin/env bash
# Parse every game script under a directory. The game's Python is a subset of
# CPython's grammar, so a CPython parse is a necessary-not-sufficient check:
# it catches the typos that would otherwise surface as a red script in game.
set -u
target="${1:-scripts}"
fail=0
while IFS= read -r f; do
  if ! python -c "import ast,sys; ast.parse(open(sys.argv[1],encoding='utf-8').read())" "$f" 2>/tmp/ct-syntax-err; then
    echo "FAIL $f"
    sed 's/^/      /' /tmp/ct-syntax-err
    fail=1
  fi
done < <(find "$target" -name '*.py' -not -path '*/_unmatched/*')
if [ "$fail" -eq 0 ]; then
  echo "ok: every script under $target parses"
fi
exit "$fail"
