"""Static Z-Wave classification data.

Unlike Zigbee, zwave-js already reports `min`/`max`/`unit`/`states` directly on `ValueMetadata`,
so this module only needs to cover what the wire format *doesn't* give us: which command classes
are protocol plumbing or diagnostics-only, which report decimals or levels, how to normalize zwave-js's
unit strings, and which property is a device's one-tap "main" action.

Pure data only — the functions that use these tables live in mapper.py.
"""

from dataclasses import dataclass

from majordom_integration_sdk.schemas.parameter import ParameterUnit
from zwave_js_server.const import CommandClass

# Protocol/network plumbing: never shown to the user, regardless of read/write access.
# (association & multi channel wiring, security/transport encapsulation, inclusion, S2, etc.)
SYSTEM_COMMAND_CLASSES: frozenset[CommandClass] = frozenset(
    {
        CommandClass.NO_OPERATION,
        CommandClass.CONTROLLER_REPLICATION,
        CommandClass.APPLICATION_STATUS,
        CommandClass.ZIP,
        CommandClass.NETWORK_MANAGEMENT_INCLUSION,
        CommandClass.NETWORK_MANAGEMENT_BASIC,
        CommandClass.NETWORK_MANAGEMENT_PROXY,
        CommandClass.NETWORK_MANAGEMENT_PRIMARY,
        CommandClass.NETWORK_MANAGEMENT_INSTALLATION_MAINTENANCE,
        CommandClass.TRANSPORT_SERVICE,
        CommandClass.CRC_16_ENCAP,
        CommandClass.APPLICATION_CAPABILITY,
        CommandClass.ASSOCIATION,
        CommandClass.ASSOCIATION_GRP_INFO,
        CommandClass.MULTI_CHANNEL,
        CommandClass.MULTI_CHANNEL_ASSOCIATION,
        CommandClass.MULTI_CMD,
        CommandClass.SUPERVISION,
        CommandClass.ZWAVEPLUS_INFO,
        CommandClass.INCLUSION_CONTROLLER,
        CommandClass.NODE_NAMING,
        CommandClass.NODE_PROVISIONING,
        CommandClass.MANUFACTURER_PROPRIETARY,
        CommandClass.PROPRIETARY,
        CommandClass.SECURITY,
        CommandClass.SECURITY_2,
        CommandClass.SECURITY_SCHEME0_MARK,
        CommandClass.MARK,
        CommandClass.TIME,
        CommandClass.TIME_PARAMETERS,
        CommandClass.CLOCK,
        CommandClass.GEOGRAPHIC_LOCATION,
        CommandClass.FIRMWARE_UPDATE_MD,
        CommandClass.GROUPING_NAME,
        CommandClass.REMOTE_ASSOCIATION_ACTIVATE,
        CommandClass.REMOTE_ASSOCIATION,
        CommandClass.SCREEN_MD,
        CommandClass.SCREEN_ATTRIBUTES,
        CommandClass.DEVICE_RESET_LOCALLY,
    }
)

# Technically readable/reportable, but the "settings/advanced" kind of reading (battery %,
# firmware version, RSSI-ish diagnostics, wake-up interval) rather than a main everyday control.
# ParameterVisibility.setting explicitly covers this case per its docstring.
DIAGNOSTIC_COMMAND_CLASSES: frozenset[CommandClass] = frozenset(
    {
        CommandClass.BATTERY,
        CommandClass.VERSION,
        CommandClass.MANUFACTURER_SPECIFIC,
        CommandClass.POWERLEVEL,
        CommandClass.WAKE_UP,
        CommandClass.INDICATOR,
        CommandClass.PROTECTION,
        CommandClass.CONFIGURATION,  # device settings behind an "advanced" tap, not main interaction
    }
)

# CCs that report one-shot occurrences (button presses, scene activations) rather than a state — modeled as
# ParameterRole.event. zwave-js marks such values `stateful: false` and sends them as "value notification".
# Notification CC is not one: zwave-js models its variables as states with an idle value.
EVENT_COMMAND_CLASSES: frozenset[CommandClass] = frozenset(
    {
        CommandClass.CENTRAL_SCENE,
        CommandClass.SCENE_ACTIVATION,
    }
)

