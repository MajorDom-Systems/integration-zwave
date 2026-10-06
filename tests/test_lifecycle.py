"""Lifecycle: start, restart, availability, losing the server, and devices that change behind the Hub's back."""

import asyncio
import contextlib

import aiohttp
from majordom_integration_sdk.controller import AbstractController
from majordom_integration_sdk.testing import RecordingControllerOutput
from zwave_js_server.client import Client

from majordom_zwave import ZwaveController, config
from tests.helpers import command, pair, param, stored, wait_for_value, wait_until
from tests.network import MockNetwork

SWITCH = "37-0-targetValue"


def test_the_server_url_comes_from_the_documented_variable(monkeypatch):
    monkeypatch.setenv("ZWAVE_SERVER_URL", "ws://zwave.local:3000")
    assert config.server_url() == "ws://zwave.local:3000"
    monkeypatch.delenv("ZWAVE_SERVER_URL")
    assert config.server_url() == "ws://localhost:3000"


async def restart(controller: ZwaveController, deps: AbstractController.Dependencies) -> ZwaveController:
    """Stop and start the integration again, with the Hub's data kept (a Hub restart)."""
    await controller.stop()
    again = ZwaveController(deps)
    await again.start()
    return again


async def test_paired_devices_are_reconnected_after_a_restart(
    controller: ZwaveController, deps, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)
    output.connected_devices.clear()

    again = await restart(controller, deps)
    try:
        assert device.id in output.connected_devices
        await network.report(5, "switch", True)
        assert await wait_for_value(output, param(device, SWITCH), lambda v: v is True)
        assert device.id not in again.discoveries  # paired, not offered again
    finally:
        await again.stop()


async def test_a_device_that_stops_answering_is_lost_and_found_again(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)
    switch = param(device, SWITCH)

    await network.silence(5)
    with contextlib.suppress(ConnectionError):  # it does not answer
        await command(controller, device, switch, True)
    await wait_until(lambda: device.id in output.lost_devices, 10, "the device to be lost")
    lost = await stored(controller, device.id)
    assert lost.available is False
    assert lost.last_error

    output.connected_devices.clear()
    await network.revive(5)
    await wait_until(lambda: device.id in output.connected_devices, 10, "the device to come back")
    back = await stored(controller, device.id)
    assert back.available is True
    assert back.last_error is None


async def test_a_dead_device_is_reported_unavailable_after_a_restart(
    controller: ZwaveController, deps, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)
    await network.silence(5)
    with contextlib.suppress(ConnectionError):
        await command(controller, device, param(device, SWITCH), True)
    await wait_until(lambda: device.id in output.lost_devices, 10, "the device to be lost")
    output.lost_devices.clear()
    output.connected_devices.clear()

    again = await restart(controller, deps)
    try:
        assert device.id in output.lost_devices
        assert device.id not in output.connected_devices
    finally:
        await again.stop()


async def test_losing_the_server_loses_the_devices_and_it_reconnects_when_back(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)

    await network.drop_server()
    await wait_until(lambda: device.id in output.lost_devices, 10, "the devices to be lost with the server")

    output.connected_devices.clear()
    await network.serve()
    await wait_until(lambda: device.id in output.connected_devices, 15, "the reconnection")
    await network.report(5, "switch", True)
    assert await wait_for_value(output, param(device, SWITCH), lambda v: v is True)


async def test_starting_without_the_server_does_not_fail_and_connects_once_it_is_up(
    controller: ZwaveController, output: RecordingControllerOutput, make_network
):
    network = await make_network(serve=False)

    await controller.start()  # the server is not up yet: reported, not raised
    assert output.errors and output.errors[-1][1] is True  # still running

    await network.serve()
    await wait_until(lambda: controller.connected, 15, "the connection")


async def test_stop_is_clean_without_a_connection(controller: ZwaveController, make_network):
    await make_network(serve=False)
    await controller.start()
    await controller.stop()
    await controller.stop()


async def test_a_device_excluded_elsewhere_is_lost_with_a_reason(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)

    # removed with another tool (e.g. Z-Wave JS UI, another client of the same server) while the integration runs
    async with aiohttp.ClientSession() as session:
        other_tool = Client(network.url, session)
        await other_tool.connect()
        ready = asyncio.Event()
        listening = asyncio.create_task(other_tool.listen(ready))
        await ready.wait()
        assert other_tool.driver is not None
        await other_tool.driver.controller.async_begin_exclusion()
        await network.exclude(5)
        await other_tool.disconnect()
        listening.cancel()

    await wait_until(lambda: device.id in output.lost_devices, 10, "the excluded device to be lost")
    assert (await stored(controller, device.id)).last_error


async def test_another_device_reusing_a_node_id_is_not_taken_for_the_paired_one(
    controller: ZwaveController, deps, output: RecordingControllerOutput, make_network
):
    network = await make_network()
    await controller.start()
    device = await pair(controller, output, network)
    await controller.stop()
    await network.stop()

    # while the Hub was off, the device was replaced: another product now has node id 5
    await make_network([{"node": 5, "kind": "switch", "productId": 2}])
    output.connected_devices.clear()
    again = ZwaveController(deps)
    await again.start()
    try:
        assert device.id not in output.connected_devices
        assert device.id in output.lost_devices
        assert (await stored(again, device.id)).last_error
    finally:
        await again.stop()
