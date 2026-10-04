#!/bin/sh
# Every Python the host runs goes through here, in web's image: the host's own Python, if
# any, never matters. Usage: python.sh [docker run options...] -- command [args...]
set -eu

src=$(cd "$(dirname "$0")/.." && pwd)
image=${CTESTER_WEB_IMAGE:-python:3.13-slim}
typst=${CTESTER_TYPST_IMAGE:-ghcr.io/typst/typst:0.15.1}

# The pinned typst is statically linked: copied out of its image, it runs here as
# typst_build.py's CTESTER_TYPST_BIN. Copied only when it changed, since the content timer
# comes every five minutes.
docker run --rm --network none --entrypoint sh -v ctester-typst:/tools "$typst" -c \
    'cmp -s /bin/typst /tools/typst || { cp /bin/typst /tools/.typst && mv /tools/.typst /tools/typst; }'

# Puts the image between the caller's options and its command.
seen=
for arg do
    shift
    if [ -z "$seen" ] && [ "$arg" = -- ]; then
        seen=1
        set -- "$@" "$image"
    else
        set -- "$@" "$arg"
    fi
done
[ -n "$seen" ] || { echo "usage: python.sh [docker run options...] -- command" >&2; exit 2; }

exec docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --tmpfs /tmp \
    -v "$src:/src:ro" -v ctester-typst:/tools:ro \
    -e CTESTER_TYPST_BIN=/tools/typst -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/src/worker \
    -e CTESTER_LOG_LEVEL -e CTESTER_LOG_FORMAT \
    "$@"
