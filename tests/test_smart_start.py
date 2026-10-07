"""SmartStart: a device provisioned from its QR code joins by itself when it is powered on, securely, without a PIN."""

import asyncio

import aiohttp
from majordom_integration_sdk.schemas.device import CredentialsType, ProvidedCredentials
from majordom_integration_sdk.testing import RecordingControllerOutput
from zwave_js_server.client import Client

from majordom_zwave import ZwaveController
from tests.helpers import hub_creates_device, param, stored, wait_until
from tests.network import MockNetwork

SWITCH = "37-0-targetValue"


async def provisioned(network: MockNetwork) -> list[str]:
    """The DSKs zwave-js keeps in its SmartStart provisioning list (read as another client of the server would)."""
    async with aiohttp.ClientSession() as session:
        client = Client(network.url, session)
        await client.connect()
        ready = asyncio.Event()
        listening = asyncio.create_task(client.listen(ready))
        await ready.wait()
        assert client.driver is not None
        entries = await client.driver.controller.async_get_provisioning_entries()
        await client.disconnect()
        listening.cancel()
    return [entry.dsk for entry in entries]


async def provision(controller: ZwaveController, network: MockNetwork, duration: int = 60) -> dict[str, str]:
    label = await network.join(5, "secure", smartStart=True)
    await controller.start_pairing_window(duration, ProvidedCredentials(type=CredentialsType.qr, value=label["qr"]))
    return label


async def test_a_provisioned_device_joins_when_powered_on_and_pairs_securely(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    label = await provision(controller, network)
    assert label["dsk"] in await provisioned(network)
    assert not output.received_discoveries  # nothing joins before the device is powered on

    await network.power_on(5)
    await wait_until(lambda: output.received_discoveries, 20, "the device to join")
    discovery = output.received_discoveries[-1]
    assert discovery.last_error is None  # S2 from its QR code: no PIN needed
    await hub_creates_device(controller.dependencies, discovery)
    device = await stored(controller, await controller.pair_device(discovery, None))

    param(device, SWITCH)  # only supported securely: present only if S2 bootstrapping succeeded


async def test_provisioning_outlives_the_pairing_window(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    await provision(controller, network, duration=1)
    await asyncio.sleep(1.5)  # the window closed long before the device is installed and powered

    await network.power_on(5)
    await wait_until(lambda: output.received_discoveries, 20, "the device to join")


async def test_unpairing_a_smart_start_device_removes_its_provisioning(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    label = await provision(controller, network)
    await network.power_on(5)
    await wait_until(lambda: output.received_discoveries, 20, "the device to join")
    discovery = output.received_discoveries[-1]
    await hub_creates_device(controller.dependencies, discovery)
    device = await stored(controller, await controller.pair_device(discovery, None))

    unpairing = asyncio.create_task(controller.unpair(device))
    await asyncio.sleep(0.3)
    await network.exclude(5)
    await asyncio.wait_for(unpairing, 10)

    assert label["dsk"] not in await provisioned(network)  # or zwave-js would include it again at its next power-up


async def test_an_s2_qr_code_is_not_provisioned(controller: ZwaveController, network: MockNetwork):
    await controller.start()
    label = await network.join(5, "secure")  # an S2 code: included now, in the window

    await controller.start_pairing_window(60, ProvidedCredentials(type=CredentialsType.qr, value=label["qr"]))

    assert label["dsk"] not in await provisioned(network)
