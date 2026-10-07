// The entity catalogue of the mock network: one device kind per command class zwave-js's mock can host, each with
// every capability of that CC switched on; behaviors for common CCs zwave-js does not mock (scene buttons,
// thermostat fan and state, garage doors, and Battery and Wake Up for a sleeping device); and a builder for S2 QR
// codes. tests/catalogue.py lists the same recipes, and why every other CC is not one.
import { createHash } from "node:crypto";

import {
	AlarmSensorCCGet,
	AlarmSensorCCReport,
	AlarmSensorCCSupportedGet,
	AlarmSensorCCSupportedReport,
	BarrierOperatorCCEventSignalingGet,
	BarrierOperatorCCEventSignalingReport,
	BarrierOperatorCCEventSignalingSet,
	BarrierOperatorCCGet,
	BarrierOperatorCCReport,
	BarrierOperatorCCSet,
	BarrierOperatorCCSignalingCapabilitiesGet,
	BarrierOperatorCCSignalingCapabilitiesReport,
	BatteryCCGet,
	BatteryCCReport,
	CentralSceneCCConfigurationGet,
	CentralSceneCCConfigurationReport,
	CentralSceneCCConfigurationSet,
	CentralSceneCCSupportedGet,
	CentralSceneCCSupportedReport,
	EntryControlCCConfigurationGet,
	EntryControlCCConfigurationReport,
	EntryControlCCConfigurationSet,
	EntryControlCCEventSupportedGet,
	EntryControlCCEventSupportedReport,
	EntryControlCCKeySupportedGet,
	EntryControlCCKeySupportedReport,
	HumidityControlModeCCGet,
	HumidityControlModeCCReport,
	HumidityControlModeCCSet,
	HumidityControlModeCCSupportedGet,
	HumidityControlModeCCSupportedReport,
	HumidityControlOperatingStateCCGet,
	HumidityControlOperatingStateCCReport,
	HumidityControlSetpointCCCapabilitiesGet,
	HumidityControlSetpointCCCapabilitiesReport,
	HumidityControlSetpointCCGet,
	HumidityControlSetpointCCReport,
	HumidityControlSetpointCCScaleSupportedGet,
	HumidityControlSetpointCCScaleSupportedReport,
	HumidityControlSetpointCCSet,
	HumidityControlSetpointCCSupportedGet,
	HumidityControlSetpointCCSupportedReport,
	ProtectionCCGet,
	ProtectionCCReport,
	ProtectionCCSet,
	ProtectionCCSupportedGet,
	ProtectionCCSupportedReport,
	ThermostatFanModeCCGet,
	ThermostatFanModeCCReport,
	ThermostatFanModeCCSet,
	ThermostatFanModeCCSupportedGet,
	ThermostatFanModeCCSupportedReport,
	ThermostatFanStateCCGet,
	ThermostatFanStateCCReport,
	ThermostatOperatingStateCCGet,
	ThermostatOperatingStateCCReport,
	ThermostatSetpointCCSet,
	WakeUpCCIntervalCapabilitiesGet,
	WakeUpCCIntervalCapabilitiesReport,
	WakeUpCCIntervalGet,
	WakeUpCCIntervalReport,
	WakeUpCCIntervalSet,
	WakeUpCCNoMoreInformation,
} from "@zwave-js/cc";
import { BinarySensorType, ThermostatMode, ThermostatSetpointType } from "@zwave-js/cc";
import { CommandClasses, getAllMeters, getAllNotifications, getAllSensors } from "@zwave-js/core";
import { ccCaps } from "@zwave-js/testing";

const cc = (ccId, version, capabilities = {}) => ccCaps({ ccId, version, ...capabilities });
const members = (enumeration) => Object.values(enumeration).filter((value) => typeof value === "number");
const level = () => cc(CommandClasses["Multilevel Switch"], 4, { defaultValue: 0, primarySwitchType: 2 });

