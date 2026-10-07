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
# ParameterRole.event (except their settings, see SETTING_VALUES). zwave-js marks such values `stateful: false` and
# sends them as "value notification". Notification CC is not one: zwave-js models its variables as states.
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

# Levels 0-99 (99 is fully on) are percentages in MajorDom, as with Matter, Zigbee and ESPHome: 0-98 stay, 99 is 100.
# A window covering's position is one too (its 0 "closed" and 99 "open" labels are the ends of the range).
LEVEL_COMMAND_CLASSES: frozenset[CommandClass] = frozenset(
    {CommandClass.SWITCH_MULTILEVEL, CommandClass.BASIC, CommandClass.WINDOW_COVERING}
)
LEVEL_PROPERTIES: frozenset[str] = frozenset({"currentValue", "targetValue"})

# The device's configuration within a CC that is otherwise everyday use: shown as settings (None: the whole CC)
SETTING_VALUES: dict[CommandClass, frozenset[str] | None] = {
    CommandClass.DOOR_LOCK: frozenset(
        {
            "operationType",
            "lockTimeoutConfiguration",
            "autoRelockTime",
            "holdAndReleaseTime",
            "twistAssist",
            "blockToBlock",
            "insideHandlesCanOpenDoorConfiguration",
            "outsideHandlesCanOpenDoorConfiguration",
        }
    ),
    CommandClass.CENTRAL_SCENE: frozenset({"slowRefresh"}),  # "send held down notifications"
    CommandClass.BARRIER_OPERATOR: frozenset({"signalingState"}),  # audible / visual warning while moving
    CommandClass.SOUND_SWITCH: frozenset({"defaultToneId", "defaultVolume"}),
    CommandClass.NOTIFICATION: frozenset({"alarmType", "alarmLevel"}),  # legacy (V1) vendor alarm codes
    CommandClass.USER_CODE: None,  # user slots and keypad mode (the codes themselves are secrets: system)
    CommandClass.ENTRY_CONTROL: None,  # a keypad's key cache (its key presses arrive as notifications, not values)
}

# Values that describe another value rather than a state of the device, or protocol wiring: hidden
SYSTEM_VALUES: frozenset[tuple[int, int | str]] = frozenset(
    {
        (CommandClass.HUMIDITY_CONTROL_SETPOINT, "setpointScale"),  # the setpoint's unit
        (CommandClass.THERMOSTAT_SETPOINT, "setpointScale"),
        (CommandClass.WAKE_UP, "controllerNodeId"),  # which node gets the wake-ups: the controller
    }
)

# Notification CC variables (`<type>-<variable>`) that are diagnostics, not states people look at: settings
NOTIFICATION_SETTING_VARIABLES: frozenset[str] = frozenset(
    {
        "Maintenance status",
        "Periodic inspection status",
        "Dust in device status",
        "Test status",
        "Hardware status",
        "Software status",
        "Battery maintenance status",
        "Device configuration status",
        "Barrier performing initialization process status",
        "Barrier UL disabling status",
        "Barrier vacation mode status",
    }
)

# Notification CC variables several notification types have: named with their type ("Sensor status (Water Alarm)")
NOTIFICATION_SHARED_VARIABLES: frozenset[str] = frozenset(
    {
        "Sensor status",
        "Alarm status",
        "Cover status",
        "Maintenance status",
        "Periodic inspection status",
        "Dust in device status",
        "Test status",
    }
)

