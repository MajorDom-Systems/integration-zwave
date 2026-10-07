"""The command-class catalogue: every CC zwave-js knows is hosted by a mock device (a recipe, tests/mock/catalogue.mjs),
is protocol plumbing, or is explained here — and what each hosted CC must map to.

Spec terms: "plumbing" CCs carry no user-facing value (they map to `system`); "unhostable" ones have no zwave-js mock
(their values still go through the generic mapping, checked shape by shape in test_value_shapes).
"""

from majordom_integration_sdk.schemas.parameter import (
    ParameterDataType as T,
)
from majordom_integration_sdk.schemas.parameter import (
    ParameterRole as R,
)
from majordom_integration_sdk.schemas.parameter import (
    ParameterUnit as U,
)
from majordom_integration_sdk.schemas.parameter import (
    ParameterVisibility as V,
)

from majordom_zwave.zwave_spec import SYSTEM_COMMAND_CLASSES

# recipe → the command classes it hosts (beyond the ones every mock device has, see BASE)
RECIPES: dict[str, set[int]] = {
    "basic": {0x20},
    "binary_sensor": {0x30},
    "binary_switch": {0x25},
    "color_switch": {0x33, 0x26},
    "configuration": {0x70},
    "door_lock": {0x62},
    "energy_production": {0x90},
    "indicator": {0x87},
    "lock": {0x76},
    "meter": {0x32},
    "multilevel_sensor": {0x31},
    "multilevel_switch": {0x26},
    "node_naming": {0x77},
    "notification": {0x71},
    "scene_activation": {0x2B},
    "schedule_entry_lock": {0x4E, 0x63},
    "sound_switch": {0x79},
    "thermostat_mode": {0x40},
    "thermostat_setback": {0x47},
    "thermostat_setpoint": {0x43},
    "user_code": {0x63},
    "user_credential": {0x83},
    "window_covering": {0x6A},
    # not mocked by zwave-js: the harness answers for them (BEHAVIORS in catalogue.mjs)
    "central_scene": {0x5B},
    "thermostat_fan_mode": {0x44},
    "thermostat_fan_state": {0x45},
    "thermostat_operating_state": {0x42},
    "barrier_operator": {0x66},
    "protection": {0x75, 0x25},
    "humidity_control": {0x64, 0x6D, 0x6E},
    "entry_control": {0x6F},
    "alarm_sensor": {0x9C},
    "powerlevel": {0x73, 0x25},
    "sleeping": {0x80, 0x84, 0x25},  # Battery and Wake Up, on a switch
}

# On every mock device (identity, interview), or used by the scenario tests (endpoints, supervision, S2)
BASE = {0x5E, 0x72, 0x86}
INFRASTRUCTURE = BASE | {0x60, 0x6C, 0x9F}

# Not in zwave-js-server-python's CommandClass yet: newer than the library
NEWER_THAN_THE_LIBRARY = {
    0x01: "Z-Wave Protocol: the protocol's own frames, no values",
    0x04: "Z-Wave Long Range: the protocol's own frames, no values",
    0x83: "User Credential: hosted (recipe user_credential); compared by its number",
}

PLUMBING = {int(cc) for cc in SYSTEM_COMMAND_CLASSES} | {0x01, 0x04}

