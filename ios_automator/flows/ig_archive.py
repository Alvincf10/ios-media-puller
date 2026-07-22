"""IG: Home → Profile → read stats → screenshot → Menu → Archive (WDA HTTP)."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from lib.apps import resolve_bundle_id
from lib.run_log import ig_done, ig_phase
from lib.session import AutomatorSession, default_output_dir

logger = logging.getLogger("ios_automator.ig_archive")

SELECTORS = Path(__file__).resolve().parents[1] / "appium" / "selectors.json"

SKIP_NAMES = frozenset(
    {
        "profile",
        "profil",
        "instagram",
        "back",
        "menu",
        "options",
        "opsi",
        "settings",
        "pengaturan",
        "home",
        "beranda",
        "archive",
        "arsip",
        "edit profile",
        "share profile",
        "posts",
        "post",
        "followers",
        "following",
        "pengikut",
        "mengikuti",
        "complete your profile",
        "can't decide...",
        "",
    }
)

BIO_SKIP = frozenset(
    {
        "add a bio",
        "add bio",
        "tell your followers a little bit about yourself.",
        "activator-bio-small",
    }
)

# IG handle: denirwan_08 (tanpa @ di accessibility tree)
HANDLE_RE = re.compile(r"^@?([a-z][a-z0-9._]{2,29})$", re.IGNORECASE)
STAT_VALUE_RE = re.compile(
    r"^([\d,.]+(?:[KMBkmb])?)\s+"
    r"(post|posts|posting|postingan|follower|followers|pengikut|following|mengikuti)\b",
    re.IGNORECASE,
)


def _looks_like_handle(text: str) -> bool:
    m = HANDLE_RE.match(text.strip())
    return bool(m and ("_" in m.group(1) or m.group(1).isalnum()))


def _looks_like_display_name(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 2 or len(t) > 40:
        return False
    low = t.lower()
    if low in SKIP_NAMES:
        return False
    if low.startswith(("tap ", "switch ", "add ", "complete ", "find ")):
        return False
    if "tap to" in low or "open settings" in low or "creation menu" in low:
        return False
    if any(ch.isdigit() for ch in t) and " " not in t:
        return False
    if t.startswith("http"):
        return False
    # Nama tampilan: "Denirwan" — huruf, boleh spasi tipis
    return t[0].isupper() and not t.startswith("Edit") and not t.startswith("Share")


def _load_selectors() -> dict:
    with SELECTORS.open(encoding="utf-8") as fh:
        return json.load(fh)["instagram"]


async def _tap_any(
    session: AutomatorSession,
    block: dict,
    *,
    timeout: float = 18.0,
) -> None:
    strategies = block.get("strategies", [])
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        for strat in strategies:
            using = strat["using"]
            value = strat["value"]
            try:
                await session.tap(value, using=using)
                logger.info("tapped [%s] %s", using, value)
                return
            except Exception as exc:  # noqa: BLE001
                last = exc
        await session.sleep(0.35)

    fb = block.get("fallback_xy")
    if fb:
        size = await session.window_size()
        x = int(size["width"] * float(fb["x_ratio"]))
        y = int(size["height"] * float(fb["y_ratio"]))
        logger.warning("selector gagal, tap_xy fallback (%d, %d)", x, y)
        await session.tap_xy(x, y)
        return

    raise RuntimeError(f"Element not found: {strategies!r}; last={last}")


async def _element_id(session: AutomatorSession, using: str, value: str) -> str | None:
    try:
        await session.ensure_session()
        eid = await session._call(  # noqa: SLF001
            session.client.find_element,
            using,
            value,
            session.session_id,
        )
        return eid or None
    except Exception:  # noqa: BLE001
        return None


async def _wait_and_tap_profile(session: AutomatorSession, ig: dict) -> None:
    """Tap Profile segera setelah tab bar IG siap — tidak menunggu home marker penuh."""
    block = ig["profile_tab"]
    strategies = block.get("strategies", [])
    max_wait = float(ig.get("profile_tab_wait_sec", 10.0))
    poll = float(ig.get("profile_tab_poll_sec", 0.25))
    deadline = time.time() + max_wait

    while time.time() < deadline:
        for strat in strategies:
            using = strat["using"]
            value = strat["value"]
            if await _element_id(session, using, value):
                await session.tap(value, using=using)
                logger.info("profile tab ready — tapped [%s] %s", using, value)
                return
        await session.sleep(poll)

    logger.warning("profile tab belum ready dalam %.1fs — fallback tap_any", max_wait)
    await _tap_any(session, block)


async def _wait_home_optional(session: AutomatorSession, ig: dict) -> None:
    """Legacy: tunggu home marker (dipakai Appium flow). HTTP flow pakai _wait_and_tap_profile."""
    home = ig.get("home_marker", {})
    if not home.get("strategies"):
        return
    if home.get("optional"):
        deadline = time.time() + 3.0
        while time.time() < deadline:
            for strat in home["strategies"]:
                if await _element_id(session, strat["using"], strat["value"]):
                    logger.info("home marker found: %s", strat["value"])
                    return
            await session.sleep(0.25)
        logger.warning("home marker tidak ketemu — lanjut")
        return
    await _tap_any(session, home, timeout=20.0)


def _parse_count(raw: str) -> int | str:
    text = raw.strip().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMBkmb])?$", text)
    if not m:
        return raw.strip()
    num = float(m.group(1))
    suffix = (m.group(2) or "").upper()
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(num * mult)


def _node_text(node: ET.Element) -> str:
    for key in ("value", "label", "name"):
        val = (node.attrib.get(key) or "").strip()
        if val:
            return val
    return ""


def _find_node(root: ET.Element, name_hint: str) -> ET.Element | None:
    hint = name_hint.lower()
    for node in root.iter():
        name = (node.attrib.get("name") or "").lower()
        if hint in name:
            return node
    return None


def _stat_from_button(root: ET.Element, name_hint: str) -> int | str | None:
    node = _find_node(root, name_hint)
    if node is None:
        return None
    text = _node_text(node)
    m = STAT_VALUE_RE.match(text)
    if m:
        return _parse_count(m.group(1))
    # Fallback: angka di child StaticText pertama
    for child in node.iter():
        if child is node:
            continue
        val = (child.attrib.get("value") or child.attrib.get("name") or "").strip()
        if val.isdigit():
            return int(val)
    return None


def _read_bio(root: ET.Element) -> str:
    # IG iOS 18+ exposes bio as user-detail-header-info-label (bukan *-bio).
    for hint in (
        "user-detail-header-info-label",
        "user-detail-header-bio",
        "profile-bio",
        "user-bio",
    ):
        node = _find_node(root, hint)
        if node is None:
            continue
        text = _node_text(node)
        if text and text.lower() not in BIO_SKIP and hint not in text:
            return text
        for child in node.iter():
            if child is node:
                continue
            child_text = _node_text(child)
            if child_text and child_text.lower() not in BIO_SKIP:
                return child_text

    for node in root.iter():
        name = (node.attrib.get("name") or "").strip()
        low = name.lower()
        if "bio" not in low or "activator" in low or low in BIO_SKIP:
            continue
        text = _node_text(node)
        if text and text.lower() not in BIO_SKIP and not text.lower().startswith("add "):
            return text
    return ""


def _read_profile_info(xml: str, ig: dict) -> dict[str, Any]:
    root = ET.fromstring(xml)

    username = ""
    title_btn = _find_node(root, "user-switch-title-button")
    if title_btn is not None:
        cand = _node_text(title_btn).lstrip("@")
        if _looks_like_handle(cand):
            username = cand

    display_name = ""
    for node in root.iter():
        name = (node.attrib.get("name") or "").strip()
        label = (node.attrib.get("label") or "").strip()
        if not name or name != label or not _looks_like_display_name(name):
            continue
        y = int(node.attrib.get("y", "0") or 0)
        if 95 <= y <= 240:
            display_name = name
            break

    for hint in ("user-detail-header-username", "user-detail-header-full-name"):
        if display_name:
            break
        node = _find_node(root, hint)
        if node is not None:
            text = _node_text(node)
            if text and not _looks_like_handle(text) and _looks_like_display_name(text):
                display_name = text
                break

    posts = _stat_from_button(root, "user-detail-header-media-button")
    followers = _stat_from_button(root, "user-detail-header-followers")
    following = _stat_from_button(root, "user-detail-header-following")

    handles: list[str] = []
    display_names: list[str] = []
    for node in root.iter():
        for key in ("name", "label", "value"):
            field = (node.attrib.get(key) or "").strip()
            if not field or field.lower() in SKIP_NAMES:
                continue
            if _looks_like_handle(field):
                handles.append(field.lstrip("@"))
            elif _looks_like_display_name(field):
                display_names.append(field)

    if not username and handles:
        handles.sort(key=lambda h: ("_" not in h, h))
        username = handles[0]
    if not display_name and display_names:
        display_name = display_names[0]

    if not username:
        for pat in (
            r'name="(@?[a-z][a-z0-9._]{2,29})"',
            r'label="(@?[a-z][a-z0-9._]{2,29})"',
            r'value="(@?[a-z][a-z0-9._]{2,29})"',
        ):
            for m in re.finditer(pat, xml):
                val = m.group(1).strip().lstrip("@")
                if _looks_like_handle(val):
                    username = val
                    break
            if username:
                break

    if not display_name:
        for pat in (r'name="([A-Z][a-zA-Z]{2,30})"', r'label="([A-Z][a-zA-Z]{2,30})"'):
            for m in re.finditer(pat, xml):
                val = m.group(1).strip()
                if _looks_like_display_name(val):
                    display_name = val
                    break
            if display_name:
                break

    bio = _read_bio(root)

    info = {
        "username": username or "UNKNOWN",
        "display_name": display_name,
        "bio": bio,
        "posts": posts if posts is not None else "",
        "followers": followers if followers is not None else "",
        "following": following if following is not None else "",
    }
    if info["username"] == "UNKNOWN":
        for strat in ig.get("profile_name", {}).get("strategies", []):
            val = strat.get("value")
            if val and _looks_like_handle(val):
                info["username"] = val.lstrip("@")
                break
    return info


async def _read_profile(session: AutomatorSession, ig: dict, out_dir: Path) -> dict[str, Any]:
    xml = await session.source_xml()
    (out_dir / "page_source_profile.xml").write_text(xml, encoding="utf-8")
    info = _read_profile_info(xml, ig)
    (out_dir / "profile.json").write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Backward compat
    (out_dir / "profile_name.txt").write_text(info["username"] + "\n", encoding="utf-8")
    return info


async def run_ig_archive(args) -> int:
    ig = _load_selectors()
    bundle = resolve_bundle_id("instagram")
    out_dir = Path(args.output) if args.output else default_output_dir("ig_archive")
    out_dir.mkdir(parents=True, exist_ok=True)
    wda_url = args.http or "http://127.0.0.1:8100"

    session = AutomatorSession.connect_http(wda_url, timeout=max(args.timeout, 30.0))
    try:
        ig_phase("launch", f"bundle={bundle}")
        await session.start(bundle)
        wait_sec = float(ig.get("launch_wait_sec", 1.0))
        logger.info("Tunggu IG shell %.1fs", wait_sec)
        await session.sleep(wait_sec)

        ig_phase("profile", "tap tab Profile")
        logger.info("Tap Profile tab (segera setelah tab bar siap)")
        await _wait_and_tap_profile(session, ig)
        await session.sleep(0.8)

        profile = await _read_profile(session, ig, out_dir)
        ig_phase(
            "profile",
            f"@{profile['username']} posts={profile['posts']} followers={profile['followers']} following={profile['following']}",
        )
        logger.info(
            "Profile: @%s | posts=%s followers=%s following=%s bio=%r",
            profile["username"],
            profile["posts"],
            profile["followers"],
            profile["following"],
            profile["bio"],
        )
        await session.screenshot(out_dir / "profile.png")
        ig_phase("screenshot", "profile.png")

        if getattr(args, "stop_after", "all") == "profile":
            ig_done(out_dir, ok=True)
            return 0

        ig_phase("archive", "tap Menu / Settings")
        logger.info("Tap Menu / Settings")
        await _tap_any(session, ig["menu_button"])
        await session.sleep(1.0)

        logger.info("Tap Archive")
        await _tap_any(session, ig["archive_item"])
        await session.sleep(1.0)
        await session.screenshot(out_dir / "archive.png")
        ig_phase("screenshot", "archive.png")

        logger.info("Done → %s", out_dir.resolve())
        ig_done(out_dir, ok=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("IG archive flow failed: %s", exc)
        ig_phase("error", str(exc))
        try:
            await session.screenshot(out_dir / "error.png")
            (out_dir / "page_source_error.xml").write_text(await session.source_xml(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        ig_done(out_dir, ok=False)
        return 1
    finally:
        await session.close()
