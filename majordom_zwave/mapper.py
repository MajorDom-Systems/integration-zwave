from typing import Any
from uuid import UUID, NAMESPACE_DNS, uuid5

from majordom_integration_sdk.schemas.parameter import ParameterDataType, ParameterRole, ParameterUnit, ParameterVisibility
from zwave_js_server.model.duration import Duration
from zwave_js_server.model.node import Node
from zwave_js_server.model.value import AllowedRangeValue, Value, ValueMetadata, ValueType

from .zwave_spec import (
    DIAGNOSTIC_COMMAND_CLASSES,
    EVENT_COMMAND_CLASSES,
    MAIN_VALUE_BY_COMMAND_CLASS,
    SYSTEM_COMMAND_CLASSES,
    UNIT_MAP,
)


class ZwaveMapper:
    def device_uuid_from_node_id(self, node_id: int) -> UUID:
        return uuid5(NAMESPACE_DNS, f"device-{node_id}")

    def parameter_uuid(self, device_id: UUID, value_id: str) -> UUID:
        return uuid5(NAMESPACE_DNS, f"parameter-{device_id}-{value_id}")

    # -------------------------------------------------------------------------
    # Value metadata -> SDK parameter schema
    # -------------------------------------------------------------------------

    def get_unit(self, raw_unit: str | None) -> ParameterUnit | None:
        """Maps a raw unit string to ParameterUnit; None if not in UNIT_MAP."""
        if not raw_unit:
            return None
        return UNIT_MAP.get(raw_unit)

    def _is_duration_property(self, value: Value) -> bool:
        """True for CC-specific "duration" properties, matched by name since
        zwave-js-server-python doesn't wrap them in its Duration class."""
        return value.property_name == "duration" or value.property_ == "duration"

    def format_zwave_value(self, value: Value) -> Any:
        """Formats a raw value to match parse_zwave_data_type() — keep in sync."""
        if self._is_duration_property(value):
            # None means "unknown" here; Duration itself expects the string "unknown".
            return str(Duration(value.value)) if value.value is not None else "unknown"
        return value.value

    def get_min_step(self, value: Value) -> int | float | None:
        """Step size if zwave-js reported one; most devices don't, so no default."""
        for entry in value.metadata.allowed or []:
            if isinstance(entry, AllowedRangeValue) and entry.step:
                return entry.step
        return None

    def get_role(self, command_class: int, metadata: ValueMetadata) -> ParameterRole:
        """Sensor/control/event from command class + read/write access."""
        if command_class in EVENT_COMMAND_CLASSES:
            return ParameterRole.event
        if metadata.writeable:
            return ParameterRole.control
        return ParameterRole.sensor

    def get_visibility(self, command_class: int, metadata: ValueMetadata) -> ParameterVisibility:
        """Readable -> user, writeable-only -> setting, else system; SYSTEM/DIAGNOSTIC
        command classes override this for plumbing/diagnostic values."""
        if command_class in SYSTEM_COMMAND_CLASSES:
            return ParameterVisibility.system
        if command_class in DIAGNOSTIC_COMMAND_CLASSES:
            return ParameterVisibility.setting
        if metadata.readable or metadata.writeable:
            return ParameterVisibility.user
        return ParameterVisibility.system

    def parse_zwave_data_type(self, value: Value) -> ParameterDataType:
        """Maps a Value to ParameterDataType. ValueType alone can't tell integer from
        decimal/enum, or resolve ValueType.ANY, so those fall back to the raw value."""
        metadata = value.metadata

        if metadata.type == ValueType.BOOLEAN:
            return ParameterDataType.bool
        if metadata.type == ValueType.STRING:
            return ParameterDataType.string
        if metadata.type == ValueType.NUMBER:
            if metadata.states:
                return ParameterDataType.enum
            raw = value.value
            if isinstance(raw, float) and not raw.is_integer():
                return ParameterDataType.decimal
            return ParameterDataType.integer

        # ValueType.ANY: keep in sync with format_zwave_value's duration handling.
        if self._is_duration_property(value):
            return ParameterDataType.string
        raw = value.value
        if isinstance(raw, bool):
            return ParameterDataType.bool
        if isinstance(raw, int):
            return ParameterDataType.integer
        if isinstance(raw, float):
            return ParameterDataType.decimal
        if isinstance(raw, str):
            return ParameterDataType.string
        if isinstance(raw, dict):
            return ParameterDataType.struct
        # Opaque CC-specific object — expose as data rather than guessing a shape.
        return ParameterDataType.data

    def parse_zwave_valid_values(self, metadata: ValueMetadata) -> dict[int | float | str, str] | None:
        """Converts states (`{"0": "Off"}`) to valid_values, coercing keys to int."""
        if not metadata.states:
            return None
        result: dict[int | float | str, str] = {}
        for raw_key, label in metadata.states.items():
            try:
                result[int(raw_key)] = label
            except ValueError:
                result[raw_key] = label
        return result

    def get_main_parameter(self, device_id: UUID, node: Node) -> tuple[UUID | None, bool | int | float | None]:
        """Picks the value for the device's one-tap action, by MAIN_VALUE_BY_COMMAND_CLASS
        priority. Returns (None, None) if none applies."""
        for command_class, spec in MAIN_VALUE_BY_COMMAND_CLASS.items():
            value = next(
                (
                    v
                    for v in node.values.values()
                    if v.command_class == command_class and v.property_name == spec.property_name
                ),
                None,
            )
            if value is not None:
                return self.parameter_uuid(device_id, value.value_id), spec.default_value
        return None, None