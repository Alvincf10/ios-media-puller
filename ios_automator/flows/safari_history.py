"""Safari: Riwayat yang terlihat → judul / URL / screenshot (WDA HTTP).

Hanya data di layar. Bukan History.db, bukan backup, bukan private browsing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from lib.apps import resolve_bundle_id
from lib.run_log import safari_done, safari_phase
from lib.session import AutomatorSession, default_output_dir

logger = logging.getLogger("ios_automator.safari_history")

SELECTORS = Path(__file__).resolve().parents[1] / "appium" / "selectors.json"

CHROME = frozenset(
    {
        "safari",
        "bookmarks",
        "penanda",
        "reading list",
        "daftar bacaan",
        "history",
        "riwayat",
        "search",
        "cari",
        "search history",
        "cari riwayat",
        "edit",
        "ubah",
        "done",
        "selesai",
        "cancel",
        "batal",
        "clear",
        "clear history",
        "hapus",
        "hapus riwayat",
        "private",
        "pribadi",
        "tabs",
        "tab",
        "new tab",
        "tab baru",
        "share",
        "bagikan",
        "today",
        "hari ini",
        "yesterday",
        "kemarin",
        "earlier this week",
        "earlier this month",
        "earlier",
        "lebih awal",
        "minggu ini",
        "bulan ini",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "senin",
        "selasa",
        "rabu",
        "kamis",
        "jumat",
        "jum'at",
        "sabtu",
        "minggu",
        "continue",
        "lanjutkan",
        "not now",
        "jangan sekarang",
        "close",
        "tutup",
        "start page",
        "halaman awal",
        "",
    }
)

URL_RE = re.compile(
    r"(https?://[^\s,]+|(?:www\.)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s,]*)?)",
    re.IGNORECASE,
)


def _load_selectors() -> dict:
    with SELECTORS.open(encoding="utf-8") as fh:
        return json.load(fh)["safari"]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(1, min(100, int(raw)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        return max(0.05, float(raw))
    except ValueError:
        return default


def _node_text(node: ET.Element) -> str:
    for key in ("label", "name", "value"):
        val = (node.attrib.get(key) or "").strip()
        if val:
            return val
    return ""


def _looks_chrome(text: str) -> bool:
    return text.strip().lower() in CHROME


def _looks_url(text: str) -> bool:
    raw = text.strip()
    if not raw or _looks_chrome(raw):
        return False
    return bool(URL_RE.fullmatch(raw) or URL_RE.search(raw))


def _first_url(text: str) -> str:
    match = URL_RE.search(text.strip())
    return match.group(0).rstrip(".,)") if match else ""


def _cell_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            (row.get("url") or "").strip().lower(),
            (row.get("title") or "").strip().lower()[:80],
        ]
    )


def _parse_texts_to_row(texts: list[str], *, y: int, full_label: str) -> dict[str, Any] | None:
    parts = [t.strip() for t in texts if t and t.strip() and not _looks_chrome(t)]
    if not parts and full_label and not _looks_chrome(full_label):
        parts = [p.strip() for p in re.split(r"[\n,]", full_label) if p.strip() and not _looks_chrome(p)]
    if not parts:
        return None
    url = ""
    title_parts: list[str] = []
    for part in parts:
        found = _first_url(part) if _looks_url(part) else ""
        if found and not url:
            url = found
            leftover = part.replace(found, "").strip(" -,")
            if leftover and not _looks_chrome(leftover):
                title_parts.append(leftover)
        elif not _looks_chrome(part):
            title_parts.append(part)
    title = title_parts[0] if title_parts else ""
    if not title and not url:
        return None
    if title and _looks_chrome(title) and not url:
        return None
    return {"title": title, "url": url, "y": y}


def _parse_history_rows(xml: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml)
    rows: list[dict[str, Any]] = []
    for node in root.iter():
        if not node.tag.endswith("Cell"):
            continue
        try:
            y = int(node.attrib.get("y", "0") or 0)
            h = int(node.attrib.get("height", "0") or 0)
        except ValueError:
            continue
        if h < 28 or y < 60:
            continue
        child_texts: list[str] = []
        for child in node.iter():
            if child is node:
                continue
            if not (child.tag.endswith("StaticText") or child.tag.endswith("Button")):
                continue
            text = _node_text(child)
            if text and text not in child_texts:
                child_texts.append(text)
        full_label = (node.attrib.get("label") or node.attrib.get("name") or "").strip()
        texts = child_texts
        if not texts and full_label:
            texts = [p.strip() for p in re.split(r"[\n,]", full_label) if p.strip()]
        row = _parse_texts_to_row(texts, y=y, full_label=full_label)
        if row:
            rows.append(row)
    rows.sort(key=lambda r: r["y"])
    return rows


def _merge_rows(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {_cell_key(r) for r in existing if _cell_key(r) != "|"}
    out = list(existing)
    for row in incoming:
        key = _cell_key(row)
        if key == "|" or key in seen:
            continue
        seen.add(key)
        out.append({k: v for k, v in row.items() if k != "y"})
    return out


def _history_visible(xml: str) -> bool:
    return bool(_parse_history_rows(xml))


async def _tap_any(session: AutomatorSession, block: dict, *, timeout: float = 8.0) -> bool:
    strategies = block.get("strategies", [])
    deadline = time.time() + timeout
    while time.time() < deadline:
        for strat in strategies:
            try:
                await session.tap(strat["value"], using=strat["using"])
                logger.info("tapped [%s] %s", strat["using"], strat["value"])
                return True
            except Exception:  # noqa: BLE001
                continue
        await session.sleep(0.3)
    return False


async def _tap_bookmarks_fallback(session: AutomatorSession, block: dict) -> bool:
    xy = block.get("fallback_xy") or {}
    try:
        x_ratio = float(xy.get("x_ratio", 0.70))
        y_ratio = float(xy.get("y_ratio", 0.94))
    except (TypeError, ValueError):
        return False
    size = await session.window_size()
    x = int(int(size["width"]) * x_ratio)
    y = int(int(size["height"]) * y_ratio)
    await session.tap_xy(x, y)
    return True


async def _dismiss_optional(session: AutomatorSession, safari: dict) -> None:
    block = safari.get("dismiss_whats_new")
    if block and await _tap_any(session, block, timeout=2.0):
        await session.sleep(0.4)


async def _ensure_history(session: AutomatorSession, safari: dict) -> None:
    xml = await session.source_xml()
    if _history_visible(xml):
        return
    safari_phase("bookmarks", "tap Bookmarks")
    opened = await _tap_any(session, safari["bookmarks"], timeout=5.0)
    if not opened:
        logger.warning("Tombol Bookmarks tidak ketemu — fallback koordinat toolbar")
        await _tap_bookmarks_fallback(session, safari["bookmarks"])
    await session.sleep(0.8)
    xml = await session.source_xml()
    if _history_visible(xml):
        return
    safari_phase("history", "tap History / Riwayat")
    if not await _tap_any(session, safari["history_tab"], timeout=5.0):
        logger.warning("Tab History tidak ketemu — lanjut layar sekarang")
    await session.sleep(0.8)


async def run_safari_history(args) -> int:
    safari = _load_selectors()
    bundle = resolve_bundle_id("safari")
    out_dir = Path(args.output) if args.output else default_output_dir("safari_history")
    out_dir.mkdir(parents=True, exist_ok=True)
    wda_url = args.http or "http://127.0.0.1:8100"
    max_shots = _env_int("IOS_SAFARI_MAX_SCREENSHOTS", 5)
    pause = _env_float("IOS_SAFARI_SCROLL_PAUSE_SEC", 0.45)
    duration = _env_float("IOS_SAFARI_SCROLL_DURATION_SEC", 0.2)
    distance = min(0.95, _env_float("IOS_SAFARI_SCROLL_DISTANCE", 0.72))
    scroll_dir = os.environ.get("IOS_SAFARI_SCROLL_DIRECTION", "down").strip().lower()
    if scroll_dir not in {"up", "down"}:
        scroll_dir = "down"
    debug_source = os.environ.get("IOS_SAFARI_DEBUG_SOURCE", "0").strip() == "1"

    session = AutomatorSession.connect_http(wda_url, timeout=max(args.timeout, 30.0))
    collected: list[dict[str, Any]] = []
    try:
        safari_phase("launch", f"bundle={bundle}")
        await session.start(bundle)
        await session.sleep(float(safari.get("launch_wait_sec", 2.0)))
        await _dismiss_optional(session, safari)
        await _ensure_history(session, safari)

        shots: list[str] = []
        for i in range(max_shots):
            xml = await session.source_xml()
            if i == 0 or debug_source:
                name = "page_source_history.xml" if i == 0 else f"page_source_history_{i:02d}.xml"
                (out_dir / name).write_text(xml, encoding="utf-8")
            visible = _parse_history_rows(xml)
            collected = _merge_rows(collected, visible)
            png = out_dir / f"history_{i:02d}.png"
            await session.screenshot(png)
            shots.append(png.name)
            safari_phase(
                "history",
                f"shot {i + 1}/{max_shots} visible={len(visible)} unique={len(collected)}",
            )
            if i + 1 >= max_shots:
                break
            await session.scroll(scroll_dir, distance=distance, duration=duration)
            await session.sleep(pause)

        payload = {
            "app": "safari",
            "scope": "visible_history_only",
            "captured": [
                "title (jika terlihat di cell)",
                "url / hostname (jika terlihat di cell)",
                "history screenshots",
            ],
            "not_captured": [
                "History.db lengkap",
                "private browsing",
                "item yang belum di-scroll ke layar",
                "Chrome / Firefox (bukan Safari)",
            ],
            "screenshots": shots,
            "count": len(collected),
            "visits": collected,
        }
        (out_dir / "history.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Safari history: %d kunjungan unik → %s", len(collected), out_dir.resolve())
        safari_done(out_dir, ok=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("Safari history flow failed: %s", exc)
        safari_phase("error", str(exc))
        try:
            await session.screenshot(out_dir / "error.png")
            (out_dir / "page_source_error.xml").write_text(await session.source_xml(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        safari_done(out_dir, ok=False)
        return 1
    finally:
        await session.close()
