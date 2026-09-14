#!/bin/bash
# unity mode: links the student's files with the tests and Unity.
# Exit codes: 10 compile error, 11 link error, 12 compile timeout, 86 memory error,
# otherwise Unity's own. Nothing that could quote the test code reaches the output.
set -u

# An empty CTESTER_SANITIZERS disables sanitizers, hence `-` rather than `:-`, and no
# quotes where it is used. gnu23 rather than c23, which would hide M_PI.
C_STD="${CTESTER_C_STD:-gnu23}"
SANITIZERS="${CTESTER_SANITIZERS-"-fsanitize=address,undefined"}"
ASAN_OPTS="${CTESTER_ASAN_OPTIONS:-exitcode=86:detect_leaks=0}"
COMPILE_TIMEOUT="${CTESTER_COMPILE_TIMEOUT:-10}"
RUN_TIMEOUT="${CTESTER_RUN_TIMEOUT:-5}"

cd /work || exit 70

rc=0
for source in /in/src/*.c; do
    [ -e "$source" ] || continue
    timeout -s KILL $COMPILE_TIMEOUT \
        gcc -std=$C_STD -Wall -Wextra $SANITIZERS -I/in/src \
            -c "$source" -o "/work/$(basename "$source" .c).o" 2>>/work/gcc.err
    rc=$?
    [ $rc -eq 0 ] || break
done
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

# Linker errors would quote the tests, so they are discarded. Without
# UNITY_INCLUDE_DOUBLE, Unity's double assertions compile to a stub that always fails.
timeout -s KILL $COMPILE_TIMEOUT \
    gcc -DUNITY_INCLUDE_DOUBLE $SANITIZERS \
        /work/*.o /in/tests/*.c /in/unity/unity.c \
        -I/in/unity -I/in/tests -I/in/src -o /work/t -lm 2>/dev/null
rc=$?
if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then
    exit 12
fi
if [ $rc -ne 0 ]; then
    exit 11
fi

# An ASan stack trace would name the calling test: only its exit code (86) is kept.
ASAN_OPTIONS="$ASAN_OPTS" \
    timeout -s KILL $RUN_TIMEOUT /work/t 2>/dev/null
exit $?
