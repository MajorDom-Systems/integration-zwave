"""The catalogue: every command class zwave-js knows is hosted, plumbing, or explained (fast checks); one mock device
per hosted CC maps exactly as expected and round-trips every writable value (the sweep). The monthly canary runs it
against the latest zwave-js, zwave-js-server and zwave-js-server-python: new CCs, values, value types and units fail
here until they are supported or explained.
"""

import json
import logging
import re
import subprocess
from collections import Counter
from types import SimpleNamespace
from typing import Any, cast

import pytest
from majordom_integration_sdk.parameter_audit import audit_device_parameters
from majordom_integration_sdk.schemas.parameter import ParameterDataType, ParameterRole, ParameterVisibility
from majordom_integration_sdk.testing import RecordingControllerOutput
from zwave_js_server.const import CommandClass
from zwave_js_server.model.value import Value, ValueMetadata

from majordom_zwave import ZwaveController, mapper
from majordom_zwave.zwave_spec import CONVERTED_UNITS, PLAIN_UNITS, UNIT_MAP
from tests.catalogue import (
    COMMON,
    EXPECTED,
    INFRASTRUCTURE,
    MAIN,
    NEWER_THAN_THE_LIBRARY,
    NO_REPORT,
    PLUMBING,
    RECIPES,
    SIMILAR_NAMES,
    UNHOSTABLE,
    VARIANTS,
)
from tests.helpers import command, pair, values, wait_for_value
from tests.network import MOCK_DIR, MockNetwork