export const RECIPES = {
	basic: () => [cc(CommandClasses.Basic, 2)],
	binary_sensor: () => [cc(CommandClasses["Binary Sensor"], 2, { supportedSensorTypes: [1, 10, 12] })], // general, door/window, motion
	binary_switch: () => [cc(CommandClasses["Binary Switch"], 2, { defaultValue: false })],
	color_switch: () => [
		level(),
		cc(CommandClasses["Color Switch"], 2, { colorComponents: { 0: 0, 1: 0, 2: 0, 3: 0, 4: 0 } }), // white + RGB
	],
	configuration: () => [
		cc(CommandClasses.Configuration, 4, {
			parameters: [
				{ "#": 1, valueSize: 1, name: "Brightness on power-up", minValue: 0, maxValue: 99, defaultValue: 50, format: 1 },
				{ "#": 2, valueSize: 1, name: "LED mode", minValue: 0, maxValue: 2, defaultValue: 0, format: 2 }, // enumerated
				{ "#": 3, valueSize: 2, name: "Offset", minValue: -100, maxValue: 100, defaultValue: 0, format: 0 }, // signed
				{ "#": 4, valueSize: 1, name: "Firmware flags", minValue: 0, maxValue: 255, defaultValue: 7, format: 1, readonly: true },
			],
		}),
	],
	door_lock: () => [
		cc(CommandClasses["Door Lock"], 4, {
			supportedOperationTypes: [1, 2], // constant, timed
			supportedDoorLockModes: [0, 1, 255], // unsecured, unsecured with timeout, secured
			autoRelockSupported: true,
			holdAndReleaseSupported: true,
			blockToBlockSupported: true,
			twistAssistSupported: true,
		}),
	],
	energy_production: () => [cc(CommandClasses["Energy Production"], 1)],
	indicator: () => [cc(CommandClasses.Indicator, 3, { indicators: { 0x50: { properties: [3, 4, 5] }, 0x43: { properties: [2] } } })],
	lock: () => [cc(CommandClasses.Lock, 1)],
	meter: () => [
		cc(CommandClasses.Meter, 6, { meterType: 1, supportedScales: [0, 2, 4, 5], supportedRateTypes: [1], supportsReset: true }),
	], // electric: kWh, W, V, A
	multilevel_sensor: () => [
		cc(CommandClasses["Multilevel Sensor"], 11, {
			sensors: { 1: { supportedScales: [0] }, 3: { supportedScales: [1] }, 5: { supportedScales: [0] } }, // °C, lux, %
			getValue: (type) => ({ 1: 21, 3: 350, 5: 40 })[type],
		}),
	],
	multilevel_switch: () => [level()],
	node_naming: () => [cc(CommandClasses["Node Naming and Location"], 1, { name: "Hall", location: "Upstairs" })],
	notification: () => [
		cc(CommandClasses.Notification, 8, {
			// water, access (manual and keypad lock/unlock: events), security
			notificationTypesAndEvents: { 0x05: [0x02], 0x06: [0x01, 0x02, 0x05, 0x06], 0x07: [0x03, 0x08] },
		}),
	],
	scene_activation: () => [{ ccId: CommandClasses["Scene Activation"], version: 1, isSupported: true }],
	schedule_entry_lock: () => [
		cc(CommandClasses["User Code"], 2, { numUsers: 2 }),
		cc(CommandClasses["Schedule Entry Lock"], 3, { numWeekDaySlots: 1, numYearDaySlots: 1, numDailyRepeatingSlots: 1 }),
	],
	sound_switch: () => [
		cc(CommandClasses["Sound Switch"], 2, {
			defaultToneId: 1,
			defaultVolume: 50,
			tones: [
				{ name: "Beep", duration: 1 },
				{ name: "Chime", duration: 3 },
			],
		}),
	],
	thermostat_mode: () => [cc(CommandClasses["Thermostat Mode"], 3, { supportedModes: [0, 1, 2, 3] })], // off, heat, cool, auto
	thermostat_setback: () => [cc(CommandClasses["Thermostat Setback"], 1)],
	thermostat_setpoint: () => [
		cc(CommandClasses["Thermostat Setpoint"], 3, {
			setpoints: {
				1: { minValue: 5, maxValue: 30, defaultValue: 20, scale: "°C" }, // heating
				2: { minValue: 50, maxValue: 95, defaultValue: 77, scale: "°F" }, // cooling, in °F
			},
		}),
	],
	user_code: () => [cc(CommandClasses["User Code"], 2, { numUsers: 2 })],
	user_credential: () => [cc(CommandClasses["User Credential"], 1, { numberOfSupportedUsers: 2 })],
	window_covering: () => [
		cc(CommandClasses["Window Covering"], 1, { supportedParameters: [13, 23], travelTime: 0 }), // outbound bottom, slats angle
	],
	// Every variant zwave-js knows of the CCs with many (its registries): sensor types, meters and their scales,
	// notification types and their states and events, setpoint types, thermostat modes
	binary_sensor_all: () => [
		cc(CommandClasses["Binary Sensor"], 2, { supportedSensorTypes: members(BinarySensorType).filter((t) => t !== 0xff) }),
	],
	multilevel_sensor_all: () => [
		cc(CommandClasses["Multilevel Sensor"], 11, {
			sensors: Object.fromEntries(getAllSensors().map((s) => [s.key, { supportedScales: [Number(Object.keys(s.scales)[0])] }])),
			getValue: () => 1,
		}),
	],
	multilevel_sensor_scales: () => [
		// the other scales of each sensor (a sensor reports in one scale at a time): every unit zwave-js knows
		cc(CommandClasses["Multilevel Sensor"], 11, {
			sensors: Object.fromEntries(
				getAllSensors()
					.filter((s) => Object.keys(s.scales).length > 1)
					.map((s) => [s.key, { supportedScales: [Number(Object.keys(s.scales).at(-1))] }]),
			),
			getValue: () => 1,
		}),
	],
	meter_all: () => ({
		// one meter per endpoint; Multi Channel v4 discovers endpoints the root does not mirror (v1 only counts those)
		commandClasses: [cc(CommandClasses["Multi Channel"], 4)],
		endpoints: getAllMeters().map((meter) => ({
			commandClasses: [
				cc(CommandClasses.Meter, 6, {
					meterType: meter.key,
					supportedScales: Object.keys(meter.scales).map(Number),
					supportedRateTypes: [1],
					supportsReset: true,
				}),
			],
		})),
	}),
	notification_all: () => [
		cc(CommandClasses.Notification, 8, {
			notificationTypesAndEvents: Object.fromEntries(
				getAllNotifications().map((n) => [
					n.type,
					[...n.variables.flatMap((variable) => [...variable.states.keys()]), ...n.events.keys()],
				]),
			),
		}),
	],
	thermostat_setpoint_all: () => [
		cc(CommandClasses["Thermostat Setpoint"], 3, {
			setpoints: Object.fromEntries(
				members(ThermostatSetpointType)
					.filter((t) => t !== 0)
					.map((t) => [t, { minValue: 5, maxValue: 35, defaultValue: 20, scale: "°C" }]),
			),
		}),
	],
	thermostat_mode_all: () => [cc(CommandClasses["Thermostat Mode"], 3, { supportedModes: members(ThermostatMode) })],
	// Not mocked by zwave-js: see BEHAVIORS
	central_scene: () => [{ ccId: CommandClasses["Central Scene"], version: 3, isSupported: true }],
	thermostat_fan_mode: () => [{ ccId: CommandClasses["Thermostat Fan Mode"], version: 3, isSupported: true }],
	thermostat_fan_state: () => [{ ccId: CommandClasses["Thermostat Fan State"], version: 1, isSupported: true }],
	thermostat_operating_state: () => [{ ccId: CommandClasses["Thermostat Operating State"], version: 1, isSupported: true }],
	barrier_operator: () => [{ ccId: CommandClasses["Barrier Operator"], version: 1, isSupported: true }],
	protection: () => [
		cc(CommandClasses["Binary Switch"], 2, { defaultValue: false }), // a plug with a child lock
		{ ccId: CommandClasses.Protection, version: 2, isSupported: true },
	],
	humidity_control: () => [
		{ ccId: CommandClasses["Humidity Control Setpoint"], version: 2, isSupported: true },
		{ ccId: CommandClasses["Humidity Control Mode"], version: 2, isSupported: true },
		{ ccId: CommandClasses["Humidity Control Operating State"], version: 1, isSupported: true },
	],
	entry_control: () => [{ ccId: CommandClasses["Entry Control"], version: 1, isSupported: true }], // a keypad
	alarm_sensor: () => [{ ccId: CommandClasses["Alarm Sensor"], version: 2, isSupported: true }], // older smoke / CO
	powerlevel: () => [
		cc(CommandClasses["Binary Switch"], 2, { defaultValue: false }),
		{ ccId: CommandClasses.Powerlevel, version: 1, isSupported: true }, // a radio test's results arrive as notifications
	],
	// Not a CC of its own: a battery device that sleeps between wake-ups (Wake Up CC), here a sleeping switch
	sleeping: () => ({
		commandClasses: [
			cc(CommandClasses["Binary Switch"], 2, { defaultValue: false }),
			{ ccId: CommandClasses.Battery, version: 1, isSupported: true },
			{ ccId: CommandClasses["Wake Up"], version: 2, isSupported: true },
		],
		isListening: false,
		isFrequentListening: false,
	}),
};

