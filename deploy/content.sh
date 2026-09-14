#!/bin/sh
set -eu

dir=/opt/ctester
content=${CTESTER_CONTENT:-$dir/content}
published=${CTESTER_PUBLISHED:-$dir/published}
stamp=$dir/.content-deployed

repo=$(git -C "$content" rev-parse --show-toplevel 2>/dev/null || true)

if [ -n "$repo" ]; then
    if [ -n "${CTESTER_CONTENT_SSH_KEY:-}" ]; then
        GIT_SSH_COMMAND="ssh -i $CTESTER_CONTENT_SSH_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        export GIT_SSH_COMMAND
    fi
    GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=fetch.recurseSubmodules GIT_CONFIG_VALUE_0=false \
        git -C "$repo" fetch --quiet origin "${CTESTER_CONTENT_BRANCH:-main}"
    git -C "$repo" merge --ff-only --quiet FETCH_HEAD

    head="$(git -C "$repo" rev-parse HEAD) $(date +%F)"
    if [ "$head" = "$(cat "$stamp" 2>/dev/null || true)" ]; then
        exit 0
    fi
fi

chmod -R u=rwX,go=rX "${repo:-$content}"
find "${repo:-$content}" \( -name quiz.json -o -name io.json \) -type f -exec chmod 0600 {} +

CTESTER_CONTENT="$content" CTESTER_PUBLISHED="$published" \
PYTHONPATH="$dir/src/worker" PYTHONDONTWRITEBYTECODE=1 \
    python3 -c 'import runner; print("ctester: published %d exercise(s)" % len(runner.publish_catalogue()))'

if grep -rl answer "$published" 2>/dev/null; then
    echo "ctester: ALERT, an answer key reached the published release (files above)" >&2
    exit 1
fi

echo "ctester: release $(cat "$published/current.json")"

if [ -n "$repo" ]; then
    echo "$head" > "$stamp"
fi
