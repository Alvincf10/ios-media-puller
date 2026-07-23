"""IG: Home → Profile → read stats → screenshot → Menu → Archive (WDA HTTP)."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from lib.apps import resolve_bundle_id
from lib.run_log import ig_done, ig_phase
from lib.session import AutomatorSession, default_output_dir

logger = logging.getLogger("ios_automator.ig_profile")

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
        "start your first note...",
        "start your first note",
        "notes",
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
# "3 posts" | "1.4K followers" | "1,4 thousand followers" | "1,4 ribu pengikut"
STAT_VALUE_RE = re.compile(
    r"^([\d.,]+)\s*"
    r"(?:([KMBkmb])|thousand|ribu|million|juta|billion|miliar)?\s*"
    r"(post|posts|posting|postingan|follower|followers|pengikut|following|mengikuti)\b",
    re.IGNORECASE,
)
NUMBER_ONLY_RE = re.compile(r"^[\d.,]+$")


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
    if low.startswith(("tap ", "switch ", "add ", "complete ", "find ", "start ")):
        return False
    if "first note" in low or "your followers" in low:
        return False
    if "tap to" in low or "open settings" in low or "creation menu" in low:
        return False
    if any(ch.isdigit() for ch in t) and " " not in t:
        return False
    if t.startswith("http"):
        return False
    # Nama tampilan: "Denirwan" / "vin's" — huruf di depan (boleh lowercase)
    return t[0].isalpha() and not t.startswith("Edit") and not t.startswith("Share")


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


def _normalize_locale_number(raw: str) -> float:
    """Parse angka IG lokal: 1.411 → 1411, 1,4 → 1.4, 1.4K / 1,4 thousand."""
    text = raw.strip().lower().replace("\u00a0", " ")
    mult = 1.0
    word_mult = {
        "k": 1_000,
        "thousand": 1_000,
        "ribu": 1_000,
        "m": 1_000_000,
        "million": 1_000_000,
        "juta": 1_000_000,
        "b": 1_000_000_000,
        "billion": 1_000_000_000,
        "miliar": 1_000_000_000,
    }
    m = re.match(
        r"^([\d.,]+)\s*([kmb]|thousand|ribu|million|juta|billion|miliar)?$",
        text,
        re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"bukan angka: {raw!r}")
    num_s = m.group(1)
    suffix = (m.group(2) or "").lower()
    if suffix:
        mult = float(word_mult.get(suffix, 1))

    if "," in num_s and "." in num_s:
        # 1.234,5 (EU) atau 1,234.5 (US) — ambil separator terakhir sebagai desimal
        if num_s.rfind(",") > num_s.rfind("."):
            num_s = num_s.replace(".", "").replace(",", ".")
        else:
            num_s = num_s.replace(",", "")
    elif "," in num_s:
        # 1,4 → desimal; 1,411 → ribuan EU jarang di IG short form
        parts = num_s.split(",")
        num_s = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) <= 2 else num_s.replace(",", "")
    elif "." in num_s:
        parts = num_s.split(".")
        # 1.411 (tiga digit setelah titik) → ribuan; 1.4 → desimal
        if len(parts) == 2 and len(parts[1]) == 3 and parts[0].isdigit():
            num_s = "".join(parts)
        else:
            num_s = num_s  # desimal US / short K form
    return float(num_s) * mult


def _parse_count(raw: str) -> int | str:
    try:
        return int(round(_normalize_locale_number(raw)))
    except ValueError:
        return raw.strip()


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

    # Prefer angka di child StaticText (lebih akurat: "1.411" vs button value "1,4 thousand…")
    for child in node.iter():
        if child is node:
            continue
        if not child.tag.endswith("StaticText"):
            continue
        val = (child.attrib.get("value") or child.attrib.get("name") or "").strip()
        if not val or not NUMBER_ONLY_RE.match(val):
            continue
        parsed = _parse_count(val)
        if isinstance(parsed, int):
            return parsed

    text = _node_text(node)
    m = STAT_VALUE_RE.match(text)
    if not m:
        return None
    num_raw = m.group(1)
    low = text.lower()
    if re.search(r"\b(thousand|ribu)\b", low):
        return _parse_count(f"{num_raw} thousand")
    if re.search(r"\b(million|juta)\b", low):
        return _parse_count(f"{num_raw} million")
    if re.search(r"\b(billion|miliar)\b", low):
        return _parse_count(f"{num_raw} billion")
    suffix = m.group(2) or ""
    if suffix and re.fullmatch(r"[KMBkmb]", suffix):
        return _parse_count(f"{num_raw}{suffix}")
    return _parse_count(num_raw)


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


async def _wait_archive_loaded(session: AutomatorSession, ig: dict) -> None:
    """Tunggu Stories archive selesai loading (spinner hilang) baru screenshot."""
    timeout = float(ig.get("archive_load_timeout_sec", 25.0))
    poll = float(ig.get("archive_load_poll_sec", 0.5))
    stable_needed = float(ig.get("archive_stable_sec", 1.0))
    deadline = time.time() + timeout
    clear_since: float | None = None

    while time.time() < deadline:
        xml = await session.source_xml()
        loading = "XCUIElementTypeActivityIndicator" in xml
        if loading:
            clear_since = None
            logger.debug("Archive masih loading (ActivityIndicator)…")
        else:
            if clear_since is None:
                clear_since = time.time()
                logger.info("Archive spinner hilang — tunggu stabil %.1fs", stable_needed)
            elif time.time() - clear_since >= stable_needed:
                logger.info("Archive ready")
                return
        await session.sleep(poll)

    logger.warning("Archive masih loading setelah %.0fs — screenshot tetap diambil", timeout)


# Banner di atas Stories archive — jangan screenshot sebelum ini hilang dari layar
ARCHIVE_BANNER_HINTS = (
    "your archived stories aren't visible",
    "archived stories aren't visible",
    "aren't visible to other people",
    "story arsip tidak terlihat",
    "arsip story tidak terlihat",
)


def _archive_banner_visible(xml: str) -> bool:
    low = xml.lower()
    return any(h in low for h in ARCHIVE_BANNER_HINTS)


def _archive_scroll_direction() -> str:
    """Arah scroll WDA: 'up' = jari ke bawah (default). 'down' = jari ke atas."""
    raw = os.environ.get("IOS_ARCHIVE_SCROLL_DIRECTION", "up").strip().lower()
    # Alias user-friendly
    if raw in {"bawah", "finger-down", "finger_down"}:
        return "up"
    if raw in {"atas", "finger-up", "finger_up"}:
        return "down"
    if raw in {"up", "down"}:
        return raw
    return "up"


def _archive_max_screenshots() -> int:
    raw = os.environ.get("IOS_ARCHIVE_MAX_SCREENSHOTS", "5").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 5
    return max(1, min(n, 100))


def _archive_scroll_pause_sec() -> float:
    raw = os.environ.get("IOS_ARCHIVE_SCROLL_PAUSE_SEC", "1.0").strip()
    try:
        return max(0.3, float(raw))
    except ValueError:
        return 1.0


def _archive_year_range() -> list[int] | None:
    """Baca IOS_ARCHIVE_YEAR_FROM / IOS_ARCHIVE_YEAR_TO → list tahun inklusif.

    Kosong keduanya = None (tidak filter tahun, perilaku lama).
    """
    raw_from = os.environ.get("IOS_ARCHIVE_YEAR_FROM", "").strip()
    raw_to = os.environ.get("IOS_ARCHIVE_YEAR_TO", "").strip()
    if not raw_from and not raw_to:
        return None
    try:
        y_from = int(raw_from) if raw_from else int(raw_to)
        y_to = int(raw_to) if raw_to else int(raw_from)
    except ValueError:
        logger.warning("YEAR_FROM/TO tidak valid — ignore filter tahun")
        return None
    if y_from > y_to:
        y_from, y_to = y_to, y_from
    # Batasi rentang wajar
    y_from = max(2010, min(y_from, 2100))
    y_to = max(2010, min(y_to, 2100))
    return list(range(y_from, y_to + 1))


def _find_year_tap_point(xml: str, year: int) -> tuple[int, int] | None:
    """Cari elemen yang label/name/value == tahun → pusat tap."""
    root = ET.fromstring(xml)
    year_s = str(year)
    for node in root.iter():
        for key in ("name", "label", "value"):
            val = (node.attrib.get(key) or "").strip()
            if val != year_s and not re.fullmatch(rf"{year_s}\b.*", val):
                if val != year_s:
                    continue
            try:
                x = int(node.attrib.get("x", "0") or 0)
                y = int(node.attrib.get("y", "0") or 0)
                w = int(node.attrib.get("width", "0") or 0)
                h = int(node.attrib.get("height", "0") or 0)
            except ValueError:
                continue
            if w < 10 or h < 10:
                continue
            # Prefer elemen yang tepat "2024"
            if val == year_s:
                return x + w // 2, y + h // 2
    # Second pass: contains year as whole word
    for node in root.iter():
        for key in ("name", "label", "value"):
            val = (node.attrib.get(key) or "").strip()
            if not re.search(rf"\b{year}\b", val):
                continue
            try:
                x = int(node.attrib.get("x", "0") or 0)
                y = int(node.attrib.get("y", "0") or 0)
                w = int(node.attrib.get("width", "0") or 0)
                h = int(node.attrib.get("height", "0") or 0)
            except ValueError:
                continue
            if w >= 10 and h >= 10:
                return x + w // 2, y + h // 2
    return None


async def _tap_archive_subtab(session: AutomatorSession, ig: dict, which: str) -> None:
    """Tap sub-tab archive: grid | calendar."""
    key = "archive_calendar_tab" if which == "calendar" else "archive_grid_tab"
    block = ig.get(key) or {}
    if block.get("strategies"):
        try:
            await _tap_any(session, block, timeout=8.0)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("tap %s via selector gagal: %s — coba page source / xy", which, exc)

    # Fallback: cari label di page source
    labels = {
        "calendar": ("calendar", "kalender"),
        "grid": ("grid", "stories", "arsip cerita"),
    }
    xml = await session.source_xml()
    root = ET.fromstring(xml)
    wanted = labels.get(which, ())
    for node in root.iter():
        if not (node.tag.endswith("Button") or node.tag.endswith("Cell")):
            continue
        blob = f"{node.attrib.get('name', '')} {node.attrib.get('label', '')}".lower()
        if not any(w in blob for w in wanted):
            continue
        try:
            x = int(node.attrib.get("x", "0") or 0)
            y = int(node.attrib.get("y", "0") or 0)
            w = int(node.attrib.get("width", "0") or 0)
            h = int(node.attrib.get("height", "0") or 0)
        except ValueError:
            continue
        if y > 200 or h < 20:
            continue
        await session.tap_xy(x + w // 2, y + h // 2)
        logger.info("archive subtab %s via source (%d,%d)", which, x + w // 2, y + h // 2)
        return

    fb = block.get("fallback_xy")
    if fb:
        size = await session.window_size()
        x = int(size["width"] * float(fb["x_ratio"]))
        y = int(size["height"] * float(fb["y_ratio"]))
        logger.warning("archive subtab %s fallback_xy (%d,%d)", which, x, y)
        await session.tap_xy(x, y)
        return
    raise RuntimeError(f"Archive subtab {which} tidak ditemukan")


async def _select_archive_year(session: AutomatorSession, ig: dict, year: int, out_dir: Path) -> bool:
    """Buka kalender archive dan pilih tahun. Return True jika berhasil tap tahun."""
    ig_phase("archive", f"pilih tahun {year}")
    logger.info("Pilih archive year=%d", year)

    await _tap_archive_subtab(session, ig, "calendar")
    await session.sleep(1.0)
    await _wait_archive_loaded(session, ig)

    xml = await session.source_xml()
    (out_dir / f"page_source_calendar_{year}.xml").write_text(xml, encoding="utf-8")

    # Kadang perlu tap header tahun dulu agar list tahun muncul
    point = _find_year_tap_point(xml, year)
    if point is None:
        # Scroll di kalender untuk cari tahun (dari baru ke lama = jari ke bawah)
        scroll_dir = _archive_scroll_direction()
        for attempt in range(1, 10):
            await session.scroll(scroll_dir, distance=0.4, duration=0.3)
            await session.sleep(0.6)
            xml = await session.source_xml()
            point = _find_year_tap_point(xml, year)
            if point:
                logger.info("Tahun %d ketemu setelah scroll kalender ×%d", year, attempt)
                break
            # Coba arah sebaliknya sekali di tengah
            if attempt == 5:
                scroll_dir = "down" if scroll_dir == "up" else "up"

    if point is None:
        # Tap teks tahun yang sedang tampil (header) lalu cari lagi
        for node_name in (str(year), "Years", "Tahun"):
            try:
                await session.tap(node_name, using="name")
                await session.sleep(0.8)
                break
            except Exception:  # noqa: BLE001
                continue
        xml = await session.source_xml()
        (out_dir / f"page_source_calendar_{year}_picker.xml").write_text(xml, encoding="utf-8")
        point = _find_year_tap_point(xml, year)

    if point is None:
        logger.warning("Tahun %d tidak ditemukan di UI kalender — skip", year)
        return False

    x, y = point
    await session.tap_xy(x, y)
    logger.info("Tapped year %d at (%d,%d)", year, x, y)
    await session.sleep(1.0)
    await _wait_archive_loaded(session, ig)

    # Kembali ke grid stories untuk screenshot thumbnail
    try:
        await _tap_archive_subtab(session, ig, "grid")
        await session.sleep(0.8)
        await _wait_archive_loaded(session, ig)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gagal kembali ke grid setelah pilih tahun: %s", exc)
    return True


async def _scroll_past_archive_banner(session: AutomatorSession, ig: dict) -> None:
    """Scroll ke bawah sampai banner 'Your archived stories aren't visible' hilang."""
    scroll_dir = _archive_scroll_direction()
    pause = _archive_scroll_pause_sec()
    max_scrolls = int(os.environ.get("IOS_ARCHIVE_BANNER_MAX_SCROLLS", "12"))
    max_scrolls = max(1, min(max_scrolls, 40))

    xml = await session.source_xml()
    if not _archive_banner_visible(xml):
        logger.info("Banner archive tidak terlihat — langsung screenshot")
        return

    logger.info(
        "Banner 'Your archived stories aren't visible' masih ada — scroll %s sampai hilang",
        scroll_dir,
    )
    ig_phase("archive", "scroll sampai banner hilang")

    for i in range(1, max_scrolls + 1):
        await session.scroll(scroll_dir, distance=0.45, duration=0.35)
        await session.sleep(pause)
        await _wait_archive_loaded(session, ig)
        xml = await session.source_xml()
        if not _archive_banner_visible(xml):
            logger.info("Banner hilang setelah %d scroll — mulai screenshot", i)
            return
        logger.info("Banner masih ada — scroll lagi (%d/%d)", i, max_scrolls)

    logger.warning(
        "Banner masih terlihat setelah %d scroll — screenshot tetap dilanjutkan",
        max_scrolls,
    )


