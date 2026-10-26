"""Shared fixtures: a fresh controller and Hub doubles per test, and the mock Z-Wave network it connects to."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from majordom_integration_sdk import Endpoint, Peripherals, Platform
from majordom_integration_sdk.testing import RecordingControllerOutput, build_test_platform

from majordom_zwave import ZwaveController
from tests.network import MakeNetwork, MockNetwork


@pytest.fixture
def platform() -> Platform:
    return build_test_platform()


@pytest.fixture
def output() -> RecordingControllerOutput:
    return RecordingControllerOutput()


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch):
    """Shorten the waits meant for people and radios, so failure paths run in seconds."""
    monkeypatch.setattr(ZwaveController, "RECONNECT_DELAYS", (0.2, 0.5))
    monkeypatch.setattr(ZwaveController, "EXCLUSION_TIMEOUT", 2.0)
    monkeypatch.setattr(ZwaveController, "READY_TIMEOUT", 3.0)
    monkeypatch.setattr(ZwaveController, "IDENTIFY_BLINKS", 2)
    monkeypatch.setattr(ZwaveController, "IDENTIFY_PERIOD", 0.05)


@pytest.fixture
def patient(fast: None, monkeypatch: pytest.MonkeyPatch):
    """Interviewing every capability of a CC takes the mock a few seconds (Notification, User Code)."""
    monkeypatch.setattr(ZwaveController, "READY_TIMEOUT", 90.0)


@pytest.fixture
async def controller(
    platform: Platform, output: RecordingControllerOutput, fast: None
) -> AsyncIterator[ZwaveController]:
    controller = ZwaveController(platform)
    controller.output = output
    yield controller
    await controller.stop()


@pytest.fixture
async def make_network(controller: ZwaveController) -> AsyncIterator[MakeNetwork]:
    """Start a mock network (with the given nodes already included) and bind the integration's need to it."""
    networks: list[MockNetwork] = []

    async def make(nodes: list[dict[str, Any]] | None = None, serve: bool = True) -> MockNetwork:
        network = MockNetwork(nodes or [])
        networks.append(network)
        await network.start(serve=serve)
        controller.peripherals = Peripherals({"zwave": Endpoint("zwave", "zwave-js-ws", network.url)})
        return network

    yield make
    for network in networks:
        await network.stop()


@pytest.fixture
async def network(make_network: MakeNetwork) -> MockNetwork:
    """An empty network: devices join it during the test."""
    return await make_network()
