"""Z-Wave values → MajorDom parameters, and value conversion both ways.

A parameter is one Z-Wave value, except for current/target pairs (`currentValue`/`targetValue`,
`currentMode`/`targetMode`, ...): those are one parameter, commanded through the target and reporting the
current one, so the user sees one switch rather than a "Current value" sensor next to a "Target value" control.
"""

from typing import Any

from majordom_integration_sdk.schemas.parameter import (
    ParameterDataType,
    ParameterRole,
    ParameterUnit,
    ParameterVisibility,
)
from zwave_js_server.const import CommandClass
from zwave_js_server.model.duration import Duration
from zwave_js_server.model.node import Node
from zwave_js_server.model.value import AllowedRangeValue, Value, ValueType

from .zwave_spec import (
    CONVERTED_UNITS,
    DECIMAL_COMMAND_CLASSES,
    DIAGNOSTIC_COMMAND_CLASSES,
    EVENT_COMMAND_CLASSES,
    LEVEL_COMMAND_CLASSES,
    LEVEL_PROPERTIES,
    MAIN_VALUE_BY_COMMAND_CLASS,
    SYSTEM_COMMAND_CLASSES,
    UNIT_MAP,
)


def parameter_values(node: Node) -> list[tuple[Value, Value | None]]:
    """(value commanded and identifying the parameter, value its state comes from when another one) per parameter."""
    states = {target.value_id: current for target in node.values.values() if (current := _current_of(node, target))}
    merged = {current.value_id for current in states.values()}
    return [(value, states.get(value.value_id)) for value in node.values.values() if value.value_id not in merged]


def reported_parameters(node: Node) -> dict[str, str | None]:
    """Value id → the value id of the parameter it reports, None for a target whose state comes from its current."""
    routes: dict[str, str | None] = {}
    for value, state in parameter_values(node):
        routes[value.value_id] = None if state else value.value_id
        if state:
            routes[state.value_id] = value.value_id
    return routes


def _current_of(node: Node, target: Value) -> Value | None:
    prop = target.property_
    if not isinstance(prop, str) or not prop.startswith("target") or prop == "target":
        return None
    current = f"current{prop.removeprefix('target')}"
    return next(
        (
            v
            for v in node.values.values()
            if v.command_class == target.command_class
            and v.endpoint == target.endpoint
            and v.property_ == current
            and v.property_key == target.property_key
        ),
        None,
    )


def name(value: Value, state: Value | None) -> str:
    base = value.command_class_name if state else value.metadata.label or value.property_name or str(value.property_)
    return f"{base} {value.endpoint}" if value.endpoint else base


def _is_level(value: Value) -> bool:
    return value.command_class in LEVEL_COMMAND_CLASSES and value.property_ in LEVEL_PROPERTIES


def _is_duration(value: Value) -> bool:
    # zwave-js-server-python's ValueType has no "duration": it is told by the metadata type string or the property
    return value.metadata.type == "duration" or value.property_ == "duration"


def data_type(value: Value) -> ParameterDataType:
    metadata = value.metadata
    if metadata.type == ValueType.BOOLEAN:
        return ParameterDataType.bool
    if metadata.type == ValueType.STRING or metadata.type == "color" or _is_duration(value):
        return ParameterDataType.string
    if metadata.type == ValueType.NUMBER:
        if metadata.states and not metadata.allow_manual_entry:
            return ParameterDataType.enum
        return (
            ParameterDataType.decimal if value.command_class in DECIMAL_COMMAND_CLASSES else ParameterDataType.integer
        )
    raw = value.value  # ValueType.ANY: only the value itself tells
    if isinstance(raw, bool):
        return ParameterDataType.bool
    if isinstance(raw, int):
        return ParameterDataType.integer
    if isinstance(raw, float):
        return ParameterDataType.decimal
    if isinstance(raw, str):
        return ParameterDataType.string
    return ParameterDataType.data  # an opaque CC-specific object: exposed as data rather than a guessed shape


