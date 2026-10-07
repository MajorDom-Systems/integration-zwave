"""Z-Wave values → MajorDom parameters, and value conversion both ways.

A parameter is one Z-Wave value, except for current/target pairs (`currentValue`/`targetValue`,
`currentMode`/`targetMode`, ...): those are one parameter, commanded through the target and reporting the
current one, so the user sees one switch rather than a "Current value" sensor next to a "Target value" control.
"""

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from majordom_integration_sdk.schemas.parameter import (
    ParameterDataType,
    ParameterRole,
    ParameterUnit,
    ParameterVisibility,
)
from zwave_js_server.const import CommandClass
from zwave_js_server.const.command_class.multilevel_switch import MultilevelSwitchCommand
from zwave_js_server.model.duration import Duration
from zwave_js_server.model.node import Node
from zwave_js_server.model.notification import (
    BatteryNotification,
    EntryControlNotification,
    MultilevelSwitchNotification,
    NotificationNotification,
    PowerLevelNotification,
)
from zwave_js_server.model.value import AllowedRangeValue, Value, ValueType

from .zwave_spec import (
    CONVERTED_UNITS,
    DECIMAL_COMMAND_CLASSES,
    DIAGNOSTIC_COMMAND_CLASSES,
    EVENT_COMMAND_CLASSES,
    LEVEL_COMMAND_CLASSES,
    LEVEL_PROPERTIES,
    MAIN_VALUE_BY_COMMAND_CLASS,
    METER_QUANTITIES,
    NOTIFICATION_SETTING_VARIABLES,
    NOTIFICATION_SHARED_VARIABLES,
    NUMERIC_VALUES,
    PLAIN_UNITS,
    REVIEWED_COMMAND_CLASSES,
    SETTING_VALUES,
    SYSTEM_COMMAND_CLASSES,
    SYSTEM_VALUES,
    UNIT_MAP,
    USER_VALUES,
    VALUE_NAMES,
    VALUE_UNITS,
)

log = logging.getLogger(__name__)

# zwave-js's value metadata types (ValueType in @zwave-js/core); test_catalogue fails when it gains one
KNOWN_VALUE_TYPES = frozenset(
    {
        "number",
        "boolean",
        "string",
        "number[]",
        "boolean[]",
        "string[]",
        "duration",
        "timeout",
        "color",
        "buffer",
        "any",
    }
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


def _sentence(text: str) -> str:
    """'Warm White' → 'Warm white': the words after the first in lower case, acronyms (CO, RGB) as they are."""
    first, *rest = text.split(" ")
    return " ".join([first, *(word if sum(c.isupper() for c in word) > 1 else word.lower() for word in rest)])


def _readable(text: str) -> str:
    """A camelCase word ("wakeUpInterval", "UnsecuredWithTimeout") → words; anything else as it is."""
    if " " in text or not re.search(r"[a-z][A-Z]", text):
        return text
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[a-z])(?=[0-9])", " ", text)
    return _sentence(words[0].upper() + words[1:])


def _clean(label: str) -> str:
    """zwave-js labels written for its UI or logs → a parameter's name."""
    if match := re.fullmatch(r"Sensor state \((.+)\)", label):  # Binary Sensor: "Sensor state (Motion)"
        return _sentence(match[1])
    if label == "Reset accumulated values":  # Meter: every scale's reset at once
        return "Reset all meters"
    if match := re.fullmatch(r"Setpoint \((.+)\)", label):  # "Setpoint (Heating)"
        return f"{match[1]} setpoint"
    if match := re.fullmatch(r"(Reset )?(.+) Consumption \[(.+)\]", label):  # Meter: "Electric Consumption [kWh]"
        reset, meter, scale = match.groups()
        named = f"{meter} {METER_QUANTITIES.get(scale, scale)}"
        return f"Reset {named.lower()}" if reset else named
    if match := re.fullmatch(r"(.+) - (.+)", label):  # Window Covering: "Open - Outbound Bottom"
        return f"{_sentence(match[2])}: {match[1][0].lower()}{match[1][1:]}"
    if match := re.fullmatch(r"Scene 0*(\d+)", label):  # Central Scene: "Scene 001"
        return f"Scene {match[1]}"
    if match := re.fullmatch(r"Signaling State \((.+)\)", label):  # Barrier Operator: "Signaling State (Audible)"
        return f"{match[1]} warning"
    return _sentence(_readable(label))


