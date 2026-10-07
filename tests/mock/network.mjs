// Mock Z-Wave network for the end-to-end tests: zwave-js's own mock controller and mock nodes (the ones its
// integration tests use), a real zwave-js driver on top, and a real zwave-js-server in front of it.
// The nodes already on the network are given as argv; the tests drive it over stdin, one JSON command per line ({"id", "cmd", ...}); each reply is a JSON line on stdout.
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";

import { ZwavejsServer } from "@zwave-js/server";
import {
	BatteryCCReport,
	BinarySwitchCCReport,
	EntryControlCCNotification,
	MultilevelSensorCCReport,
	MultilevelSwitchCCStartLevelChange,
	MultilevelSwitchCCStopLevelChange,
	NotificationCCReport,
	PowerlevelCCTestNodeReport,
	SceneActivationCCSet,
	WakeUpCCWakeUpNotification,
} from "@zwave-js/cc";
import { CommandClasses, SecurityClass, dskFromString, dskToString, nwiHomeIdFromDSK } from "@zwave-js/core";
import {
	AddNodeStatus,
	AddNodeToNetworkRequest,
	AddNodeToNetworkRequestStatusReport,
	AddNodeType,
	ApplicationUpdateRequestSmartStartHomeIDReceived,
	IsFailedNodeRequest,
	IsFailedNodeResponse,
	RemoveFailedNodeRequest,
	RemoveFailedNodeRequestStatusReport,
	RemoveFailedNodeResponse,
	RemoveFailedNodeStartFlags,
	RemoveFailedNodeStatus,
	RemoveNodeFromNetworkRequest,
	RemoveNodeFromNetworkRequestStatusReport,
	RemoveNodeStatus,
	RemoveNodeType,
} from "@zwave-js/serial/serialapi";
import { FunctionType } from "@zwave-js/serial";
import {
	MockController,
	MockNode,
	ccCaps,
	createMockZWaveRequestFrame,
	getDefaultSupportedFunctionTypes,
} from "@zwave-js/testing";
import { Bytes } from "@zwave-js/shared";
import { createAndStartDriverWithMockPort, createDefaultMockControllerBehaviors, createDefaultMockNodeBehaviors } from "zwave-js/Testing";

import { BEHAVIORS, RECIPES, qrCode } from "./catalogue.mjs";

// stdout carries the protocol only: the libraries' console output goes to stderr
console.log = console.info = console.debug = console.warn = console.error;

const HOME_ID = 0x7e570001;
const OWN_NODE_ID = 1;

// Every kind has the CCs a real device needs to be interviewed: identity (Manufacturer Specific, Version) and
// Z-Wave Plus Info. Manufacturer ids outside the device database, so no device file changes what is reported.
const BASE = [
	CommandClasses["Z-Wave Plus Info"],
	CommandClasses["Manufacturer Specific"],
	CommandClasses.Version,
];

let sensorValue = 21; // whole: a reading like this must still be a decimal

const KINDS = {
	switch: () => [ccCaps({ ccId: CommandClasses["Binary Switch"], version: 2, defaultValue: false })],
	// confirms (or refuses) each command through Supervision CC
	supervised: () => [
		CommandClasses.Supervision,
		ccCaps({ ccId: CommandClasses["Binary Switch"], version: 2, defaultValue: false }),
	],
	dimmer: () => [ccCaps({ ccId: CommandClasses["Multilevel Switch"], version: 4, defaultValue: 0, primarySwitchType: 2 })],
	bulb: () => [
		ccCaps({ ccId: CommandClasses["Multilevel Switch"], version: 4, defaultValue: 0, primarySwitchType: 2 }),
		ccCaps({ ccId: CommandClasses["Color Switch"], version: 3, colorComponents: { 2: 0, 3: 0, 4: 0 } }),
	],
	identifiable: () => [
		ccCaps({ ccId: CommandClasses["Binary Switch"], version: 2, defaultValue: false }),
		ccCaps({ ccId: CommandClasses.Indicator, version: 3, indicators: { 0x50: { properties: [3, 4, 5] } } }),
	],
	sensor: () => [
		ccCaps({
			ccId: CommandClasses["Multilevel Sensor"],
			version: 11,
			sensors: { 1: { supportedScales: [0] } }, // air temperature, °C
			getValue: () => sensorValue,
		}),
	],
	sensor_fahrenheit: () => [
		ccCaps({
			ccId: CommandClasses["Multilevel Sensor"],
			version: 11,
			sensors: { 1: { supportedScales: [1] } }, // air temperature, °F
			getValue: () => 69.8,
		}),
	],
	scene: () => [{ ccId: CommandClasses["Scene Activation"], version: 1, isSupported: true }],
	// a double wall switch: one relay per Multi Channel endpoint, each with the same CC and labels
	two_switches: () => ({
		commandClasses: [CommandClasses["Multi Channel"], ccCaps({ ccId: CommandClasses["Binary Switch"], version: 2, defaultValue: false })],
		endpoints: [1, 2].map(() => ({
			commandClasses: [ccCaps({ ccId: CommandClasses["Binary Switch"], version: 2, defaultValue: false })],
		})),
	}),
	secure: () => [
		CommandClasses["Security 2"],
		ccCaps({ ccId: CommandClasses["Binary Switch"], version: 2, secure: true, defaultValue: false }),
	],
	...RECIPES, // the catalogue: one kind per command class (catalogue.mjs)
};

