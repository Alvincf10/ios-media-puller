#!/usr/bin/env python3
"""
Instagram archive flow via Appium XCUITest + prebuilt WebDriverAgent.

Flow:
  Launch IG → wait Home → tap Profile → read/save name → screenshot
  → tap Menu → tap Archive → done

Daily host (Linux OK):
  go-ios (start/forward WDA) + Appium server (usePrebuiltWDA) + this script

Prereq:
  - WDA already installed on iPhone (one-time Mac/Xcode)
  - Appium server running (default http://127.0.0.1:4723)
  - Device unlocked + trusted; WDA reachable (go-ios tunnel/forward)

Authorization: Authorized security research / own-device lab use only.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from appium import webdriver
from appium.options.ios import XCUITestOptions

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from helpers import load_json, read_text, tap_first, wait_any  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ig_archive_flow")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="IG → Profile → Archive (Appium + prebuilt WDA)")
    p.add_argument("--server", default="http://127.0.0.1:4723", help="Appium server URL")
    p.add_argument("--caps", type=Path, default=ROOT / "caps.json")
    p.add_argument("--selectors", type=Path, default=ROOT / "selectors.json")
    p.add_argument("--udid", default=None, help="Override device UDID (else caps / auto)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output dir (default: ../../output/ig_appium_TIMESTAMP)",
    )
    p.add_argument("--dry-run-caps", action="store_true", help="Print caps and exit")
    p.add_argument(
        "--stop-after",
        choices=("profile", "archive", "all"),
        default="all",
        help="Stop early for calibration",
    )
    return p.parse_args()


def build_options(caps: dict, udid: str | None) -> XCUITestOptions:
    data = {k: v for k, v in caps.items() if not str(k).startswith("comment")}
    if udid:
        data["appium:udid"] = udid
    opts = XCUITestOptions().load_capabilities(data)
    return opts


def save_profile_name(out_dir: Path, name: str) -> Path:
    path = out_dir / "profile_name.txt"
    path.write_text(name + "\n", encoding="utf-8")
    meta = {"profile_name": name, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (out_dir / "profile_name.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return path


def run_flow(args: argparse.Namespace) -> int:
    caps = load_json(args.caps)
    selectors_root = load_json(args.selectors)
    ig = selectors_root["instagram"]

    if args.dry_run_caps:
        print(json.dumps({k: v for k, v in caps.items() if not str(k).startswith("comment")}, indent=2))
        return 0

    out_dir = args.output or (REPO / "output" / f"ig_appium_{time.strftime('%Y%m%d_%H%M%S')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("output → %s", out_dir.resolve())

    options = build_options(caps, args.udid)
    logger.info("Connecting Appium %s (usePrebuiltWDA=%s)", args.server, caps.get("appium:usePrebuiltWDA"))
    driver = webdriver.Remote(args.server, options=options)
    driver.implicitly_wait(0)

    try:
        logger.info("Launch Instagram / wait Home")
        wait_any(driver, ig["home_marker"]["strategies"], timeout=25)
        driver.get_screenshot_as_file(str(out_dir / "01_home.png"))

        logger.info("Tap Profile tab")
        tap_first(driver, ig["profile_tab"]["strategies"], timeout=15)
        time.sleep(1.2)

        logger.info("Read profile name")
        try:
            name = read_text(
                driver,
                ig["profile_name"]["strategies"],
                attribute=ig["profile_name"].get("attribute", "name"),
                timeout=12,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal baca profile name otomatis: %s", exc)
            name = "UNKNOWN"
            (out_dir / "page_source_profile.xml").write_text(driver.page_source, encoding="utf-8")
            logger.info("Dump page_source → page_source_profile.xml (kalibrasi selectors.json)")

        path = save_profile_name(out_dir, name)
        logger.info("Saved profile name %r → %s", name, path)

        logger.info("Screenshot profile")
        driver.get_screenshot_as_file(str(out_dir / "02_profile.png"))

        if args.stop_after == "profile":
            logger.info("stop-after=profile")
            return 0

        logger.info("Tap Menu / Settings")
        tap_first(driver, ig["menu_button"]["strategies"], timeout=15)
        time.sleep(0.8)
        driver.get_screenshot_as_file(str(out_dir / "03_menu.png"))

        logger.info("Tap Archive")
        tap_first(driver, ig["archive_item"]["strategies"], timeout=15)
        time.sleep(1.0)
        driver.get_screenshot_as_file(str(out_dir / "04_archive.png"))

        logger.info("Done → %s", out_dir.resolve())
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("Flow failed: %s", exc)
        try:
            driver.get_screenshot_as_file(str(out_dir / "error.png"))
            (out_dir / "page_source_error.xml").write_text(driver.page_source, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        logger.error(
            "Kalibrasi selector: buka Appium Inspector / dump XML, "
            "edit ios_automator/appium/selectors.json"
        )
        return 1
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    return run_flow(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
