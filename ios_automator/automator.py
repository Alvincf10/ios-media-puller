#!/usr/bin/env python3
"""
iOS UI Automator CLI (WebDriverAgent via pymobiledevice3).

Padanan praktis Android UI Automator untuk riset device sendiri:
  launch / tap / swipe / scroll / screenshot / list UI source.

Prasyarat:
  - WebDriverAgent sudah terpasang & running di iPhone (build sekali di Mac)
  - Device unlocked + Trust + Developer Mode
  - Bekerja di macOS / Linux / Windows (client); build WDA tetap butuh Mac

Authorization: Authorized security research / own-device lab use only.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.apps import list_apps, resolve_bundle_id  # noqa: E402
from lib.envfile import load_env_file  # noqa: E402
from lib.session import AutomatorSession, default_output_dir  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ios_automator")

# Subcommands that need WDA on device
_WDA_CMDS = frozenset(
    {"status", "launch", "tap", "swipe", "scroll", "screenshot", "list-source", "smoke", "social"}
)


def _add_conn_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--http", default=None, help="WDA URL (default: USB via pymobiledevice3)")
    p.add_argument("--port", type=int, default=8100, help="WDA port on device (USB mode)")
    p.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds")
    p.add_argument("-v", "--verbose", action="store_true")


def _should_install_wda(args: argparse.Namespace) -> bool:
    if args.cmd not in _WDA_CMDS:
        return False
    if getattr(args, "skip_wda_install", False):
        return False
    if getattr(args, "install_wda", False):
        return True
    return os.environ.get("IOS_AUTOMATOR_INSTALL_WDA", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _run_wda_install() -> None:
    script = ROOT / "scripts" / "install_wda_altserver.sh"
    if not script.is_file():
        raise SystemExit(f"Script tidak ada: {script}")
    if not os.environ.get("APPLE_ID") or not os.environ.get("APPLE_ID_PASSWORD"):
        raise SystemExit(
            "Install WDA butuh APPLE_ID + APPLE_ID_PASSWORD.\n"
            "Isi file .env di root repo (lihat .env.example) atau export di shell."
        )
    logger.info("Menjalankan AltServer install WDA dulu…")
    subprocess.run(["bash", str(script)], check=True, cwd=str(REPO))


async def _connect(args: argparse.Namespace) -> AutomatorSession:
    try:
        if args.http:
            return AutomatorSession.connect_http(args.http, timeout=args.timeout)
        return await AutomatorSession.connect_usb(port=args.port, timeout=args.timeout)
    except ImportError:
        logger.error("pymobiledevice3 belum terpasang. pip install -r requirements.txt")
        raise SystemExit(2)
    except Exception as exc:
        logger.error("Gagal konek WDA/device: %s", exc)
        logger.error(
            "Cek: USB+Trust, Developer Mode, WDA running, "
            "atau iOS 17+ butuh tunneld (`pymobiledevice3 remote tunneld`)."
        )
        raise SystemExit(1) from exc


async def cmd_apps(_: argparse.Namespace) -> int:
    for key, bundle, name in list_apps():
        print(f"{key:12}  {bundle:32}  {name}")
    return 0


async def cmd_status(args: argparse.Namespace) -> int:
    from lib.session import WdaNotReadyError

    session = await _connect(args)
    try:
        data = await session.status()
        print(data)
        return 0
    except WdaNotReadyError as exc:
        logger.error("%s", exc)
        return 1
    finally:
        await session.close()


async def cmd_launch(args: argparse.Namespace) -> int:
    from lib.session import WdaNotReadyError

    bundle = resolve_bundle_id(args.app)
    session = await _connect(args)
    try:
        sid = await session.start(bundle)
        print(sid)
        if args.screenshot:
            out = Path(args.screenshot)
            await session.sleep(args.wait)
            await session.screenshot(out)
        return 0
    except WdaNotReadyError as exc:
        logger.error("%s", exc)
        return 1
    finally:
        await session.close()


async def cmd_tap(args: argparse.Namespace) -> int:
    bundle = resolve_bundle_id(args.app) if args.app else None
    session = await _connect(args)
    try:
        await session.ensure_session(bundle)
        if args.x is not None and args.y is not None:
            await session.tap_xy(args.x, args.y)
        else:
            if not args.selector:
                logger.error("Butuh --selector atau --x/--y")
                return 2
            await session.tap(args.selector, using=args.using)
        return 0
    finally:
        await session.close()


async def cmd_swipe(args: argparse.Namespace) -> int:
    bundle = resolve_bundle_id(args.app) if args.app else None
    session = await _connect(args)
    try:
        await session.ensure_session(bundle)
        await session.swipe(
            args.start_x,
            args.start_y,
            args.end_x,
            args.end_y,
            duration=args.duration,
        )
        return 0
    finally:
        await session.close()


async def cmd_scroll(args: argparse.Namespace) -> int:
    bundle = resolve_bundle_id(args.app) if args.app else None
    session = await _connect(args)
    try:
        await session.ensure_session(bundle)
        for _ in range(args.times):
            await session.scroll(args.direction, distance=args.distance, duration=args.duration)
            await session.sleep(args.pause)
        return 0
    finally:
        await session.close()


async def cmd_screenshot(args: argparse.Namespace) -> int:
    bundle = resolve_bundle_id(args.app) if args.app else None
    out = Path(args.out) if args.out else default_output_dir() / "screen.png"
    session = await _connect(args)
    try:
        await session.ensure_session(bundle)
        await session.screenshot(out)
        print(out.resolve())
        return 0
    finally:
        await session.close()


async def cmd_list_source(args: argparse.Namespace) -> int:
    bundle = resolve_bundle_id(args.app) if args.app else None
    session = await _connect(args)
    try:
        await session.ensure_session(bundle)
        if args.xml:
            xml = await session.source_xml()
            path = Path(args.xml)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(xml, encoding="utf-8")
            logger.info("source XML → %s", path.resolve())
        rows = await session.list_elements(limit=args.limit)
        for i, row in enumerate(rows, 1):
            print(
                f"{i:3}  type={row['type']!s:28}  "
                f"name={row['name']!r:40}  label={row['label']!r}"
            )
        return 0
    finally:
        await session.close()


async def cmd_smoke(args: argparse.Namespace) -> int:
    """Launch app (default: Settings) → wait → screenshot. Tidak butuh selector sosial."""
    from flows.smoke import run_smoke

    return await run_smoke(args)


async def cmd_social(args: argparse.Namespace) -> int:
    """Stub flow: launch IG/X/FB → optional swipes → screenshot. Selector diisi belakangan."""
    from flows.social_archive import run_social_stub

    return await run_social_stub(args)


async def cmd_ig_archive(args: argparse.Namespace) -> int:
    """IG: Profile → read name → screenshot → Archive (WDA HTTP)."""
    from flows.ig_archive import run_ig_archive

    return await run_ig_archive(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ios_automator",
        description="iOS UI Automator (WDA + pymobiledevice3)",
    )
    p.add_argument(
        "--install-wda",
        action="store_true",
        dest="install_wda_global",
        help="Sign+install WDA via AltServer sebelum subcommand",
    )
    p.add_argument(
        "--skip-wda-install",
        action="store_true",
        dest="skip_wda_install_global",
        help="Lewati auto-install WDA",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("apps", help="List short names → bundle ids")
    s.set_defaults(func=cmd_apps)

    s = sub.add_parser("status", help="WDA /status")
    _add_conn_args(s)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("launch", help="Start WDA session + launch app")
    _add_conn_args(s)
    s.add_argument("app", help="Short name (instagram/x/facebook/settings) or bundle id")
    s.add_argument("--wait", type=float, default=2.0, help="Wait before optional screenshot")
    s.add_argument("--screenshot", type=Path, default=None, help="Save PNG after launch")
    s.set_defaults(func=cmd_launch)

    s = sub.add_parser("tap", help="Tap by accessibility id/name/xpath or coordinates")
    _add_conn_args(s)
    s.add_argument("--app", default=None, help="App short name / bundle (new session)")
    s.add_argument("--selector", default=None, help="Element selector")
    s.add_argument("--using", default="accessibility id", help="Lookup strategy")
    s.add_argument("--x", type=int, default=None)
    s.add_argument("--y", type=int, default=None)
    s.set_defaults(func=cmd_tap)

    s = sub.add_parser("swipe", help="Swipe start→end coordinates")
    _add_conn_args(s)
    s.add_argument("--app", default=None)
    s.add_argument("start_x", type=int)
    s.add_argument("start_y", type=int)
    s.add_argument("end_x", type=int)
    s.add_argument("end_y", type=int)
    s.add_argument("--duration", type=float, default=0.25)
    s.set_defaults(func=cmd_swipe)

    s = sub.add_parser("scroll", help="Scroll up/down/left/right relative to screen")
    _add_conn_args(s)
    s.add_argument("--app", default=None)
    s.add_argument("direction", choices=("up", "down", "left", "right"))
    s.add_argument("--times", type=int, default=1)
    s.add_argument("--distance", type=float, default=0.45)
    s.add_argument("--duration", type=float, default=0.3)
    s.add_argument("--pause", type=float, default=0.4)
    s.set_defaults(func=cmd_scroll)

    s = sub.add_parser("screenshot", help="Capture PNG via WDA")
    _add_conn_args(s)
    s.add_argument("--app", default=None)
    s.add_argument("-o", "--out", type=Path, default=None)
    s.set_defaults(func=cmd_screenshot)

    s = sub.add_parser("list-source", help="Dump tappable-ish UI nodes (calibrate selectors)")
    _add_conn_args(s)
    s.add_argument("--app", default=None)
    s.add_argument("--limit", type=int, default=80)
    s.add_argument("--xml", type=Path, default=None, help="Also write full source XML")
    s.set_defaults(func=cmd_list_source)

    s = sub.add_parser("smoke", help="Smoke: launch Settings + screenshot")
    _add_conn_args(s)
    s.add_argument("--app", default="settings")
    s.add_argument("--wait", type=float, default=2.0)
    s.add_argument("-o", "--output", type=Path, default=None)
    s.set_defaults(func=cmd_smoke)

    s = sub.add_parser("social", help="Stub: launch IG/X/FB + scroll + screenshot")
    _add_conn_args(s)
    s.add_argument("app", choices=("instagram", "x", "facebook"))
    s.add_argument("--wait", type=float, default=3.0)
    s.add_argument("--scrolls", type=int, default=0, help="Extra down-scrolls before SS")
    s.add_argument("-o", "--output", type=Path, default=None)
    s.set_defaults(func=cmd_social)

    s = sub.add_parser("ig-archive", help="IG: Profile → name → screenshot → Archive")
    _add_conn_args(s)
    s.add_argument("--stop-after", choices=("profile", "all"), default="all")
    s.add_argument("-o", "--output", type=Path, default=None)
    s.set_defaults(func=cmd_ig_archive)

    return p


async def _async_main() -> int:
    load_env_file(REPO / ".env")
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "verbose", False):
        logging.getLogger().setLevel(logging.DEBUG)
    # normalize global flag names
    args.install_wda = bool(getattr(args, "install_wda_global", False))
    args.skip_wda_install = bool(getattr(args, "skip_wda_install_global", False))
    if _should_install_wda(args):
        _run_wda_install()
    return await args.func(args)


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