function capabilities(kind, options = {}) {
	const make = KINDS[kind];
	if (!make) throw new Error(`unknown node kind ${kind}`);
	const made = make();
	const { commandClasses, ...node } = Array.isArray(made) ? { commandClasses: made } : made; // node: endpoints, flags
	return {
		manufacturerId: 0xfff0,
		productType: options.productType ?? 0x0001,
		productId: options.productId ?? 0x0001,
		commandClasses: [...BASE, ...commandClasses],
		...node,
		...(kind === "secure"
			? { securityClasses: new Set([options.access ? SecurityClass.S2_AccessControl : SecurityClass.S2_Authenticated]) }
			: {}),
	};
}

function withPayload(message, bytes) {
	message.payload = Bytes.from(bytes);
	return message;
}

class Network {
	failed = new Set(); // node ids the controller reports as failed
	silenced = new Set(); // node ids that stop responding (no ACK, no reply)
	rejecting = new Set(); // node ids that refuse commands
	removeCallbackId = undefined; // of the running exclusion, to complete it on request
	adding = false; // an inclusion is running (see the AddNodeToNetworkRequest behaviors)
	pendingDsk = undefined; // of the device waiting to join
	sequence = 0; // of the keypad's notifications

	async start(nodes) {
		this.cacheDir = await mkdtemp(path.join(tmpdir(), "zwave-mock-"));
		const securityKeys = {
			S0_Legacy: Bytes.from("0102030405060708090a0b0c0d0e0f10", "hex"),
			S2_Unauthenticated: Bytes.from("11111111111111111111111111111111", "hex"),
			S2_Authenticated: Bytes.from("22222222222222222222222222222222", "hex"),
			S2_AccessControl: Bytes.from("33333333333333333333333333333333", "hex"),
		};
		const { driver, continueStartup, mockPort, serial } = await createAndStartDriverWithMockPort({
			// ZWAVE_MOCK_LOG=<file>: the driver's debug log, to see what zwave-js made of the mock (stdout is the protocol)
			logConfig: process.env.ZWAVE_MOCK_LOG
				? { enabled: true, level: "debug", logToFile: true, filename: process.env.ZWAVE_MOCK_LOG }
				: { enabled: false },
			securityKeys,
			storage: { cacheDir: this.cacheDir, lockDir: path.join(this.cacheDir, "locks") },
			testingHooks: { skipFirmwareIdentification: true },
		});
		this.driver = driver;
		this.controller = await MockController.create({
			homeId: HOME_ID,
			ownNodeId: OWN_NODE_ID,
			mockPort,
			serial,
			securityKeys, // the network's keys: secure nodes bootstrap with them
			capabilities: {
				supportedFunctionTypes: [
					...getDefaultSupportedFunctionTypes(),
					FunctionType.IsFailedNode,
					FunctionType.RemoveFailedNode,
				],
			},
		});
		this.controller.defineBehavior(...createDefaultMockControllerBehaviors());
		this.controller.defineBehavior(...this.behaviors()); // defined later: checked before the defaults
		for (const spec of nodes) this.controller.addNode(await this.createNode(spec.node, spec.kind, spec));
		const ready = new Promise((resolve) => driver.once("all nodes ready", resolve));
		continueStartup();
		await ready;
	}

