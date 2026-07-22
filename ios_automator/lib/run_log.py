"""Central run log for IG automation pipeline."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG_FILE = Path(os.environ.get("IOS_RUN_LOG", REPO / "logs" / "automation.log"))
STATUS_FILE = Path(os.environ.get("IOS_RUN_STATUS", REPO / "logs" / "status.json"))


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(level: str, msg: str) -> None:
    line = f"{_ts()} [{level}] {msg}"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print(line, flush=True)


def _update_status(state: str, **fields: object) -> None:
    data: dict[str, object] = {}
    if STATUS_FILE.is_file():
        try:
            data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data["state"] = state
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    data.update(fields)
    if state in {"done", "failed"}:
        data["finished_at"] = data["updated_at"]
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ig_phase(phase: str, detail: str = "") -> None:
    msg = f"automation Instagram — {phase}"
    if detail:
        msg = f"{msg} | {detail}"
    log("IG", msg)
    _update_status("ig_running", phase=phase, detail=detail)


def ig_done(output_dir: Path, *, ok: bool = True) -> None:
    out = str(output_dir.resolve())
    if ok:
        log("IG", f"automation Instagram selesai | output={out}")
        _update_status("done", phase="instagram", exit_code=0, output_dir=out)
    else:
        log("ERROR", f"automation Instagram gagal | output={out}")
        _update_status("failed", phase="instagram", exit_code=1, output_dir=out)
