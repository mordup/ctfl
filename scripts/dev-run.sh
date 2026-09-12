#!/usr/bin/env bash
# Swap the running CTFL instance for one built from this checkout, or back.
#
#   scripts/dev-run.sh             stop whatever ctfl is running, start `python -m ctfl` from here
#   scripts/dev-run.sh installed   stop whatever is running, start the packaged ctfl
#   scripts/dev-run.sh stop        stop the running instance and leave nothing running
#
# The app is single-instance (fcntl lock), so the running copy must go first.
# Output of the launched process goes to $LOG.
set -euo pipefail

cd "$(dirname "$0")/.."
LOG="${XDG_RUNTIME_DIR:-/tmp}/ctfl-dev.log"
MODE="${1:-dev}"

running() {
    pgrep -f -- '(-m ctfl|/bin/ctfl)$' || true
}

stop() {
    local pids
    pids="$(running)"
    [ -z "$pids" ] && return 0
    # shellcheck disable=SC2086
    kill $pids
    for _ in $(seq 1 50); do
        [ -z "$(running)" ] && return 0
        sleep 0.1
    done
    echo "ctfl did not exit after SIGTERM (pids: $pids)" >&2
    return 1
}

launch() {
    nohup "$@" >"$LOG" 2>&1 &
    local pid=$!
    disown
    sleep 3
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "ctfl exited immediately; log follows" >&2
        tail -n 20 "$LOG" >&2
        return 1
    fi
    echo "running: $* (pid $pid, log $LOG)"
}

case "$MODE" in
    dev)
        stop
        launch python -m ctfl
        ;;
    installed)
        stop
        bin="$(command -v ctfl || true)"
        [ -n "$bin" ] || { echo "no installed ctfl on PATH" >&2; exit 1; }
        launch "$bin"
        ;;
    stop)
        stop
        echo "stopped"
        ;;
    *)
        echo "usage: $0 [dev|installed|stop]" >&2
        exit 2
        ;;
esac
