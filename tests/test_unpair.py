"""Unpairing: removing the device from the Z-Wave network."""

import asyncio

import pytest
from majordom_integration_sdk.testing import RecordingControllerOutput

from majordom_zwave import ZwaveController
from tests.helpers import pair, stored
from tests.network import MockNetwork


async def test_a_failed_device_is_removed_without_the_device(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)
    await network.fail(5)

    await controller.unpair(device)

    assert 5 not in await network.node_ids()


async def test_a_live_device_is_removed_once_it_confirms_the_exclusion(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)

    unpairing = asyncio.create_task(controller.unpair(device))
    await asyncio.sleep(0.3)
    assert not unpairing.done()  # waits for the user to press the device's button
    await network.exclude(5)
    await asyncio.wait_for(unpairing, 10)

    assert 5 not in await network.node_ids()


async def test_excluding_another_device_does_not_count_as_removing_this_one(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "switch")
    other = await pair(controller, output, network, 6, "switch")

    unpairing = asyncio.create_task(controller.unpair(device))
    await asyncio.sleep(0.3)
    await network.exclude(6)  # the user pressed the button of the wrong device

    with pytest.raises(LookupError, match="another device"):
        await asyncio.wait_for(unpairing, 10)
    assert other.id in output.lost_devices
    assert 5 in await network.node_ids()


async def test_an_unconfirmed_exclusion_times_out_with_a_reason(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)

    with pytest.raises(TimeoutError):
        await controller.unpair(device)

    assert (await stored(controller, device.id)).last_error
    assert 5 in await network.node_ids()
    await controller.start_pairing_window(1)  # the exclusion was stopped: inclusion can start
