from typing import cast
from uuid import uuid4

import pytest
from majordom_integration_sdk.controller import AbstractController
from majordom_integration_sdk.schemas.device import (
    CredentialsType,
    Device,
    DeviceState,
    Discovery,
)
from majordom_integration_sdk.schemas.parameter import (
    ParameterDataType,
    ParameterRole,
    ParameterState,
    ParameterVisibility,
)
from majordom_integration_sdk.testing import (
    RecordingControllerOutput,
    build_test_dependencies,
)
from virtual_zwave_network import VirtualZwaveNetwork

from majordom_zwave import ZwaveController

INTEGRATION = "Zwave"


@pytest.fixture(scope="session")
def deps() -> AbstractController.Dependencies:
    return build_test_dependencies(integration=INTEGRATION)


@pytest.fixture(scope="session")
def output(deps: AbstractController.Dependencies) -> RecordingControllerOutput:
    # deps.output is typed as the abstract ControllerOutput; build_test_dependencies()
    # always wires the concrete RecordingControllerOutput, so this cast is safe and
    # gives tests access to its recorded fields (.events, .connected_devices, ...).
    return cast(RecordingControllerOutput, deps.output)


@pytest.fixture(scope="session")
def controller(deps: AbstractController.Dependencies) -> ZwaveController:
    return ZwaveController(deps)


@pytest.fixture(autouse=True)
def virtual_zwave():
    # autouse: any test calling controller.start() needs this active, even if
    # it never touches nodes directly (otherwise it hits a real socket).
    with VirtualZwaveNetwork() as net:
        yield net


async def _seed(deps: AbstractController.Dependencies, device: DeviceState) -> None:
    async with deps.make_device_repository() as repo:
        await repo.save(device)


@pytest.fixture
def discovery() -> Discovery:
    return Discovery(
        id=uuid4(),
        integration=INTEGRATION,
        expected_credentials_options=[CredentialsType.none],
        transport="wifi",
        device_manufacturer="ACME",
        device_name="Zwave Lamp",
        device_category=None,
        device_icon=None,
    )


@pytest.fixture
def make_provisional_device(deps: AbstractController.Dependencies):
    async def _factory(discovery: Discovery) -> DeviceState:
        # parameters=[] on purpose: a placeholder param here needs Zwave-specific
        # integration_data (not None), or pair_device's re-read as ZwaveDeviceState
        # fails validation. Pairing is what maps and persists real parameters.
        device = DeviceState(
            id=discovery.id,
            name="Living Room Lamp",
            room_id=uuid4(),
            transport=discovery.transport,
            integration=INTEGRATION,
            manufacturer=discovery.device_manufacturer,
            parameters=[],
        )
        await _seed(deps, device)
        return device

    return _factory


@pytest.fixture
async def device_state(deps: AbstractController.Dependencies) -> DeviceState:
    power = ParameterState(
        id=uuid4(),
        name="Power",
        data_type=ParameterDataType.bool,
        role=ParameterRole.control,
        visibility=ParameterVisibility.user,
        integration_data=None,
        value=True,
    )
    state = DeviceState(
        id=uuid4(),
        name="Living Room Lamp",
        room_id=uuid4(),
        transport="wifi",
        integration=INTEGRATION,
        manufacturer="ACME",
        parameters=[power],
    )
    await _seed(deps, state)
    return state


@pytest.fixture
def device(device_state: DeviceState) -> Device:
    return Device.model_validate(device_state.model_dump())


@pytest.fixture
def parameter(device_state: DeviceState) -> ParameterState:
    return device_state.parameters[0]
