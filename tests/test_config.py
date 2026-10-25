"""zwave-js-server: run on the stick, in the Hub's region, for the controller that needs it; its port is the runtime's
to choose: the compose and the endpoint follow it."""

import json
from pathlib import Path
from types import SimpleNamespace

from majordom_integration_sdk import Context, Endpoint
from majordom_integration_sdk.runtime import PeripheralState, Pinned, Runtime
from majordom_integration_sdk.testing import FakeCompose, build_test_platform

import majordom_zwave
from majordom_zwave import ZwaveController
from majordom_zwave.config import zwave_js_server
from tests.helpers import wait_until

PORTS = SimpleNamespace(api=45813)


def test_prefers_its_usual_port():
    assert zwave_js_server().ports == {"api": 3000}


def test_listens_on_the_allocated_port():
    command = [part.format(ports=PORTS) for part in zwave_js_server().compose["command"]]
    assert command[command.index("--port") + 1] == "45813"


def test_provides_its_url_on_the_allocated_port():
    assert zwave_js_server().provides[0].url.format(ports=PORTS) == "ws://127.0.0.1:45813"


async def test_runs_on_the_stick_in_the_hubs_region_for_the_controller(tmp_path: Path):
    platform = build_test_platform().copy(context=Context(region="Europe"))
    stick = Endpoint("zwave", "serial-api", "/dev/serial/by-id/usb-0658_0200-if00")
    exported = majordom_zwave.peripherals(platform)
    [controller] = [peripheral for peripheral in exported if isinstance(peripheral, ZwaveController)]
    runtime = Runtime(tmp_path, [Pinned(stick), FakeCompose(), *exported], context=lambda: platform.context)
    await runtime.start()
    try:
        await wait_until(lambda: runtime.status(controller).state == PeripheralState.RUNNING, 10, "the controller")
        assert runtime.providers(controller) == {"zwave": "zwave-js-server"}
        compose = json.loads((tmp_path / "peripherals" / "compose" / "compose.json").read_text())
        container = compose["services"]["zwave-js-server"]
        assert container["devices"] == [f"{stick.url}:/dev/zwave"]
        assert container["environment"]["RF_REGION"] == "Europe"
    finally:
        await runtime.stop()
