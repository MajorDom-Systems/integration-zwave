// What zwave-js knows, for the drift checks (tests/test_catalogue.py): its command classes, the value metadata types,
// the units of its sensor, meter and named scales, and the harness's catalogue recipes. Prints one JSON object.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import * as core from "@zwave-js/core";

import { RECIPES } from "./catalogue.mjs";

const commandClasses = Object.fromEntries(
	Object.entries(core.CommandClasses).filter(([, id]) => typeof id === "number").map(([name, id]) => [id, name]),
);

// ValueType is a TypeScript type only: read it from the declarations
const require = createRequire(import.meta.url);
const coreDir = path.dirname(require.resolve("@zwave-js/core/package.json"));
const declarations = readFileSync(path.join(coreDir, "build/esm/values/Metadata.d.ts"), "utf8");
const union = declarations.match(/export type ValueType = ([^;]+);/)?.[1] ?? "";
const valueTypes = [...union.matchAll(/"([^"]+)"/g)].map((m) => m[1]);

const units = new Set();
const add = (scale) => scale?.unit && units.add(scale.unit);
for (const sensor of core.getAllSensors()) Object.values(sensor.scales ?? {}).forEach(add);
for (const group of Object.values(core.getAllNamedScaleGroups())) Object.values(group).forEach(add);
for (const meter of core.getAllMeters()) Object.values(meter.scales ?? {}).forEach(add);

const recipes = Object.keys(RECIPES);
process.stdout.write(JSON.stringify({ commandClasses, valueTypes, units: [...units].sort(), recipes }));
