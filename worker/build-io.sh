#!/bin/bash
# io mode: builds a complete program and runs it on each input case.
# Exit codes: 10 compile error (stdout is gcc's stderr), 12 compile timeout, 0 cases ran.
# Cases are framed by "<nonce> BEGIN/ERR/END"; the nonce is per job, so a program
# cannot print fake frames. No test code is mounted, so all output may be shown.
set -u

# An empty CTESTER_SANITIZERS disables sanitizers, hence `-` rather than `:-`, and no
# quotes where it is used. gnu23 rather than c23, which would hide M_PI.
C_STD="${CTESTER_C_STD:-gnu23}"
SANITIZERS="${CTESTER_SANITIZERS-"-fsanitize=address,undefined"}"
ASAN_OPTS="${CTESTER_ASAN_OPTIONS:-exitcode=86:detect_leaks=0}"
COMPILE_TIMEOUT="${CTESTER_COMPILE_TIMEOUT:-10}"
RUN_TIMEOUT="${CTESTER_RUN_TIMEOUT:-5}"

cd /work || exit 70

timeout -s KILL $COMPILE_TIMEOUT \
    gcc -std=$C_STD -Wall -Wextra $SANITIZERS -I/in/src \
        /in/src/*.c -o /work/t -lm 2>/work/gcc.err
rc=$?
if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then
    exit 12
fi
if [ $rc -ne 0 ]; then
    cat /work/gcc.err
    exit 10
fi

if [ -s /work/gcc.err ]; then
    printf '%s WARN\n' "$CTESTER_NONCE"
    cat /work/gcc.err
    printf '\n%s ENDWARN\n' "$CTESTER_NONCE"
fi

for case_file in /in/cases/*.in; do
    [ -e "$case_file" ] || continue
    name=$(basename "$case_file" .in)
    printf '%s BEGIN %s\n' "$CTESTER_NONCE" "$name"
    ASAN_OPTIONS="$ASAN_OPTS" \
        timeout -s KILL $RUN_TIMEOUT /work/t < "$case_file" 2>/work/err
    code=$?
    printf '\n%s ERR %s\n' "$CTESTER_NONCE" "$name"
    cat /work/err
    printf '\n%s END %s %s\n' "$CTESTER_NONCE" "$name" "$code"
done

exit 0
