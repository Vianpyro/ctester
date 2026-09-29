#!/bin/sh
# Starts on-demand judges (ctester-judge@N, CTESTER_WORKERS < N <= CTESTER_WORKERS_MAX) while
# jobs wait. It never stops one: they leave by themselves once idle, so no run is cut short.
set -u

dir=/opt/ctester
base=${CTESTER_WORKERS:-2}

while :; do
    sleep 2
    # A deployment is under way.
    [ -e "$dir/status/maintenance" ] && continue
    # Re-read each time, so raising or lowering the cap takes effect without a restart.
    max=$(sed -n 's/^CTESTER_WORKERS_MAX=//p' "$dir/.env" | tail -n 1)
    case $max in ''|*[!0-9]*) continue;; esac
    [ "$max" -gt "$base" ] || continue
    [ "$("$dir/bin/ctester-judge" backlog 2>/dev/null || echo 0)" -gt 0 ] || continue
    for n in $(seq $((base + 1)) "$max"); do
        if ! systemctl is-active --quiet "ctester-judge@$n.service"; then
            systemctl start "ctester-judge@$n.service"
            # Time for it to claim the job before the backlog is read again.
            sleep 5
            break
        fi
    done
done
