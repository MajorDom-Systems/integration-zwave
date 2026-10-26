"""zwave-js-server: run on the stick, in the Hub's region, for the controller that needs it; its port is the runtime's
to choose: the compose and the endpoint follow it."""

import json
from pathlib import Path

import pytest
from majordom_integration_sdk import Endpoint
from majordom_integration_sdk.runtime import Pinned, Runtime, StatusKind
from majordom_integration_sdk.testing import FakeCompose, build_test_platform

import majordom_zwave
from majordom_zwave import ZwaveController
from majordom_zwave.config import ZwaveNetwork
from tests.helpers import wait_until


def test_a_malformed_network_key_is_refused():
    with pytest.raises(ValueError, match="pattern"):  # zwave-js-server would exit on it, again and again
        ZwaveNetwork(s2_authenticated="not a key")


def test_the_generated_network_keys_are_valid():
    keys = ZwaveNetwork().model_dump()
    assert ZwaveNetwork.model_validate(keys).model_dump() == keys


@pytest.mark.parametrize(("region", "rendered"), [("Europe", "Europe"), (None, "")])  # none: the stick keeps its own
async def test_runs_on_the_stick_in_the_hubs_region_for_the_controller(
    tmp_path: Path, region: str | None, rendered: str
):
    platform = build_test_platform(tmp_path / "peripherals", region=region)
    stick = Endpoint("zwave", "serial-api", "/dev/serial/by-id/usb-0658_0200-if00")
    exported = majordom_zwave.peripherals(platform)
    [controller] = [peripheral for peripheral in exported if isinstance(peripheral, ZwaveController)]
    runtime = Runtime(tmp_path, [Pinned(stick), FakeCompose(), *exported], platform=platform)
    await runtime.start()
    try:
        # started once the server runs; FakeCompose runs none, so it fails to connect and is started again later
        await wait_until(lambda: runtime.status(controller).kind == StatusKind.RETRYING, 10, "the controller's start")
        assert runtime.providers(controller) == {"zwave": "zwave-js-server"}
        compose = json.loads((tmp_path / "peripherals" / "compose" / "compose.json").read_text())
        container = compose["services"]["zwave-js-server"]
        assert container["devices"] == [f"{stick.url}:/dev/zwave"]
        assert container["environment"]["RF_REGION"] == rendered
        port = container["command"][container["command"].index("--port") + 1]
        assert controller.peripherals.endpoint("zwave").url == f"ws://127.0.0.1:{port}"
    finally:
        await runtime.stop()
