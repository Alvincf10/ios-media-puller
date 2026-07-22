from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BY_MAP = {
    "accessibility id": AppiumBy.ACCESSIBILITY_ID,
    "id": AppiumBy.ID,
    "name": AppiumBy.NAME,
    "xpath": AppiumBy.XPATH,
    "class name": AppiumBy.CLASS_NAME,
    "predicate": AppiumBy.IOS_PREDICATE,
    "class chain": AppiumBy.IOS_CLASS_CHAIN,
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def find_first(driver, strategies: list[dict[str, str]], timeout: float = 12.0):
    last_err: Optional[Exception] = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        for strat in strategies:
            using = strat["using"].lower()
            value = strat["value"]
            by = BY_MAP.get(using)
            if by is None:
                continue
            try:
                el = WebDriverWait(driver, 1.5).until(EC.presence_of_element_located((by, value)))
                if el:
                    return el
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        time.sleep(0.3)
    raise TimeoutException(f"Element not found for strategies={strategies!r}; last={last_err}")


def tap_first(driver, strategies: list[dict[str, str]], timeout: float = 12.0) -> None:
    el = find_first(driver, strategies, timeout=timeout)
    el.click()


def wait_any(driver, strategies: list[dict[str, str]], timeout: float = 20.0) -> None:
    find_first(driver, strategies, timeout=timeout)


def read_text(driver, strategies: list[dict[str, str]], attribute: str = "name", timeout: float = 12.0) -> str:
    el = find_first(driver, strategies, timeout=timeout)
    for attr in (attribute, "name", "label", "value"):
        try:
            val = el.get_attribute(attr)
        except Exception:  # noqa: BLE001
            val = None
        if val and str(val).strip():
            return str(val).strip()
    text = (el.text or "").strip()
    if text:
        return text
    raise RuntimeError(f"Could not read text/attribute from element (attr={attribute})")
