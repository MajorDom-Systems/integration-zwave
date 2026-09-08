"""Static Z-Wave classification data.

Unlike Zigbee, zwave-js already reports `min`/`max`/`unit`/`states` directly on `ValueMetadata`,
so this module only needs to cover what the wire format *doesn't* give us: which command classes
are protocol plumbing or diagnostics-only, how to normalize zwave-js's freeform unit strings,
and which property is a device's one-tap "main" action.

Pure data only — the functions/methods that use these tables live on ZwaveMapper in mapper.py.
"""

from dataclasses import dataclass

from majordom_integration_sdk.schemas.parameter import ParameterUnit
from zwave_js_server.const import CommandClass

# The standard, cross-vendor Indicator CC value for "make the device blink so I can find it"
# (Indicator CC spec, indicator id 0x50 "Node Identify"). Setting it triggers the device's own
# built-in identify blink pattern and it self-resets — there's nothing to turn back off.
IDENTIFY_INDICATOR_ID = 0x50


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

# CCs that report one-shot occurrences rather than a persistent state (button presses,
# scene activations, alarms) — modeled as ParameterRole.event regardless of read/write flags.
EVENT_COMMAND_CLASSES: frozenset[CommandClass] = frozenset(
    {
        CommandClass.CENTRAL_SCENE,
        CommandClass.SCENE_ACTIVATION,
        CommandClass.NOTIFICATION,
    }
)

# zwave-js's ValueMetadata.unit is a freeform string straight from the device's CC report, not a
# controlled vocabulary — map the ones we recognize, leave the rest unmapped rather than guessed.
# Extend this as new unit strings show up in the field.
UNIT_MAP: dict[str, ParameterUnit] = {
    "%": ParameterUnit.percentage,
    "s": ParameterUnit.second,
    "Hz": ParameterUnit.hertz,
    "kg": ParameterUnit.kilogram,
    "°": ParameterUnit.arcdegree,
    "deg": ParameterUnit.arcdegree,
    "m": ParameterUnit.meters,
    "m/s": ParameterUnit.mps,
    "m/s2": ParameterUnit.mps2,
    "rpm": ParameterUnit.rpm,
    "N": ParameterUnit.newton,
    "J": ParameterUnit.joule,
    "W": ParameterUnit.watt,
    "°C": ParameterUnit.celsius,
    "K": ParameterUnit.kelvin,
    "V": ParameterUnit.volt,
    "A": ParameterUnit.ampere,
    "lx": ParameterUnit.lux,
    "Pa": ParameterUnit.pascal,
    "ppm": ParameterUnit.ppm,
    "b": ParameterUnit.bytes,
    "B": ParameterUnit.bytes,
    # Deliberately unmapped (no ParameterUnit equivalent yet — falls back to `plain`):
    # "kWh" (energy-over-time, not instantaneous joule), "dB"/"dBm" (log scale), "UV index".
}


@dataclass(frozen=True)
class MainValueSpec:
    """Identifies a device's one-tap main parameter and the value to send for it.

    Z-Wave has no invokable "commands" the way Zigbee/Matter clusters do — every action is a
    property get/set — so every Z-Wave main parameter is attribute-like (the same shape as
    Matter's FanControl case, the one cluster where Matter's own main parameter is attribute-type
    too, rather than a command). `default_value` is what a tap sends when the app doesn't already
    know the device's current state (e.g. right after pairing); once telemetry is flowing, the
    app is expected to flip between the parameter's known states itself rather than always
    sending this same value on every tap.
    """

    property_name: str
    default_value: bool | int | float


# Priority order matters: the first command class present on the node wins, same as
# ZigBeeController's MAIN_PARAMETER_BY_CLUSTER. Only CCs with an unambiguous "main" action are
# listed — e.g. Thermostat Mode is deliberately left out, since there's no single mode that's
# the obviously-correct one-tap action across vendors.
MAIN_VALUE_BY_COMMAND_CLASS: dict[CommandClass, MainValueSpec] = {
    CommandClass.SWITCH_BINARY: MainValueSpec("targetValue", True),
    # 255 = "restore last non-zero level" per the Multilevel Switch CC spec, i.e. "turn on".
    CommandClass.SWITCH_MULTILEVEL: MainValueSpec("targetValue", 255),
    # BarrierState.OPEN = 255.
    CommandClass.BARRIER_OPERATOR: MainValueSpec("targetState", 255),
    # DoorLockMode.SECURED = 255 — lock, not unlock, is the safer default one-tap action.
    CommandClass.DOOR_LOCK: MainValueSpec("targetMode", 255),
}
