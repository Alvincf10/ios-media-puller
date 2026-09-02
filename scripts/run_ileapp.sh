#!/usr/bin/env bash
# Parse an iOS backup / filesystem dump with iLEAPP.
# iLEAPP does not talk to the phone — feed it a backup (or Photos.sqlite).
#
# Usage:
#   ./scripts/run_ileapp.sh                         # auto-find latest EDM itunes backup
#   ./scripts/run_ileapp.sh -i /path/to/backup
#   ./scripts/run_ileapp.sh -t file -i Photos.sqlite
#   ./scripts/run_ileapp.sh -m ileapp_profiles/browser_mail.ilprofile
#   ./scripts/run_ileapp.sh --setup-only            # clone + venv, no parse
#
# Encrypted itunes backup: set IOS_BACKUP_PASSWORD in .env (same as EDM).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ILEAPP_DIR="${ILEAPP_DIR:-$ROOT/iLEAPP}"
ILEAPP_REPO="${ILEAPP_REPO:-https://github.com/abrignoni/iLEAPP.git}"
ILEAPP_VENV="${ILEAPP_VENV:-$ILEAPP_DIR/.venv}"
OUTPUT_ROOT="${ROOT}/output"

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

usage() {
  cat <<'EOF'
Usage: ./scripts/run_ileapp.sh [options]

  -i, --input PATH     Backup folder, zip/tar, or single file
  -t, --type TYPE      itunes | fs | zip | tar | gz | file  (auto if omitted)
  -o, --output DIR     Output folder (must exist; default: output/ileapp_TIMESTAMP)
  -m, --profile FILE   iLEAPP .ilprofile (subset of artifacts)
      --setup-only     Clone iLEAPP + install venv, then exit
  -h, --help           Show this help

Auto-detect looks for:
  1) ILEAPP_INPUT from .env
  2) latest itunes / EDM backup under output/
EOF
}

INPUT_PATH="${ILEAPP_INPUT:-}"
INPUT_TYPE=""
OUTPUT_PATH=""
PROFILE_PATH="${ILEAPP_PROFILE:-}"
SETUP_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--input) INPUT_PATH="${2:-}"; shift 2 ;;
    -t|--type) INPUT_TYPE="${2:-}"; shift 2 ;;
    -o|--output) OUTPUT_PATH="${2:-}"; shift 2 ;;
    -m|--profile) PROFILE_PATH="${2:-}"; shift 2 ;;
    --setup-only) SETUP_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

is_itunes_backup() {
  local dir="$1"
  [[ -d "$dir" ]] || return 1
  [[ -f "$dir/Info.plist" ]] || return 1
  # Failed/partial EDM runs leave empty Manifest.plist without Manifest.db
  [[ -f "$dir/Manifest.db" || -s "$dir/Manifest.plist" ]]
}

detect_type() {
  local path="$1"
  if [[ -f "$path" ]]; then
    case "${path##*.}" in
      zip) echo zip ;;
      tar) echo tar ;;
      gz|tgz) echo gz ;;
      *) echo file ;;
    esac
    return
  fi
  if is_itunes_backup "$path"; then
    echo itunes
    return
  fi
  echo fs
}

