"""iOS UI automator helpers (WebDriverAgent via pymobiledevice3)."""

from .apps import KNOWN_APPS, resolve_bundle_id
from .session import AutomatorSession

__all__ = ["KNOWN_APPS", "resolve_bundle_id", "AutomatorSession"]