# The everyday controls and live readings: `user` (None: every value of the CC). Following the docs' "when in doubt,
# hide it", every other value of a REVIEWED_COMMAND_CLASSES CC is a `setting`, and a CC nobody reviewed is `system`
# (still usable by automations and the API).
USER_VALUES: dict[CommandClass, frozenset[str] | None] = {
    CommandClass.BASIC: frozenset({"targetValue"}),  # when it is the device's only control
    CommandClass.SWITCH_BINARY: frozenset({"targetValue"}),
    CommandClass.SWITCH_MULTILEVEL: frozenset({"targetValue"}),
    CommandClass.SWITCH_COLOR: frozenset({"hexColor"}),  # one colour control; the channels are settings
    CommandClass.SENSOR_BINARY: None,
    CommandClass.SENSOR_MULTILEVEL: None,
    CommandClass.METER: frozenset({"value"}),  # the readings; their resets are settings
    CommandClass.NOTIFICATION: None,  # its states (but see NOTIFICATION_SETTING_VARIABLES)
    CommandClass.SENSOR_ALARM: frozenset({"state"}),
    CommandClass.DOOR_LOCK: frozenset({"targetMode", "doorStatus", "latchStatus", "boltStatus"}),
    CommandClass.LOCK: frozenset({"locked"}),
    CommandClass.BARRIER_OPERATOR: frozenset({"targetState", "position"}),
    CommandClass.WINDOW_COVERING: frozenset({"targetValue"}),
    CommandClass.THERMOSTAT_MODE: frozenset({"mode"}),
    CommandClass.THERMOSTAT_SETPOINT: frozenset({"setpoint"}),
    CommandClass.THERMOSTAT_OPERATING_STATE: frozenset({"state"}),
    CommandClass.THERMOSTAT_FAN_MODE: frozenset({"mode"}),
    CommandClass.THERMOSTAT_FAN_STATE: frozenset({"state"}),
    CommandClass.HUMIDITY_CONTROL_SETPOINT: frozenset({"setpoint"}),
    CommandClass.HUMIDITY_CONTROL_MODE: frozenset({"mode"}),
    CommandClass.HUMIDITY_CONTROL_OPERATING_STATE: frozenset({"state"}),
    CommandClass.BATTERY: frozenset({"level"}),  # a live reading (the docs' example), despite the CC's diagnostics
    CommandClass.CENTRAL_SCENE: frozenset({"scene"}),
    CommandClass.SCENE_ACTIVATION: frozenset({"sceneId"}),
    CommandClass.SOUND_SWITCH: frozenset({"toneId"}),
    CommandClass.ENERGY_PRODUCTION: frozenset({"value"}),
}

# CCs whose values were reviewed one by one (the catalogue hosts each): what is not `user` is a `setting`
REVIEWED_COMMAND_CLASSES: frozenset[int] = (
    frozenset(USER_VALUES)
    | DIAGNOSTIC_COMMAND_CLASSES
    | {
        CommandClass.SCHEDULE_ENTRY_LOCK,
        CommandClass.USER_CODE,
        CommandClass.ENTRY_CONTROL,
        CommandClass.THERMOSTAT_SETBACK,
        CommandClass.HUMIDITY_CONTROL_SETPOINT,
        0x83,  # User Credential (newer than zwave-js-server-python's CommandClass)
    }
)

