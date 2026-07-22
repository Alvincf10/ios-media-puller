from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger("ios_automator")


class WdaNotReadyError(RuntimeError):
    """Raised when WebDriverAgent is missing or not listening on the device."""

    HINT = (
        "WebDriverAgent belum siap di iPhone.\n"
        "  • Error Number 3 / ConnectionFailed = port 8100 tidak ada listener "
        "(WDA belum terpasang atau belum running).\n"
        "  • Cek app: belum ada *WebDriverAgent* / *xctrunner* di device.\n"
        "  • Build & install WDA sekali dari Mac + Xcode, lalu trust developer.\n"
        "  • Detail: ios_automator/README.md (section Install WDA).\n"
        "  • iOS 17+: jalankan juga `pymobiledevice3 remote tunneld` bila perlu."
    )

    def __init__(self, detail: str = "") -> None:
        msg = self.HINT if not detail else f"{detail}\n\n{self.HINT}"
        super().__init__(msg)


@dataclass
class AutomatorSession:
    """Thin wrapper over pymobiledevice3 WDA client (USB or HTTP)."""

    client: Any
    session_id: Optional[str] = None
    bundle_id: Optional[str] = None
    _owns_lockdown: bool = False
    _lockdown: Any = field(default=None, repr=False)

    @classmethod
    async def connect_usb(cls, port: int = 8100, timeout: float = 15.0) -> AutomatorSession:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.wda import WdaServiceClient

        lockdown = await create_using_usbmux()
        client = WdaServiceClient(service_provider=lockdown, port=port, timeout=timeout)
        name = lockdown.display_name or lockdown.product_type
        logger.info(
            "USB device: %s | iOS %s | UDID %s",
            name,
            lockdown.product_version,
            lockdown.udid,
        )
        return cls(client=client, _owns_lockdown=True, _lockdown=lockdown)

    @classmethod
    def connect_http(cls, base_url: str = "http://127.0.0.1:8100", timeout: float = 15.0) -> AutomatorSession:
        from pymobiledevice3.services.wda import WdaClient

        client = WdaClient(base_url=base_url, timeout=timeout)
        logger.info("HTTP WDA: %s", base_url)
        return cls(client=client)

    async def status(self) -> dict[str, Any]:
        try:
            return await self._call(self.client.get_status)
        except Exception as exc:
            raise WdaNotReadyError(str(exc)) from exc

    async def start(self, bundle_id: Optional[str] = None) -> str:
        # Probe WDA first so failures are actionable (missing install vs app crash).
        await self.status()
        try:
            sid = await self._call(self.client.start_session, bundle_id)
        except WdaNotReadyError:
            raise
        except Exception as exc:
            raise WdaNotReadyError(str(exc)) from exc
        self.session_id = sid
        self.bundle_id = bundle_id
        self.client.session_id = sid
        logger.info("WDA session %s (bundle=%s)", sid, bundle_id or "-")
        return sid

    async def ensure_session(self, bundle_id: Optional[str] = None) -> str:
        if self.session_id:
            return self.session_id
        return await self.start(bundle_id)

    async def tap(
        self,
        selector: str,
        *,
        using: str = "accessibility id",
        bundle_id: Optional[str] = None,
    ) -> None:
        await self.ensure_session(bundle_id or self.bundle_id)
        element_id = await self._call(self.client.find_element, using, selector, self.session_id)
        await self._call(self.client.click, element_id, self.session_id)
        logger.info("tap [%s] %s", using, selector)

    async def tap_xy(self, x: int, y: int, *, bundle_id: Optional[str] = None) -> None:
        """Tap via zero-length drag (coordinate tap)."""
        await self.ensure_session(bundle_id or self.bundle_id)
        await self._call(self.client.swipe, x, y, x, y, 0.05, self.session_id)
        logger.info("tap_xy (%d, %d)", x, y)

    async def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        *,
        duration: float = 0.25,
        bundle_id: Optional[str] = None,
    ) -> None:
        await self.ensure_session(bundle_id or self.bundle_id)
        await self._call(
            self.client.swipe,
            start_x,
            start_y,
            end_x,
            end_y,
            duration,
            self.session_id,
        )
        logger.info("swipe (%d,%d) → (%d,%d) %.2fs", start_x, start_y, end_x, end_y, duration)

    async def scroll(
        self,
        direction: str = "down",
        *,
        distance: float = 0.45,
        duration: float = 0.3,
        bundle_id: Optional[str] = None,
    ) -> None:
        """Scroll relative to window size. direction: up|down|left|right."""
        await self.ensure_session(bundle_id or self.bundle_id)
        size = await self._call(self.client.get_window_size, self.session_id)
        width = int(size["width"])
        height = int(size["height"])
        cx, cy = width // 2, height // 2
        delta_x = int(width * distance)
        delta_y = int(height * distance)
        direction = direction.lower().strip()
        if direction == "down":
            await self.swipe(cx, cy + delta_y // 2, cx, cy - delta_y // 2, duration=duration)
        elif direction == "up":
            await self.swipe(cx, cy - delta_y // 2, cx, cy + delta_y // 2, duration=duration)
        elif direction == "left":
            await self.swipe(cx + delta_x // 2, cy, cx - delta_x // 2, cy, duration=duration)
        elif direction == "right":
            await self.swipe(cx - delta_x // 2, cy, cx + delta_x // 2, cy, duration=duration)
        else:
            raise ValueError("direction must be up|down|left|right")

    async def type_text(self, text: str, *, bundle_id: Optional[str] = None) -> None:
        await self.ensure_session(bundle_id or self.bundle_id)
        await self._call(self.client.send_keys, text, self.session_id)
        logger.info("typed %d chars", len(text))

    async def press(self, button: str = "home") -> None:
        await self._call(self.client.press_button, button, self.session_id)
        logger.info("press %s", button)

    async def screenshot(self, out: Path, *, bundle_id: Optional[str] = None) -> Path:
        await self.ensure_session(bundle_id or self.bundle_id)
        png = await self._call(self.client.get_screenshot, self.session_id)
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(png)
        logger.info("screenshot → %s (%d bytes)", out.resolve(), len(png))
        return out

    async def window_size(self) -> dict[str, Any]:
        await self.ensure_session(self.bundle_id)
        return await self._call(self.client.get_window_size, self.session_id)

    async def source_xml(self) -> str:
        await self.ensure_session(self.bundle_id)
        return await self._call(self.client.get_source, self.session_id)

    async def list_elements(self, *, limit: int = 80) -> list[dict[str, str]]:
        """Parse WDA accessibility source into label/name/type rows."""
        xml = await self.source_xml()
        root = ET.fromstring(xml)
        rows: list[dict[str, str]] = []
        for node in root.iter():
            label = (node.attrib.get("label") or "").strip()
            name = (node.attrib.get("name") or "").strip()
            value = (node.attrib.get("value") or "").strip()
            typ = (node.attrib.get("type") or node.tag or "").strip()
            if not (label or name or value):
                continue
            rows.append(
                {
                    "type": typ,
                    "name": name,
                    "label": label,
                    "value": value[:80],
                    "enabled": node.attrib.get("enabled", ""),
                    "visible": node.attrib.get("visible", ""),
                }
            )
            if len(rows) >= limit:
                break
        return rows

    async def sleep(self, seconds: float) -> None:
        await _maybe_async_sleep(seconds)

    async def close(self) -> None:
        if self._owns_lockdown and self._lockdown is not None:
            close = getattr(self._lockdown, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

    async def _call(self, fn, *args):
        result = fn(*args)
        if hasattr(result, "__await__"):
            return await result
        return result


async def _maybe_async_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


def default_output_dir(prefix: str = "automator") -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return Path(__file__).resolve().parents[2] / "output" / f"{prefix}_{stamp}"
