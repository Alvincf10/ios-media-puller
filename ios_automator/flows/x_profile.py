"""X (Twitter): Home screenshot → Profile → parse header → scroll+screenshot posts."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from lib.apps import resolve_bundle_id
from lib.run_log import x_done, x_phase
from lib.session import AutomatorSession, default_output_dir

logger = logging.getLogger("ios_automator.x_profile")

SELECTORS = Path(__file__).resolve().parents[1] / "appium" / "selectors.json"

SKIP_NAMES = frozenset(
    {
        "x",
        "twitter",
        "home",
        "beranda",
        "profile",
        "profil",
        "search",
        "cari",
        "explore",
        "notifications",
        "notifikasi",
        "messages",
        "pesan",
        "communities",
        "komunitas",
        "grok",
        "spaces",
        "edit profile",
        "edit profil",
        "following",
        "mengikuti",
        "followers",
        "pengikut",
        "posts",
        "postingan",
        "replies",
        "balasan",
        "media",
        "likes",
        "suka",
        "highlights",
        "articles",
        "subscribe",
        "langganan",
        "share",
        "bagikan",
        "back",
        "kembali",
        "profile photo",
        "header photo",
        "share profile",
        "finish verification",
        "you’re not verified yet",
        "you're not verified yet",
        "",
    }
)

PROFILE_MENU_LABELS = (
    "profile",
    "profil",
)


def _find_menu_item(xml: str, labels: tuple[str, ...]) -> tuple[int, int] | None:
    """Cari item Profile di side drawer (bukan tab bar)."""
    root = ET.fromstring(xml)
    wanted = [l.lower() for l in labels]
    best: tuple[int, int, int] | None = None  # (y, cx, cy)
    for node in root.iter():
        tag = node.tag
        if not (
            tag.endswith("Button")
            or tag.endswith("Cell")
            or tag.endswith("StaticText")
            or tag.endswith("Other")
        ):
            continue
        label = _clean_ax_text(node.attrib.get("label") or "").lower()
        name = _clean_ax_text(node.attrib.get("name") or "").lower()
        value = _clean_ax_text(node.attrib.get("value") or "").lower()
        matched = False
        for w in wanted:
            if label == w or name == w or value == w:
                matched = True
                break
        if not matched:
            continue
        # Hindari "Edit profile", "Share Profile", "Profile photo"
        blob = f"{label} {name} {value}"
        if any(bad in blob for bad in ("edit", "share", "photo", "header", "menu")):
            continue
        try:
            x = int(node.attrib.get("x", "0") or 0)
            y = int(node.attrib.get("y", "0") or 0)
            width = int(node.attrib.get("width", "0") or 0)
            height = int(node.attrib.get("height", "0") or 0)
        except ValueError:
            continue
        if width < 20 or height < 16:
            continue
        # Drawer item biasanya di kiri layar, di bawah header
        if x > 220 or y < 80 or y > 700:
            continue
        cx, cy = x + width // 2, y + height // 2
        if best is None or y < best[0]:
            best = (y, cx, cy)
    if best:
        return best[1], best[2]
    return None


async def _tap_account_menu(session: AutomatorSession, cfg: dict) -> None:
    """Tap foto profil kiri atas — prioritas selector cepat, bukan dump page source."""
    block = cfg.get("account_menu") or {}

    # 1) Accessibility id / name / label — biasanya <1s
    for strat in block.get("strategies", []):
        using = strat["using"]
        value = strat["value"]
        # xpath di home feed X sangat lambat — skip di jalur cepat
        if using == "xpath":
            continue
        try:
            await session.tap(value, using=using)
            logger.info("account menu cepat — tapped [%s] %s", using, value)
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("account menu try [%s] %s: %s", using, value, exc)

    # 2) Koordinat fallback (tanpa source_xml)
    fb = block.get("fallback_xy")
    if fb:
        size = await session.window_size()
        x = int(size["width"] * float(fb["x_ratio"]))
        y = int(size["height"] * float(fb["y_ratio"]))
        logger.info("account menu fallback_xy (%d, %d)", x, y)
        await session.tap_xy(x, y)
        return

    raise RuntimeError("Account Menu tidak ketemu (NavigationBarDashButton / fallback_xy)")


async def _tap_drawer_profile(session: AutomatorSession, cfg: dict) -> None:
    """Setelah drawer terbuka: tap Profile — selector dulu, source_xml hanya fallback singkat."""
    block = cfg.get("drawer_profile") or {}
    labels = tuple(cfg.get("profile_menu_labels", list(PROFILE_MENU_LABELS)))

    for strat in block.get("strategies", []):
        using = strat["using"]
        value = strat["value"]
        if using == "xpath":
            continue
        try:
            await session.tap(value, using=using)
            logger.info("drawer Profile cepat — tapped [%s] %s", using, value)
            return
        except Exception as exc:  # noqa: BLE001
            logger.debug("drawer Profile try [%s] %s: %s", using, value, exc)

    # Satu dump singkat (drawer jauh lebih kecil dari home feed)
    try:
        xml = await session.source_xml()
        point = _find_menu_item(xml, labels)
        if point:
            x, y = point
            await session.tap_xy(x, y)
            logger.info("drawer Profile via page source — tap_xy (%d, %d)", x, y)
            return
    except Exception as exc:  # noqa: BLE001
        logger.debug("drawer profile page source: %s", exc)

    fb = block.get("fallback_xy")
    if fb:
        size = await session.window_size()
        x = int(size["width"] * float(fb["x_ratio"]))
        y = int(size["height"] * float(fb["y_ratio"]))
        logger.warning("drawer Profile fallback_xy (%d, %d)", x, y)
        await session.tap_xy(x, y)
        return

    raise RuntimeError("Drawer Profile tidak ketemu")


async def _open_own_profile(session: AutomatorSession, cfg: dict, out_dir: Path | None = None) -> None:
    """X iOS: Home → avatar kiri atas → Profile di drawer."""
    debug = os.environ.get("IOS_X_DEBUG_SOURCE", "0").strip() == "1"
    logger.info("Buka profile: Account Menu (kiri atas) → Profile")
    await _tap_account_menu(session, cfg)
    await session.sleep(float(cfg.get("drawer_settle_sec", 0.35)))

    if debug and out_dir is not None:
        try:
            (out_dir / "page_source_drawer.xml").write_text(await session.source_xml(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    await _tap_drawer_profile(session, cfg)

# "1,234 Following" | "12.3K Followers" | "1,4 ribu Following"
STAT_RE = re.compile(
    r"^([\d.,]+)\s*"
    r"(?:([KMBkmb])|thousand|ribu|million|juta)?\s*"
    r"(following|mengikuti|followers?|pengikut)\b",
    re.IGNORECASE,
)
# Button accessibility: "Following. 123" / "123 Following"
STAT_ALT_RE = re.compile(
    r"(?:^|\b)(?:(following|mengikuti|followers?|pengikut)[.\s]+([\d.,]+[KMBkmb]?)|"
    r"([\d.,]+[KMBkmb]?)\s*(following|mengikuti|followers?|pengikut))\b",
    re.IGNORECASE,
)
HANDLE_RE = re.compile(r"@([A-Za-z0-9_]{1,15})\b")
NUMBER_ONLY_RE = re.compile(r"^[\d.,]+[KMBkmb]?$", re.IGNORECASE)
# "5 Following 0 Followers" (bisa ada em-space / bidi marks)
STAT_PAIR_RE = re.compile(
    r"([\d.,]+)\s*([KMBkmb])?\s*(Following|Followers|Mengikuti|Pengikut)\b",
    re.IGNORECASE,
)
# Unicode bidi / isolate marks yang sering nempel di label X iOS
_BIDI_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def _clean_ax_text(raw: str) -> str:
    """Buang bidi isolates + whitespace aneh dari accessibility label X."""
    text = _BIDI_RE.sub("", raw or "")
    text = text.replace("\u00a0", " ").replace("\u2003", " ").replace("\u2002", " ")
    return " ".join(text.split()).strip()


def _load_selectors() -> dict:
    with SELECTORS.open(encoding="utf-8") as fh:
        return json.load(fh)["x"]


def _max_screenshots() -> int:
    raw = os.environ.get("IOS_X_MAX_SCREENSHOTS", "5").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 5
    return max(1, min(n, 100))


def _scroll_pause_sec() -> float:
    # Default cepat: cukup untuk UI settle, bukan 1s.
    raw = os.environ.get("IOS_X_SCROLL_PAUSE_SEC", "0.35").strip()
    try:
        return max(0.05, float(raw))
    except ValueError:
        return 0.35


def _scroll_duration_sec() -> float:
    raw = os.environ.get("IOS_X_SCROLL_DURATION_SEC", "0.18").strip()
    try:
        return max(0.08, float(raw))
    except ValueError:
        return 0.18


def _scroll_distance() -> float:
    """Fraksi tinggi layar per swipe antar post screenshot.

    0.55 (lama) → overlap besar / post dobel.
    ~0.78–0.85 → hampir 1 halaman konten, sisa overlap kecil di sticky header.
    """
    raw = os.environ.get("IOS_X_SCROLL_DISTANCE", "0.78").strip()
    try:
        return max(0.35, min(float(raw), 0.95))
    except ValueError:
        return 0.78


def _first_scroll_distance() -> float:
    """Scroll pertama setelah profile.png — lompat header + banner verifikasi."""
    raw = os.environ.get("IOS_X_FIRST_SCROLL_DISTANCE", "0.90").strip()
    try:
        return max(0.4, min(float(raw), 0.98))
    except ValueError:
        return 0.90


def _scroll_direction() -> str:
    """Default: down = jari ke atas (lihat post lebih lama)."""
    raw = os.environ.get("IOS_X_SCROLL_DIRECTION", "down").strip().lower()
    if raw in {"atas", "finger-up", "finger_up", "keatas", "ke-atas"}:
        return "down"
    if raw in {"bawah", "finger-down", "finger_down", "kebawah", "ke-bawah"}:
        return "up"
    if raw in {"up", "down"}:
        return raw
    return "down"


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
        val = _clean_ax_text(node.attrib.get(key) or "")
        if val:
            return val
    return ""


def _node_by_name(root: ET.Element, name: str) -> ET.Element | None:
    for node in root.iter():
        if (node.attrib.get("name") or "") == name:
            return node
    return None


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


def _looks_like_display_name(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 1 or len(t) > 50:
        return False
    low = t.lower()
    if low in SKIP_NAMES:
        return False
    if t.startswith("@"):
        return False
    if low.startswith(("tap ", "edit ", "share ", "follow ", "ikuti ")):
        return False
    if any(
        k in low
        for k in (
            "following",
            "follower",
            "mengikuti",
            "pengikut",
            "joined",
            "bergabung",
            "tweet",
            "post",
            "reply",
            "repost",
            "like",
            "view",
            "hour",
            "minute",
            "jam",
            "menit",
        )
    ):
        return False
    if t.startswith("http"):
        return False
    if NUMBER_ONLY_RE.match(t):
        return False
    return True


def _looks_like_bio(text: str) -> bool:
    t = text.strip()
    if not t or len(t) < 3 or len(t) > 400:
        return False
    low = t.lower()
    if low in SKIP_NAMES:
        return False
    if HANDLE_RE.match(t):
        return False
    if STAT_RE.match(t) or STAT_ALT_RE.search(t):
        return False
    if NUMBER_ONLY_RE.match(t):
        return False
    if low.startswith(("http://", "https://")):
        return True
    # Bio biasanya multi-kata atau punya emoji/punctuation
    if " " in t or any(ch in t for ch in (".", ",", "!", "?", "|", "/", "#")):
        return True
    return len(t) >= 8 and not t[0].isdigit()


def _assign_stat(kind: str, value: int | str, info: dict[str, Any]) -> None:
    kind = kind.lower()
    if kind.startswith("follower") or kind == "pengikut":
        if info.get("followers") in ("", None):
            info["followers"] = value
    elif kind.startswith("following") or kind == "mengikuti":
        if info.get("following") in ("", None):
            info["following"] = value


def _parse_stat_field(field: str, info: dict[str, Any]) -> None:
    field = _clean_ax_text(field)
    if not field:
        return
    # Prefer findall: "5 Following 0 Followers" punya dua pasangan
    pairs = list(STAT_PAIR_RE.finditer(field))
    if pairs:
        for m in pairs:
            num_raw = m.group(1)
            suffix = m.group(2) or ""
            kind = m.group(3)
            parsed = _parse_count(f"{num_raw}{suffix}" if suffix else num_raw)
            _assign_stat(kind, parsed, info)
        return

    m = STAT_RE.match(field)
    if m:
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
        return

    m2 = STAT_ALT_RE.search(field)
    if not m2:
        return
    if m2.group(1):
        kind, num_raw = m2.group(1), m2.group(2)
    else:
        num_raw, kind = m2.group(3), m2.group(4)
    _assign_stat(kind, _parse_count(num_raw), info)


def _extract_handle(text: str) -> str:
    m = HANDLE_RE.search(_clean_ax_text(text))
    return m.group(1) if m else ""


def _read_profile_info(xml: str) -> dict[str, Any]:
    root = ET.fromstring(xml)
    info: dict[str, Any] = {
        "username": "",
        "display_name": "",
        "bio": "",
        "followers": "",
        "following": "",
    }

    # Prefer accessibility id resmi X iOS
    full = _node_by_name(root, "ProfileHeaderFullName")
    if full:
        info["display_name"] = _node_text(full)

    sub = _node_by_name(root, "ProfileHeaderSubtitle")
    if sub:
        info["username"] = _extract_handle(_node_text(sub)) or _extract_handle(
            sub.attrib.get("value") or ""
        ) or _extract_handle(sub.attrib.get("label") or "")

    bio_node = _node_by_name(root, "ProfileHeaderBio")
    if bio_node:
        # Ambil value/label di node StaticText (bukan child Link)
        for key in ("value", "label"):
            val = _clean_ax_text(bio_node.attrib.get(key) or "")
            if val and not val.lower().startswith("link:"):
                info["bio"] = val
                break
        if not info["bio"]:
            info["bio"] = _node_text(bio_node)

    # Fallback handle dari seluruh tree
    if not info["username"]:
        for node in root.iter():
            for key in ("value", "label", "name"):
                handle = _extract_handle(node.attrib.get(key) or "")
                if handle:
                    y = int(node.attrib.get("y", "0") or 0)
                    if y <= 500:
                        info["username"] = handle
                        break
            if info["username"]:
                break

    # Following / Followers
    for node in root.iter():
        for key in ("name", "label", "value"):
            field = node.attrib.get(key) or ""
            if "following" in field.lower() or "follower" in field.lower() or "mengikuti" in field.lower():
                _parse_stat_field(field, info)

    # Fallback display name
    if not info["display_name"]:
        name_candidates: list[tuple[int, str]] = []
        for node in root.iter():
            if not (node.tag.endswith("StaticText") or node.tag.endswith("Button")):
                continue
            text = _node_text(node)
            if not _looks_like_display_name(text):
                continue
            y = int(node.attrib.get("y", "0") or 0)
            h = int(node.attrib.get("height", "0") or 0)
            if 40 <= y <= 280 and h >= 16:
                name_candidates.append((y, text))
        if name_candidates:
            name_candidates.sort(key=lambda c: c[0])
            info["display_name"] = name_candidates[0][1]

    # Fallback bio
    if not info["bio"]:
        bio_candidates: list[tuple[int, str]] = []
        for node in root.iter():
            if not node.tag.endswith("StaticText"):
                continue
            text = _node_text(node)
            if not _looks_like_bio(text):
                continue
            if info["display_name"] and text == info["display_name"]:
                continue
            if info["username"] and text.lstrip("@") == info["username"]:
                continue
            y = int(node.attrib.get("y", "0") or 0)
            if 120 <= y <= 520:
                bio_candidates.append((y, text))
        if bio_candidates:
            bio_candidates.sort(key=lambda c: c[0])
            info["bio"] = bio_candidates[0][1]

    return info


async def _on_profile_screen(session: AutomatorSession) -> bool:
    xml = await session.source_xml()
    low = xml.lower()
    has_handle = bool(re.search(r"@[A-Za-z0-9_]{1,15}", xml))
    has_stats = ("following" in low or "mengikuti" in low) and (
        "follower" in low or "pengikut" in low
    )
    has_edit = "edit profile" in low or "edit profil" in low
    return (has_handle and has_stats) or (has_edit and has_stats)


async def _capture_post_screenshots(
    session: AutomatorSession,
    out_dir: Path,
) -> list[str]:
    """Screenshot timeline posts.

    Alur cepat:
      1) Scroll pertama besar (lewati header/banner) — supaya post_01 ≠ profile.png
      2) SS → scroll (jarak ~0.78 layar) → jeda singkat → SS …
    """
    max_shots = _max_screenshots()
    pause = _scroll_pause_sec()
    duration = _scroll_duration_sec()
    distance = _scroll_distance()
    first_distance = _first_scroll_distance()
    scroll_dir = _scroll_direction()
    saved: list[str] = []
    prev_hash: str | None = None

    x_phase(
        "posts",
        f"max={max_shots} dir={scroll_dir} dist={distance} first={first_distance} "
        f"pause={pause}s dur={duration}s",
    )

    # Lewati header profile + "You're not verified" sebelum post_01
    logger.info(
        "Scroll awal ke timeline (distance=%.2f) supaya post tidak dobel dengan profile.png",
        first_distance,
    )
    await session.scroll(scroll_dir, distance=first_distance, duration=duration)
    await session.sleep(pause)

    for i in range(1, max_shots + 1):
        name = f"post_{i:02d}.png"
        path = out_dir / name
        await session.screenshot(path)
        saved.append(name)
        x_phase("screenshot", f"{name} ({i}/{max_shots})")

        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if prev_hash is not None and digest == prev_hash:
            logger.info("Screenshot sama dengan sebelumnya — stop posts")
            break
        prev_hash = digest

        if i >= max_shots:
            break

        logger.info(
            "X posts scroll %s dist=%.2f (%d/%d)…",
            scroll_dir,
            distance,
            i,
            max_shots,
        )
        await session.scroll(scroll_dir, distance=distance, duration=duration)
        await session.sleep(pause)

    meta = {
        "count": len(saved),
        "max_requested": max_shots,
        "files": saved,
        "scroll_direction": scroll_dir,
        "scroll_distance": distance,
        "first_scroll_distance": first_distance,
        "scroll_pause_sec": pause,
        "scroll_duration_sec": duration,
        "notes": (
            "distance ~0.78 ≈ 1 halaman konten (kurangi dobel). "
            "first_scroll melewatkan header sebelum post_01."
        ),
    }
    (out_dir / "post_screenshots.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return saved


async def run_x_profile(args) -> int:
    cfg = _load_selectors()
    bundle = resolve_bundle_id("x")
    out_dir = Path(args.output) if args.output else default_output_dir("x_profile")
    out_dir.mkdir(parents=True, exist_ok=True)
    wda_url = args.http or "http://127.0.0.1:8100"

    session = AutomatorSession.connect_http(wda_url, timeout=max(args.timeout, 30.0))
    try:
        x_phase("launch", f"bundle={bundle}")
        await session.start(bundle)
        wait_sec = float(cfg.get("launch_wait_sec", 2.0))
        logger.info("Tunggu X shell %.1fs", wait_sec)
        await session.sleep(wait_sec)

        x_phase("home", "screenshot homepage")
        await session.screenshot(out_dir / "home.png")
        if os.environ.get("IOS_X_DEBUG_SOURCE", "0").strip() == "1":
            try:
                (out_dir / "page_source_home.xml").write_text(await session.source_xml(), encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass

        x_phase("profile", "Account Menu (kiri atas) → Profile")
        await _open_own_profile(session, cfg, out_dir)
        await session.sleep(float(cfg.get("profile_settle_sec", 0.5)))

        # Satu dump source saja (untuk profile.json) — jangan dump berulang
        xml = await session.source_xml()
        profile = _read_profile_info(xml)
        if not profile.get("username") and not (
            "ProfileHeaderFullName" in xml or "ProfileHeaderBio" in xml
        ):
            logger.warning("Belum di layar profile — ulangi Account Menu → Profile")
            await _open_own_profile(session, cfg, out_dir)
            await session.sleep(0.5)
            xml = await session.source_xml()
            profile = _read_profile_info(xml)

        (out_dir / "page_source_profile.xml").write_text(xml, encoding="utf-8")
        (out_dir / "profile.json").write_text(
            json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if profile.get("username"):
            (out_dir / "profile_name.txt").write_text(profile["username"] + "\n", encoding="utf-8")

        x_phase(
            "profile",
            f"@{profile.get('username') or '?'} name={profile.get('display_name')!r} "
            f"followers={profile.get('followers')} following={profile.get('following')}",
        )
        logger.info(
            "Profile: @%s name=%r bio=%r followers=%s following=%s",
            profile.get("username") or "?",
            profile.get("display_name"),
            (profile.get("bio") or "")[:80],
            profile.get("followers"),
            profile.get("following"),
        )

        await session.screenshot(out_dir / "profile.png")
        x_phase("screenshot", "profile.png")

        # Warm window size cache sebelum loop scroll (hindari get_window_size lambat tiap swipe)
        await session.window_size()
        posts = await _capture_post_screenshots(session, out_dir)
        logger.info("Posts screenshots: %d → %s", len(posts), out_dir.resolve())
        x_done(out_dir, ok=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("X profile flow failed: %s", exc)
        x_phase("error", str(exc))
        try:
            await session.screenshot(out_dir / "error.png")
            (out_dir / "page_source_error.xml").write_text(await session.source_xml(), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        x_done(out_dir, ok=False)
        return 1
    finally:
        await session.close()
