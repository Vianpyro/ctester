#!/bin/sh
set -eu

dir=/opt/ctester
src=$dir/src
stamp=$dir/.deployed
defer=$dir/.pull-defer

cd "$dir"

git -C "$src" fetch --quiet origin "${CTESTER_BRANCH:-main}"
git -C "$src" merge --ff-only --quiet FETCH_HEAD

head=$(git -C "$src" rev-parse HEAD)
if [ "$head" = "$(cat "$stamp" 2>/dev/null || true)" ]; then
    exit 0
fi

PYTHONDONTWRITEBYTECODE=1 python3 "$src/tests/test_ctester.py"

spool_empty() {
    [ -z "$(ls -A "$dir/spool" 2>/dev/null || true)" ]
}

open_windows() {
    docker compose exec -T web python3 -c \
        'import json,urllib.request as u;print(json.load(u.urlopen("http://127.0.0.1:8000/live?id=ctester-pull"))["n"] - 1)' \
        2>/dev/null || echo 0
}

calm() {
    end=$(( $(date +%s) + ${CTESTER_PULL_WINDOW:-900} ))
    while :; do
        n=$(open_windows)
        if spool_empty && [ "${n:-0}" -le "${CTESTER_PULL_LIVE_MAX:-0}" ]; then
            return 0
        fi
        if [ "$(date +%s)" -ge "$end" ]; then
            echo "ctester: not calm after ${CTESTER_PULL_WINDOW:-900} s" \
                 "(spool: $(ls -A "$dir/spool" 2>/dev/null | wc -l), windows: ${n:-0})" >&2
            return 1
        fi
        sleep 30
    done
}

if [ "${CTESTER_FORCE:-}" = "1" ] || calm; then
    rm -f "$defer"
else
    count=$(( $(cat "$defer" 2>/dev/null || echo 0) + 1 ))
    if [ "$count" -lt "${CTESTER_PULL_MAX_DEFER:-3}" ]; then
        echo "$count" > "$defer"
        echo "ctester: deployment deferred ($count/${CTESTER_PULL_MAX_DEFER:-3})" >&2
        exit 0
    fi
    echo "ctester: deferred ${CTESTER_PULL_MAX_DEFER:-3} times, deploying anyway" >&2
    rm -f "$defer"
fi

systemctl daemon-reload
systemctl restart 'ctester-runner@*.service'
docker compose up -d --remove-orphans
docker compose restart web

echo "$head" > "$stamp"
echo "ctester: deployed $head"
