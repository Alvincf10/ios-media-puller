from __future__ import annotations

import logging
from pathlib import Path

from lib.apps import resolve_bundle_id
from lib.session import AutomatorSession, default_output_dir

logger = logging.getLogger("ios_automator.smoke")


async def run_smoke(args) -> int:
    bundle = resolve_bundle_id(args.app)
    out_dir = Path(args.output) if args.output else default_output_dir("smoke")
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.http:
        session = AutomatorSession.connect_http(args.http, timeout=args.timeout)
    else:
        session = await AutomatorSession.connect_usb(port=args.port, timeout=args.timeout)

    try:
        await session.start(bundle)
        await session.sleep(args.wait)
        path = await session.screenshot(out_dir / f"{args.app}_home.png")
        size = await session.window_size()
        logger.info("window size: %s", size)
        logger.info("smoke OK → %s", path.resolve())
        return 0
    except Exception as exc:
        logger.error("smoke failed:\n%s", exc)
        return 1
    finally:
        await session.close()