_NO_MOCK = "zwave-js has no mock for it; its values go through the generic mapping (test_value_shapes)"
_RARE = "no mock, and rare in homes (commercial metering, IP gateways, AV): generic mapping (test_value_shapes)"
UNHOSTABLE: dict[int, str] = {
    **dict.fromkeys(
        [
            0x27,  # All Switch
            0x28,  # Binary Toggle Switch
            0x29,  # Multilevel Toggle Switch
            0x2C,  # Scene Actuator Configuration
            0x2D,  # Scene Controller Configuration
            0x46,  # Climate Control Schedule
            0x4C,  # Door Lock Logging
            0x50,  # Basic Window Covering
            0x51,  # Move To Position Window Covering
            0x53,  # Schedule
            0x5D,  # Anti-Theft
            0x6B,  # Irrigation
            0x7E,  # Anti-Theft Unlock
            0x82,  # Hail
            0x89,  # Language
            0x9D,  # Alarm Silence
            0x9E,  # Sensor Configuration
            0xA3,  # Generic Schedule
        ],
        _NO_MOCK,
    ),
    **dict.fromkeys(
        [
            0x35,  # Pulse Meter
            0x36,  # Basic Tariff Information
            0x37,  # HRV Status
            0x39,  # HRV Control
            0x3A,  # Demand Control Plan Configuration
            0x3B,  # Demand Control Plan Monitor
            0x3C,  # Meter Table Configuration
            0x3D,  # Meter Table Monitor
            0x3E,  # Meter Table Push Configuration
            0x3F,  # Prepayment
            0x41,  # Prepayment Encapsulation
            0x48,  # Rate Table Configuration
            0x49,  # Rate Table Monitor
            0x4A,  # Tariff Table Configuration
            0x4B,  # Tariff Table Monitor
            0x4F,  # Z/IP 6LoWPAN
            0x58,  # Z/IP ND
            0x5F,  # Z/IP Gateway
            0x61,  # Z/IP Portal
            0x68,  # Z/IP Naming and Location
            0x5C,  # IP Association
            0x69,  # Mailbox
            0x94,  # Simple AV Control
            0x9A,  # IP Configuration
            0x9B,  # Association Command Configuration
            0xA0,  # IR Repeater
            0xA1,  # Authentication
            0xA2,  # Authentication Media Write
        ],
        _RARE,
    ),
}

# What each hosted CC maps to, reviewed value by value against the docs' parameter UX (docs/device-integration/
# parameter-ux.md): everyday controls and live readings `user` (the main tile among them), a CC's configuration and
# diagnostics `setting`, wiring, metadata, secrets and durations `system`; names for people, not zwave-js's labels.
Row = tuple[str, T, R, V, U]  # (name, data type, role, visibility, unit)

# Every device's identity values (Manufacturer Specific, Version): checked once, the same on every recipe
COMMON: dict[str, Row] = {
    "114-0-productId": ("Product ID", T.integer, R.sensor, V.setting, U.plain),
    "114-0-productType": ("Product type", T.integer, R.sensor, V.setting, U.plain),
    "114-0-manufacturerId": ("Manufacturer ID", T.integer, R.sensor, V.setting, U.plain),
    "134-0-firmwareVersions": ("Firmware version", T.string, R.sensor, V.setting, U.plain),
    "134-0-protocolVersion": ("Z-Wave protocol version", T.string, R.sensor, V.setting, U.plain),
    "134-0-libraryType": ("Z-Wave library type", T.enum, R.sensor, V.setting, U.plain),
}

