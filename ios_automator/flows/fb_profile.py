"""Facebook: Home screenshot → Profile → name / friends / posts / followers."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from lib.apps import resolve_bundle_id
from lib.run_log import fb_done, fb_phase
from lib.session import AutomatorSession, default_output_dir

logger = logging.getLogger("ios_automator.fb_profile")

SELECTORS = Path(__file__).resolve().parents[1] / "appium" / "selectors.json"

SKIP_NAMES = frozenset(
    {
        "facebook",
        "home",
        "beranda",
        "profile",
        "profil",
        "your profile",
        "menu",
        "friends",
        "teman",
        "followers",
        "pengikut",
        "following",
        "posts",
        "postingan",
        "see all",
        "lihat semua",
        "edit profile",
        "edit profil",
        "edit profile picture",
        "edit cover photo button",
        "cover photo",
        "profile picture",
        "profile tools",
        "search facebook",
        "add to story",
        "create",
        "buat",
        "photos",
        "reels",
        "notifications",
        "groups",
        "manage posts",
        "",
    }
)

PROFILE_TAB_LABELS = (
    "your profile",
    "profil anda",
    "profil kamu",
    "profile",
    "profil",
)

# "1,411 friends" | "1.4K friends" | "1,4 ribu teman" | "234 posts"
STAT_RE = re.compile(
    r"^([\d.,]+)\s*"
    r"(?:([KMBkmb])|thousand|ribu|million|juta)?\s*"
    r"(friends?|teman|followers?|pengikut|following|mengikuti|posts?|postingan)\b",
    re.IGNORECASE,
)
NUMBER_ONLY_RE = re.compile(r"^[\d.,]+$")


def _load_selectors() -> dict:
    with SELECTORS.open(encoding="utf-8") as fh:
        return json.load(fh)["facebook"]


def _normalize_locale_number(raw: str) -> float:
    text = raw.strip().lower().replace("\u00a0", " ")
    word_mult = {
        "k": 1_000,
        "thousand": 1_000,
        "ribu": 1_000,
        "m": 1_000_000,
        "million": 1_000_000,
        "juta": 1_000_000,
        "b": 1_000_000_000,
    }
    m = re.match(
        r"^([\d.,]+)\s*([kmb]|thousand|ribu|million|juta)?$",
        text,
        re.IGNORECASE,
    )
    if not m:
        raise ValueError(f"bukan angka: {raw!r}")
    num_s = m.group(1)
    suffix = (m.group(2) or "").lower()
    mult = float(word_mult.get(suffix, 1))

    if "," in num_s and "." in num_s:
        if num_s.rfind(",") > num_s.rfind("."):
            num_s = num_s.replace(".", "").replace(",", ".")
        else:
            num_s = num_s.replace(",", "")
    elif "," in num_s:
        parts = num_s.split(",")
        num_s = "".join(parts[:-1]) + "." + parts[-1] if len(parts[-1]) <= 2 else num_s.replace(",", "")
    elif "." in num_s:
        parts = num_s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[0].isdigit():
            num_s = "".join(parts)
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


def _find_tab_bar_button(xml: str, labels: tuple[str, ...]) -> tuple[int, int] | None:
    """Cari tombol tab bar by label → kembalikan pusat (x, y)."""
    root = ET.fromstring(xml)
    wanted = [l.lower() for l in labels]
    for node in root.iter():
        if not node.tag.endswith("Button"):
            continue
        label = (node.attrib.get("label") or "").strip().lower()
        name = (node.attrib.get("name") or "").strip().lower()
        matched = False
        for w in wanted:
            if label == w or name == w or (w in label) or (w in name and "tab-bar" not in name):
                matched = True
                break
        if not matched:
            continue
        try:
            x = int(node.attrib.get("x", "0") or 0)
            y = int(node.attrib.get("y", "0") or 0)
            w = int(node.attrib.get("width", "0") or 0)
            h = int(node.attrib.get("height", "0") or 0)
        except ValueError:
            continue
        # Tab bar biasanya di bawah layar
        if y < 600 or w < 20 or h < 20:
            continue
        return x + w // 2, y + h // 2
    return None


async def _wait_and_tap_profile(session: AutomatorSession, fb: dict) -> None:
    """Tap tab Profile. FB iOS pakai label 'Your profile' (id tab-bar-item-* dinamis)."""
    block = fb["profile_tab"]
    strategies = block.get("strategies", [])
    max_wait = float(fb.get("profile_tab_wait_sec", 12.0))
    poll = float(fb.get("profile_tab_poll_sec", 0.25))
    deadline = time.time() + max_wait
    labels = tuple(fb.get("profile_tab_labels", list(PROFILE_TAB_LABELS)))

    while time.time() < deadline:
        # 1) Dari page source — paling andal untuk label "Your profile"
        try:
            xml = await session.source_xml()
            point = _find_tab_bar_button(xml, labels)
            if point:
                x, y = point
                await session.tap_xy(x, y)
                logger.info("profile tab via page source — tap_xy (%d, %d)", x, y)
                return
        except Exception as exc:  # noqa: BLE001
            logger.debug("page source tab lookup: %s", exc)

        # 2) Selector WDA biasa
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


def _looks_like_display_name(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 2 or len(t) > 60:
        return False
    low = t.lower()
    if low in SKIP_NAMES:
        return False
    if "search" in low or "facebook" in low:
        return False
    if low.startswith(("tap ", "add ", "create ", "see ", "find ", "edit ", "manage ")):
        return False
    if any(k in low for k in ("friend", "follower", "post", "teman", "pengikut", "postingan", "story", "photo")):
        return False
    if t.startswith("http"):
        return False
    if NUMBER_ONLY_RE.match(t):
        return False
    return t[0].isalpha()


def _assign_stat(kind: str, value: int | str, info: dict[str, Any]) -> None:
    kind = kind.lower()
    if kind.startswith("friend") or kind == "teman":
        if info.get("friends") in ("", None):
            info["friends"] = value
    elif kind.startswith("follower") or kind == "pengikut":
        if info.get("followers") in ("", None):
            info["followers"] = value
    elif kind.startswith("following") or kind == "mengikuti":
        if info.get("following") in ("", None):
            info["following"] = value
    elif kind.startswith("post"):
        if info.get("posts") in ("", None):
            info["posts"] = value


def _read_profile_info(xml: str) -> dict[str, Any]:
    root = ET.fromstring(xml)
    info: dict[str, Any] = {
        "display_name": "",
        "friends": "",
        "posts": "",
        "followers": "",
        "following": "",
    }

    # Stats dari teks "N friends / N posts / N followers" (button name/label)
    for node in root.iter():
        for key in ("name", "label", "value"):
            field = (node.attrib.get(key) or "").strip()
            if not field:
                continue
            m = STAT_RE.match(field)
            if not m:
                continue
            num_raw = m.group(1)
            suffix = m.group(2) or ""
            kind = m.group(3)
            low = field.lower()
            if re.search(r"\b(thousand|ribu)\b", low):
                parsed = _parse_count(f"{num_raw} thousand")
            elif re.search(r"\b(million|juta)\b", low):
                parsed = _parse_count(f"{num_raw} million")
            elif suffix and re.fullmatch(r"[KMBkmb]", suffix):
                parsed = _parse_count(f"{num_raw}{suffix}")
            else:
                parsed = _parse_count(num_raw)
            _assign_stat(kind, parsed, info)

    # Nama: Button name==label di area header (dekat foto profil), contoh "Deni Irwan"
    name_candidates: list[tuple[int, str]] = []
    for node in root.iter():
        if not node.tag.endswith("Button"):
            continue
        name = (node.attrib.get("name") or "").strip()
        label = (node.attrib.get("label") or "").strip()
        if not name or name != label or not _looks_like_display_name(name):
            continue
        y = int(node.attrib.get("y", "0") or 0)
        if 100 <= y <= 280:
            name_candidates.append((y, name))
    if name_candidates:
        name_candidates.sort(key=lambda c: c[0])
        info["display_name"] = name_candidates[0][1]

    if not info["display_name"]:
        for node in root.iter():
            if not node.tag.endswith("StaticText"):
                continue
            text = _node_text(node)
            if not _looks_like_display_name(text):
                continue
            y = int(node.attrib.get("y", "0") or 0)
            h = int(node.attrib.get("height", "0") or 0)
            if 40 <= y <= 320 and h >= 18:
                info["display_name"] = text
                break

    return info


async def _on_profile_screen(session: AutomatorSession) -> bool:
    xml = await session.source_xml()
    low = xml.lower()
    return (
        'label="your profile"' in low and "selected" in low
    ) or ("edit profile" in low and "2 posts" in low) or (
        "edit profile" in low and "profile picture" in low and "cover photo" in low
    )


async def run_fb_profile(args) -> int:
    fb = _load_selectors()
    bundle = resolve_bundle_id("facebook")
    out_dir = Path(args.output) if args.output else default_output_dir("fb_profile")
    out_dir.mkdir(parents=True, exist_ok=True)
    wda_url = args.http or "http://127.0.0.1:8100"

    session = AutomatorSession.connect_http(wda_url, timeout=max(args.timeout, 30.0))
    try:
        fb_phase("launch", f"bundle={bundle}")
        await session.start(bundle)
        wait_sec = float(fb.get("launch_wait_sec", 2.0))
        logger.info("Tunggu Facebook shell %.1fs", wait_sec)
        await session.sleep(wait_sec)

        fb_phase("home", "screenshot homepage")
        await session.screenshot(out_dir / "home.png")
        try:
            (out_dir / "page_source_home.xml").write_text(await session.source_xml(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        fb_phase("profile", "tap tab Your profile")
        logger.info("Tap Profile tab (Your profile)")
        await _wait_and_tap_profile(session, fb)
        await session.sleep(float(fb.get("profile_settle_sec", 1.5)))

        if not await _on_profile_screen(session):
            logger.warning("Belum di layar profile — tap ulang Your profile")
            await _wait_and_tap_profile(session, fb)
            await session.sleep(1.5)

        xml = await session.source_xml()
        (out_dir / "page_source_profile.xml").write_text(xml, encoding="utf-8")
        profile = _read_profile_info(xml)
        (out_dir / "profile.json").write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        fb_phase(
            "profile",
            f"name={profile['display_name']!r} friends={profile['friends']} "
            f"posts={profile['posts']} followers={profile['followers']}",
        )
        logger.info(
            "Profile: name=%r friends=%s posts=%s followers=%s following=%s",
            profile["display_name"],
            profile["friends"],
            profile["posts"],
            profile["followers"],
            profile["following"],
        )

        await session.screenshot(out_dir / "profile.png")
        fb_phase("screenshot", "profile.png")

        logger.info("Done → %s", out_dir.resolve())
        fb_done(out_dir, ok=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("Facebook profile flow failed: %s", exc)
        fb_phase("error", str(exc))
        try:
            await session.screenshot(out_dir / "error.png")
            (out_dir / "page_source_error.xml").write_text(await session.source_xml(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        fb_done(out_dir, ok=False)
        return 1
    finally:
        await session.close()
