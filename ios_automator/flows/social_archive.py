from __future__ import annotations

import logging
from pathlib import Path

from lib.apps import resolve_bundle_id
from lib.session import AutomatorSession, default_output_dir

logger = logging.getLogger("ios_automator.social")

# Placeholder steps — isi setelah kalibrasi `list-source` di device login.
# Format: ("tap", using, selector) | ("scroll", direction) | ("wait", seconds) | ("screenshot", name)
ARCHIVE_STEPS: dict[str, list[tuple]] = {
    "instagram": [
        # contoh setelah kalibrasi:
        # ("tap", "accessibility id", "profile-tab"),
        # ("tap", "accessibility id", "menu"),
        # ("tap", "name", "Archive"),
        ("wait", 1.0),
        ("screenshot", "01_after_launch.png"),
    ],
    "x": [
        ("wait", 1.0),
        ("screenshot", "01_after_launch.png"),
    ],
    "facebook": [
        ("wait", 1.0),
        ("screenshot", "01_after_launch.png"),
    ],
}


async def run_social_stub(args) -> int:
    app = args.app
    bundle = resolve_bundle_id(app)
    out_dir = Path(args.output) if args.output else default_output_dir(f"social_{app}")
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.http:
        session = AutomatorSession.connect_http(args.http, timeout=args.timeout)
    else:
        session = await AutomatorSession.connect_usb(port=args.port, timeout=args.timeout)

    try:
        await session.start(bundle)
        await session.sleep(args.wait)

        for step in ARCHIVE_STEPS.get(app, []):
            await _run_step(session, out_dir, step)

        for i in range(max(0, args.scrolls)):
            await session.scroll("down")
            await session.sleep(0.5)
            await session.screenshot(out_dir / f"scroll_{i + 1:02d}.png")

        final = await session.screenshot(out_dir / "final.png")
        logger.info(
            "social stub selesai untuk %s → %s (isi ARCHIVE_STEPS setelah list-source)",
            app,
            final.parent.resolve(),
        )
        return 0
    except Exception as exc:
        logger.error("social stub failed:\n%s", exc)
        return 1
    finally:
        await session.close()


async def _run_step(session: AutomatorSession, out_dir: Path, step: tuple) -> None:
    kind = step[0]
    if kind == "wait":
        await session.sleep(float(step[1]))
    elif kind == "tap":
        _, using, selector = step
        await session.tap(selector, using=using)
        await session.sleep(0.8)
    elif kind == "scroll":
        await session.scroll(str(step[1]))
        await session.sleep(0.5)
    elif kind == "screenshot":
        await session.screenshot(out_dir / str(step[1]))
    elif kind == "tap_xy":
        await session.tap_xy(int(step[1]), int(step[2]))
        await session.sleep(0.5)
    else:
        raise ValueError(f"Unknown step kind: {kind}")