# key (value id without the node: <cc>-<endpoint>-<property>[-<key>]) → (name, data type, role, visibility, unit)
EXPECTED: dict[str, dict[str, Row]] = {
    "alarm_sensor": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "156-0-state-1": ("Smoke state", T.bool, R.sensor, V.user, U.plain),
        "156-0-severity-1": ("Smoke severity", T.integer, R.sensor, V.setting, U.percentage),
        "156-0-duration-1": ("Smoke duration", T.integer, R.sensor, V.setting, U.second),
        "156-0-state-2": ("CO state", T.bool, R.sensor, V.user, U.plain),
        "156-0-severity-2": ("CO severity", T.integer, R.sensor, V.setting, U.percentage),
        "156-0-duration-2": ("CO duration", T.integer, R.sensor, V.setting, U.second),
    },
    "barrier_operator": {
        "102-0-signalingState-1": ("Audible warning", T.enum, R.control, V.setting, U.plain),
        "102-0-signalingState-2": ("Visual warning", T.enum, R.control, V.setting, U.plain),
        "102-0-position": ("Position", T.integer, R.sensor, V.user, U.percentage),
        "102-0-targetState": ("Door", T.enum, R.control, V.user, U.plain),
    },
    "basic": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.user, U.percentage),
        "32-0-duration": ("Remaining duration", T.string, R.sensor, V.system, U.plain),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.setting, U.plain),
    },
    "binary_sensor": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "48-0-General Purpose": ("General purpose", T.bool, R.sensor, V.user, U.plain),
        "48-0-Door/Window": ("Door/Window", T.bool, R.sensor, V.user, U.plain),
        "48-0-Motion": ("Motion", T.bool, R.sensor, V.user, U.plain),
    },
    "binary_switch": {
        "37-0-duration": ("Remaining duration", T.string, R.sensor, V.system, U.plain),
        "37-0-targetValue": ("Power", T.bool, R.control, V.user, U.plain),
    },
    "central_scene": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "91-0-scene-001": ("Scene 1", T.enum, R.event, V.user, U.plain),
        "91-0-scene-002": ("Scene 2", T.enum, R.event, V.user, U.plain),
        "91-0-slowRefresh": ("Slow refresh while held", T.bool, R.control, V.setting, U.plain),
    },
    "color_switch": {
        "38-0-duration": ("Remaining duration (Multilevel Switch)", T.string, R.sensor, V.system, U.plain),
        "38-0-targetValue": ("Level", T.integer, R.control, V.user, U.percentage),
        "38-0-Up": ("Level up", T.bool, R.control, V.setting, U.plain),
        "38-0-Down": ("Level down", T.bool, R.control, V.setting, U.plain),
        "38-0-restorePrevious": ("Restore last level", T.none, R.control, V.setting, U.plain),
        "51-0-hexColor": ("Color", T.string, R.control, V.user, U.plain),
        "51-0-targetColor-0": ("Warm white", T.integer, R.control, V.setting, U.plain),
        "51-0-targetColor-1": ("Cold white", T.integer, R.control, V.setting, U.plain),
        "51-0-targetColor-2": ("Red", T.integer, R.control, V.setting, U.plain),
        "51-0-targetColor-3": ("Green", T.integer, R.control, V.setting, U.plain),
        "51-0-targetColor-4": ("Blue", T.integer, R.control, V.setting, U.plain),
        "51-0-targetColor": ("Color Switch", T.data, R.control, V.system, U.plain),
        "51-0-duration": ("Remaining duration (Color Switch)", T.string, R.sensor, V.system, U.plain),
        "38-0-levelChange": ("Level change", T.enum, R.event, V.system, U.plain),
    },
    "configuration": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.user, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.setting, U.plain),
        "112-0-1": ("Brightness on power-up", T.integer, R.control, V.setting, U.plain),
        "112-0-2": ("LED mode", T.integer, R.control, V.setting, U.plain),
        "112-0-3": ("Offset", T.integer, R.control, V.setting, U.plain),
        "112-0-4": ("Firmware flags", T.integer, R.sensor, V.setting, U.plain),
    },
    "door_lock": {
        "98-0-targetMode": ("Lock", T.enum, R.control, V.user, U.plain),
        "98-0-operationType": ("Operation type", T.enum, R.control, V.setting, U.plain),
        "98-0-doorStatus": ("Door", T.string, R.sensor, V.user, U.plain),
        "98-0-latchStatus": ("Latch", T.string, R.sensor, V.user, U.plain),
        "98-0-boltStatus": ("Bolt", T.string, R.sensor, V.user, U.plain),
        "98-0-insideHandlesCanOpenDoorConfiguration": (
            "Inside handles that open the door",
            T.data,
            R.control,
            V.system,
            U.plain,
        ),
        "98-0-outsideHandlesCanOpenDoorConfiguration": (
            "Outside handles that open the door",
            T.data,
            R.control,
            V.system,
            U.plain,
        ),
        "98-0-autoRelockTime": ("Auto-relock time", T.integer, R.control, V.setting, U.second),
        "98-0-holdAndReleaseTime": ("Hold and release time", T.integer, R.control, V.setting, U.second),
        "98-0-twistAssist": ("Twist assist", T.bool, R.control, V.setting, U.plain),
        "98-0-blockToBlock": ("Block to block", T.bool, R.control, V.setting, U.plain),
        "98-0-insideHandlesCanOpenDoor": ("Inside handles open the door", T.data, R.sensor, V.system, U.plain),
        "98-0-outsideHandlesCanOpenDoor": ("Outside handles open the door", T.data, R.sensor, V.system, U.plain),
        "98-0-duration": ("Remaining duration until target lock mode", T.string, R.sensor, V.system, U.plain),
        "98-0-lockTimeoutConfiguration": ("Timed mode duration", T.integer, R.control, V.setting, U.second),
        "98-0-lockTimeout": ("Time until relock", T.integer, R.sensor, V.setting, U.second),
    },
    "energy_production": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "144-0-value-0": ("Power", T.decimal, R.sensor, V.user, U.watt),
        "144-0-value-1": ("Total production", T.decimal, R.sensor, V.user, U.kwh),
        "144-0-value-2": ("Production today", T.decimal, R.sensor, V.user, U.kwh),
        "144-0-value-3": ("Operating time", T.decimal, R.sensor, V.user, U.second),
    },
    "entry_control": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "111-0-keyCacheSize": ("Key cache size", T.integer, R.control, V.setting, U.plain),
        "111-0-keyCacheTimeout": ("Key cache timeout", T.integer, R.control, V.setting, U.second),
        "111-0-event": ("Keypad", T.enum, R.event, V.user, U.plain),
        "111-0-code": ("Keypad code", T.string, R.event, V.system, U.plain),
    },
    "humidity_control": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "100-0-setpointScale-1": ("Setpoint scale (humidifier)", T.enum, R.sensor, V.system, U.plain),
        "100-0-setpoint-1": ("Humidifier setpoint", T.decimal, R.control, V.user, U.percentage),
        "100-0-setpointScale-2": ("Setpoint scale (de-humidifier)", T.enum, R.sensor, V.system, U.plain),
        "100-0-setpoint-2": ("De-humidifier setpoint", T.decimal, R.control, V.user, U.percentage),
        "109-0-mode": ("Humidity mode", T.enum, R.control, V.user, U.plain),
        "110-0-state": ("Humidity operating state", T.enum, R.sensor, V.user, U.plain),
    },
    "indicator": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.user, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.setting, U.plain),
        "135-0-67-2": ("Button 1 indication", T.bool, R.control, V.setting, U.plain),
        "135-0-value": ("Indicator value", T.integer, R.control, V.setting, U.plain),
        "135-0-identify": ("Identify", T.none, R.control, V.setting, U.plain),
    },
    "lock": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "118-0-locked": ("Locked", T.bool, R.control, V.user, U.plain),
    },
    "meter": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "50-0-value-65537": ("Electric energy", T.decimal, R.sensor, V.user, U.kwh),
        "50-0-value-66049": ("Electric power", T.decimal, R.sensor, V.user, U.watt),
        "50-0-value-66561": ("Electric voltage", T.decimal, R.sensor, V.user, U.volt),
        "50-0-value-66817": ("Electric current", T.decimal, R.sensor, V.user, U.ampere),
        "50-0-reset-65537": ("Reset electric energy", T.none, R.control, V.setting, U.plain),
        "50-0-reset": ("Reset all meters", T.none, R.control, V.setting, U.plain),
    },
    "multilevel_sensor": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "49-0-Air temperature": ("Air temperature", T.decimal, R.sensor, V.user, U.celsius),
        "49-0-Illuminance": ("Illuminance", T.decimal, R.sensor, V.user, U.lux),
        "49-0-Humidity": ("Humidity", T.decimal, R.sensor, V.user, U.percentage),
    },
    "multilevel_switch": {
        "38-0-duration": ("Remaining duration", T.string, R.sensor, V.system, U.plain),
        "38-0-targetValue": ("Level", T.integer, R.control, V.user, U.percentage),
        "38-0-Up": ("Level up", T.bool, R.control, V.setting, U.plain),
        "38-0-Down": ("Level down", T.bool, R.control, V.setting, U.plain),
        "38-0-restorePrevious": ("Restore last level", T.none, R.control, V.setting, U.plain),
        "38-0-levelChange": ("Level change", T.enum, R.event, V.system, U.plain),
    },
    "node_naming": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.user, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.setting, U.plain),
        "119-0-name": ("Node name", T.string, R.control, V.system, U.plain),
        "119-0-location": ("Node location", T.string, R.control, V.system, U.plain),
    },
    "notification": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "113-0-Water Alarm-Sensor status": ("Sensor status (Water alarm)", T.enum, R.sensor, V.user, U.plain),
        "113-0-Home Security-Cover status": ("Cover status (Home security)", T.enum, R.sensor, V.user, U.plain),
        "113-0-Home Security-Motion sensor status": ("Motion sensor status", T.enum, R.sensor, V.user, U.plain),
        "113-0-alarmType": ("Alarm type", T.integer, R.sensor, V.setting, U.plain),
        "113-0-alarmLevel": ("Alarm level", T.integer, R.sensor, V.setting, U.plain),
        "113-0-event-6": ("Access control event", T.enum, R.event, V.user, U.plain),
        "113-0-details-6": ("Access control event details", T.string, R.event, V.system, U.json),
    },
    "powerlevel": {
        "37-0-duration": ("Remaining duration", T.string, R.sensor, V.system, U.plain),
        "37-0-targetValue": ("Power", T.bool, R.control, V.user, U.plain),
        "115-0-test": ("Powerlevel test", T.enum, R.event, V.setting, U.plain),
    },
    "protection": {
        "37-0-duration": ("Remaining duration", T.string, R.sensor, V.system, U.plain),
        "37-0-targetValue": ("Power", T.bool, R.control, V.user, U.plain),
        "117-0-local": ("Local protection", T.enum, R.control, V.setting, U.plain),
        "117-0-rf": ("Remote protection", T.enum, R.control, V.setting, U.plain),
        "117-0-exclusiveControlNodeId": ("Exclusive control", T.integer, R.control, V.setting, U.plain),
        "117-0-timeout": ("Remote protection timeout", T.string, R.control, V.setting, U.plain),
    },
    "scene_activation": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "43-0-sceneId": ("Scene", T.integer, R.event, V.user, U.plain),
        "43-0-dimmingDuration": ("Scene dimming duration", T.string, R.event, V.system, U.plain),
    },
    "schedule_entry_lock": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "99-0-adminCode": ("Admin code", T.string, R.control, V.system, U.plain),
        "99-0-userIdStatus-1": ("User 1 status", T.enum, R.control, V.setting, U.plain),
        "99-0-userCode-1": ("User 1 code", T.string, R.control, V.system, U.plain),
        "99-0-userIdStatus-2": ("User 2 status", T.enum, R.control, V.setting, U.plain),
        "99-0-userCode-2": ("User 2 code", T.string, R.control, V.system, U.plain),
        "99-0-keypadMode": ("Keypad mode", T.integer, R.sensor, V.setting, U.plain),
    },
    "sleeping": {
        "37-0-duration": ("Remaining duration", T.string, R.sensor, V.system, U.plain),
        "37-0-targetValue": ("Power", T.bool, R.control, V.user, U.plain),
        "128-0-level": ("Battery level", T.integer, R.sensor, V.user, U.percentage),
        "132-0-wakeUpInterval": ("Wake-up interval", T.integer, R.control, V.setting, U.second),
        "132-0-controllerNodeId": ("Wake-up destination", T.integer, R.sensor, V.system, U.plain),
        "128-0-replacement": ("Battery replacement", T.enum, R.event, V.user, U.plain),
    },
    "sound_switch": {
        "121-0-defaultToneId": ("Default tone", T.enum, R.control, V.setting, U.plain),
        "121-0-defaultVolume": ("Default volume", T.integer, R.control, V.setting, U.percentage),
        "121-0-toneId": ("Play tone", T.enum, R.control, V.user, U.plain),
        "121-0-volume": ("Tone volume", T.integer, R.control, V.setting, U.percentage),
    },
    "thermostat_fan_mode": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "68-0-mode": ("Fan mode", T.enum, R.control, V.user, U.plain),
        "68-0-off": ("Fan off", T.bool, R.control, V.setting, U.plain),
    },
    "thermostat_fan_state": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "69-0-state": ("Fan state", T.enum, R.sensor, V.user, U.plain),
    },
    "thermostat_mode": {
        "64-0-mode": ("Thermostat mode", T.enum, R.control, V.user, U.plain),
        "64-0-manufacturerData": ("Manufacturer data", T.data, R.sensor, V.system, U.plain),
    },
    "thermostat_operating_state": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "66-0-state": ("Operating state", T.enum, R.sensor, V.user, U.plain),
    },
    "thermostat_setback": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.user, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.setting, U.plain),
    },
    "thermostat_setpoint": {
        "67-0-setpoint-1": ("Heating setpoint", T.decimal, R.control, V.user, U.celsius),
        "67-0-setpoint-2": ("Cooling setpoint", T.decimal, R.control, V.user, U.celsius),
    },
    "user_code": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.system, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.system, U.plain),
        "99-0-adminCode": ("Admin code", T.string, R.control, V.system, U.plain),
        "99-0-userIdStatus-1": ("User 1 status", T.enum, R.control, V.setting, U.plain),
        "99-0-userCode-1": ("User 1 code", T.string, R.control, V.system, U.plain),
        "99-0-userIdStatus-2": ("User 2 status", T.enum, R.control, V.setting, U.plain),
        "99-0-userCode-2": ("User 2 code", T.string, R.control, V.system, U.plain),
        "99-0-keypadMode": ("Keypad mode", T.integer, R.sensor, V.setting, U.plain),
    },
    "user_credential": {
        "32-0-targetValue": ("Level", T.integer, R.control, V.user, U.percentage),
        "32-0-restorePrevious": ("Restore last level", T.none, R.control, V.setting, U.plain),
    },
    "window_covering": {
        "106-0-targetValue-13": ("Outbound bottom", T.integer, R.control, V.user, U.percentage),
        "106-0-duration-13": ("Outbound bottom: remaining duration", T.string, R.sensor, V.system, U.plain),
        "106-0-targetValue-23": ("Horizontal slats angle", T.integer, R.control, V.user, U.percentage),
        "106-0-duration-23": ("Horizontal slats angle: remaining duration", T.string, R.sensor, V.system, U.plain),
        "106-0-levelChangeUp-13": ("Outbound bottom: open", T.bool, R.control, V.setting, U.plain),
        "106-0-levelChangeDown-13": ("Outbound bottom: close", T.bool, R.control, V.setting, U.plain),
        "106-0-levelChangeUp-23": (
            "Horizontal slats angle: change tilt (down inside)",
            T.bool,
            R.control,
            V.setting,
            U.plain,
        ),
        "106-0-levelChangeDown-23": (
            "Horizontal slats angle: change tilt (up inside)",
            T.bool,
            R.control,
            V.setting,
            U.plain,
        ),
    },
}