find_latest_edm_backup() {
  local cand latest="" latest_mtime=0 mtime
  shopt -s nullglob
  for cand in \
    "$OUTPUT_ROOT"/itunes_backup_browser_mail/* \
    "$OUTPUT_ROOT"/itunes_backup/* \
    "$OUTPUT_ROOT"/edm_*/evidence/original/*; do
    [[ -d "$cand" ]] || continue
    is_itunes_backup "$cand" || continue
    mtime=$(stat -f '%m' "$cand" 2>/dev/null || stat -c '%Y' "$cand")
    if (( mtime >= latest_mtime )); then
      latest_mtime=$mtime
      latest="$cand"
    fi
  done
  shopt -u nullglob
  [[ -n "$latest" ]] && printf '%s\n' "$latest"
}

ileapp_source_ok() {
  [[ -f "$ILEAPP_DIR/ileapp.py" ]] \
    && [[ -f "$ILEAPP_DIR/requirements.txt" ]] \
    && [[ -d "$ILEAPP_DIR/scripts/artifacts" ]]
}

ensure_ileapp() {
  if ileapp_source_ok; then
    echo "[ileapp] source OK — $ILEAPP_DIR"
    return
  fi
  echo "[ileapp] cloning $ILEAPP_REPO → $ILEAPP_DIR"
  mkdir -p "$ILEAPP_DIR"
  git -c http.postBuffer=524288000 -c http.version=HTTP/1.1 \
    clone --depth 1 --single-branch --progress \
    "$ILEAPP_REPO" "$ILEAPP_DIR"
  ileapp_source_ok || {
    echo "[ileapp] clone tidak lengkap (butuh ileapp.py + requirements.txt + scripts/artifacts)" >&2
    exit 2
  }
}

ensure_venv() {
  if [[ ! -x "$ILEAPP_VENV/bin/python" ]]; then
    echo "[ileapp] creating venv at $ILEAPP_VENV (isolated from project .venv)"
    python3 -m venv "$ILEAPP_VENV"
  fi
  # shellcheck disable=SC1091
  source "$ILEAPP_VENV/bin/activate"
  if ! python -c "import pandas, PIL, simplekml" >/dev/null 2>&1; then
    echo "[ileapp] installing requirements (first run, may take a few minutes)"
    python -m pip install -U pip
    # cwd = iLEAPP so relative whl_files/ paths in requirements.txt resolve
    ( cd "$ILEAPP_DIR" && python -m pip install -r requirements.txt )
  fi
}

ensure_ileapp

if [[ "$SETUP_ONLY" -eq 1 ]]; then
  ensure_venv
  echo "[ileapp] setup done. Parse with: ./scripts/run_ileapp.sh -i /path/to/backup"
  exit 0
fi

if [[ -z "$INPUT_PATH" ]]; then
  INPUT_PATH="$(find_latest_edm_backup || true)"
fi

if [[ -z "$INPUT_PATH" ]]; then
  cat >&2 <<'EOF'
[ileapp] tidak ada input.

iLEAPP butuh backup / dump, bukan HP hidup.
Backup EDM sebelumnya gagal (PasswordProtected) — isi IOS_BACKUP_PASSWORD di .env,
jalankan acquire EDM sampai evidence/original/<udid> berisi Info.plist + Manifest.db,
lalu ulang script ini.

Atau parse file yang sudah ada:
  ./scripts/run_ileapp.sh -t file -i /path/ke/Photos.sqlite
  ./scripts/run_ileapp.sh -i /path/ke/itunes_backup
EOF
  exit 2
fi

if [[ ! -e "$INPUT_PATH" ]]; then
  echo "[ileapp] input tidak ditemukan: $INPUT_PATH" >&2
  exit 2
fi

INPUT_PATH="$(cd "$(dirname "$INPUT_PATH")" && pwd)/$(basename "$INPUT_PATH")"
[[ -n "$INPUT_TYPE" ]] || INPUT_TYPE="$(detect_type "$INPUT_PATH")"

if [[ -z "$OUTPUT_PATH" ]]; then
  OUTPUT_PATH="$OUTPUT_ROOT/ileapp_$(date +%Y%m%d_%H%M%S)"
fi
mkdir -p "$OUTPUT_PATH"

ensure_venv

echo "[ileapp] type=$INPUT_TYPE"
echo "[ileapp] input=$INPUT_PATH"
echo "[ileapp] output=$OUTPUT_PATH"

cmd=(python "$ILEAPP_DIR/ileapp.py" -t "$INPUT_TYPE" -i "$INPUT_PATH" -o "$OUTPUT_PATH")
if [[ -n "$PROFILE_PATH" ]]; then
  cmd+=(-m "$PROFILE_PATH")
  echo "[ileapp] profile=$PROFILE_PATH"
fi
if [[ "$INPUT_TYPE" == "itunes" && -n "${IOS_BACKUP_PASSWORD:-}" ]]; then
  cmd+=(--itunes_password "$IOS_BACKUP_PASSWORD")
fi

"${cmd[@]}"
echo "[ileapp] selesai — $OUTPUT_PATH"