def role(value: Value) -> ParameterRole:
    if value.command_class in EVENT_COMMAND_CLASSES or value.metadata.stateful is False:
        return ParameterRole.event
    return ParameterRole.control if value.metadata.writeable else ParameterRole.sensor


def visibility(value: Value, node: Node) -> ParameterVisibility:
    command_class = value.command_class
    if (
        command_class in SYSTEM_COMMAND_CLASSES
        or value.metadata.secret
        or _is_duration(value)
        or data_type(value) == ParameterDataType.data
        or (command_class == CommandClass.BASIC and _has_other_application_values(node))
    ):
        return ParameterVisibility.system
    if command_class in DIAGNOSTIC_COMMAND_CLASSES:
        return ParameterVisibility.setting
    return ParameterVisibility.user


def _has_other_application_values(node: Node) -> bool:
    """Basic CC only mirrors the device's real CCs (for old controllers): shown only when nothing else is."""
    ignored = SYSTEM_COMMAND_CLASSES | DIAGNOSTIC_COMMAND_CLASSES | {CommandClass.BASIC}
    return any(v.command_class not in ignored for v in node.values.values())


def unit(value: Value) -> ParameterUnit:
    if _is_level(value):
        return ParameterUnit.percentage
    raw = value.metadata.unit or ""
    if raw in CONVERTED_UNITS:
        return CONVERTED_UNITS[raw][0]
    return UNIT_MAP.get(raw, ParameterUnit.plain)


def limits(value: Value) -> tuple[Any, Any, Any]:
    """(min, max, step) in MajorDom's units."""
    if data_type(value) not in (ParameterDataType.integer, ParameterDataType.decimal):
        return None, None, None
    if _is_level(value):
        return 0, 100, 1
    step = next((a.step for a in value.metadata.allowed or [] if isinstance(a, AllowedRangeValue) and a.step), None)
    return to_hub(value, value.metadata.min), to_hub(value, value.metadata.max), step


def valid_values(value: Value) -> dict[int | float | str, str] | None:
    """Enum labels: zwave-js `states` (`{"0": "Off"}`), keyed by the integer the value takes."""
    if data_type(value) != ParameterDataType.enum or not value.metadata.states:
        return None
    result: dict[int | float | str, str] = {}
    for key, label in value.metadata.states.items():
        try:
            result[int(key)] = label
        except ValueError:
            result[key] = label
    return result


def to_hub(value: Value, raw: Any) -> Any:
    """A value as the device reports it → as MajorDom expresses it."""
    if _is_duration(value):
        return str(Duration(raw)) if raw is not None else "unknown"
    if raw is None or isinstance(raw, bool) or not isinstance(raw, int | float):
        return raw
    if _is_level(value):
        return 100 if raw == 99 else int(raw)  # 99 is fully on; above it are special values (255: last level)
    converted = CONVERTED_UNITS.get(value.metadata.unit or "")
    if converted:
        _, factor, offset = converted
        return round(raw * factor + offset, 2)
    return raw


def to_device(value: Value, hub: Any) -> Any:
    """A value as MajorDom commands it → as the device takes it."""
    if hub is None or isinstance(hub, bool) or not isinstance(hub, int | float):
        return hub
    if _is_level(value):
        return 99 if hub >= 99 else int(hub)
    converted = CONVERTED_UNITS.get(value.metadata.unit or "")
    if converted:
        _, factor, offset = converted
        return round((hub - offset) / factor, 2)
    return hub


def main_value(node: Node) -> tuple[Value, Any] | None:
    """The value of the device's one-tap action and what a tap sends, by MAIN_VALUE_BY_COMMAND_CLASS priority."""
    for command_class, spec in MAIN_VALUE_BY_COMMAND_CLASS.items():
        for value in node.values.values():
            if value.command_class == command_class and value.property_ == spec.property_name:
                return value, spec.default_value
    return None
