"""Commands: Hub → device, and what is reported back."""

import asyncio

import pytest
from majordom_integration_sdk.schemas.device import CredentialsType, ProvidedCredentials
from majordom_integration_sdk.testing import RecordingControllerOutput

from majordom_zwave import ZwaveController
from tests.helpers import command, pair, param, stored, values, wait_for_value
from tests.network import MockNetwork

SWITCH = "37-0-targetValue"
LEVEL = "38-0-targetValue"


async def test_a_command_switches_the_device_and_its_report_comes_back(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)
    switch = param(device, SWITCH)

    await command(controller, device, switch, True)

    assert await wait_for_value(output, switch, lambda v: v is True) is True
    assert "BinarySwitchCCSet" in await network.frames(5)


async def test_a_level_command_is_a_percentage(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "dimmer")
    level = param(device, LEVEL)

    await command(controller, device, level, 100)  # Z-Wave's top level is 99
    assert await wait_for_value(output, level, lambda v: v == 100) == 100
    await command(controller, device, level, 40)
    assert await wait_for_value(output, level, lambda v: v == 40) == 40


async def test_a_failed_command_is_surfaced_and_not_reported_as_applied(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)
    switch = param(device, SWITCH)
    await network.silence(5)
    output.events.clear()

    with pytest.raises(ConnectionError):
        await command(controller, device, switch, True)

    assert True not in values(output, switch.id)
    assert (await stored(controller, device.id)).last_error


async def test_a_command_the_device_refuses_is_surfaced_and_not_reported_as_applied(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "supervised")
    switch = param(device, SWITCH)
    await network.reject(5)
    output.events.clear()

    with pytest.raises(RuntimeError):
        await command(controller, device, switch, True)

    assert True not in values(output, switch.id)
    assert (await stored(controller, device.id)).last_error


async def test_a_successful_command_clears_the_last_error(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)
    switch = param(device, SWITCH)
    await network.silence(5)
    with pytest.raises(ConnectionError):
        await command(controller, device, switch, True)

    await network.revive(5)
    await command(controller, device, switch, True)

    assert (await stored(controller, device.id)).last_error is None


async def test_a_read_only_parameter_cannot_be_commanded(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "sensor")

    with pytest.raises(ValueError):
        await command(controller, device, param(device, "49-0-Air temperature"), 30)


async def test_a_secure_device_that_ignored_a_command_gets_a_fresh_session_and_the_command_again(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork, monkeypatch
):
    """A device that lost power can keep a dead S2 session and never ask for a new one (seen on a Shelly Wave): it
    takes commands without acting on them. A nonce from the controller starts a new session."""
    monkeypatch.setattr(ZwaveController, "VERIFY_DELAY", 0.5)
    await controller.start()
    pin = lambda label: ProvidedCredentials(type=CredentialsType.code, value=label["pin"])  # noqa: E731
    device = await pair(controller, output, network, 5, "secure", credentials=pin)
    switch = param(device, SWITCH)
    await network.desync(5)

    await command(controller, device, switch, True)

    for _ in range(50):
        if await network.switch(5):
            break
        await asyncio.sleep(0.1)
    assert await network.switch(5) is True
