#!/usr/bin/env bash
# The structural probes the phase03 claims name, in one place.
#
# Each check is a rule the tree must satisfy and a grep that proves it. They
# exist to be RED before the code that satisfies them, so a new script cannot
# quietly break a rule the ISA says holds. Run with no argument for all of
# them, or name one: ./check-phase03.sh fail-safe
#
# Exit 0 only when every requested check passes.
set -u
cd "$(dirname "$0")/.." || exit 2

TREE=scripts/phase03
# Directories holding MACHINE scripts: ones with a `self` that owns hardware
# and therefore a fail-safe direction. control_room is deliberately absent —
# a card is a view with no setpoint to hold or release, so demanding a
# FAIL_SAFE of one would be asking it to declare something it cannot have.
# The check flagged the first card written, which is the probe earning its
# keep rather than a false positive.
MACHINE_DIRS="atmos factory harvesting power rover sensor bio"
fail=0

say()  { printf '%s\n' "$*"; }
bad()  { printf 'FAIL  %s\n' "$*"; fail=1; }
good() { printf 'ok    %s\n' "$*"; }

machine_scripts() {
  for d in $MACHINE_DIRS; do
    [ -d "$TREE/$d" ] && find "$TREE/$d" -name '*.py'
  done
}

# -- ISC-3: no hard-coded machine instance ids ---------------------------
# A type id ("oxygen_generator") is fine and necessary; an instance id
# ("o2gen_1") is not, because the base is discovered by enumeration. Instance
# ids are the ones ending in _<digits>.
check_ids() {
  hits=$(grep -rnoE '"[a-z][a-z0-9]*(_[a-z0-9]+)*_[0-9]+"' "$TREE" \
         --include='*.py' | grep -v '_test' || true)
  if [ -n "$hits" ]; then
    bad "ISC-3 hard-coded instance ids:"; printf '%s\n' "$hits" | sed 's/^/        /'
  else
    good "ISC-3 no hard-coded instance ids"
  fi
}

# -- ISC-4: never dereference a get_component result inline -------------
# get_component returns None for an unknown or unresearched id, so
# get_component("x").foo() is an AttributeError waiting for a fresh save.
check_probes() {
  hits=$(grep -rnE 'get_component\([^)]*\)\s*\.' "$TREE" --include='*.py' || true)
  if [ -n "$hits" ]; then
    bad "ISC-4 get_component dereferenced inline:"; printf '%s\n' "$hits" | sed 's/^/        /'
  else
    good "ISC-4 no inline get_component dereference"
  fi
}

# -- ISC-14: every machine script declares its fail-safe direction -------
check_fail_safe() {
  missing=""
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    grep -q '^FAIL_SAFE' "$f" || missing="$missing $f"
  done <<EOF
$(machine_scripts)
EOF
  if [ -n "$missing" ]; then
    bad "ISC-14 machine scripts with no FAIL_SAFE:"
    for f in $missing; do printf '        %s\n' "$f"; done
  else
    good "ISC-14 every machine script declares FAIL_SAFE"
  fi
}

# -- ISC-10: no remote actuation ----------------------------------------
# Process control is self-only. Any of these called on something that is not
# `self` would raise in game, so catching it here is strictly cheaper.
check_actuation() {
  verbs='set_throttle|set_recipe|set_intake|set_heat|set_tilt|set_order|set_enabled|dump_waste|dispatch_rescue'
  hits=$(grep -rnE "(^|[^a-z_.])[a-z_][a-z0-9_]*\.($verbs)\(" "$TREE" --include='*.py' \
         | grep -vE '(^|[^a-z_])self\.' | grep -vE '^\s*#' || true)
  if [ -n "$hits" ]; then
    bad "ISC-10 actuation on a non-self receiver:"; printf '%s\n' "$hits" | sed 's/^/        /'
  else
    good "ISC-10 all actuation is on self"
  fi
}

# -- ISC-9: never clear a family with an empty prefix --------------------
check_wipe() {
  hits=$(grep -rnE '\.clear\(\s*""\s*\)' "$TREE" --include='*.py' || true)
  if [ -n "$hits" ]; then
    bad "ISC-9 clear with an empty prefix:"; printf '%s\n' "$hits" | sed 's/^/        /'
  else
    good "ISC-9 no empty-prefix clear"
  fi
}

# -- ISC-40: one writer per Archive prefix ------------------------------
# Each loop may only write keys under its own prefix. trace.py is exempt: it
# writes "<loop>.trace" from a parameter, and its caller supplies the loop.
check_prefixes() {
  declare -A own=( [safety.py]=safety [planner.py]=plan )
  for f in "${!own[@]}"; do
    path="$TREE/automation/$f"
    [ -f "$path" ] || continue
    keys=$(grep -oE '(set|transaction)\(\s*"[a-z]+\.' "$path" \
           | grep -oE '"[a-z]+\.' | tr -d '".' | sort -u)
    for k in $keys; do
      if [ "$k" != "${own[$f]}" ]; then
        bad "ISC-40 $f writes prefix '$k', owns '${own[$f]}'"
      fi
    done
  done
  [ "$fail" -eq 0 ] && good "ISC-40 each loop writes only its own prefix"
}

want="${1:-all}"
case "$want" in
  ids)        check_ids ;;
  probes)     check_probes ;;
  fail-safe)  check_fail_safe ;;
  actuation)  check_actuation ;;
  wipe)       check_wipe ;;
  prefixes)   check_prefixes ;;
  all)        check_ids; check_probes; check_fail_safe
              check_actuation; check_wipe; check_prefixes ;;
  *)          say "unknown check: $want"; exit 2 ;;
esac

exit "$fail"
