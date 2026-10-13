// How zwave-js reads one parameter of a device from our device files (its priority dir), at a firmware version.
// node device_config.mjs <priority dir> <manufacturer id> <product type> <product id> <firmware> <parameter>
import { ConfigManager } from "@zwave-js/config";

const [dir, manufacturer, type, id, firmware, number] = process.argv.slice(2);
const manager = new ConfigManager({ deviceConfigPriorityDir: dir });
await manager.loadAll();
const config = await manager.lookupDevice(Number(manufacturer), Number(type), Number(id), firmware);
const [, info] = [...(config?.paramInformation ?? [])].find(([key]) => key.parameter === Number(number)) ?? [];
console.log(JSON.stringify({ file: config?.filename, valueSize: info?.valueSize, options: info?.options.map((o) => o.value) }));