# The device's one-tap main parameter (None: nothing has an unambiguous one-tap action)
MAIN: dict[str, str | None] = {
    "barrier_operator": "102-0-targetState",
    "basic": "32-0-targetValue",
    "binary_switch": "37-0-targetValue",
    "color_switch": "38-0-targetValue",
    "configuration": "32-0-targetValue",
    "door_lock": "98-0-targetMode",
    "indicator": "32-0-targetValue",
    "lock": "118-0-locked",
    "multilevel_switch": "38-0-targetValue",
    "node_naming": "32-0-targetValue",
    "powerlevel": "37-0-targetValue",
    "protection": "37-0-targetValue",
    "sleeping": "37-0-targetValue",
    "thermostat_setback": "32-0-targetValue",
    "user_credential": "32-0-targetValue",
    "window_covering": "106-0-targetValue-13",
}


# Writable values whose new value does not come back as a report from the mock device, and why
NO_REPORT: dict[str, str] = {
    "32-0-targetValue": "Basic Set gets no report back from the mock (zwave-js verifies with a Get later)",
    "51-0-hexColor": "a combined view of the channels: the channels report, not this",
    **dict.fromkeys(
        [f"51-0-targetColor-{c}" for c in range(5)],
        "zwave-js's mock cannot decode a Color Switch Set (TypeError in its parser): the mock drops it, unanswered",
    ),
    "98-0-insideHandlesCanOpenDoorConfiguration": "an object value: not writable from MajorDom (system)",
    "98-0-outsideHandlesCanOpenDoorConfiguration": "an object value: not writable from MajorDom (system)",
    "119-0-name": "system: the Hub keeps the name",
    "119-0-location": "system: the Hub keeps the location",
    "99-0-adminCode": "a secret: never written from MajorDom",
    "99-0-userCode-1": "a secret",
    "99-0-userCode-2": "a secret",
    "121-0-toneId": "playing a tone: the mock reports it finished (0), not the tone",
    "121-0-volume": "only used with a tone being played",
    "135-0-67-2": "zwave-js's Indicator mock takes the Set but does not keep the indicator's state",
    "135-0-value": "zwave-js's Indicator mock takes the Set but does not keep the indicator's state",
    "117-0-exclusiveControlNodeId": "the device does not support exclusive control (as many do not)",
    "98-0-operationType": "zwave-js sets the lock configuration as a whole: timed mode needs its timeout with it",
    "98-0-lockTimeoutConfiguration": "zwave-js sets the lock configuration as a whole: a timeout needs timed mode",
    "99-0-userIdStatus-1": "a user slot is enabled together with its code (a secret): zwave-js rejects it alone",
    "99-0-userIdStatus-2": "a user slot is enabled together with its code (a secret): zwave-js rejects it alone",
}