def name(value: Value, state: Value | None) -> str:
    key = value.property_key_name or ("" if value.property_key is None else str(value.property_key))
    template = VALUE_NAMES.get((value.command_class, value.property_, value.property_key)) or VALUE_NAMES.get(
        (value.command_class, value.property_)
    )
    if template is not None and "{key}" in template and not key:  # the CC's keyless value (all channels at once)
        template = None
    label = value.metadata.label or value.property_name or str(value.property_)
    variable = _notification_variable(value)
    if template is not None:
        base = template.format(key=_sentence(key), label=_clean(label))
    elif state:  # a pair with no name of its own: named by its CC
        base = value.command_class_name
    elif variable and variable[1] in NOTIFICATION_SHARED_VARIABLES:  # "Sensor status": of which notification type
        base = f"{variable[1]} ({_sentence(variable[0])})"
    else:
        base = _clean(label)
    return f"{base} {value.endpoint}" if value.endpoint else base


def names(pairs: list[tuple[Value, Value | None]]) -> list[str]:
    """Each parameter's name. A name several values share gets what tells them apart: a Notification variable its
    notification type ("Sensor status (Smoke Alarm)"), anything else its CC ("Remaining duration (Color Switch)")."""
    plain = [name(value, state) for value, state in pairs]
    shared = {n for n, count in Counter(plain).items() if count > 1}
    return [f"{n} ({_context(value)})" if n in shared else n for n, (value, _) in zip(plain, pairs, strict=True)]


def _notification_variable(value: Value) -> tuple[str, str] | None:
    """A Notification CC state's (notification type, variable): zwave-js's property and property key."""
    kind, variable = value.property_, value.property_key
    if value.command_class != CommandClass.NOTIFICATION or not isinstance(kind, str) or not isinstance(variable, str):
        return None
    return kind, variable


def _context(value: Value) -> str:
    variable = _notification_variable(value)
    return _sentence(variable[0]) if variable else value.command_class_name


def _is_level(value: Value) -> bool:
    return value.command_class in LEVEL_COMMAND_CLASSES and value.property_ in LEVEL_PROPERTIES


def _is_duration(value: Value) -> bool:
    # zwave-js-server-python's ValueType has no "duration": it is told by the metadata type string (not by the
    # property's name: an Alarm Sensor's "duration" is a number of seconds)
    return value.metadata.type == "duration"


def _is_button(value: Value) -> bool:
    """A write-only action ("Reset", "Identify", "Restore previous value"): its only state is `true`, the trigger.
    Start/stop pairs (`true`/`false`, like "Up"/"Down" dimming) stay booleans."""
    metadata = value.metadata
    return (
        metadata.type == ValueType.BOOLEAN
        and bool(metadata.writeable)
        and not metadata.readable
        and set(metadata.states or {}) <= {"true"}
    )


def data_type(value: Value) -> ParameterDataType:
    metadata = value.metadata
    kind = metadata.type
    if kind not in KNOWN_VALUE_TYPES:
        log.warning("[MAP] %s has the unknown value type %r: hidden as data", value.value_id, kind)
        return ParameterDataType.data
    if _is_button(value):
        return ParameterDataType.none
    if kind == ValueType.BOOLEAN:
        return ParameterDataType.bool
    if kind in ("string", "string[]", "color", "timeout") or _is_duration(value):  # a list of strings: as text
        return ParameterDataType.string
    if kind in ("number[]", "boolean[]", "buffer"):
        return ParameterDataType.data
    if kind == ValueType.NUMBER:
        if _is_level(value) or (value.command_class, value.property_) in NUMERIC_VALUES:
            return ParameterDataType.integer
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
    if value.metadata.stateful is False or (value.command_class in EVENT_COMMAND_CLASSES and not _is_setting(value)):
        return ParameterRole.event
    return ParameterRole.control if value.metadata.writeable else ParameterRole.sensor


def _is_setting(value: Value) -> bool:
    variable = _notification_variable(value)
    if variable and variable[1] in NOTIFICATION_SETTING_VARIABLES:  # a diagnostic, like "Maintenance status"
        return True
    properties = SETTING_VALUES.get(value.command_class, frozenset())
    return properties is None or value.property_ in properties


def _is_user(value: Value) -> bool:
    properties = USER_VALUES.get(value.command_class, frozenset())
    return properties is None or value.property_ in properties


def visibility(value: Value, node: Node) -> ParameterVisibility:
    command_class = value.command_class
    if (
        command_class in SYSTEM_COMMAND_CLASSES
        or (command_class, value.property_) in SYSTEM_VALUES
        or value.metadata.secret
        or _is_duration(value)
        or data_type(value) == ParameterDataType.data
        or (command_class == CommandClass.BASIC and _has_other_application_values(node))
    ):
        return ParameterVisibility.system
    if _is_setting(value):
        return ParameterVisibility.setting
    if _is_user(value):
        return ParameterVisibility.user
    if command_class in REVIEWED_COMMAND_CLASSES:
        return ParameterVisibility.setting
    return ParameterVisibility.system  # a CC nobody reviewed: hidden ("when in doubt, hide it"), still usable