// A device's state between commands, for the behaviors below
const state = (self, key, initial) => (self.state.has(key) ? self.state.get(key) : initial);

/** Behaviors zwave-js's mock lacks, by device kind: each answers its CC's Get/Set like a real device would. */
export const BEHAVIORS = {
	// zwave-js 15.31's mock refuses every setpoint above the minimum (`value > min || value > max`): a correct Set,
	// stored under the mock's own state keys so its Get reports it
	thermostat_setpoint: () => ({
		handleCC(controller, self, receivedCC) {
			if (!(receivedCC instanceof ThermostatSetpointCCSet)) return;
			const { setpoints } = self.getCCCapabilities(CommandClasses["Thermostat Setpoint"], receivedCC.endpointIndex);
			const limits = setpoints?.[receivedCC.setpointType];
			if (!limits || receivedCC.value < limits.minValue || receivedCC.value > limits.maxValue) return { action: "fail" };
			self.state.set(`ThermostatSetpoint_setpoint_${receivedCC.setpointType}`, receivedCC.value);
			self.state.set(`ThermostatSetpoint_scale_${receivedCC.setpointType}`, receivedCC.scale);
			return { action: "ok" };
		},
	}),
	central_scene: () => ({
		handleCC(controller, self, receivedCC) {
			const address = { nodeId: controller.ownNodeId };
			if (receivedCC instanceof CentralSceneCCSupportedGet) {
				const keys = [0, 1, 2, 3]; // pressed, released, held down, pressed twice
				const report = new CentralSceneCCSupportedReport({
					...address,
					sceneCount: 2,
					supportsSlowRefresh: true,
					supportedKeyAttributes: { 1: keys, 2: keys },
				});
				return { action: "sendCC", cc: report };
			}
			if (receivedCC instanceof CentralSceneCCConfigurationGet) {
				const slowRefresh = state(self, "slowRefresh", false);
				return { action: "sendCC", cc: new CentralSceneCCConfigurationReport({ ...address, slowRefresh }) };
			}
			if (receivedCC instanceof CentralSceneCCConfigurationSet) {
				self.state.set("slowRefresh", receivedCC.slowRefresh);
				return { action: "ok" };
			}
		},
	}),
	thermostat_fan_mode: () => ({
		handleCC(controller, self, receivedCC) {
			const address = { nodeId: controller.ownNodeId };
			if (receivedCC instanceof ThermostatFanModeCCSupportedGet) {
				const report = new ThermostatFanModeCCSupportedReport({ ...address, supportedModes: [0, 1, 3, 6] });
				return { action: "sendCC", cc: report }; // auto low, low, high, circulation
			}
			if (receivedCC instanceof ThermostatFanModeCCGet) {
				const report = new ThermostatFanModeCCReport({ ...address, mode: state(self, "fanMode", 0), off: state(self, "fanOff", false) });
				return { action: "sendCC", cc: report };
			}
			if (receivedCC instanceof ThermostatFanModeCCSet) {
				self.state.set("fanMode", receivedCC.mode);
				if (receivedCC.off !== undefined) self.state.set("fanOff", receivedCC.off);
				return { action: "ok" };
			}
		},
	}),
	thermostat_fan_state: () => ({
		handleCC(controller, self, receivedCC) {
			if (receivedCC instanceof ThermostatFanStateCCGet) {
				return { action: "sendCC", cc: new ThermostatFanStateCCReport({ nodeId: controller.ownNodeId, state: 1 }) }; // running
			}
		},
	}),
	thermostat_operating_state: () => ({
		handleCC(controller, self, receivedCC) {
			if (receivedCC instanceof ThermostatOperatingStateCCGet) {
				return { action: "sendCC", cc: new ThermostatOperatingStateCCReport({ nodeId: controller.ownNodeId, state: 1 }) }; // heating
			}
		},
	}),
	barrier_operator: () => ({
		handleCC(controller, self, receivedCC) {
			const address = { nodeId: controller.ownNodeId };
			const report = () => {
				const open = state(self, "barrierOpen", false);
				return new BarrierOperatorCCReport({ ...address, currentState: open ? 255 : 0, position: open ? 100 : 0 });
			};
			if (receivedCC instanceof BarrierOperatorCCGet) return { action: "sendCC", cc: report() };
			if (receivedCC instanceof BarrierOperatorCCSet) {
				self.state.set("barrierOpen", receivedCC.targetState === 255); // a garage door that opens at once
				return { action: "sendCC", cc: report() };
			}
			if (receivedCC instanceof BarrierOperatorCCSignalingCapabilitiesGet) {
				const capabilities = new BarrierOperatorCCSignalingCapabilitiesReport({ ...address, supportedSubsystemTypes: [1, 2] });
				return { action: "sendCC", cc: capabilities }; // audible, visual
			}
			if (receivedCC instanceof BarrierOperatorCCEventSignalingGet) {
				const subsystemType = receivedCC.subsystemType;
				const subsystemState = state(self, `signaling${subsystemType}`, 255);
				return { action: "sendCC", cc: new BarrierOperatorCCEventSignalingReport({ ...address, subsystemType, subsystemState }) };
			}
			if (receivedCC instanceof BarrierOperatorCCEventSignalingSet) {
				self.state.set(`signaling${receivedCC.subsystemType}`, receivedCC.subsystemState);
				return { action: "ok" };
			}
		},
	}),
	protection: () => ({
		handleCC(controller, self, receivedCC) {
			const address = { nodeId: controller.ownNodeId };
			if (receivedCC instanceof ProtectionCCSupportedGet) {
				const report = new ProtectionCCSupportedReport({
					...address,
					supportsTimeout: false,
					supportsExclusiveControl: false,
					supportedLocalStates: [0, 1, 2], // unprotected, by sequence, no operation possible
					supportedRFStates: [0, 1], // unprotected, no control
				});
				return { action: "sendCC", cc: report };
			}
			if (receivedCC instanceof ProtectionCCGet) {
				const report = new ProtectionCCReport({ ...address, local: state(self, "local", 0), rf: state(self, "rf", 0) });
				return { action: "sendCC", cc: report };
			}
			if (receivedCC instanceof ProtectionCCSet) {
				self.state.set("local", receivedCC.local);
				if (receivedCC.rf !== undefined) self.state.set("rf", receivedCC.rf);
				return { action: "ok" };
			}
		},
	}),
	humidity_control: () => ({
		handleCC(controller, self, receivedCC) {
			const address = { nodeId: controller.ownNodeId };
			if (receivedCC instanceof HumidityControlSetpointCCSupportedGet) {
				const report = new HumidityControlSetpointCCSupportedReport({ ...address, supportedSetpointTypes: [1, 2] });
				return { action: "sendCC", cc: report }; // humidifier, de-humidifier
			}
			if (receivedCC instanceof HumidityControlSetpointCCScaleSupportedGet) {
				return { action: "sendCC", cc: new HumidityControlSetpointCCScaleSupportedReport({ ...address, supportedScales: [0] }) }; // %
			}
			if (receivedCC instanceof HumidityControlSetpointCCCapabilitiesGet) {
				const report = new HumidityControlSetpointCCCapabilitiesReport({
					...address,
					type: receivedCC.setpointType,
					minValue: 10,
					maxValue: 90,
					minValueScale: 0,
					maxValueScale: 0,
				});
				return { action: "sendCC", cc: report };
			}
			if (receivedCC instanceof HumidityControlSetpointCCGet) {
				const type = receivedCC.setpointType;
				const value = state(self, `humidity${type}`, 50);
				return { action: "sendCC", cc: new HumidityControlSetpointCCReport({ ...address, type, scale: 0, value }) };
			}
			if (receivedCC instanceof HumidityControlSetpointCCSet) {
				self.state.set(`humidity${receivedCC.setpointType}`, receivedCC.value);
				return { action: "ok" };
			}
			if (receivedCC instanceof HumidityControlModeCCSupportedGet) {
				const report = new HumidityControlModeCCSupportedReport({ ...address, supportedModes: [0, 1, 2, 3] });
				return { action: "sendCC", cc: report }; // off, humidify, de-humidify, auto
			}
			if (receivedCC instanceof HumidityControlModeCCGet) {
				return { action: "sendCC", cc: new HumidityControlModeCCReport({ ...address, mode: state(self, "humidityMode", 0) }) };
			}
			if (receivedCC instanceof HumidityControlModeCCSet) {
				self.state.set("humidityMode", receivedCC.mode);
				return { action: "ok" };
			}
			if (receivedCC instanceof HumidityControlOperatingStateCCGet) {
				return { action: "sendCC", cc: new HumidityControlOperatingStateCCReport({ ...address, state: 0 }) }; // idle
			}
		},
	}),
	entry_control: () => ({
		handleCC(controller, self, receivedCC) {
			const address = { nodeId: controller.ownNodeId };
			if (receivedCC instanceof EntryControlCCKeySupportedGet) {
				const digits = [...Array(10).keys()].map((d) => 0x30 + d); // the keypad's 0-9
				return { action: "sendCC", cc: new EntryControlCCKeySupportedReport({ ...address, supportedKeys: digits }) };
			}
			if (receivedCC instanceof EntryControlCCEventSupportedGet) {
				const report = new EntryControlCCEventSupportedReport({
					...address,
					supportedDataTypes: [2], // ASCII
					supportedEventTypes: [2, 3, 5, 6, 25], // enter, disarm all, arm away, arm home, cancel
					minKeyCacheSize: 1,
					maxKeyCacheSize: 32,
					minKeyCacheTimeout: 1,
					maxKeyCacheTimeout: 10,
				});
				return { action: "sendCC", cc: report };
			}
			if (receivedCC instanceof EntryControlCCConfigurationGet) {
				const report = new EntryControlCCConfigurationReport({
					...address,
					keyCacheSize: state(self, "keyCacheSize", 4),
					keyCacheTimeout: state(self, "keyCacheTimeout", 5),
				});
				return { action: "sendCC", cc: report };
			}
			if (receivedCC instanceof EntryControlCCConfigurationSet) {
				self.state.set("keyCacheSize", receivedCC.keyCacheSize);
				self.state.set("keyCacheTimeout", receivedCC.keyCacheTimeout);
				return { action: "ok" };
			}
		},
	}),
	alarm_sensor: () => ({
		handleCC(controller, self, receivedCC) {
			const address = { nodeId: controller.ownNodeId };
			if (receivedCC instanceof AlarmSensorCCSupportedGet) {
				return { action: "sendCC", cc: new AlarmSensorCCSupportedReport({ ...address, supportedSensorTypes: [1, 2] }) }; // smoke, CO
			}
			if (receivedCC instanceof AlarmSensorCCGet) {
				const report = new AlarmSensorCCReport({ ...address, sensorType: receivedCC.sensorType, state: false, severity: 0, duration: 0 });
				return { action: "sendCC", cc: report };
			}
		},
	}),
	sleeping: (network, id) => ({
		handleCC(controller, self, receivedCC) {
			const address = { nodeId: controller.ownNodeId };
			if (receivedCC instanceof BatteryCCGet) {
				return { action: "sendCC", cc: new BatteryCCReport({ ...address, level: 87, isLow: false }) };
			}
			if (receivedCC instanceof WakeUpCCIntervalCapabilitiesGet) {
				const report = new WakeUpCCIntervalCapabilitiesReport({
					...address,
					minWakeUpInterval: 300,
					maxWakeUpInterval: 86400,
					defaultWakeUpInterval: 3600,
					wakeUpIntervalSteps: 60,
					wakeUpOnDemandSupported: false,
				});
				return { action: "sendCC", cc: report };
			}
			if (receivedCC instanceof WakeUpCCIntervalGet) {
				const interval = self.state.get("wakeUpInterval") ?? 3600;
				return {
					action: "sendCC",
					cc: new WakeUpCCIntervalReport({ ...address, wakeUpInterval: interval, controllerNodeId: 1 }),
				};
			}
			if (receivedCC instanceof WakeUpCCIntervalSet) {
				self.state.set("wakeUpInterval", receivedCC.wakeUpInterval);
				return { action: "ok" };
			}
			if (receivedCC instanceof WakeUpCCNoMoreInformation) {
				network.silence(id, true); // back to sleep: the radio is off until the next wake-up
				return { action: "stop" };
			}
		},
	}),
};

/** An S2 QR code for a device (version 0, or 1 for SmartStart): the format zwave-js parses (packages/core/src/qr). */
export function qrCode({ dsk, requestedKeys, manufacturerId, productType, productId, smartStart = false }) {
	const d5 = (n) => String(n).padStart(5, "0");
	const tlv = (type, data) => `${String(type << 1).padStart(2, "0")}${String(data.length).padStart(2, "0")}${data}`;
	const body =
		String(requestedKeys).padStart(3, "0") +
		dsk.replaceAll("-", "") +
		tlv(0, d5((0x10 << 8) | 0x01) + d5(0x0700)) + // product type: binary switch, power switch; installer icon
		tlv(1, d5(manufacturerId) + d5(productType) + d5(productId) + d5(0x0100)); // product id, app version 1.0
	const checksum = createHash("sha1").update(body).digest().readUInt16BE(0);
	return `90${smartStart ? "01" : "00"}${d5(checksum)}${body}`;
}