# Names for values whose zwave-js label reads as protocol, not as a control, by (CC, property[, property key]);
# {key}: the value's key (a colour channel, a covering)
VALUE_NAMES: dict[tuple[int, int | str] | tuple[int, int | str, int | str | None], str] = {
    (CommandClass.BASIC, "targetValue"): "Level",
    (CommandClass.BASIC, "restorePrevious"): "Restore last level",
    (CommandClass.SWITCH_BINARY, "targetValue"): "Power",
    (CommandClass.SWITCH_MULTILEVEL, "targetValue"): "Level",
    (CommandClass.SWITCH_MULTILEVEL, "Up"): "Level up",
    (CommandClass.SWITCH_MULTILEVEL, "Down"): "Level down",
    (CommandClass.SWITCH_MULTILEVEL, "restorePrevious"): "Restore last level",
    (CommandClass.SWITCH_COLOR, "hexColor"): "Color",
    (CommandClass.SWITCH_COLOR, "targetColor"): "{key}",
    (CommandClass.WINDOW_COVERING, "targetValue"): "{key}",
    (CommandClass.DOOR_LOCK, "targetMode"): "Lock",
    (CommandClass.DOOR_LOCK, "doorStatus"): "Door",
    (CommandClass.DOOR_LOCK, "latchStatus"): "Latch",
    (CommandClass.DOOR_LOCK, "boltStatus"): "Bolt",
    (CommandClass.DOOR_LOCK, "lockTimeout"): "Time until relock",
    (CommandClass.DOOR_LOCK, "operationType"): "Operation type",
    (CommandClass.DOOR_LOCK, "lockTimeoutConfiguration"): "Timed mode duration",
    (CommandClass.DOOR_LOCK, "autoRelockTime"): "Auto-relock time",
    (CommandClass.DOOR_LOCK, "holdAndReleaseTime"): "Hold and release time",
    (CommandClass.DOOR_LOCK, "twistAssist"): "Twist assist",
    (CommandClass.DOOR_LOCK, "blockToBlock"): "Block to block",
    (CommandClass.DOOR_LOCK, "insideHandlesCanOpenDoorConfiguration"): "Inside handles that open the door",
    (CommandClass.DOOR_LOCK, "outsideHandlesCanOpenDoorConfiguration"): "Outside handles that open the door",
    (CommandClass.DOOR_LOCK, "insideHandlesCanOpenDoor"): "Inside handles open the door",
    (CommandClass.DOOR_LOCK, "outsideHandlesCanOpenDoor"): "Outside handles open the door",
    (CommandClass.BARRIER_OPERATOR, "targetState"): "Door",
    (CommandClass.BARRIER_OPERATOR, "position"): "Position",
    (CommandClass.VERSION, "firmwareVersions"): "Firmware version",
    (CommandClass.VERSION, "libraryType"): "Z-Wave library type",
    (CommandClass.WAKE_UP, "wakeUpInterval"): "Wake-up interval",
    (CommandClass.WAKE_UP, "controllerNodeId"): "Wake-up destination",
    (CommandClass.CENTRAL_SCENE, "slowRefresh"): "Slow refresh while held",
    (CommandClass.SCENE_ACTIVATION, "sceneId"): "Scene",
    (CommandClass.SCENE_ACTIVATION, "dimmingDuration"): "Scene dimming duration",
    (CommandClass.USER_CODE, "userIdStatus"): "User {key} status",
    (CommandClass.USER_CODE, "userCode"): "User {key} code",
    (CommandClass.SOUND_SWITCH, "toneId"): "Play tone",
    (CommandClass.SOUND_SWITCH, "volume"): "Tone volume",
    (CommandClass.SOUND_SWITCH, "defaultToneId"): "Default tone",
    (CommandClass.PROTECTION, "local"): "Local protection",
    (CommandClass.PROTECTION, "rf"): "Remote protection",
    (CommandClass.PROTECTION, "exclusiveControlNodeId"): "Exclusive control",
    (CommandClass.PROTECTION, "timeout"): "Remote protection timeout",
    (CommandClass.THERMOSTAT_FAN_MODE, "mode"): "Fan mode",
    (CommandClass.THERMOSTAT_FAN_MODE, "off"): "Fan off",
    (CommandClass.THERMOSTAT_FAN_STATE, "state"): "Fan state",
    (CommandClass.HUMIDITY_CONTROL_MODE, "mode"): "Humidity mode",
    (CommandClass.HUMIDITY_CONTROL_OPERATING_STATE, "state"): "Humidity operating state",
    (CommandClass.ENERGY_PRODUCTION, "value", 1): "Total production",
    (CommandClass.ENERGY_PRODUCTION, "value", 2): "Production today",
    (CommandClass.ENERGY_PRODUCTION, "value", 3): "Operating time",
}

# A meter value's quantity, by the scale in its label ("Electric Consumption [kWh]" → "Electric energy")
METER_QUANTITIES: dict[str, str] = {
    "kWh": "energy",
    "kVAh": "apparent energy",
    "W": "power",
    "Pulse count": "pulses",
    "V": "voltage",
    "A": "current",
    "Power Factor": "power factor",
    "kVar": "reactive power",
    "kVarh": "reactive energy",
    "Cubic meters": "volume",
    "Cubic feet": "volume (ft³)",
    "US gallons": "volume (gal)",
}

