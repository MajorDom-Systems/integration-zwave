"""MajorDom Z-Wave integration.

Bridges a Z-Wave network (via a running `zwave-js-server` instance) to a MajorDom Hub.
See `controller.py` for the entry point the Hub actually instantiates.
"""

from .controller import ZwaveController

__all__ = ["ZWaveController"]
