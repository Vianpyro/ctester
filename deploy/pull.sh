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

# The judge binary comes from CI for this exact commit; without it nothing is deployed.
repo=${CTESTER_REPO:-Vianpyro/ctester}
judge=$dir/bin/ctester-judge-$head
if [ ! -x "$judge" ]; then
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    release="https://github.com/$repo/releases/download/judge-$head"
    if ! curl -fsSL -o "$tmp/ctester-judge" "$release/ctester-judge" ||
       ! curl -fsSL -o "$tmp/ctester-judge.sha256" "$release/ctester-judge.sha256"; then
        echo "ctester: no judge release for $head yet, deploying on a later run" >&2
        exit 0
    fi
    (cd "$tmp" && sha256sum -c --quiet ctester-judge.sha256)
    gh attestation verify "$tmp/ctester-judge" --repo "$repo"
    install -D -m 0755 "$tmp/ctester-judge" "$judge"
fi
"$judge" self-check > /dev/null

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

ln -sfn "$judge" "$dir/bin/ctester-judge.next"
mv -T "$dir/bin/ctester-judge.next" "$dir/bin/ctester-judge"
ls -t "$dir"/bin/ctester-judge-* | tail -n +3 | xargs -r rm -f

# Idempotent: the first run also retires the Python runner units the judge replaces.
systemctl stop 'ctester-runner@*.service' 2>/dev/null || true
rm -f /etc/systemd/system/multi-user.target.wants/ctester-runner@*.service \
      /etc/systemd/system/ctester-runner@.service
ln -sfn "$src/deploy/systemd/ctester-judge@.service" /etc/systemd/system/ctester-judge@.service
systemctl daemon-reload
for n in $(seq 1 "${CTESTER_WORKERS:-2}"); do
    systemctl enable --quiet "ctester-judge@$n.service"
    systemctl restart "ctester-judge@$n.service"
done
docker compose up -d --remove-orphans
docker compose restart web

# The judge does not publish on start, so the catalogue is republished with the new code.
rm -f "$dir/.content-deployed"
systemctl start --no-block ctester-content.service

echo "$head" > "$stamp"
echo "ctester: deployed $head"
