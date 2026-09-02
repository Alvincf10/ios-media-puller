"""Apple Mail: Inbox yang terlihat → pengirim / subjek / screenshot (WDA HTTP).

Hanya data di layar. Bukan backup, bukan body email, bukan seluruh mailbox.
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
from lib.run_log import mail_done, mail_phase
from lib.session import AutomatorSession, default_output_dir

logger = logging.getLogger("ios_automator.mail_inbox")

SELECTORS = Path(__file__).resolve().parents[1] / "appium" / "selectors.json"

CHROME = frozenset(
    {
        "mail",
        "mailboxes",
        "kotak surat",
        "inbox",
        "kotak masuk",
        "all inboxes",
        "semua kotak masuk",
        "vip",
        "flagged",
        "ditandai",
        "drafts",
        "konsep",
        "sent",
        "terkirim",
        "trash",
        "sampah",
        "junk",
        "search",
        "cari",
        "edit",
        "filter",
        "filters",
        "compose",
        "tulis",
        "new message",
        "pesan baru",
        "get mail",
        "ambil mail",
        "select",
        "pilih",
        "cancel",
        "batal",
        "done",
        "selesai",
        "continue",
        "lanjutkan",
        "not now",
        "jangan sekarang",
        "allow",
        "izinkan",
        "don't allow",
        "jangan izinkan",
        "today",
        "hari ini",
        "yesterday",
        "kemarin",
        "unread",
        "belum dibaca",
        "see all",
        "lihat semua",
        "",
    }
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TIME_RE = re.compile(
    r"^("
    r"today|hari ini|yesterday|kemarin|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"senin|selasa|rabu|kamis|jumat|jum'?at|sabtu|minggu|"
    r"\d{1,2}:\d{2}(\s*[ap]\.?m\.?)?|"
    r"\d{1,2}[./-]\d{1,2}([./-]\d{2,4})?"
    r")$",
    re.IGNORECASE,
)


def _load_selectors() -> dict:
    with SELECTORS.open(encoding="utf-8") as fh:
        return json.load(fh)["mail"]


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


def _looks_time(text: str) -> bool:
    return bool(TIME_RE.match(text.strip()))


def _cell_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            (row.get("sender_name") or "").strip().lower(),
            (row.get("subject") or "").strip().lower()[:80],
        ]
    )


def _parse_texts_to_row(texts: list[str], *, y: int, full_label: str) -> dict[str, Any] | None:
    parts = [t.strip() for t in texts if t and t.strip() and not _looks_chrome(t)]
    if not parts:
        return None
    time_label = ""
    if parts and _looks_time(parts[-1]):
        time_label = parts.pop()
    sender = parts[0] if parts else ""
    if not sender or _looks_chrome(sender) or _looks_time(sender):
        return None
    subject = parts[1] if len(parts) > 1 else ""
    preview = " ".join(parts[2:]) if len(parts) > 2 else ""
    emails = EMAIL_RE.findall(full_label or " ".join(parts))
    return {
        "sender_name": sender,
        "sender_email": emails[0] if emails else "",
        "subject": subject,
        "preview": preview,
        "time_label": time_label,
        "y": y,
    }


def _parse_inbox_rows(xml: str) -> list[dict[str, Any]]:
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
        if h < 36 or y < 80:
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


async def _dismiss_optional(session: AutomatorSession, mail: dict) -> None:
    for key in ("dismiss_notification", "dismiss_whats_new"):
        block = mail.get(key)
        if not block:
            continue
        if await _tap_any(session, block, timeout=2.0):
            await session.sleep(0.4)


def _mailbox_list_visible(xml: str) -> bool:
    low = xml.lower()
    return ("mailboxes" in low or "kotak surat" in low) and (
        "all inboxes" in low or "inbox" in low or "kotak masuk" in low
    )


async def _ensure_inbox(session: AutomatorSession, mail: dict) -> None:
    xml = await session.source_xml()
    if _parse_inbox_rows(xml):
        return
    if _mailbox_list_visible(xml):
        mail_phase("inbox", "tap Inbox / All Inboxes")
        if not await _tap_any(session, mail["inbox_mailbox"], timeout=6.0):
            logger.warning("Tidak ketemu tombol Inbox — lanjut layar sekarang")
        await session.sleep(1.0)


async def run_mail_inbox(args) -> int:
    mail = _load_selectors()
    bundle = resolve_bundle_id("mail")
    out_dir = Path(args.output) if args.output else default_output_dir("mail_inbox")
    out_dir.mkdir(parents=True, exist_ok=True)
    wda_url = args.http or "http://127.0.0.1:8100"
    max_shots = _env_int("IOS_MAIL_MAX_SCREENSHOTS", 5)
    pause = _env_float("IOS_MAIL_SCROLL_PAUSE_SEC", 0.45)
    duration = _env_float("IOS_MAIL_SCROLL_DURATION_SEC", 0.2)
    distance = min(0.95, _env_float("IOS_MAIL_SCROLL_DISTANCE", 0.72))
    scroll_dir = os.environ.get("IOS_MAIL_SCROLL_DIRECTION", "down").strip().lower()
    if scroll_dir not in {"up", "down"}:
        scroll_dir = "down"
    debug_source = os.environ.get("IOS_MAIL_DEBUG_SOURCE", "0").strip() == "1"

    session = AutomatorSession.connect_http(wda_url, timeout=max(args.timeout, 30.0))
    collected: list[dict[str, Any]] = []
    try:
        mail_phase("launch", f"bundle={bundle}")
        await session.start(bundle)
        await session.sleep(float(mail.get("launch_wait_sec", 2.0)))
        await _dismiss_optional(session, mail)
        await _ensure_inbox(session, mail)

        shots: list[str] = []
        for i in range(max_shots):
            xml = await session.source_xml()
            if i == 0 or debug_source:
                name = "page_source_inbox.xml" if i == 0 else f"page_source_inbox_{i:02d}.xml"
                (out_dir / name).write_text(xml, encoding="utf-8")
            visible = _parse_inbox_rows(xml)
            collected = _merge_rows(collected, visible)
            png = out_dir / f"inbox_{i:02d}.png"
            await session.screenshot(png)
            shots.append(png.name)
            mail_phase(
                "inbox",
                f"shot {i + 1}/{max_shots} visible={len(visible)} unique={len(collected)}",
            )
            if i + 1 >= max_shots:
                break
            await session.scroll(scroll_dir, distance=distance, duration=duration)
            await session.sleep(pause)

        payload = {
            "app": "mail",
            "scope": "visible_inbox_only",
            "captured": [
                "sender_name",
                "sender_email (hanya jika terlihat di cell)",
                "subject",
                "preview",
                "time_label",
                "inbox screenshots",
            ],
            "not_captured": [
                "email body",
                "attachments",
                "full mailbox / Envelope Index",
                "accounts yang tidak terbuka di layar",
            ],
            "screenshots": shots,
            "count": len(collected),
            "messages": collected,
        }
        (out_dir / "senders.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info("Mail inbox: %d pengirim unik → %s", len(collected), out_dir.resolve())
        mail_done(out_dir, ok=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("Mail inbox flow failed: %s", exc)
        mail_phase("error", str(exc))
        try:
            await session.screenshot(out_dir / "error.png")
            (out_dir / "page_source_error.xml").write_text(await session.source_xml(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        mail_done(out_dir, ok=False)
        return 1
    finally:
        await session.close()