# Values these CCs report are scaled decimals by spec (a reading of 21.0 is still a decimal), so the type does not
# depend on the value seen at pairing
DECIMAL_COMMAND_CLASSES: frozenset[CommandClass] = frozenset(
    {
        CommandClass.SENSOR_MULTILEVEL,
        CommandClass.METER,
        CommandClass.THERMOSTAT_SETPOINT,
        CommandClass.ENERGY_PRODUCTION,
        CommandClass.HUMIDITY_CONTROL_SETPOINT,
    }
)

# Levels 0-99 (99 is fully on) are percentages in MajorDom, as with Matter, Zigbee and ESPHome: 0-98 stay, 99 is 100
LEVEL_COMMAND_CLASSES: frozenset[CommandClass] = frozenset({CommandClass.SWITCH_MULTILEVEL, CommandClass.BASIC})
LEVEL_PROPERTIES: frozenset[str] = frozenset({"currentValue", "targetValue"})

# zwave-js's ValueMetadata.unit is the unit string of the CC's scale (packages/core/src/registries/Scales.ts and
# Meters.ts) — map the ones MajorDom has a unit for, leave the rest `plain` rather than guessed.
UNIT_MAP: dict[str, ParameterUnit] = {
    "%": ParameterUnit.percentage,
    "s": ParameterUnit.second,
    "Hz": ParameterUnit.hertz,
    "kg": ParameterUnit.kilogram,
    "°": ParameterUnit.arcdegree,
    "m": ParameterUnit.meters,
    "m/s": ParameterUnit.mps,
    "m/s²": ParameterUnit.mps2,
    "rpm": ParameterUnit.rpm,
    "N": ParameterUnit.newton,
    "J": ParameterUnit.joule,
    "kWh": ParameterUnit.kwh,
    "W": ParameterUnit.watt,
    "°C": ParameterUnit.celsius,
    "K": ParameterUnit.kelvin,
    "V": ParameterUnit.volt,
    "A": ParameterUnit.ampere,
    "lx": ParameterUnit.lux,
    "Lux": ParameterUnit.lux,
    "Pa": ParameterUnit.pascal,
    "ppm": ParameterUnit.ppm,
    "µg/m³": ParameterUnit.ugm3,
    "b": ParameterUnit.bytes,
    "B": ParameterUnit.bytes,
}

# Units MajorDom has no unit for, converted to one it has: (unit, factor, offset), hub value = raw * factor + offset
CONVERTED_UNITS: dict[str, tuple[ParameterUnit, float, float]] = {
    "°F": (ParameterUnit.celsius, 5 / 9, -32 * 5 / 9),
    "kPa": (ParameterUnit.pascal, 1000, 0),
}


@dataclass(frozen=True)
class MainValueSpec:
    """Identifies a device's one-tap main parameter and what a tap does (`Parameter.default_value`).

    Z-Wave has no invokable "commands" the way Zigbee/Matter clusters do — every action is a property set — so
    every main parameter is a value. `default_value` follows the SDK: None lets the data type decide (a bool
    toggles), a set is cycled through (two values: a toggle), a single value is a button that always sends it.
    """

    property_name: str
    default_value: set[int] | None


# Priority order matters: the first command class present on the node wins, same as
# ZigBeeController's MAIN_PARAMETER_BY_CLUSTER. Only CCs with an unambiguous "main" action are
# listed — e.g. Thermostat Mode is deliberately left out, since there's no single mode that's
# the obviously-correct one-tap action across vendors.
MAIN_VALUE_BY_COMMAND_CLASS: dict[CommandClass, MainValueSpec] = {
    CommandClass.SWITCH_BINARY: MainValueSpec("targetValue", None),
    # Off and fully on, as percentages (see LEVEL_COMMAND_CLASSES).
    CommandClass.SWITCH_MULTILEVEL: MainValueSpec("targetValue", {0, 100}),
    # BarrierState CLOSED = 0, OPEN = 255.
    CommandClass.BARRIER_OPERATOR: MainValueSpec("targetState", {0, 255}),
    # DoorLockMode UNSECURED = 0, SECURED = 255: not a cycle through every mode the lock has.
    CommandClass.DOOR_LOCK: MainValueSpec("targetMode", {0, 255}),
}
