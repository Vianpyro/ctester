#!/bin/sh
# Stands in for `docker` in the runner's tests: records each call, then plays build-io.sh,
# build-unity.sh or build-scratch.sh on the mounted stage.
echo "$*" >> "$(dirname "$0")/calls"
[ "$1" = rm ] && exit 0
nonce=""; src=""; cases=""; console=0
while [ $# -gt 0 ]; do
  case "$1" in
    -e) case "$2" in CTESTER_NONCE=*) nonce="${2#CTESTER_NONCE=}";; esac; shift 2;;
    -v) case "$2" in *:/in/src:ro) src="${2%%:*}";; *:/in/cases:ro) cases="${2%%:*}";; esac; shift 2;;
    -i) console=1; shift;;
    *) shift;;
  esac
done
if [ $console = 1 ]; then
  printf '%s RUN\n' "$nonce"; read line; echo "lu: $line"; exit 0
fi
if grep -q ERREUR "$src"/*.c; then echo "sub.c:1: error: ERREUR"; exit 10; fi
if [ -n "$cases" ]; then
  for c in "$cases"/*.in; do
    n=$(basename "$c" .in)
    printf '%s BEGIN %s\n' "$nonce" "$n"
    if grep -q FAUX "$src"/*.c; then echo 0; else cat "$c"; fi
    printf '\n%s ERR %s\n\n%s END %s 0\n' "$nonce" "$n" "$nonce" "$n"
  done
  exit 0
fi
if grep -q FAUX "$src"/*.c; then echo "t.c:1:test_x:FAIL"; echo "3 Tests 1 Failures 0 Ignored"; exit 1; fi
echo "3 Tests 0 Failures 0 Ignored"
