"""State: what a paired device reports, in which shape, and how it maps Z-Wave values to parameters."""

from majordom_integration_sdk.schemas.parameter import (
    ParameterDataType,
    ParameterRole,
    ParameterUnit,
    ParameterVisibility,
)
from majordom_integration_sdk.testing import RecordingControllerOutput

from majordom_zwave import ZwaveController
from tests.helpers import assert_values_match_parameters, changes, pair, param, values, wait_for_value
from tests.network import MockNetwork

SWITCH = "37-0-targetValue"
LEVEL = "38-0-targetValue"
TEMPERATURE = "49-0-Air temperature"


async def test_pairing_reports_the_current_value_of_every_readable_parameter(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "sensor")

    temperature = param(device, TEMPERATURE)
    assert values(output, temperature.id) == [21]
    assert_values_match_parameters(output, device)


async def test_changes_made_on_the_device_are_reported(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)
    switch = param(device, SWITCH)

    await network.report(5, "switch", True)  # e.g. toggled by hand

    assert await wait_for_value(output, switch, lambda v: v is True) is True


async def test_a_sensor_reading_is_a_decimal_with_its_unit(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "sensor")  # paired while reading a whole 21
    temperature = param(device, TEMPERATURE)
    assert (temperature.data_type, temperature.unit, temperature.role) == (
        ParameterDataType.decimal,
        ParameterUnit.celsius,
        ParameterRole.sensor,
    )

    await network.report(5, "sensor", 23.25)
    await wait_for_value(output, temperature, lambda v: v == 23.25)
    assert_values_match_parameters(output, device)


async def test_fahrenheit_readings_are_reported_in_celsius(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "sensor_fahrenheit")
    temperature = param(device, TEMPERATURE)

    assert temperature.unit == ParameterUnit.celsius
    assert values(output, temperature.id) == [21]  # 69.8 °F


async def test_a_level_is_a_percentage(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "dimmer")
    level = param(device, LEVEL)

    assert (level.data_type, level.unit, level.min_value, level.max_value) == (
        ParameterDataType.integer,
        ParameterUnit.percentage,
        0,
        100,
    )
    assert level.integration_data.state_value_id is not None
    assert device.main_parameter == level.id
    # a tap toggles off / fully on, within the declared range (a set: the SDK's repository round-trip returns a list)
    assert level.default_value is not None and set(level.default_value) == {0, 100}


async def test_scene_activations_are_events(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "scene")

    await network.report(5, "scene", 3)  # a scene button pressed: stateless, sent as a value notification

    scene = next(p for p in device.parameters if p.role == ParameterRole.event)
    assert await wait_for_value(output, scene, lambda v: v == 3) == 3


async def test_compatibility_and_transition_values_are_not_shown(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "sensor")
    switch = await pair(controller, output, network, 6, "switch")

    # Basic CC mirrors the real CCs for old controllers; a transition's remaining time is not a state of its own
    basic = [p for p in device.parameters if p.integration_data.value_id.split("-")[1] == "32"]
    durations = [p for p in switch.parameters if p.integration_data.value_id.endswith("-duration")]
    assert basic and durations
    assert {p.visibility for p in basic + durations} == {ParameterVisibility.system}


async def test_parameters_of_another_endpoint_are_told_apart(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "two_switches")

    names = [p.name for p in device.parameters]
    assert len(names) == len(set(names)), names
    assert {"37-1-targetValue", "37-2-targetValue"} <= {
        p.integration_data.value_id.split("-", 1)[1] for p in device.parameters
    }


async def test_fetch_reports_the_current_values(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)
    switch = param(device, SWITCH)
    output.events.clear()

    await controller.fetch(device)

    assert values(output, switch.id) == [False]
    assert {c.parameter_id for c in changes(output)} <= {p.id for p in device.parameters}
    assert_values_match_parameters(output, device)
