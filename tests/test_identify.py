"""Identify: make the device show itself, without switching what it controls."""

import pytest
from majordom_integration_sdk.testing import RecordingControllerOutput

from majordom_zwave import ZwaveController
from tests.helpers import pair
from tests.network import MockNetwork


async def test_a_device_with_the_identify_indicator_identifies_itself(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "identifiable")

    await controller.identify(device)

    frames = await network.frames(5)
    assert "IndicatorCCSet" in frames
    assert "BinarySwitchCCSet" not in frames


async def test_a_light_without_the_indicator_blinks_and_returns_to_its_level(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "bulb")

    await controller.identify(device)

    frames = await network.frames(5)
    assert frames.count("MultilevelSwitchCCSet") >= 3  # off/on blinks, then back to the level it had


@pytest.mark.parametrize("kind", ["switch", "dimmer"])
async def test_a_device_not_known_to_be_a_light_is_not_toggled(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork, kind: str
):
    await controller.start()
    device = await pair(controller, output, network, 5, kind)  # a relay or a motor: a heater, a pump, a blind

    await controller.identify(device)

    frames = await network.frames(5)
    assert "BinarySwitchCCSet" not in frames
    assert "MultilevelSwitchCCSet" not in frames
