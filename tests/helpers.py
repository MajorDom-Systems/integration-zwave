"""Helpers shared by the tests: what the Hub does around pairing, and waiting for what the integration reports."""

import asyncio
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from majordom_integration_sdk.controller import AbstractController
from majordom_integration_sdk.schemas import DeviceParameterChange
from majordom_integration_sdk.schemas.command import DeviceCommand
from majordom_integration_sdk.schemas.device import Device, Discovery, ProvidedCredentials
from majordom_integration_sdk.schemas.parameter import ParameterDataType
from majordom_integration_sdk.testing import RecordingControllerOutput

from majordom_zwave import ZwaveController
from majordom_zwave.model import ZwaveDevice, ZwaveParameter
from tests.network import MockNetwork

ROOM = UUID(int=42)


async def wait_until(predicate: Callable[[], Any], timeout: float = 10.0, message: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(f"timed out after {timeout}s waiting for {message}")


async def hub_creates_device(
    deps: AbstractController.Dependencies, discovery: Discovery, name: str = "Hall lamp"
) -> None:
    """The Hub creates the device (name, room) before it asks to pair it (`DeviceProvider.create_device`)."""
    async with deps.make_device_repository() as repo:
        await repo.save(
            Device(
                id=discovery.id,
                name=name,
                room_id=ROOM,
                transport=discovery.transport,
                integration=discovery.integration,
                manufacturer=discovery.device_manufacturer,
            )
        )


async def discover(
    controller: ZwaveController,
    output: RecordingControllerOutput,
    network: MockNetwork,
    node: int,
    kind: str,
    credentials: Callable[[dict[str, str]], ProvidedCredentials | None] = lambda _: None,
    duration: int = 60,
    **options: Any,
) -> Discovery:
    """Open the pairing window and let a device join; returns its discovery."""
    label = await network.join(node, kind, **options)
    seen = len(output.received_discoveries)
    await controller.start_pairing_window(duration, credentials(label))
    await wait_until(lambda: len(output.received_discoveries) > seen, 20, f"discovery of node {node}")
    return output.received_discoveries[-1]


async def pair(
    controller: ZwaveController,
    output: RecordingControllerOutput,
    network: MockNetwork,
    node: int = 5,
    kind: str = "switch",
    **options: Any,
) -> ZwaveDevice:
    """Include a device and pair it as the Hub does; returns the stored device."""
    discovery = await discover(controller, output, network, node, kind, **options)
    await hub_creates_device(controller.dependencies, discovery)
    device_id = await controller.pair_device(discovery, None)
    return await stored(controller, device_id or discovery.id)


async def stored(controller: ZwaveController, device_id: UUID) -> ZwaveDevice:
    async with controller.dependencies.make_device_repository() as repo:
        device = await repo.get(device_id, as_=ZwaveDevice)
    assert device is not None, f"device {device_id} is not stored"
    return device


def param(device: ZwaveDevice, key: str) -> ZwaveParameter:
    """The parameter of a Z-Wave value, by its key without the node: `<cc>-<endpoint>-<property>[-<key>]`."""
    matches = [p for p in device.parameters if p.integration_data.value_id.split("-", 1)[1] == key]
    assert len(matches) == 1, (
        f"expected one parameter for {key}, got {[p.integration_data.value_id for p in device.parameters]}"
    )
    return ZwaveParameter.model_validate(matches[0].model_dump())


def changes(output: RecordingControllerOutput) -> list[DeviceParameterChange]:
    return [e for e in output.events if isinstance(e, DeviceParameterChange)]


def values(output: RecordingControllerOutput, parameter_id: UUID) -> list[Any]:
    return [e.value for e in changes(output) if e.parameter_id == parameter_id]


async def wait_for_value(
    output: RecordingControllerOutput,
    parameter: ZwaveParameter,
    predicate: Callable[[Any], bool],
    timeout: float = 10.0,
) -> Any:
    await wait_until(
        lambda: any(predicate(v) for v in values(output, parameter.id)),
        timeout,
        f"a value of {parameter.name} (seen: {values(output, parameter.id)})",
    )
    return next(v for v in reversed(values(output, parameter.id)) if predicate(v))


async def command(controller: ZwaveController, device: ZwaveDevice, parameter: ZwaveParameter, value: Any) -> None:
    await controller.send_command(
        DeviceCommand(device_id=device.id, parameter_id=parameter.id, value=value), device, parameter
    )


PYTHON_TYPES: dict[ParameterDataType, tuple[type, ...]] = {
    ParameterDataType.bool: (bool,),
    ParameterDataType.integer: (int,),
    ParameterDataType.decimal: (int, float),
    ParameterDataType.enum: (int,),
    ParameterDataType.string: (str,),
}


def assert_values_match_parameters(output: RecordingControllerOutput, device: ZwaveDevice) -> None:
    """Every reported value has the type its parameter declares, and lies within its limits."""
    by_id = {p.id: p for p in device.parameters}
    for change in changes(output):
        parameter = by_id.get(change.parameter_id)
        assert parameter is not None, f"event for unknown parameter {change.parameter_id}"
        if change.value is None or parameter.data_type not in PYTHON_TYPES:
            continue
        assert isinstance(change.value, PYTHON_TYPES[parameter.data_type]), (
            f"{parameter.name}: {change.value!r} is not {parameter.data_type}"
        )
        if parameter.data_type is not ParameterDataType.bool and isinstance(change.value, int | float):
            assert parameter.min_value is None or change.value >= parameter.min_value, (
                f"{parameter.name}: {change.value}"
            )
            assert parameter.max_value is None or change.value <= parameter.max_value, (
                f"{parameter.name}: {change.value}"
            )
        if parameter.data_type is ParameterDataType.enum:
            assert parameter.valid_values and change.value in parameter.valid_values, (
                f"{parameter.name}: {change.value}"
            )
