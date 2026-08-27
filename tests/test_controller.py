"""Tests that drive the controller through its lifecycle.

These are **prefilled to fail** against the unimplemented skeleton: every test below calls a
method that still raises `NotImplementedError`, so CI stays red until you implement the
controller.

Run these against a **virtual / simulated device** — a fake endpoint that speaks your
protocol in-process (no real hardware, no network), so CI is deterministic. Add a fixture
for it in `conftest.py` and have the controller talk to it. Each test should then assert on
**both sides**: what the controller reported back to the Hub (via `deps.output`) *and* what
actually landed on the device (the virtual device observed the command / changed state) —
don't just call the method and assume it worked.

Persistence is the Hub's job (see `conftest.py`): the fixtures seed the repository the way
the Hub would, so assert on the controller's protocol behaviour and reports — not that the
integration created a device row.

(The template's own CI excludes this file so the template repo stays green — see
`.github/workflows/test.yml`. Your integration repo runs it in full, and it's red until you
implement the controller.)
"""
import asyncio

from majordom_integration_sdk.controller import AbstractController
from majordom_integration_sdk.schemas.command import DeviceCommand
from majordom_integration_sdk.schemas.device import Device, Discovery
from majordom_integration_sdk.schemas.parameter import ParameterState

from majordom_zwave import ZwaveController
from majordom_zwave.model import ZwaveDevice, ZwaveDeviceState


async def test_pairs_a_discovered_device(
    controller: ZwaveController,
    deps: AbstractController.Dependencies,
    make_provisional_device, # already stored under discovery.id by the Hub-side fixture
) -> None:
    await controller.start()
    await controller.start_pairing_window(30)

    # Physically trigger inclusion on the device now (put it into pairing mode).
    print("\n>>> Put the Z-Wave device into inclusion mode now (you have 30s)...")
    await asyncio.sleep(30)

    assert controller.discoveries, "No device was discovered during the pairing window"
    discovery = next(iter(controller.discoveries.values()))
    await make_provisional_device(discovery)
    await controller.pair_device(discovery, credentials=None)
    await controller.stop()

    # # Hub-side: controller reported the device as connected.
    assert discovery.id in deps.output.connected_devices

    # # Repo-side: parameters were mapped and persisted during pairing.
    async with deps.make_device_repository() as repo:
        paired = await repo.get(discovery.id, as_=ZwaveDevice)
    assert paired is not None
    # assert paired.parameters, "Expected at least one parameter to be mapped during pairing"
    assert paired.integration_data.node_id is not None
    # TODO: verify pairing actually completed — the controller established the session and
    #   reported back (it does not persist the device itself):
    #   - Hub side: `discovery.id` is in `deps.output.connected_devices`.
    #   - Device side: the virtual device accepted the credentials / opened a session.
    #   - Parameters: if you map parameters during pairing, assert their initial states were
    #     written via the repository (`repo.save_parameter_state`).


async def test_fetches_state(
    controller: ZwaveController,
    deps: AbstractController.Dependencies,
) -> None:
    await controller.start()
    async with deps.make_device_repository() as repo:
        devices = await repo.get_all(as_=ZwaveDevice)
        device = devices[0]
        await controller.fetch(device)
    await controller.stop()
    # TODO: verify the refresh reached the device and propagated back:
    #   - Set a known state on the virtual device first, then assert `deps.output.events`
    #     (or the repository's parameter states) now reflect exactly that state — not stale
    #     or default values.


async def test_sends_a_command(deps: AbstractController.Dependencies, controller: ZwaveController) -> None:
    await controller.start()
    async with deps.make_device_repository() as repo:
        devices = await repo.get_all(as_=ZwaveDevice)
        device = devices[0]
        state = await repo.state(device.id, as_=ZwaveDeviceState)

        parameter = next(p for p in state.parameters if p.id == state.main_parameter)

        command = DeviceCommand(device_id=device.id, parameter_id=parameter.id, value=0)
        await controller.send_command(command, device, parameter)
        await controller.stop()


async def test_identifies(controller: ZwaveController, deps: AbstractController.Dependencies) -> None:
    await controller.start()
    async with deps.make_device_repository() as repo:
        devices = await repo.get_all(as_=ZwaveDevice)
        device = devices[0]
        await controller.identify(device)
    await controller.stop()    
# # TODO: assert the virtual device recorded an identify request (e.g. its identify counter
#     #   incremented / the identify command was received).


async def test_unpairs(controller: ZwaveController, deps: AbstractController.Dependencies) -> None:
    await controller.start()
    async with deps.make_device_repository() as repo:
        devices = await repo.get_all(as_=ZwaveDevice)
        device = devices[0]
        await controller.unpair(device)
    await controller.stop()
#     # TODO: verify removal took effect:
#     #   - Device side: the virtual device saw the session torn down / was de-registered.
#     #   - Controller: the device is gone — no more connections or commands should be accepted.