# Numbers whose `states` label special values of a range, not the only values: integers, not enums
NUMERIC_VALUES: frozenset[tuple[int, int | str]] = frozenset(
    {
        (CommandClass.SOUND_SWITCH, "volume"),  # 0 is "the default volume"
        (CommandClass.WAKE_UP, "wakeUpInterval"),  # 0 is "disabled"
    }
)

# Units zwave-js puts only in a value's label ("Duration in seconds …"), not in its metadata
VALUE_UNITS: dict[tuple[int, int | str], ParameterUnit] = {
    (CommandClass.DOOR_LOCK, "lockTimeoutConfiguration"): ParameterUnit.second,
    (CommandClass.DOOR_LOCK, "lockTimeout"): ParameterUnit.second,
    (CommandClass.DOOR_LOCK, "autoRelockTime"): ParameterUnit.second,
    (CommandClass.DOOR_LOCK, "holdAndReleaseTime"): ParameterUnit.second,
    (CommandClass.WAKE_UP, "wakeUpInterval"): ParameterUnit.second,
}

# zwave-js's ValueMetadata.unit is the unit string of the CC's scale (its sensor, meter and named-scale registries,
# plus a few CC-specific ones). Every registry unit is mapped, converted, or deliberately plain (test_catalogue checks).
UNIT_MAP: dict[str, ParameterUnit] = {
    "%": ParameterUnit.percentage,
    "s": ParameterUnit.second,
    "seconds": ParameterUnit.second,  # Energy Production's total time
    "Hz": ParameterUnit.hertz,
    "kg": ParameterUnit.kilogram,
    "°": ParameterUnit.arcdegree,
    "°N": ParameterUnit.arcdegree,  # a direction
    "°S": ParameterUnit.arcdegree,
    "m": ParameterUnit.meters,
    "m/s": ParameterUnit.mps,
    "m/s²": ParameterUnit.mps2,
    "m³/h": ParameterUnit.m3h,
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
    "inHg": (ParameterUnit.pascal, 3386.389, 0),
    "mmHg": (ParameterUnit.pascal, 133.322, 0),
    "psi": (ParameterUnit.pascal, 6894.757, 0),
    "Wh": (ParameterUnit.kwh, 0.001, 0),
    "Btu/h": (ParameterUnit.watt, 0.29307107, 0),
    "mV": (ParameterUnit.volt, 0.001, 0),
    "mA": (ParameterUnit.ampere, 0.001, 0),
    "kHz": (ParameterUnit.hertz, 1000, 0),
    "cm": (ParameterUnit.meters, 0.01, 0),
    "ft": (ParameterUnit.meters, 0.3048, 0),
    "lb": (ParameterUnit.kilogram, 0.45359237, 0),
    "Mph": (ParameterUnit.mps, 0.44704, 0),
    "cfm": (ParameterUnit.m3h, 1.699011, 0),
}

# Units MajorDom has no unit for, and no unit it has to convert them to: reported as they are, unit `plain`
PLAIN_UNITS: frozenset[str] = frozenset(
    {
        "g/m³",  # absolute humidity
        "W/m²",  # solar radiation
        "mm/h",  # rain rate
        "in/h",
        "l",  # volume
        "m³",
        "gallon",
        "gal",
        "ft³",
        "l/h",  # water flow
        "Ωm",  # soil / water conductivity
        "S/m",
        "kΩ",
        "dB",  # sound level
        "dBA",
        "dBm",  # signal strength
        "m³/m³",  # soil moisture
        "aw",  # water activity
        "mol/m³",
        "bq/m³",  # radon
        "pCi/l",
        "pH",
        "bpm",  # heart rate
        "mg/l",
        "kVAh",  # apparent energy, reactive power and energy
        "kVar",
        "kVarh",
    }
)


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
    # Lock CC (older locks): a bool, so a tap toggles it.
    CommandClass.LOCK: MainValueSpec("locked", None),
    # A window covering's position: closed and fully open, as percentages.
    CommandClass.WINDOW_COVERING: MainValueSpec("targetValue", {0, 100}),
    # Basic CC, when it is the only control the device has: off and fully on, as percentages.
    CommandClass.BASIC: MainValueSpec("targetValue", {0, 100}),
}
