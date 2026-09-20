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

Work lands on `develop`; `master` is protected and released via **Actions → Release**. Tests drive
the controller with the SDK's test doubles against an in-memory `zwave-js-server-python`
stub — no real server, radio, or Z-Wave stick required (see `tests/`).

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
  (e.g. `ws://localhost:3000`) — see `majordom_zwave/config.py`.

## About this integration

- **Protocol / platform:** Z-Wave, via [`zwave-js-server`](https://github.com/zwave-js/zwave-js-server)
  / [`zwave-js-server-python`](https://github.com/home-assistant-libs/zwave-js-server-python).
- **Transport(s):** Z-Wave (sub-GHz RF mesh).
- **Supported devices:** any Z-Wave / Z-Wave Plus device exposing standard Command Classes
  (Binary/Multilevel Switch, Indicator, etc.) that Z-Wave JS supports.
- **Credentials needed to pair:** none for the Hub's pairing flow — `Discovery` always advertises
  `CredentialsType.none`. S2 `code` (PIN) and `qr` (DSK) are supported, but must be supplied when
  *opening the pairing window*, not at `pair_device` time — Z-Wave needs them during inclusion,
  before the node exists as a discovery. `secret` is not supported.

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

Verified against real hardware, not just the virtual-device test suite:

- **Z-Wave controller:** Z-Stick 7 (ZWA010)
- **Test device:** HKZW-RGB01 v1.0 (RGB bulb)

Ran the same lifecycle as `tests/test_controller.py` — pairing, `fetch`, `send_command`,
`identify`, and `unpair` — all completed successfully.

### Progress

**Implementation** — makes the integration functional:

- [x] Discovery of joining devices via `zwave-js-server`'s `"node added"` event; also reconciles
      nodes already on the network but not yet claimed (e.g. after a Hub restart) —
      `controller_did_receive_discovery` called
- [ ] Discovery of already-paired devices on reconnect — currently `start()` marks known devices
      available internally on startup without going through `controller_did_connect_device` (see Notes)
- [x] `start_pairing_window` (default, S2 PIN, S2 QR/SmartStart, auto-grant of requested
      security classes with no user prompt)
- [x] Device pairing
- [x] Device schema mapped (via `ZwaveMapper`: values → parameters, role/visibility/units)
- [x] Hub → Device control (`send_command`)
- [x] Device → Hub event subscription (`controller_did_receive_events` on `"value updated"`)
- [x] `identify` (Indicator CC, falls back to blinking a Binary/Multilevel Switch)
- [x] `unpair` (failed-node removal, or live interactive exclusion confirmed by the device)
- [x] `fetch`
- [x] Availability tracking while running (`"dead"`/`"alive"` → `controller_did_lose_device` /
      `controller_did_connect_device`) — `last_error` isn't set/cleared on these specific
      transitions though (see Notes)
- [x] Graceful shutdown in `stop` (tasks cancelled, client disconnected, session closed)
- [x] Tests pass against a virtual/simulated device (`tests/test_controller.py`) and against real
      hardware (see **Manual testing** above)

**Quality** — makes it reliable and maintainable (the bar for release):

- [ ] **Recovers automatically** from connection loss / offline device / restarted backend — no
      reconnect/backoff around `Client.connect()`/`listen()` yet
- [ ] **No exception escapes the controller** — event handlers (`_node_added`, `_value_updated`,
      `_set_availability`, `_grant_security_classes`) run via fire-and-forget tasks with no
      individual `try`/`except`; an exception there surfaces only as an unretrieved task exception
- [ ] **Failures are surfaced, not raised** — done in a couple of places (reconnect-missing,
      pending exclusion) but not consistently across all paths
- [ ] **Re-authenticates automatically** — not applicable to Z-Wave (no expiring credential concept)
- [x] **Fully asynchronous** — no blocking I/O found on the event loop
- [x] **Stable identity** — device/parameter UUIDs derived via `ZwaveMapper`'s SDK-backed helpers
- [x] **End-to-end tests** drive pair → command → fetch → events → `unpair` against a virtual device
- [ ] **Failure paths tested** — offline device / transport error / rejected credentials not covered yet
- [ ] **Broad device coverage** — one virtual device type in CI, one real device manually
- [x] **Fully typed** (`ty`) and **clean** (`poe check`) — ruff, ty, pytest, and
      `poetry build`/`check` all pass
- [x] **Readable & structured** — conversion logic lives in `ZwaveMapper`, models separated
- [x] **Efficient** — subscription-based (`"value updated"`/`"dead"`/`"alive"`), not polling
- [ ] **Diagnosable** — decent per-area log tags (`[PAIR]`, `[CMD]`, `[JOIN]`, …), but
      `send_command`'s exception handler re-raises with `from None`, discarding the original traceback
- [x] **Rich parameter metadata** — role/visibility/`main_parameter` resolved per value via `ZwaveMapper`
- [ ] **Owned** — add a listed maintainer
- [ ] _nice-to-have:_ localizable naming · firmware/software updates · user-facing supported-device docs

### Notes

- Z-Wave discovery doesn't use `zeroconf`/`ssdp`/`ble` — joined/reconciled nodes are surfaced
  directly from `zwave-js-server`'s own `"node added"` event.
- On startup, devices already known to the Hub are matched against the live node list and marked
  available/subscribed directly, without a corresponding `controller_did_connect_device` call —
  worth revisiting if the Hub relies on that call to refresh its own state after a restart.
- `last_error` is set explicitly when a paired device isn't found on the network at startup and
  while an exclusion is pending, but isn't cleared/set on ordinary `"dead"`/`"alive"` transitions.

## License

See [LICENSE](LICENSE). For commercial licensing or partnership inquiries regarding MajorDom,
contact us via [parker-industries.org/partnership](https://parker-industries.org/partnership).
