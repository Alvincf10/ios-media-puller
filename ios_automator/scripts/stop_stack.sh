#!/usr/bin/env bash
# Stop background stack processes started by run_stack.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WDA_PORT="${WDA_PORT:-8100}"
TUNNEL_INFO_PORT="${GO_IOS_TUNNEL_INFO_PORT:-60105}"
MODE="${1:-wda}"

export PATH="${HOME}/.local/bin:${PATH}"

# shellcheck disable=SC1091
[[ -f "$ROOT/ios_automator/scripts/run_log.sh" ]] && source "$ROOT/ios_automator/scripts/run_log.sh"

stop_wda() {
  pkill -f "ios runwda" 2>/dev/null || true
  pkill -f "ios forward.*${WDA_PORT}" 2>/dev/null || true
}

stop_keep_awake() {
  bash "$ROOT/ios_automator/scripts/keep_screen_on.sh" stop 2>/dev/null || true
}

stop_tunnel() {
  bash "$ROOT/ios_automator/scripts/start_tunnel.sh" stop 2>/dev/null || true
}

case "$MODE" in
  wda)
    stop_wda
    stop_keep_awake
    if declare -F run_log >/dev/null 2>&1; then
      run_log CLEANUP "stop WDA + keep-screen-on (tunnel tetap hidup)"
    else
      echo "[cleanup] stop WDA + keep-screen-on (tunnel tetap hidup)"
    fi
    ;;
  all)
    stop_wda
    stop_keep_awake
    stop_tunnel
    if declare -F run_log >/dev/null 2>&1; then
      run_log CLEANUP "stop semua: WDA + keep-screen-on + tunnel"
    else
      echo "[cleanup] stop semua: WDA + keep-screen-on + tunnel"
    fi
    ;;
  none)
    if declare -F run_log >/dev/null 2>&1; then
      run_log CLEANUP "skip — stack dibiarkan hidup"
    else
      echo "[cleanup] skip — stack dibiarkan hidup"
    fi
    ;;
  *)
    echo "Usage: $0 {wda|all|none}" >&2
    echo "  wda   — stop runwda/forward + keep-screen-on (default, tunnel tetap)" >&2
    echo "  all   — stop semua termasuk tunnel" >&2
    echo "  none  — tidak stop apa pun" >&2
    exit 2
    ;;
esac

sleep 1
