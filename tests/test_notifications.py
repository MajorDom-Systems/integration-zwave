"""Notifications: what devices send as one-off events rather than values (zwave-js "notification" events) — a keypad's
entries, Notification CC events, a remote's dimming, a low battery, a radio test's result."""

import json

import pytest
from majordom_integration_sdk.schemas.parameter import ParameterRole
from majordom_integration_sdk.testing import RecordingControllerOutput

from majordom_zwave import ZwaveController
from tests.helpers import pair, param, values, wait_for_value
from tests.network import MockNetwork
from tests.test_sleeping import wait_for_asleep

pytestmark = pytest.mark.usefixtures("patient")


async def test_a_keypad_entry_reports_its_event_and_the_code(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "entry_control")
    event, code = param(device, "111-0-event"), param(device, "111-0-code")
    assert event.role == code.role == ParameterRole.event
    assert event.valid_values == {2: "Enter", 3: "Disarm all", 5: "Away", 6: "Home", 25: "Cancel"}  # what it supports

    await network.report(5, "keypad", {"eventType": 2, "code": "1234"})  # 1234, then Enter

    assert await wait_for_value(output, event, lambda v: v == 2) == 2
    assert await wait_for_value(output, code, lambda v: v == "1234") == "1234"


async def test_a_keypad_event_without_a_code_reports_no_code(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 5, "entry_control")
    event, code = param(device, "111-0-event"), param(device, "111-0-code")

    await network.report(5, "keypad", {"eventType": 5})  # the Away button

    assert await wait_for_value(output, event, lambda v: v == 5) == 5
    assert values(output, code.id) == []


async def test_a_notification_event_reports_the_event_and_its_details(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 6, "notification")
    event, details = param(device, "113-0-event-6"), param(device, "113-0-details-6")  # Access Control
    assert event.name == "Access control event"
    assert event.valid_values == {
        1: "Manual lock operation",
        2: "Manual unlock operation",
        5: "Keypad lock operation",
        6: "Keypad unlock operation",
    }

    await network.report(6, "notification", {"type": 6, "event": 5, "parameters": [3]})  # locked with user 3's code

    assert await wait_for_value(output, event, lambda v: v == 5) == 5
    reported = await wait_for_value(output, details, lambda v: v is not None)
    assert json.loads(reported) == {"userId": 3}


async def test_a_notification_event_without_details_reports_none(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 6, "notification")
    event, details = param(device, "113-0-event-6"), param(device, "113-0-details-6")

    await network.report(6, "notification", {"type": 6, "event": 1})  # locked by hand

    assert await wait_for_value(output, event, lambda v: v == 1) == 1
    assert values(output, details.id) == []


async def test_an_event_the_device_did_not_announce_is_not_reported(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 6, "notification")
    event = param(device, "113-0-event-6")

    await network.report(6, "notification", {"type": 6, "event": 3})  # auto lock: not in its supported events
    await network.report(6, "notification", {"type": 6, "event": 2})

    await wait_for_value(output, event, lambda v: v == 2)
    assert values(output, event.id) == [2]  # a value outside the enum would not be a valid state


async def test_dimming_from_the_device_reports_start_and_stop(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 7, "multilevel_switch")
    change = param(device, "38-0-levelChange")
    assert change.valid_values == {0: "Stopped", 1: "Started up", 2: "Started down"}

    await network.report(7, "level_change", "up")
    await wait_for_value(output, change, lambda v: v == 1)
    await network.report(7, "level_change", "stop")
    await wait_for_value(output, change, lambda v: v == 0)
    await network.report(7, "level_change", "down")
    await wait_for_value(output, change, lambda v: v == 2)


async def test_a_low_battery_reports_that_it_needs_replacing(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 8, "sleeping")
    replacement = param(device, "128-0-replacement")
    await wait_for_asleep(network, 8)

    await network.wake(8)
    await network.report(8, "battery_low", None)

    assert await wait_for_value(output, replacement, lambda v: v == 1) == 1  # soon


async def test_a_radio_test_result_is_reported(
    controller: ZwaveController, output: RecordingControllerOutput, network: MockNetwork
):
    await controller.start()
    device = await pair(controller, output, network, 9, "powerlevel")
    result = param(device, "115-0-test")

    await network.report(9, "powerlevel", 1)  # success

    assert await wait_for_value(output, result, lambda v: v == 1) == 1