	// What the default mock controller lacks. These messages are normally only sent by the host or only parsed
	// by it, so the mock reads some requests' fields from the payload, and sets the replies' payload itself.
	behaviors() {
		const network = this;
		return [
			{
				// SmartStart, which the mock does not know: zwave-js listens for provisioned devices while it has some,
				// and includes one by its DSK when it asks to join (`power_on`)
				async onHostMessage(controller, msg) {
					if (!(msg instanceof AddNodeToNetworkRequest)) return;
					if (msg.addNodeType === AddNodeType.SmartStartListen) return true; // nothing to answer
					if (msg.addNodeType !== AddNodeType.SmartStartDSK || !controller.nodePendingInclusion) return;
					controller.state.set("inclusionState", 1); // the mock's AddingNode: its closing Stop reports Done
					network.adding = true;
					const ready = new AddNodeToNetworkRequestStatusReport({ callbackId: msg.callbackId, status: AddNodeStatus.Ready });
					await controller.sendMessageToHost(ready);
					void network.includePending(controller, msg.callbackId);
					return true;
				},
			},
			{
				async onHostMessage(controller, msg) {
					if (msg instanceof IsFailedNodeRequest) {
						const failed = network.failed.has(msg.payload[0]);
						await controller.sendMessageToHost(withPayload(new IsFailedNodeResponse({ result: failed }), [failed ? 1 : 0]));
						return true;
					}
				},
			},
			{
				async onHostMessage(controller, msg) {
					if (!(msg instanceof RemoveFailedNodeRequest)) return;
					const nodeId = msg.failedNodeId;
					const node = controller.nodes.get(nodeId);
					const removable = node && network.failed.has(nodeId);
					const started = removable ? RemoveFailedNodeStartFlags.OK : RemoveFailedNodeStartFlags.NodeNotFound;
					await controller.sendMessageToHost(withPayload(new RemoveFailedNodeResponse({ removeStatus: started }), [started]));
					if (removable) {
						controller.removeNode(node);
						network.failed.delete(nodeId);
						const status = RemoveFailedNodeStatus.NodeRemoved;
						const report = new RemoveFailedNodeRequestStatusReport({ callbackId: msg.callbackId, removeStatus: status });
						await controller.sendMessageToHost(withPayload(report, [msg.callbackId, status]));
					}
					return true;
				},
			},
			{
				// zwave-js stops inclusion twice (the second without callback); the default behavior takes a stop
				// while idle for a start, and then refuses the next inclusion: ignore it
				async onHostMessage(controller, msg) {
					if (!(msg instanceof AddNodeToNetworkRequest)) return;
					const stop = msg.addNodeType === AddNodeType.Stop;
					if (stop && !network.adding) return true;
					network.adding = !stop;
					return false;
				},
			},
			{
				// The default behavior only enters the exclusion state; remember the callback to finish it in `exclude`
				async onHostMessage(controller, msg) {
					if (msg instanceof RemoveNodeFromNetworkRequest && msg.removeNodeType !== RemoveNodeType.Stop) {
						network.removeCallbackId = msg.callbackId;
					}
					return false;
				},
			},
		];
	}

	nodeBehaviors(id, kind) {
		const network = this;
		return [
			...(BEHAVIORS[kind] ? [BEHAVIORS[kind](network, id)] : []), // what zwave-js's mock lacks for this kind
			{
				handleCC(controller, self, receivedCC) {
					if (network.silenced.has(id)) return { action: "stop" }; // out of range: no answer
					// rejects what it is told to do: a supervised command gets a Fail status back
					if (network.rejecting.has(id) && receivedCC.constructor.name.endsWith("Set")) return { action: "fail" };
				},
			},
		];
	}

	/** The inclusion the default AddNode behavior runs, for a SmartStart inclusion (the device in nodePendingInclusion). */
	async includePending(controller, callbackId) {
		const { setup, ...options } = controller.nodePendingInclusion;
		const node = await MockNode.create({ controller, ...options });
		node.defineBehavior(...createDefaultMockNodeBehaviors());
		setup?.(node);
		const supportedCCs = [...node.implementedCCs].filter(([, info]) => info.isSupported && info.version > 0).map(([id]) => id);
		const { basicDeviceClass, genericDeviceClass, specificDeviceClass } = node.capabilities;
		const nodeInfo = { nodeId: node.id, basicDeviceClass, genericDeviceClass, specificDeviceClass, supportedCCs };
		const report = (status, extra = {}) =>
			controller.sendMessageToHost(new AddNodeToNetworkRequestStatusReport({ callbackId, status, ...extra }));
		await new Promise((resolve) => setTimeout(resolve, 10));
		await report(AddNodeStatus.NodeFound);
		await new Promise((resolve) => setTimeout(resolve, 10));
		await report(AddNodeStatus.AddingSlave, { nodeInfo });
		await new Promise((resolve) => setTimeout(resolve, 10));
		controller.addNode(node);
		await report(AddNodeStatus.ProtocolDone);
	}