def _find_year_tap_point(xml: str, year: int) -> tuple[int, int] | None:
    """Cari elemen yang label/name/value == tahun → pusat tap."""
    root = ET.fromstring(xml)
    year_s = str(year)
    exact: tuple[int, int] | None = None
    fuzzy: tuple[int, int] | None = None
    for node in root.iter():
        for key in ("name", "label", "value"):
            val = (node.attrib.get(key) or "").strip()
            if not val:
                continue
            try:
                x = int(node.attrib.get("x", "0") or 0)
                y = int(node.attrib.get("y", "0") or 0)
                w = int(node.attrib.get("width", "0") or 0)
                h = int(node.attrib.get("height", "0") or 0)
            except ValueError:
                continue
            if w < 10 or h < 10:
                continue
            cx, cy = x + w // 2, y + h // 2
            if val == year_s:
                exact = (cx, cy)
            elif re.search(rf"\b{year}\b", val) and fuzzy is None:
                fuzzy = (cx, cy)
    return exact or fuzzy


async def _capture_archive_screenshots_once(
    session: AutomatorSession,
    ig: dict,
    out_dir: Path,
    *,
    prefix: str,
    max_shots: int,
) -> list[str]:
    """Screenshot + scroll satu sesi (satu tahun atau semua)."""
    pause = _archive_scroll_pause_sec()
    scroll_dir = _archive_scroll_direction()
    saved: list[str] = []
    prev_hash: str | None = None

    for i in range(1, max_shots + 1):
        if i > 1:
            await _wait_archive_loaded(session, ig)

        name = f"{prefix}_{i:02d}.png"
        path = out_dir / name
        await session.screenshot(path)
        saved.append(name)
        ig_phase("screenshot", f"{name} ({i}/{max_shots})")

        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if prev_hash is not None and digest == prev_hash:
            logger.info("Screenshot sama dengan sebelumnya — stop (%s)", prefix)
            break
        prev_hash = digest

        if i >= max_shots:
            break

        logger.info("Archive scroll %s (%s %d/%d)…", scroll_dir, prefix, i, max_shots)
        await session.scroll(scroll_dir, distance=0.55, duration=0.35)
        await session.sleep(pause)

    return saved