# Every variant zwave-js knows (recipes *_all): too many values to list, so each value of the CC must follow its rule
# (key pattern → (data type, role, visibilities, unit; None: any, the drift check covers units)), at least `minimum`
VARIANTS: dict[str, tuple[int, dict[str, tuple[T, R, set[V], U | None]]]] = {
    "binary_sensor_all": (13, {r"48-0-.+": (T.bool, R.sensor, {V.user}, U.plain)}),
    "multilevel_sensor_all": (88, {r"49-0-.+": (T.decimal, R.sensor, {V.user}, None)}),
    "multilevel_sensor_scales": (40, {r"49-0-.+": (T.decimal, R.sensor, {V.user}, None)}),
    "meter_all": (
        36,
        {
            r"50-\d-value-\d+": (T.decimal, R.sensor, {V.user}, None),
            r"50-\d-reset(-\d+)?": (T.none, R.control, {V.setting}, U.plain),
        },
    ),
    "notification_all": (
        120,
        {
            r"113-0-alarm(Type|Level)": (T.integer, R.sensor, {V.setting}, U.plain),
            r"113-0-event-\d+": (T.enum, R.event, {V.user}, U.plain),
            r"113-0-details-\d+": (T.string, R.event, {V.system}, U.json),
            # diagnostics, not states people look at
            r"113-0-.+-(Maintenance|Periodic inspection|Dust in device|Test) status": (
                T.enum,
                R.sensor,
                {V.setting},
                U.plain,
            ),
            r"113-0-.+": (T.enum, R.sensor, {V.user, V.setting}, U.plain),  # states; diagnostics as settings
        },
    ),
    "thermostat_setpoint_all": (11, {r"67-0-setpoint-\d+": (T.decimal, R.control, {V.user}, U.celsius)}),
    "thermostat_mode_all": (1, {r"64-0-mode": (T.enum, R.control, {V.user}, U.plain)}),
}

# `user` parameters whose names are alike on purpose (the SDK's audit flags near-duplicates)
SIMILAR_NAMES: list[tuple[str, str]] = [
    ("Humidifier setpoint", "De-humidifier setpoint"),
    ("Heating setpoint", "Cooling setpoint"),
    ("Smoke state", "CO state"),
    ("Scene 1", "Scene 2"),
    ("Electric energy", "Electric power"),
    ("Production today", "Total production"),
]