	silence(id, silent) {
		// out of range: frames to it are neither acknowledged nor answered
		if (silent) this.silenced.add(id);
		else this.silenced.delete(id);
		const node = this.controller.nodes.get(id);
		if (node) node.autoAckControllerFrames = !silent;
	}

	async createNode(id, kind, options) {
		const node = await MockNode.create({ id, controller: this.controller, capabilities: capabilities(kind, options) });
		node.defineBehavior(...createDefaultMockNodeBehaviors());
		node.defineBehavior(...this.nodeBehaviors(id, kind)); // checked before the defaults
		return node;
	}

	async startServer(port) {
		this.port = port ?? this.port;
		this.server = new ZwavejsServer(this.driver, { port: this.port, host: "127.0.0.1" });
		await this.server.start(true);
	}

	async handle(request) {
		const { cmd } = request;
		switch (cmd) {
			case "server": // start zwave-js-server on the given port (also after `drop_server`)
				await this.startServer(request.port);
				return { port: this.port };
			case "drop_server": // the server goes away: every client loses its connection
				await this.server.destroy();
				return {};
			case "join": {
				// a node waiting to be included: it joins once the controller starts inclusion
				const id = request.node;
				const caps = capabilities(request.kind, request);
				const network = this;
				// The PIN and DSK come from the node's key pair, generated when the node is created at inclusion:
				// generate it now, so the test knows them before including (as printed on a real device's label)
				const probe = await MockNode.create({ id, controller: this.controller, capabilities: caps });
				if (request.silent) this.silenced.add(id); // joins, then never answers: its interview cannot finish
				this.controller.nodePendingInclusion = {
					id,
					capabilities: caps,
					setup(node) {
						node.ecdhKeyPair = probe.ecdhKeyPair;
						node.defineBehavior(...network.nodeBehaviors(id, request.kind));
						node.autoAckControllerFrames = !network.silenced.has(id);
					},
				};
				// as zwave-js reads it from the key the node sends: its first 16 bytes (MockNode.dsk skips one byte)
				const dsk = dskToString(probe.ecdhKeyPair.publicKey.slice(0, 16));
				const keys = [...(caps.securityClasses ?? [])].reduce((mask, c) => mask | (1 << c), 0); // S2 classes 0..2
				const qr = qrCode({ dsk, requestedKeys: keys, ...caps, smartStart: Boolean(request.smartStart) });
				this.pendingDsk = dsk;
				return { pin: dsk.slice(0, 5), dsk, qr };
			}
			case "fail": // the controller reports the node as failed (it can be removed without the device)
				this.failed.add(request.node);
				this.silence(request.node, true);
				return {};
			case "silence":
				this.silence(request.node, true);
				return {};
			case "reject":
				this.rejecting.add(request.node);
				return {};
			case "wake": {
				// a sleeping device wakes up (its interval elapsed, or its button): it takes queued commands, then sleeps
				const node = this.controller.nodes.get(request.node);
				this.silence(request.node, false);
				const notification = new WakeUpCCWakeUpNotification({ nodeId: OWN_NODE_ID });
				await node.sendToController(createMockZWaveRequestFrame(notification, { ackRequested: false }));
				return {};
			}
			case "power_on": {
				// a provisioned (SmartStart) device is powered on: it asks the controller to include it
				if (!this.pendingDsk) throw new Error("no device waiting to join");
				const nwiHomeId = nwiHomeIdFromDSK(dskFromString(this.pendingDsk));
				const classes = { basicDeviceClass: 4, genericDeviceClass: 0x10, specificDeviceClass: 0x01 };
				const request = new ApplicationUpdateRequestSmartStartHomeIDReceived({ remoteNodeId: 0, nwiHomeId, ...classes, supportedCCs: [] });
				// remote node, rx status, NWI home id, CC list length, device classes (the update type is prepended)
				const payload = [0, 0, ...nwiHomeId, 0, classes.basicDeviceClass, classes.genericDeviceClass, classes.specificDeviceClass];
				await this.controller.sendMessageToHost(withPayload(request, payload));
				return {};
			}
			case "awake":
				return { awake: !this.silenced.has(request.node) };
			case "revive": {
				// the node answers again and announces itself with a report
				this.silence(request.node, false);
				this.failed.delete(request.node);
				await this.report({ node: request.node, kind: "switch", value: request.value ?? false });
				return {};
			}
			case "exclude": {
				// the user puts the device into exclusion mode while the controller is excluding
				const node = this.controller.nodes.get(request.node);
				if (!node || this.removeCallbackId === undefined) throw new Error("no exclusion running for this node");
				const callbackId = this.removeCallbackId;
				await this.controller.sendMessageToHost(new RemoveNodeFromNetworkRequestStatusReport({ callbackId, status: RemoveNodeStatus.NodeFound }));
				await this.controller.sendMessageToHost(
					new RemoveNodeFromNetworkRequestStatusReport({ callbackId, status: RemoveNodeStatus.RemovingSlave, nodeId: node.id }),
				);
				this.controller.removeNode(node);
				await this.controller.sendMessageToHost(
					new RemoveNodeFromNetworkRequestStatusReport({ callbackId, status: RemoveNodeStatus.Done, nodeId: node.id }),
				);
				return {};
			}
			case "report":
				await this.report(request);
				return {};
			case "frames": {
				// the CC commands a node received, by class name, for assertions on what was sent
				const node = this.controller.nodes.get(request.node);
				return { frames: (node?.receivedControllerFrames ?? []).map((f) => f.payload?.constructor?.name).filter(Boolean) };
			}
			case "nodes": // the node ids the controller knows
				return { nodes: [...this.controller.nodes.keys()].filter((id) => id !== OWN_NODE_ID) };
			case "stop":
				setImmediate(async () => {
					await this.stop();
					process.exit(0);
				});
				return {};
			default:
				throw new Error(`unknown command ${cmd}`);
		}
	}

