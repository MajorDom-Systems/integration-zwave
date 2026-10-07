"""Shared fixtures: a fresh controller and Hub doubles per test, and the mock Z-Wave network it connects to."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

import pytest
from majordom_integration_sdk.controller import AbstractController
from majordom_integration_sdk.testing import RecordingControllerOutput, build_test_dependencies

from majordom_zwave import ZwaveController
from tests.network import MockNetwork

INTEGRATION = "ZWave"


@pytest.fixture
def deps() -> AbstractController.Dependencies:
    return build_test_dependencies(integration=INTEGRATION)


@pytest.fixture
def output(deps: AbstractController.Dependencies) -> RecordingControllerOutput:
    return cast(RecordingControllerOutput, deps.output)


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shorten the waits meant for people and radios, so failure paths run in seconds."""
    monkeypatch.setattr(ZwaveController, "RECONNECT_DELAYS", (0.2, 0.5))
    monkeypatch.setattr(ZwaveController, "EXCLUSION_TIMEOUT", 2.0)
    monkeypatch.setattr(ZwaveController, "READY_TIMEOUT", 3.0)
    monkeypatch.setattr(ZwaveController, "IDENTIFY_BLINKS", 2)
    monkeypatch.setattr(ZwaveController, "IDENTIFY_PERIOD", 0.05)


@pytest.fixture
def patient(fast: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Interviewing every capability of a CC takes the mock a few seconds (Notification, User Code)."""
    monkeypatch.setattr(ZwaveController, "READY_TIMEOUT", 90.0)


@pytest.fixture
async def controller(deps: AbstractController.Dependencies, fast: None) -> AsyncIterator[ZwaveController]:
    controller = ZwaveController(deps)
    yield controller
    await controller.stop()


@pytest.fixture
async def make_network(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Callable[..., Awaitable[MockNetwork]]]:
    """Start a mock network (with the given nodes already included) and point the integration at it."""
    networks: list[MockNetwork] = []

    async def make(nodes: list[dict[str, Any]] | None = None, serve: bool = True) -> MockNetwork:
        network = MockNetwork(nodes or [])
        networks.append(network)
        await network.start(serve=serve)
        monkeypatch.setenv("ZWAVE_SERVER_URL", network.url)
        return network

    yield make
    for network in networks:
        await network.stop()


@pytest.fixture
async def network(make_network: Callable[..., Awaitable[MockNetwork]]) -> MockNetwork:
    """An empty network: devices join it during the test."""
    return await make_network()
