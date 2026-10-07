<!-- MajorDom Project Banner -->
<a href="https://majordom.io" target="_blank">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="https://markparker.me/banners/majordom-dark.webp"
    />
    <img
      alt="Part of MajorDom — the next-gen smart home"
      src="https://markparker.me/banners/majordom-light.webp"
    />
  </picture>
</a>

# integration-zwave

A [MajorDom](https://majordom.io) integration — bridges **Z-Wave** devices into the MajorDom
language.

Built for the **MajorDom Hub**, but it doesn't need it: this is a standalone, standardized
library for Z-Wave that you can use on its own (see **Run it standalone** below). Built on the
[MajorDom Integration SDK](https://github.com/MajorDom-Systems/integration-sdk). The entry point
is `ZwaveController` (`majordom_zwave/controller.py`), which the Hub — or the SDK's dev runner —
instantiates and drives through its lifecycle: pairing → commands → teardown.

- **Other protocols:** browse the [MajorDom integrations](https://github.com/orgs/MajorDom-Systems/repositories?q=integration-).
- **Create your own:** start from the [integration template](https://github.com/MajorDom-Systems/integration-template).

## Documentation

Full integration-author docs — the controller lifecycle, data models, storing data, discovery,
and a worked example — live at **[docs.majordom.io](https://docs.majordom.io/device-integration)**.

## Development

```sh
poetry install && poetry run poe install
```

| Task | Description |
|------|-------------|
| `poe check` | Full quality pipeline (ruff, ty, pytest, poetry build/check) |
| `poe check --ci` | Same, plus `git diff --exit-code` |

Work lands on `develop`; `master` is protected and released via **Actions → Release**.

Tests drive the controller with the SDK's test doubles against a **mock Z-Wave network**: zwave-js's own
mock controller and mock devices, with a real zwave-js driver and a real `zwave-js-server` in front
(`tests/mock`) — the integration connects to it exactly as to a real server, no radio or stick required.
It needs Node.js 20+:

```sh
npm ci --prefix tests/mock && poetry run pytest
```

### Command-class catalogue and canary

`tests/test_catalogue.py` accounts for every command class zwave-js knows (125 today): each is hosted by a mock
device (a recipe in `tests/mock/catalogue.mjs`: 34 of them, all their capabilities switched on), is protocol plumbing,
or is listed in `tests/catalogue.py` with the reason the mock cannot host it. Each hosted one must map exactly as
`EXPECTED` says — name, type, role, visibility, unit, main parameter, reviewed value by value against the docs'
[parameter UX](https://docs.majordom.io/device-integration/parameter-ux) — pass the SDK's `parameter_audit`, and
round-trip every writable value through the device. Seven more mock devices carry *every* variant zwave-js knows
(88 sensor types and their scales, 14 binary sensors, 5 meters with all their scales, 22 notification types with all
their states and events, 12 setpoints, 16 thermostat modes), checked against rules. Fast checks fail on a new command
class, value metadata type or unit.

The monthly **canary** (`.github/workflows/canary.yml`) runs all of it against the latest zwave-js, zwave-js-server
and zwave-js-server-python: red means upstream shipped something to support, or to explain.

## Run it standalone (without the Hub)

`majordom-zwave` is a standalone library — import it into your own app, or run **just this
integration** interactively (discover, pair, control, and inspect devices from a prompt) with no Hub.
It needs a reachable `zwave-js-server` instance (see below).

See **[Standalone mode](https://docs.majordom.io/device-integration/standalone)** for the interactive
CLI, watch mode, and the programmatic API.

## Connecting to zwave-js-server

Unlike a radio-based integration, this one never talks to the Z-Wave stick directly. It connects
over WebSocket, via [`zwave-js-server-python`](https://github.com/home-assistant-libs/zwave-js-server-python),
to a running **[zwave-js-server](https://github.com/zwave-js/zwave-js-server)** process (Node.js) —
the same server Home Assistant's Z-Wave JS integration uses. `zwave-js-server` is what actually owns
the serial connection to the Z-Wave USB controller and speaks the Z-Wave protocol; this integration
just talks JSON over a WebSocket to it.

- Run `zwave-js-server` yourself (commonly via Docker) on whatever machine has the Z-Wave USB
  controller attached.
- Point this integration at it with the `ZWAVE_SERVER_URL` environment variable
  (default `ws://localhost:3000`) — see `majordom_zwave/config.py`.
- The integration keeps reconnecting (1 → 30 s backoff) while the server is unreachable; paired devices are
  reported unavailable meanwhile, with the reason as their `last_error`.

## About this integration

- **Protocol / platform:** Z-Wave, via [`zwave-js-server`](https://github.com/zwave-js/zwave-js-server)
  / [`zwave-js-server-python`](https://github.com/home-assistant-libs/zwave-js-server-python).
- **Transport(s):** Z-Wave (sub-GHz RF mesh).
- **Supported devices:** any Z-Wave / Z-Wave Plus device exposing standard Command Classes
  (Binary/Multilevel Switch, Indicator, etc.) that Z-Wave JS supports.
- **Credentials needed to pair:** given when *opening the pairing window* (`start_pairing_window`), not
  at `pair_device` time — Z-Wave needs them during inclusion, before the device exists as a discovery;
  the discovery itself always expects `CredentialsType.none`.
  - `code` — the S2 PIN (the first 5 digits of the DSK on the device's label), or the whole DSK.
  - `qr` — the device's QR code (`90…`); malformed codes are rejected. An S2 code includes the device in the
    window; a **SmartStart** code provisions it instead: zwave-js includes it securely, with no PIN, whenever it is
    powered on (hours later, after installation), and it then arrives as a discovery. Unpairing removes it from
    the provisioning list, or it would join again.
  - none — the device joins, but without the S2 Authenticated / Access Control classes (they need the
    PIN); its discovery's `last_error` says so.
  - `secret` — not supported.

  The Hub does not pass credentials to `start_pairing_window` yet (the SDK's `develop` has the parameter).

### Required harness

- **Hardware adapters:** a Z-Wave USB controller (e.g. Aeotec/Zooz Z-Stick) — but it's attached to
  whatever host runs `zwave-js-server`, not necessarily the Hub. This integration doesn't use
  `dependencies.hardware_interfaces`; the radio is abstracted behind the server.
- **Third-party software services:** [`zwave-js-server`](https://github.com/zwave-js/zwave-js-server)
  (Node.js) must be running and reachable at `ZWAVE_SERVER_URL`.
- **OS / permissions:** network reachability (TCP) to the `zwave-js-server` host:port. No special
  permissions needed on the Hub's own host.

### Protocol stack

| Layer | Protocol | Implemented by |
|-------|----------|----------------|
| **MajorDom integration** | maps Z-Wave devices/values ↔ MajorDom domain model | **this repo, always** |
| Z-Wave JS Server API | `zwave-js-server`'s WebSocket/JSON-RPC protocol | library (`zwave-js-server-python`) |
| Application | Z-Wave Command Classes (CC) | `zwave-js-server` (external Node.js service) |
| Network / MAC / PHY | Z-Wave mesh, sub-GHz RF | Z-Wave USB controller + its driver (harness) |

### Manual testing (real hardware)

Verified against real hardware, on the version before the rework of 2026-10 (the rework is tested against
the mock network only; to be re-run on hardware before release):

- **Z-Wave controller:** Z-Stick 7 (ZWA010)
- **Test device:** HKZW-RGB01 v1.0 (RGB bulb)

### Mapping

| Z-Wave | MajorDom |
|--------|----------|
| Device | `device_uuid("<home id>-<node id>")` (SDK helper): node ids repeat across networks and are reused after a device leaves |
| Value | One parameter, `parameter_uuid(device, value id)`; a current/target pair (`currentValue`/`targetValue`, `currentMode`/`targetMode`, …) is **one** parameter: commanded through the target, state from the current one |
| Multilevel Switch / Basic level, Window Covering position (0–99) | Percentage 0–100 (99 is 100) |
| Multilevel Sensor, Meter, setpoints, Energy Production | `decimal` (scaled decimals by spec), whatever the first reading |
| `states` | `enum` with labels in `valid_values` (`integer` when the device allows other values too, or when they only label special values: sound volume, wake-up interval) |
| Write-only action (`"Reset"`, `"Identify"`, `"Restore previous value"`) | `none`: a button |
| Units | Every zwave-js scale unit is mapped, converted (°F → °C, imperial → metric, Wh → kWh, mV → V, …) or deliberately `plain`; a few CCs give units only in labels (Door Lock times, wake-up interval) |
| Central Scene, Scene Activation, `stateful: false` | `event` role (sent by zwave-js as "value notification"); their settings stay controls |
| Notifications (zwave-js "notification" events) | Read-only `event` parameters: **Keypad** (the event type: Enter, Away, …) and **Keypad code** (what was typed, `system`); one **`<type>` event** per Notification CC type with events (Access control, Home security, …) and its **details** (user id…, JSON, `system`); a remote's **Level change**; **Battery replacement**; **Powerlevel test**. Enum labels are what the device announced; events it did not are dropped |
| Visibility | "When in doubt, hide it": a curated list of everyday controls and live readings is `user` (switches, levels, colour, sensors, meters, locks, thermostats, covers, garage doors, battery, …); every other value of a reviewed CC is a `setting`; wiring, metadata, secrets, durations and opaque data are `system`, and so is every value of a CC nobody reviewed (still usable by automations and the API) |
| Names | Written for people, not zwave-js's labels: `Power`, `Level`, `Color`, `Lock`, `Electric energy` (not `Electric Consumption [kWh]`), `Motion` (not `Sensor state (Motion)`), `Heating setpoint`, `Scene 1`; a name several values share gets what tells them apart (`Sensor status (Water alarm)`); camelCase enum labels become words (`Unsecured with timeout`) |
| Unsupervised set (delivered, not confirmed) | Read back from the device ~6 s later unless zwave-js already did: the Hub sees what the device did |
| Main parameter | Binary Switch (toggle) › Multilevel Switch (off / 100 %) › Barrier (closed / open) › Door Lock (unsecured / secured) › Lock (toggle) › Window Covering (closed / open) › Basic, when it is the only control (off / 100 %) |

### Progress

**Implementation** — makes the integration functional:

- [x] Discovery of joining devices (`"node added"`), and of nodes already on the network but not paired
- [x] Discovery of already-paired devices on (re)connect — matched by home id and node id, and checked against
      the device's fingerprint (a node id reused by another device is not taken for the paired one)
- [x] `start_pairing_window` (default, S2 PIN or DSK, S2 QR, SmartStart)
- [x] Device pairing (completes the device the Hub created; fails cleanly and stays discovered when the device
      does not finish its interview)
- [x] Device schema mapped (see **Mapping**)
- [x] Hub → Device control (`send_command`); the state comes back as the device's report, never echoed
- [x] Device → Hub events (`"value updated"`, `"value notification"`, `"notification"`: keypads, Notification CC
      events, remote dimming, low battery, radio tests)
- [x] `identify` — Indicator CC v3 identify; a light blinks; any other device is left alone (a relay or a motor
      may drive a heater, a pump or a blind)
- [x] `unpair` — a failed node is removed without the device; a live one when *this* device confirms the exclusion
- [x] `fetch`
- [x] Availability — `"dead"`/`"alive"`, the server connection, a device removed with another tool
- [x] Graceful shutdown in `stop`
- [x] Tests pass against a simulated network (mock zwave-js controller and devices)

**Quality** — makes it reliable and maintainable (the bar for release):

- [x] **Recovers automatically** from a lost or restarted `zwave-js-server` (reconnects with backoff)
- [x] **No exception escapes background work** — event handlers run as logged tasks; Hub calls raise after
      recording the reason
- [x] **Failures are surfaced, not swallowed** — the reason is the device's or discovery's `last_error`; an
      unreachable server at start is reported through `controller_did_encounter_error`
- [x] **Re-authenticates automatically** — not applicable (Z-Wave has no expiring credential)
- [x] **Fully asynchronous**
- [x] **Stable identity** — the SDK helpers, scoped by the network's home id
- [x] **End-to-end tests** drive pair → command → fetch → events → `unpair` against the mock network
- [x] **Failure paths tested** — unreachable or lost server, unresponsive and refusing devices, interview timeout,
      exclusion timeout, the wrong device excluded, a reused node id, a missing PIN
- [x] **Broad device coverage** — the catalogue hosts 33 command classes (switches, dimmers, lights, sensors, meters,
      locks, thermostats, covers, garage doors, scene controllers, sirens, user codes, child locks, humidifiers,
      keypads, smoke/CO alarms, sleeping devices, …); S2 by PIN, DSK, QR and SmartStart. The others are plumbing or
      explained (see **Command-class catalogue and canary**)
- [x] **Fully typed** (`ty`) and **clean** (`poe check`)
- [x] **Readable & structured** — mapping in `mapper.py`, static tables in `zwave_spec.py`
- [x] **Efficient** — subscription-based, not polling
- [x] **Diagnosable** — per-area log tags (`[PAIR]`, `[CONNECT]`, …), reasons in `last_error`, causes chained
- [x] **Rich parameter metadata** — role, visibility, units, limits, enum labels, main parameter; names and buckets
      reviewed against the docs' parameter UX for every hosted CC, and audited (`parameter_audit`)
- [ ] **Owned** — add a listed maintainer
- [ ] _nice-to-have:_ localizable naming · firmware updates · user-facing supported-device docs

### Notes

- Z-Wave discovery doesn't use `zeroconf`/`ssdp`/`ble`: nodes are surfaced from `zwave-js-server`'s own events.
- Command classes zwave-js's mock cannot host (rare ones: tariffs, IP gateways, AV, schedules, irrigation) are not
  reviewed: their values map by the generic rules and are hidden (`system`), still usable by automations and the API.
- What zwave-js's mock cannot do, so the catalogue does not round-trip it: decode a Color Switch Set, keep an
  Indicator's state; its Thermostat Setpoint Set refuses every value above the minimum, so the harness replaces it.

## License

See [LICENSE](LICENSE). For commercial licensing or partnership inquiries regarding MajorDom,
contact us via [parker-industries.org/partnership](https://parker-industries.org/partnership).