	async report({ node: id, kind, value }) {
		const node = this.controller.nodes.get(id);
		if (!node) throw new Error(`no node ${id}`);
		const address = { nodeId: OWN_NODE_ID };
		let cc;
		if (kind === "switch") cc = new BinarySwitchCCReport({ ...address, currentValue: value });
		else if (kind === "sensor") {
			sensorValue = value;
			cc = new MultilevelSensorCCReport({ ...address, type: 1, scale: 0, value });
		} else if (kind === "scene") cc = new SceneActivationCCSet({ ...address, sceneId: value });
		// what devices send as notifications (zwave-js "notification" events), `value` shaped per kind
		else if (kind === "keypad") {
			const { eventType, code } = value; // e.g. 2 (enter) and "1234"
			const data = code === undefined ? { dataType: 0 } : { dataType: 2, eventData: code }; // none, or ASCII
			cc = new EntryControlCCNotification({ ...address, sequenceNumber: ++this.sequence, eventType, ...data });
		} else if (kind === "notification") {
			const { type, event, parameters } = value; // e.g. 6 (access control), 5 (keypad lock), [3] (user 3)
			const extra = parameters ? { eventParameters: Bytes.from(parameters) } : {};
			const report = { notificationType: type, notificationEvent: event, notificationStatus: 0xff, ...extra };
			cc = new NotificationCCReport({ ...address, ...report });
		} else if (kind === "level_change") {
			cc =
				value === "stop"
					? new MultilevelSwitchCCStopLevelChange(address)
					: new MultilevelSwitchCCStartLevelChange({ ...address, direction: value, ignoreStartLevel: true });
		} else if (kind === "battery_low") {
			cc = new BatteryCCReport({ ...address, level: "low" });
		} else if (kind === "powerlevel") {
			cc = new PowerlevelCCTestNodeReport({ ...address, testNodeId: 1, status: value, acknowledgedFrames: 10 });
		} else throw new Error(`unknown report ${kind}`);
		await node.sendToController(createMockZWaveRequestFrame(cc, { ackRequested: false }));
	}

	async stop() {
		await this.server?.destroy().catch(() => {});
		await this.driver?.destroy().catch(() => {});
		await rm(this.cacheDir, { recursive: true, force: true });
	}
}

// argv: {"nodes": [{"node": 5, "kind": "switch"}, ...]}, the nodes already included when the network starts
const { nodes = [] } = JSON.parse(process.argv[2] ?? "{}");
const network = new Network();
await network.start(nodes);
const print = (message) => process.stdout.write(`${JSON.stringify(message)}\n`);
print({ ready: true });

const lines = createInterface({ input: process.stdin });
for await (const line of lines) {
	if (!line.trim()) continue;
	const request = JSON.parse(line);
	try {
		print({ id: request.id, ok: true, result: await network.handle(request) });
	} catch (error) {
		print({ id: request.id, ok: false, error: String(error?.stack ?? error) });
	}
}
await network.stop();
