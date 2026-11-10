"""Pairing: inclusion through the pairing window, S2 credentials, and what pairing leaves in the Hub."""

import asyncio
from typing import Any
from uuid import UUID

import pytest
from majordom_integration_sdk import DeviceIdTakenError, Endpoint, Peripherals
from majordom_integration_sdk.schemas.device import CredentialsType, ProvidedCredentials
from majordom_integration_sdk.schemas.parameter import ParameterRole, ParameterVisibility
from majordom_integration_sdk.testing import RecordingControllerOutput, build_test_platform
from zwave_js_server.const import InclusionState
from zwave_js_server.model.controller import Controller

from majordom_zwave import ZwaveController
from tests.helpers import ROOM, discover, hub_draft, hub_pairs, pair, param, stored, wait_until
from tests.network import HOME_ID, MockNetwork

BINARY_SWITCH = "37-0-targetValue"


async def test_a_device_included_in_the_pairing_window_is_discovered(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    discovery = await discover(controller, output, network, 5, "switch")

    assert discovery.integration == controller.key
    assert discovery.transport == "ZWAVE"
    assert discovery.expected_credentials_options == [CredentialsType.none]
    assert discovery.id in controller.discoveries


async def test_pairing_completes_the_device_the_hub_saved(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)

    assert (device.name, device.room_id) == ("Hall lamp", ROOM)  # kept from the Hub
    assert device.available is True
    assert device.last_error is None
    assert device.integration_data is not None
    assert (device.integration_data.home_id, device.integration_data.node_id) == (HOME_ID, 5)
    assert device.parameters
    assert device.physical_id in output.connected_devices
    assert device.physical_id not in controller.discoveries


async def test_identity_is_derived_through_the_sdk_helpers(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)

    # the home id scopes the node id: node ids repeat across networks and are reused after a device leaves
    assert device.physical_id == controller.device_uuid(f"{HOME_ID:08x}-5")
    for parameter in device.parameters:
        assert parameter.id == controller.parameter_uuid(
            device.physical_id, parameter.integration_data.value_id, strip=""
        )


async def test_the_switch_is_one_parameter_and_the_main_one(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)

    switch = param(device, BINARY_SWITCH)  # commands go to targetValue, the state comes from currentValue
    assert switch.integration_data.state_value_id == "5-37-0-currentValue"
    assert (switch.role, switch.visibility) == (ParameterRole.control, ParameterVisibility.user)
    assert not [p for p in device.parameters if p.integration_data.value_id.endswith("-37-0-currentValue")]
    assert device.main_parameter == switch.id
    assert switch.default_value is None  # a bool: a tap toggles it (a single value would be an always-on button)


async def test_pair_device_fills_the_draft_and_changes_nothing_in_the_hub(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    discovery = await discover(controller, output, network, 5, "switch")
    events = len(output.events)

    paired = await controller.pair_device(discovery, hub_draft(discovery, "Porch"), None)

    assert (paired.physical_id, paired.name, paired.room_id) == (discovery.id, "Porch", ROOM)
    assert paired.integration_data is not None
    assert (paired.integration_data.home_id, paired.integration_data.node_id) == (HOME_ID, 5)
    assert paired.parameters
    assert paired.main_parameter
    assert paired.available is True
    async with controller.platform.device_repository(controller) as repo:
        assert await repo.get(physical_id=discovery.id) is None
    assert discovery.id not in output.connected_devices
    assert len(output.events) == events  # the Hub reports the device after it saved it
    assert discovery.id in controller.discoveries  # a refused save leaves the node to pair again


async def test_pair_device_refuses_an_id_another_record_holds(output: RecordingControllerOutput, fast: None):
    store: dict[UUID, dict[str, Any]] = {}
    controller = ZwaveController(build_test_platform(store=store))
    controller.output = output
    held = controller.device_uuid(f"{HOME_ID:08x}-5")
    store[UUID(int=7)] = {"name": "Old lamp", "physical_id": str(held)}  # paired: the default
    network = MockNetwork([])
    await network.start()
    controller.peripherals = Peripherals({"zwave": Endpoint("zwave", "zwave-js-ws", network.url)})
    try:
        await controller.start()
        discovery = await discover(controller, output, network, 5, "switch")
        picked = hub_draft(discovery).model_copy(update={"id": UUID(int=9)})

        with pytest.raises(DeviceIdTakenError) as taken:
            await controller.pair_device(discovery, picked, None)

        assert (taken.value.name, taken.value.is_paired) == ("Old lamp", True)
        assert discovery.id in controller.discoveries
        assert not output.updated_discoveries  # the id is not the device's fault
    finally:
        await controller.stop()
        await network.stop()


async def test_a_device_that_never_becomes_ready_fails_pairing_and_stays_discovered(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    discovery = await discover(controller, output, network, 5, "switch", silent=True)  # joins, then never answers

    with pytest.raises(TimeoutError):
        await controller.pair_device(discovery, hub_draft(discovery), None)

    assert output.updated_discoveries[-1].last_error
    assert discovery.id in controller.discoveries


async def test_a_failed_pairing_is_retried_from_the_same_discovery(
    controller: ZwaveController,
    output: RecordingControllerOutput,
    network: MockNetwork,
    monkeypatch: pytest.MonkeyPatch,
):
    await controller.start()
    discovery = await discover(controller, output, network, 5, "switch")
    with monkeypatch.context() as patched:
        patched.setattr(controller, "_wait_until_ready", _raise(TimeoutError("not ready")))
        with pytest.raises(TimeoutError):
            await controller.pair_device(discovery, hub_draft(discovery), None)

    assert 5 in await network.node_ids()  # nothing undone: it stays included
    assert controller._controller().inclusion_state == InclusionState.IDLE  # no exclusion begun
    device = await hub_pairs(controller, controller.discoveries[discovery.id])
    assert device.parameters and discovery.id not in controller.discoveries


async def test_a_pairing_the_hub_never_saved_is_retried_from_the_same_discovery(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    discovery = await discover(controller, output, network, 5, "switch")
    await controller.pair_device(discovery, hub_draft(discovery), None)
    # the Hub refused the id or failed to save: nothing saved, nothing undone

    assert discovery.id in controller.discoveries
    device = await hub_pairs(controller, controller.discoveries[discovery.id])

    assert device.physical_id == discovery.id and discovery.id not in controller.discoveries
    assert 5 in await network.node_ids()


def _raise(error: Exception):
    async def fail(*_args: Any):
        raise error

    return fail


async def test_pairing_an_unknown_discovery_fails(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    discovery = await discover(controller, output, network, 5, "switch")
    stale = discovery.model_copy(update={"id": controller.device_uuid("nothing")})

    with pytest.raises(ValueError):
        await controller.pair_device(stale, hub_draft(stale), None)


async def test_stopping_ends_a_pairing_that_waits_for_the_interview(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    discovery = await discover(controller, output, network, 5, "switch", silent=True)
    pairing = asyncio.create_task(controller.pair_device(discovery, hub_draft(discovery), None))
    await asyncio.sleep(0.3)

    await controller.stop()

    with pytest.raises(ConnectionError):  # at once, not when the interview times out
        await asyncio.wait_for(pairing, 1)
    assert not controller.discoveries  # not offered again by a pairing that outlived the stop


async def test_losing_the_server_ends_a_pairing_that_waits_for_the_interview(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    """The lost connection's node never hears the interview end (the next connection has nodes of its own)."""
    await controller.start()
    discovery = await discover(controller, output, network, 5, "switch", silent=True)
    pairing = asyncio.create_task(controller.pair_device(discovery, hub_draft(discovery), None))
    await asyncio.sleep(0.3)

    await network.drop_server()

    with pytest.raises(ConnectionError, match="lost"):  # at once, not when the interview times out with other advice
        await asyncio.wait_for(pairing, 2)
    assert "pair the device again" in (output.updated_discoveries[-1].last_error or "")
    assert discovery.id in controller.discoveries


async def test_a_pairing_that_outlives_a_stop_returns_nothing(
    controller: ZwaveController,
    output: RecordingControllerOutput,
    network: MockNetwork,
    monkeypatch: pytest.MonkeyPatch,
):
    """Stopped while the node is read: refused, and the next start offers the node again."""
    await controller.start()
    discovery = await discover(controller, output, network, 5, "switch")
    reading = asyncio.Event()

    async def slow_read(node: Any) -> list[dict[str, Any]]:
        reading.set()
        await asyncio.sleep(0.5)
        return []

    monkeypatch.setattr(controller, "_supported_notification_events", slow_read)
    pairing = asyncio.create_task(controller.pair_device(discovery, hub_draft(discovery), None))
    await reading.wait()
    await controller.stop()

    with pytest.raises(ConnectionError, match="pair the device again"):
        await pairing
    assert discovery.id not in output.connected_devices


async def test_fetch_after_the_save_binds_the_node_once(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)

    assert device.physical_id in controller._nodes
    subscriptions = list(controller._unsubscribe[device.physical_id])
    await controller.fetch(device)
    await controller.fetch(device)

    assert controller._unsubscribe[device.physical_id] == subscriptions  # never a second subscription
    assert device.physical_id not in controller.discoveries


async def test_a_pairing_window_opening_across_a_stop_is_refused(
    controller: ZwaveController, network: MockNetwork, monkeypatch: pytest.MonkeyPatch
):
    """Stopped after the server opened it, before the Hub's call resumed: its closing task would outlive the stop."""
    await controller.start()
    begin = Controller.async_begin_inclusion
    answered = asyncio.Event()

    async def late(self: Controller, *args: Any, **kwargs: Any) -> bool:
        answer = await begin(self, *args, **kwargs)
        answered.set()
        await asyncio.sleep(0.3)  # the Hub's task resumes after the stop
        return answer

    monkeypatch.setattr(Controller, "async_begin_inclusion", late)
    opening = asyncio.create_task(controller.start_pairing_window(60))
    await answered.wait()
    await controller.stop()

    with pytest.raises(ConnectionError):
        await opening
    assert not controller._tasks


async def test_stopping_closes_the_pairing_window(controller: ZwaveController, network: MockNetwork):
    """zwave-js-server outlives the controller: an inclusion left running would take the next device for nobody, and
    keep the next window from opening."""
    await controller.start()
    await controller.start_pairing_window(120)

    await controller.stop()
    await controller.start()  # the same instance on the same server, as the runtime starts it again

    assert controller._controller().inclusion_state == InclusionState.IDLE


async def test_the_s2_pin_entered_with_the_pairing_window_includes_securely(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    pin = lambda label: ProvidedCredentials(type=CredentialsType.code, value=label["pin"])  # noqa: E731
    device = await pair(controller, output, network, 5, "secure", credentials=pin)

    param(device, BINARY_SWITCH)  # only supported securely: present only if S2 bootstrapping succeeded
    assert output.received_discoveries[-1].last_error is None


async def test_the_full_dsk_works_as_the_pin(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    dsk = lambda label: ProvidedCredentials(type=CredentialsType.code, value=label["dsk"])  # noqa: E731
    device = await pair(controller, output, network, 5, "secure", credentials=dsk)

    param(device, BINARY_SWITCH)


async def test_the_s2_qr_code_includes_securely(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    qr = lambda label: ProvidedCredentials(type=CredentialsType.qr, value=label["qr"])  # noqa: E731
    device = await pair(controller, output, network, 5, "secure", credentials=qr)

    param(device, BINARY_SWITCH)  # only supported securely: present only if S2 bootstrapping succeeded


async def test_without_the_pin_a_secure_device_joins_with_lower_security_and_says_so(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    discovery = await asyncio.wait_for(discover(controller, output, network, 5, "secure"), 30)  # no waiting for a PIN

    assert discovery.last_error and "PIN" in discovery.last_error


async def test_a_malformed_qr_code_is_rejected(controller: ZwaveController, network: MockNetwork):
    await controller.start()

    with pytest.raises(ValueError):
        await controller.start_pairing_window(60, ProvidedCredentials(type=CredentialsType.qr, value="not a code"))


async def test_secret_credentials_are_rejected(controller: ZwaveController, network: MockNetwork):
    await controller.start()

    with pytest.raises(ValueError):
        await controller.start_pairing_window(60, ProvidedCredentials(type=CredentialsType.secret, value="key"))


async def test_closing_the_window_keeps_live_unclaimed_devices_and_removes_failed_ones(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    alive = await discover(controller, output, network, 5, "switch", duration=1)
    await asyncio.sleep(1.5)
    assert alive.id in controller.discoveries

    failed = await discover(controller, output, network, 6, "switch", duration=3)
    for _ in range(100):  # joined and interviewed (its state read) — then it fails, before anyone pairs it
        if "BinarySwitchCCGet" in await network.frames(6):
            break
        await asyncio.sleep(0.05)
    await network.fail(6)
    await wait_until(lambda: failed.id in output.lost_discoveries, 10, "the failed node's discovery to be dropped")
    assert 6 not in await network.node_ids()


async def test_a_paired_device_can_be_found_again_after_its_discovery(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network)

    assert (await stored(controller, device.physical_id)).id == device.id
    assert not output.lost_devices


async def test_a_device_that_missed_its_identity_is_interviewed_again(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, missIdentity=True)  # busy right after joining

    assert device.integration_data is not None
    assert device.integration_data.fingerprint  # known: its device file applies, and a reused node id is told apart
