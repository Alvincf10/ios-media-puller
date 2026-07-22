#!/usr/bin/env bash
# Wrapper — pakai enable_developer_mode.sh (standalone).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec bash "$ROOT/ios_automator/scripts/enable_developer_mode.sh" "${1:-ensure}"