def _has_other_application_values(node: Node) -> bool:
    """Basic CC only mirrors the device's real CCs (for old controllers): shown only when nothing else is."""
    ignored = SYSTEM_COMMAND_CLASSES | DIAGNOSTIC_COMMAND_CLASSES | {CommandClass.BASIC}
    return any(v.command_class not in ignored for v in node.values.values())


def unit(value: Value) -> ParameterUnit:
    if _is_level(value):
        return ParameterUnit.percentage
    if (value.command_class, value.property_) in VALUE_UNITS:
        return VALUE_UNITS[value.command_class, value.property_]
    raw = value.metadata.unit or ""
    if raw in CONVERTED_UNITS:
        return CONVERTED_UNITS[raw][0]
    if raw and raw not in UNIT_MAP and raw not in PLAIN_UNITS:
        log.warning("[MAP] %s has the unknown unit %r: reported as plain", value.value_id, raw)
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
    for key, raw in value.metadata.states.items():
        label = _readable(raw)
        if value.command_class == CommandClass.CENTRAL_SCENE:  # "Key pressed", "Key held down": a key's anyway
            label = label.removeprefix("Key ")
        label = label[:1].upper() + label[1:]  # "idle", "off" as the other labels
        try:
            result[int(key)] = label
        except ValueError:
            result[key] = label
    return result


def to_hub(value: Value, raw: Any) -> Any:
    """A value as the device reports it → as MajorDom expresses it."""
    if _is_duration(value):
        return str(Duration(raw)) if raw is not None else "unknown"
    if value.metadata.type == "timeout" and raw is not None:
        return str(raw)
    if value.metadata.type == "string[]" and isinstance(raw, list):
        return ", ".join(str(item) for item in raw)
    if raw is None or isinstance(raw, bool) or not isinstance(raw, int | float):
        return raw
    if _is_level(value):
        return 100 if raw == 99 else int(raw)  # 99 is fully on; above it are special values (255: last level)
    converted = CONVERTED_UNITS.get(value.metadata.unit or "")
    if converted:
        _, factor, offset = converted
        return round(raw * factor + offset, 6)
    return raw


def to_device(value: Value, hub: Any) -> Any:
    """A value as MajorDom commands it → as the device takes it."""
    if _is_button(value):
        return True  # a button parameter (`none`) is commanded without a value
    if hub is None or isinstance(hub, bool) or not isinstance(hub, int | float):
        return hub
    if _is_level(value):
        return 99 if hub >= 99 else int(hub)
    converted = CONVERTED_UNITS.get(value.metadata.unit or "")
    if converted:
        _, factor, offset = converted
        return round((hub - offset) / factor, 6)
    return hub


def main_value(node: Node) -> tuple[Value, Any] | None:
    """The value of the device's one-tap action and what a tap sends, by MAIN_VALUE_BY_COMMAND_CLASS priority."""
    for command_class, spec in MAIN_VALUE_BY_COMMAND_CLASS.items():
        for value in node.values.values():
            if value.command_class == command_class and value.property_ == spec.property_name:
                return value, spec.default_value
    return None


# Notifications ------------------------------------------------------------------------------------------------------
# What devices send as one-off events rather than values (zwave-js "notification" events). They have no value id, so
# their parameters get one of the same shape, `<node>-<cc>-<endpoint>-<property>`; zwave-js says which keypad and
# Notification CC events a device supports (node.get_supported_notification_events), so those are exact enums.

LEVEL_CHANGES: dict[int | float | str, str] = {0: "Stopped", 1: "Started up", 2: "Started down"}
BATTERY_REPLACEMENT: dict[int | float | str, str] = {0: "Not needed", 1: "Soon", 2: "Now"}
POWERLEVEL_TEST: dict[int | float | str, str] = {0: "Failed", 1: "Success", 2: "In progress"}


@dataclass(frozen=True)
class EventParameter:
    value_id: str
    name: str
    data_type: ParameterDataType
    visibility: ParameterVisibility
    unit: ParameterUnit = ParameterUnit.plain
    valid_values: dict[int | float | str, str] | None = None


def _labels(supported: dict[str, str]) -> dict[int | float | str, str]:
    return {int(key): label for key, label in supported.items()}


