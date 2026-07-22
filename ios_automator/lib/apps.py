from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_APPS_PATH = Path(__file__).resolve().parent.parent / "apps.json"


def _load_apps() -> dict[str, dict[str, Any]]:
    with _APPS_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid apps.json: {_APPS_PATH}")
    return data


KNOWN_APPS: dict[str, dict[str, Any]] = _load_apps()


def resolve_bundle_id(app_or_bundle: str) -> str:
    """Resolve short name (instagram/x/facebook) or pass through a bundle id."""
    key = app_or_bundle.strip().lower()
    if key in KNOWN_APPS:
        return str(KNOWN_APPS[key]["bundle_id"])
    if "." in app_or_bundle:
        return app_or_bundle.strip()
    known = ", ".join(sorted(KNOWN_APPS))
    raise ValueError(f"Unknown app '{app_or_bundle}'. Use bundle id or one of: {known}")


def list_apps() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for key, meta in sorted(KNOWN_APPS.items()):
        rows.append((key, str(meta["bundle_id"]), str(meta.get("name", key))))
    return rows
