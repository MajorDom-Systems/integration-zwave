"""Run order matters: `controller`/`deps` are session-scoped, so pairing happens
once in test_pairs_a_discovered_device and later tests read that same device
back from the shared repo. `virtual_zwave` is function-scoped though (fresh,
empty node registry each test), so any test that needs to reach the "device"
re-creates the node with the same NODE_ID.
"""
import asyncio

from majordom_integration_sdk.controller import AbstractController
from majordom_integration_sdk.schemas.command import DeviceCommand

from majordom_zwave import ZwaveController
from majordom_zwave.model import ZwaveDevice, ZwaveDeviceState

from virtual_zwave_network import VirtualZwaveNetwork

NODE_ID = 5


async def test_pairs_a_discovered_device(
    controller: ZwaveController,
    deps: AbstractController.Dependencies,
    virtual_zwave: VirtualZwaveNetwork,
    make_provisional_device,
) -> None:
    await controller.start()
    await controller.start_pairing_window(10)

    virtual_zwave.node_found(NODE_ID)
    virtual_zwave.node_joined({"nodeId": NODE_ID})
    await asyncio.sleep(0.05)

    assert controller.discoveries, "No device was discovered during the pairing window"
    discovery = next(iter(controller.discoveries.values()))
    await make_provisional_device(discovery)
    await controller.pair_device(discovery, credentials=None)
    await controller.stop()

    assert discovery.id in deps.output.connected_devices

    async with deps.make_device_repository() as repo:
        paired = await repo.get(discovery.id, as_=ZwaveDevice)
        state = await repo.state(discovery.id, as_=ZwaveDeviceState)
    assert paired is not None
    assert paired.integration_data.node_id == NODE_ID
    assert state.parameters, "Expected at least one parameter to be mapped during pairing"


async def test_fetches_state(
    controller: ZwaveController,
    deps: AbstractController.Dependencies,
    virtual_zwave: VirtualZwaveNetwork,
) -> None:
    await controller.start()
    virtual_zwave.node_joined({"nodeId": NODE_ID})
    await asyncio.sleep(0.05)

    async with deps.make_device_repository() as repo:
        devices = await repo.get_all(as_=ZwaveDevice)
        device = devices[0]

    virtual_zwave.emit_value_updated(
        NODE_ID,
        command_class=37,
        command_class_name="Binary Switch",
        property="currentValue",
        new_value=True,
        prev_value=False,
    )
    events_before = len(deps.output.events)
    await controller.fetch(device)
    new_events = deps.output.events[events_before:]

    assert any(e.device_id == device.id and e.value is True for e in new_events), (
        "fetch() never reported the current value back to the Hub"
    )
    await controller.stop()


async def test_sends_a_command(
    deps: AbstractController.Dependencies,
    controller: ZwaveController,
    virtual_zwave: VirtualZwaveNetwork,
) -> None:
    await controller.start()
    virtual_zwave.node_joined({"nodeId": NODE_ID})

    async with deps.make_device_repository() as repo:
        devices = await repo.get_all(as_=ZwaveDevice)
        device = devices[0]
        state = await repo.state(device.id, as_=ZwaveDeviceState)
        parameter = next(p for p in state.parameters if p.id == state.main_parameter)

        command = DeviceCommand(device_id=device.id, parameter_id=parameter.id, value=0)
        await controller.send_command(command, device, parameter)
        await controller.stop()

    sent = [
        c for c in virtual_zwave.async_send_command.call_args_list
        if c.args[0].get("command") == "node.set_value"
    ]
    assert sent, "Controller never sent a node.set_value command to the device"
    assert sent[-1].args[0]["value"] == 0


async def test_identifies(
    controller: ZwaveController,
    deps: AbstractController.Dependencies,
    virtual_zwave: VirtualZwaveNetwork,
) -> None:
    await controller.start()
    virtual_zwave.node_joined({"nodeId": NODE_ID})

    async with deps.make_device_repository() as repo:
        devices = await repo.get_all(as_=ZwaveDevice)
        device = devices[0]
        await controller.identify(device)
    await controller.stop()

    sent = [
        c for c in virtual_zwave.async_send_command.call_args_list
        if c.args[0].get("command") == "node.set_value"
    ]
    assert sent, "controller.identify() never sent a node.set_value command to the device"


async def test_unpairs(
    controller: ZwaveController,
    deps: AbstractController.Dependencies,
    virtual_zwave: VirtualZwaveNetwork,
) -> None:
    await controller.start()
    virtual_zwave.node_joined({"nodeId": NODE_ID})

    async with deps.make_device_repository() as repo:
        devices = await repo.get_all(as_=ZwaveDevice)
        device = devices[0]

        unpair_task = asyncio.create_task(controller.unpair(device))
        await asyncio.sleep(0.05)
        virtual_zwave.node_removed(NODE_ID)
        await unpair_task

        assert NODE_ID not in virtual_zwave.controller.nodes
    await controller.stop()
