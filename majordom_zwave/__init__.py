"""MajorDom Z-Wave integration.

Bridges a Z-Wave network (via a running `zwave-js-server` instance) to a MajorDom Hub.
The Hub runs what `peripherals` exports: zwave-js-server on the stick, and the controller (`controller.py`) that
drives it.
"""

from majordom_integration_sdk import Peripheral, Platform

from .config import zwave_js_server
from .controller import ZwaveController


def peripherals(platform: Platform) -> list[Peripheral]:
    return [zwave_js_server(), ZwaveController(platform)]


__all__ = ["ZwaveController", "peripherals"]
