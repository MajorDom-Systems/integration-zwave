"""A sleeping (battery) device: awake only at its wake-ups, so commands wait for the next one."""

import asyncio

from majordom_integration_sdk.testing import RecordingControllerOutput

from majordom_zwave import ZwaveController
from tests.helpers import command, pair, param, stored, values, wait_for_value
from tests.network import MockNetwork

SWITCH = "37-0-targetValue"


async def test_a_sleeping_device_pairs_and_reports_its_battery(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "sleeping")  # awake while it is included

    assert values(output, param(device, "128-0-level").id) == [87]


async def test_a_command_to_a_sleeping_device_waits_for_its_wake_up(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "sleeping")
    switch = param(device, SWITCH)
    await wait_for_asleep(network)

    await command(controller, device, switch, True)  # queued by zwave-js: no error, and not applied yet

    assert True not in values(output, switch.id)
    assert (await stored(controller, device.id)).last_error is None
    await network.wake(5)
    assert await wait_for_value(output, switch, lambda v: v is True) is True


async def test_a_sleeping_device_is_not_lost(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "sleeping")
    await wait_for_asleep(network)

    assert device.id not in output.lost_devices
    assert (await stored(controller, device.id)).available is True


async def wait_for_asleep(network: MockNetwork, node: int = 5) -> None:
    """zwave-js sends the device back to sleep once its interview is done."""
    for _ in range(100):
        if not await network.awake(node):
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("the device did not go back to sleep")