async def _capture_archive_screenshots(
    session: AutomatorSession,
    ig: dict,
    out_dir: Path,
) -> list[str]:
    """Screenshot archive. Opsional filter tahun via YEAR_FROM / YEAR_TO.

    Env:
      IOS_ARCHIVE_MAX_SCREENSHOTS  — default 5 (per tahun jika filter aktif)
      IOS_ARCHIVE_YEAR_FROM / IOS_ARCHIVE_YEAR_TO — rentang tahun inklusif
      IOS_ARCHIVE_SCROLL_PAUSE_SEC / IOS_ARCHIVE_SCROLL_DIRECTION
    """
    max_shots = _archive_max_screenshots()
    scroll_dir = _archive_scroll_direction()
    years = _archive_year_range()

    await _scroll_past_archive_banner(session, ig)

    saved: list[str] = []
    years_done: list[int] = []
    years_skipped: list[int] = []

    if not years:
        saved = await _capture_archive_screenshots_once(
            session, ig, out_dir, prefix="archive", max_shots=max_shots
        )
    else:
        logger.info("Filter archive tahun %d → %d", years[0], years[-1])
        ig_phase("archive", f"tahun {years[0]}–{years[-1]}")
        for year in years:
            ok = await _select_archive_year(session, ig, year, out_dir)
            if not ok:
                years_skipped.append(year)
                continue
            await _scroll_past_archive_banner(session, ig)
            year_shots = await _capture_archive_screenshots_once(
                session,
                ig,
                out_dir,
                prefix=f"archive_{year}",
                max_shots=max_shots,
            )
            if year_shots:
                years_done.append(year)
                saved.extend(year_shots)
            else:
                years_skipped.append(year)

    # Compat: salin shot pertama sebagai archive.png
    if saved:
        first = out_dir / saved[0]
        if first.is_file():
            (out_dir / "archive.png").write_bytes(first.read_bytes())

    meta = {
        "count": len(saved),
        "max_per_year": max_shots,
        "files": saved,
        "scroll_direction": scroll_dir,
        "year_from": years[0] if years else None,
        "year_to": years[-1] if years else None,
        "years_done": years_done,
        "years_skipped": years_skipped,
    }
    (out_dir / "archive_screenshots.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Archive screenshots: %d file(s) → %s", len(saved), saved)
    return saved


async def run_ig_profile(args) -> int:
    ig = _load_selectors()
    bundle = resolve_bundle_id("instagram")
    out_dir = Path(args.output) if args.output else default_output_dir("ig_profile")
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
        await session.sleep(0.5)
        ig_phase("archive", "tunggu loading selesai")
        await _wait_archive_loaded(session, ig)
        shots = await _capture_archive_screenshots(session, ig, out_dir)
        ig_phase("screenshot", f"archive ×{len(shots)}")

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
