#!/bin/bash
# Console mode: builds a free-form program and hands it the terminal. No grading.
# Exit codes: 10 compile error, 12 compile timeout, 70 no /work, else the program's own.
# "<nonce> RUN" separates gcc's output from the program's.
set -u

C_STD="${CTESTER_C_STD:-gnu23}"
SANITIZERS="${CTESTER_SANITIZERS--fsanitize=address,undefined}"
ASAN_OPTS="${CTESTER_ASAN_OPTIONS:-exitcode=86:detect_leaks=0}"
COMPILE_TIMEOUT="${CTESTER_COMPILE_TIMEOUT:-10}"
# CPU time, not wall time: it tells a program waiting on scanf from an infinite loop.
# It is per process, so fork bombs are stopped by the memory limit instead.
CPU_SECONDS="${CTESTER_CPU_SECONDS:-10}"

cd /work || exit 70

# glibc block-buffers stdout when it is not a terminal, so a prompt would never show
# before scanf. This constructor unbuffers it; `static` avoids clashing with student code.
cat > /work/ctester_rt.c <<'EOF'
#include <stdio.h>
__attribute__((constructor)) static void ctester_rt_unbuffer(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
}
EOF

timeout -s KILL $COMPILE_TIMEOUT \
    gcc -std=$C_STD -Wall -Wextra $SANITIZERS -I/in/src \
        /in/src/*.c /work/ctester_rt.c -o /work/t -lm 2>/work/gcc.err
rc=$?
if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then
    exit 12
fi
if [ $rc -ne 0 ]; then
    cat /work/gcc.err
    exit 10
fi

if [ -s /work/gcc.err ]; then
    cat /work/gcc.err
fi

printf '%s RUN\n' "$CTESTER_NONCE"

# exec, not a subshell: signals reach the program directly, its exit code is the
# container's, and bash cannot print "Killed" into the student's output.
export ASAN_OPTIONS="$ASAN_OPTS"
ulimit -t $CPU_SECONDS
exec /work/t
