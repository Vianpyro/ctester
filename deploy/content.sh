#!/bin/sh
set -eu

dir=/opt/ctester
content=${CTESTER_CONTENT:-$dir/content}
published=${CTESTER_PUBLISHED:-$dir/published}
# One stamp holding one line per repository: publication is all-or-nothing anyway, so a
# single comparison of the whole file is the whole question.
stamp=$dir/.content-deployed

if [ -n "${CTESTER_CONTENT_SSH_KEY:-}" ]; then
    GIT_SSH_COMMAND="ssh -i $CTESTER_CONTENT_SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
    export GIT_SSH_COMMAND
fi

# CTESTER_CONTENT is one path or several joined by ":", the same list the judge reads.
roots=$(printf '%s' "$content" | tr ':' '\n' | grep -v '^[[:space:]]*$' || true)
[ -n "$roots" ] || { echo "ctester: CTESTER_CONTENT is empty" >&2; exit 1; }

head=""
any_repo=""
# Split on newlines only, so a path may contain spaces.
old_ifs=$IFS
IFS='
'
for root in $roots; do
    IFS=$old_ifs
    [ -d "$root" ] || { echo "ctester: no such content root: $root" >&2; exit 1; }
    repo=$(git -C "$root" rev-parse --show-toplevel 2>/dev/null || true)
    if [ -n "$repo" ]; then
        any_repo=yes
        GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=fetch.recurseSubmodules GIT_CONFIG_VALUE_0=false \
            git -C "$repo" fetch --quiet origin "${CTESTER_CONTENT_BRANCH:-main}"
        git -C "$repo" merge --ff-only --quiet FETCH_HEAD
        head="$head$repo $(git -C "$repo" rev-parse HEAD)
"
    fi
    chmod -R u=rwX,go=rX "${repo:-$root}"
    find "${repo:-$root}" \( -name quiz.json -o -name io.json \) -type f -exec chmod 0600 {} +
    IFS='
'
done
IFS=$old_ifs

if [ -n "$any_repo" ]; then
    head="$head$(date +%F)"
    if [ "$head" = "$(cat "$stamp" 2>/dev/null || true)" ]; then
        exit 0
    fi
fi

# One publish for every root: a bad commit in one repository blocks them all, which is the
# point -- a half-published catalogue is worse than an old one.
CTESTER_CONTENT="$content" CTESTER_PUBLISHED="$published" \
PYTHONPATH="$dir/src/worker" PYTHONDONTWRITEBYTECODE=1 \
    python3 -c 'import os, publish_content as p; e = os.environ; print("ctester: published %d exercise(s)" % len(p.publish_catalogue(e["CTESTER_CONTENT"], e["CTESTER_PUBLISHED"], e.get("CTESTER_PREVIEW", "") not in ("", "0"))))'

if grep -rl answer "$published" 2>/dev/null; then
    echo "ctester: ALERT, an answer key reached the published release (files above)" >&2
    exit 1
fi

echo "ctester: release $(cat "$published/current.json")"

if [ -n "$any_repo" ]; then
    printf '%s' "$head" > "$stamp"
fi