@pytest.fixture(scope="module")
def registry() -> dict[str, Any]:
    """What the installed zwave-js knows (tests/mock/registry.mjs)."""
    result = subprocess.run(["node", str(MOCK_DIR / "registry.mjs")], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


pytestmark = pytest.mark.usefixtures("patient")


def key(value_id: str) -> str:
    return value_id.split("-", 1)[1]


# Fast checks: what zwave-js knows is supported or explained ---------------------------------------------------------


def test_every_command_class_is_hosted_plumbing_or_explained(registry: dict[str, Any]):
    known = {int(cc): name for cc, name in registry["commandClasses"].items()}
    hosted = set().union(*RECIPES.values()) | INFRASTRUCTURE
    unexplained = {
        f"{name} (0x{cc:02x})" for cc, name in known.items() if cc not in hosted | PLUMBING | UNHOSTABLE.keys()
    }
    assert not unexplained, (
        f"new command classes {sorted(unexplained)}: write a recipe (tests/mock/catalogue.mjs, tests/catalogue.py), "
        "or say in tests/catalogue.py why the mock network cannot host it"
    )
    assert not hosted & UNHOSTABLE.keys(), "a hosted CC is listed as unhostable"


def test_command_classes_newer_than_the_library_are_known(registry: dict[str, Any]):
    library = {int(cc) for cc in CommandClass}
    newer = {int(cc) for cc in registry["commandClasses"]} - library
    assert newer <= NEWER_THAN_THE_LIBRARY.keys(), (
        f"zwave-js knows CCs zwave-js-server-python does not: {sorted(hex(cc) for cc in newer)}"
    )


def test_every_value_type_is_mapped(registry: dict[str, Any]):
    assert set(registry["valueTypes"]) == mapper.KNOWN_VALUE_TYPES, (
        "zwave-js's value metadata types changed: map the new ones in mapper.data_type"
    )


def test_every_unit_is_mapped_converted_or_deliberately_plain(registry: dict[str, Any]):
    handled = UNIT_MAP.keys() | CONVERTED_UNITS.keys() | PLAIN_UNITS
    assert set(registry["units"]) <= handled, (
        f"new units {sorted(set(registry['units']) - handled)}: map, convert, or list them in zwave_spec.PLAIN_UNITS"
    )


def test_the_catalogue_tables_agree(registry: dict[str, Any]):
    assert set(registry["recipes"]) >= RECIPES.keys() | VARIANTS.keys(), "a recipe is missing in catalogue.mjs"
    assert EXPECTED.keys() == RECIPES.keys()
    assert MAIN.keys() <= RECIPES.keys()


# Value shapes, for the CCs the mock network cannot host --------------------------------------------------------------


def shape(metadata: dict[str, Any], value: Any = None, command_class: int = 0x99) -> Value:
    """A value of a CC with no mock, with the given metadata: only what the mapper reads."""
    stand_in = SimpleNamespace(
        value_id=f"5-{command_class}-0-value",
        command_class=command_class,
        endpoint=0,
        property_="value",
        property_key=None,
        property_name="value",
        value=value,
        metadata=ValueMetadata(cast(Any, {"readable": True, "writeable": False, **metadata})),
    )
    return cast(Value, stand_in)


@pytest.mark.parametrize(
    ("metadata", "value", "data_type"),
    [
        ({"type": "number"}, 4, ParameterDataType.integer),
        ({"type": "number", "states": {"0": "Off", "1": "On"}}, 0, ParameterDataType.enum),
        ({"type": "number", "states": {"0": "Off"}, "allowManualEntry": True}, 0, ParameterDataType.integer),
        ({"type": "boolean"}, True, ParameterDataType.bool),
        (
            {"type": "boolean", "readable": False, "writeable": True, "states": {"true": "Go"}},
            None,
            ParameterDataType.none,
        ),
        ({"type": "string"}, "text", ParameterDataType.string),
        ({"type": "color"}, "ff0000", ParameterDataType.string),
        ({"type": "duration"}, {"value": 2, "unit": "seconds"}, ParameterDataType.string),
        ({"type": "timeout"}, {"value": 2, "unit": "seconds"}, ParameterDataType.string),
        ({"type": "number[]"}, [1, 2], ParameterDataType.data),
        ({"type": "boolean[]"}, [True], ParameterDataType.data),
        ({"type": "string[]"}, ["a"], ParameterDataType.string),  # shown as text: "1.0, 2.3"
        ({"type": "buffer"}, "AQI=", ParameterDataType.data),
        ({"type": "any"}, 1.5, ParameterDataType.decimal),
        ({"type": "any"}, {"a": 1}, ParameterDataType.data),
    ],
)
def test_every_value_shape_maps(metadata: dict[str, Any], value: Any, data_type: ParameterDataType):
    mapped = shape(metadata, value)
    assert mapper.data_type(mapped) == data_type
    if data_type == ParameterDataType.data:
        assert mapper.visibility(mapped, cast(Any, SimpleNamespace(values={}))) == ParameterVisibility.system


def test_a_command_class_nobody_reviewed_is_hidden_but_kept():
    """ "When in doubt, hide it": a value of a CC not in the catalogue is `system` (automations and the API still see
    it); the same value of a reviewed CC is a `setting`."""
    node = cast(Any, SimpleNamespace(values={}))
    reading = {"type": "number", "label": "Reading"}
    irrigation, configuration = 0x6B, 0x70
    assert mapper.visibility(shape(reading, 4, command_class=irrigation), node) == ParameterVisibility.system
    assert mapper.visibility(shape(reading, 4, command_class=configuration), node) == ParameterVisibility.setting


def test_an_unknown_value_type_is_hidden_and_logged(caplog: pytest.LogCaptureFixture):
    mapped = shape({"type": "quaternion"}, [1, 0, 0, 0])
    with caplog.at_level(logging.WARNING):
        assert mapper.data_type(mapped) == ParameterDataType.data
    assert "quaternion" in caplog.text


def test_an_unknown_unit_is_plain_and_logged(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING):
        assert mapper.unit(shape({"type": "number", "unit": "furlongs"}, 1)) == "plain"
    assert "furlongs" in caplog.text


# The sweep: one mock device per hosted CC ----------------------------------------------------------------------------


@pytest.mark.parametrize("recipe", sorted(RECIPES))
async def test_every_hosted_command_class_maps_as_expected(
    recipe: str, controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, recipe)

    mapped = {
        key(p.integration_data.value_id): (p.name, p.data_type, p.role, p.visibility, p.unit) for p in device.parameters
    }
    expected = {**COMMON, **EXPECTED[recipe]}
    differences = {
        k: (mapped.get(k), expected.get(k)) for k in mapped.keys() | expected.keys() if mapped.get(k) != expected.get(k)
    }
    assert not differences, "value: (mapped, expected)\n" + "\n".join(f"  {k}: {v}" for k, v in differences.items())

    main = next((key(p.integration_data.value_id) for p in device.parameters if p.id == device.main_parameter), None)
    assert main == MAIN.get(recipe)
    # the SDK's advisory audit: no over-exposed device screen, no near-duplicate user names
    assert not audit_device_parameters(recipe, device.parameters, ignore_similar_pairs=SIMILAR_NAMES)
    assert_readable(device)


@pytest.mark.parametrize("recipe", sorted(VARIANTS))
async def test_every_variant_maps_by_its_rules(
    recipe: str, controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, recipe)
    minimum, rules = VARIANTS[recipe]

    checked = 0
    for parameter in device.parameters:
        k = key(parameter.integration_data.value_id)
        rule = next((r for pattern, r in rules.items() if re.fullmatch(pattern, k)), None)
        if rule is None:
            continue
        data_type, role, visibilities, unit = rule
        assert (parameter.data_type, parameter.role) == (data_type, role), f"{k}: {parameter}"
        assert parameter.visibility in visibilities, f"{k}: {parameter.visibility}"
        assert unit is None or parameter.unit == unit, f"{k}: {parameter.unit}"
        checked += 1
    assert checked >= minimum
    assert_readable(device)


def assert_readable(device: Any) -> None:
    """Names and enum labels are for people: unique, without zwave-js's protocol wording, words not camelCase."""
    names = Counter(p.name for p in device.parameters)
    assert not [n for n, count in names.items() if count > 1], f"parameters share a name: {names}"
    for parameter in device.parameters:
        assert parameter.name.strip(), parameter
        assert not re.search(r"\[|Consumption|Sensor state|Setpoint \(|\(Notification\)", parameter.name), (
            parameter.name
        )
        assert not re.fullmatch(r"\S*[a-z][A-Z]\S*", parameter.name), parameter.name
        for label in (parameter.valid_values or {}).values():
            assert not re.fullmatch(r"\S*([a-z][A-Z]|[a-z][0-9])\S*", label), label
            assert not label[:1].islower(), label


def new_value(parameter: Any, current: Any) -> Any:
    """A valid value other than the current one."""
    if parameter.data_type == ParameterDataType.bool:
        return not current
    if parameter.data_type == ParameterDataType.enum:
        return next(v for v in sorted(parameter.valid_values, reverse=True) if v != current)
    middle = (parameter.min_value + parameter.max_value) / 2  # inside the range: some devices refuse its ends
    if parameter.data_type == ParameterDataType.integer:
        middle = round(middle)
    return middle if middle != current else middle + 1


@pytest.mark.parametrize("recipe", sorted(RECIPES))
async def test_every_writable_value_round_trips_through_the_device(
    recipe: str, controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, recipe)

    for parameter in device.parameters:
        k = key(parameter.integration_data.value_id)
        if parameter.role != ParameterRole.control or parameter.visibility == ParameterVisibility.system:
            continue
        if parameter.data_type == ParameterDataType.none:  # a button: it is sent, nothing comes back
            await command(controller, device, parameter, None)
            continue
        if k in NO_REPORT or parameter.data_type not in (
            ParameterDataType.bool,
            ParameterDataType.integer,
            ParameterDataType.decimal,
            ParameterDataType.enum,
        ):
            continue
        reported = values(output, parameter.id)
        if not reported:  # write-only (start/stop a movement): no state to come back
            continue
        target = new_value(parameter, reported[-1])
        await command(controller, device, parameter, target)
        # the device's report, or zwave-js's own check of the value ~5 s after an unsupervised set
        await wait_for_value(output, parameter, lambda v, t=target: v == t, timeout=10)
