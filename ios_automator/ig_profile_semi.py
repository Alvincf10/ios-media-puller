#!/usr/bin/env python3
"""
IG flow (tanpa WDA): launch Instagram → (manual tap Profile) → screenshot.

Yang sudah bisa tanpa Xcode/WDA (iOS 17+ + tunneld + Developer Mode):
  1) buka Instagram via DVT
  2) ambil screenshot via DVT

Yang BELUM bisa tanpa WDA:
  - klik otomatis tab Profile

Usage:
  # terminal 1: sudo python3 -m pymobiledevice3 remote tunneld
  # terminal 2:
  cd riset_pulling_data_ios && source .venv/bin/activate
  python ios_automator/ig_profile_semi.py
  python ios_automator/ig_profile_semi.py --auto-wait 8   # tanpa Enter, tunggu N detik
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ig_profile_semi")

BUNDLE_IG = "com.burbn.instagram"
ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> None:
    logger.info("$ %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Launch IG → manual Profile tap → screenshot (DVT)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output folder (default: output/ig_semi_YYYYMMDD_HHMMSS)",
    )
    p.add_argument(
        "--auto-wait",
        type=float,
        default=0,
        help="Jika >0: tidak minta Enter; tunggu N detik lalu screenshot "
        "(kamu tap Profile sendiri dalam waktu itu)",
    )
    p.add_argument(
        "--launch-wait",
        type=float,
        default=3.0,
        help="Tunggu setelah launch agar IG selesai load (detik)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.output or (ROOT / "output" / f"ig_semi_{time.strftime('%Y%m%d_%H%M%S')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("1/3 Launch Instagram…")
        _run(["pymobiledevice3", "developer", "dvt", "launch", BUNDLE_IG])
        time.sleep(args.launch_wait)

        after_launch = out_dir / "01_after_launch.png"
        logger.info("Screenshot setelah launch → %s", after_launch)
        _run(["pymobiledevice3", "developer", "dvt", "screenshot", str(after_launch)])

        logger.info("2/3 Di iPhone: ketuk tab Profile (pojok kanan bawah).")
        if args.auto_wait > 0:
            logger.info("Menunggu %.1fs…", args.auto_wait)
            time.sleep(args.auto_wait)
        else:
            input("Setelah Profile terbuka, tekan Enter di sini… ")

        profile_ss = out_dir / "02_profile.png"
        logger.info("3/3 Screenshot Profile → %s", profile_ss)
        _run(["pymobiledevice3", "developer", "dvt", "screenshot", str(profile_ss)])

        logger.info("Selesai: %s", out_dir.resolve())
        logger.info(
            "Catatan: klik otomatis butuh WebDriverAgent (Xcode). "
            "Lihat ios_automator/SETUP_WDA.md"
        )
        return 0
    except Exception as exc:
        logger.error("%s", exc)
        logger.error(
            "Cek: tunneld jalan, Developer Mode ON, HP unlocked, "
            "cwd repo riset_pulling_data_ios."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