def event_parameters(node: Node, supported: list[dict[str, Any]]) -> list[EventParameter]:
    """The event parameters of what a node sends as notifications; `supported`: its supported notification events."""

    def value_id(command_class: int, endpoint: int, prop: str) -> str:
        return f"{node.node_id}-{command_class}-{endpoint}-{prop}"

    def named(name: str, endpoint: int) -> str:
        return f"{name} {endpoint}" if endpoint else name

    events: list[EventParameter] = []
    for capability in supported:
        command_class, endpoint = capability["commandClass"], capability["endpoint"]
        if command_class == CommandClass.ENTRY_CONTROL:
            events += [
                EventParameter(
                    value_id(command_class, endpoint, "event"),
                    named("Keypad", endpoint),
                    ParameterDataType.enum,
                    ParameterVisibility.user,
                    valid_values=_labels(capability["supportedEventTypes"]),
                ),
                # what was typed with it: for automations (checking a code), never shown
                EventParameter(
                    value_id(command_class, endpoint, "code"),
                    named("Keypad code", endpoint),
                    ParameterDataType.string,
                    ParameterVisibility.system,
                ),
            ]
        elif command_class == CommandClass.NOTIFICATION:
            for kind, notification in capability["supportedNotificationTypes"].items():
                label = _sentence(notification["label"])
                events += [
                    EventParameter(
                        value_id(command_class, endpoint, f"event-{kind}"),
                        named(f"{label} event", endpoint),
                        ParameterDataType.enum,
                        ParameterVisibility.user,
                        valid_values=_labels(notification["supportedEvents"]),
                    ),
                    # what came with it (a user id, a code...): for automations, never shown
                    EventParameter(
                        value_id(command_class, endpoint, f"details-{kind}"),
                        named(f"{label} event details", endpoint),
                        ParameterDataType.string,
                        ParameterVisibility.system,
                        ParameterUnit.json,
                    ),
                ]
    for endpoint in node.endpoints.values():
        supports = {info.id for info in endpoint.command_classes}
        if CommandClass.SWITCH_MULTILEVEL in supports:  # dimming started or stopped on the device (or a remote) itself
            events.append(
                EventParameter(
                    value_id(CommandClass.SWITCH_MULTILEVEL, endpoint.index, "levelChange"),
                    named("Level change", endpoint.index),
                    ParameterDataType.enum,
                    ParameterVisibility.system,  # for automations (a remote's dimming), not a state to show
                    valid_values=LEVEL_CHANGES,
                )
            )
        if CommandClass.BATTERY in supports:  # "battery low"
            events.append(
                EventParameter(
                    value_id(CommandClass.BATTERY, endpoint.index, "replacement"),
                    named("Battery replacement", endpoint.index),
                    ParameterDataType.enum,
                    ParameterVisibility.user,  # "replace the battery": what people need to see
                    valid_values=BATTERY_REPLACEMENT,
                )
            )
        if CommandClass.POWERLEVEL in supports:  # a radio test's result, when one is run
            events.append(
                EventParameter(
                    value_id(CommandClass.POWERLEVEL, endpoint.index, "test"),
                    named("Powerlevel test", endpoint.index),
                    ParameterDataType.enum,
                    ParameterVisibility.setting,
                    valid_values=POWERLEVEL_TEST,
                )
            )
    return events


def notification_events(notification: Any) -> list[tuple[str, Any]]:
    """A notification → (value id of its event parameter, value) for each of its parameters it reports."""

    def value_id(prop: str) -> str:
        return f"{notification.node_id}-{notification.command_class}-{notification.endpoint_idx}-{prop}"

    if isinstance(notification, EntryControlNotification):
        events: list[tuple[str, Any]] = [(value_id("event"), notification.event_type)]
        if notification.event_data not in (None, ""):
            data = notification.event_data
            events.append((value_id("code"), data if isinstance(data, str) else json.dumps(data, sort_keys=True)))
        return events
    if isinstance(notification, NotificationNotification):
        events = [(value_id(f"event-{notification.type_}"), notification.event)]
        if notification.parameters:
            events.append(
                (value_id(f"details-{notification.type_}"), json.dumps(notification.parameters, sort_keys=True))
            )
        return events
    if isinstance(notification, MultilevelSwitchNotification):
        started = notification.event_type == MultilevelSwitchCommand.START_LEVEL_CHANGE
        change = (1 if notification.direction == "up" else 2) if started else 0
        return [(value_id("levelChange"), change)]
    if isinstance(notification, BatteryNotification):
        return [(value_id("replacement"), int(notification.urgency))]
    if isinstance(notification, PowerLevelNotification):
        return [(value_id("test"), int(notification.status))]
    return []
