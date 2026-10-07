import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from typing import Any, ClassVar, override
from uuid import UUID

from aiohttp import ClientSession
from majordom_integration_sdk.controller import AbstractController
from majordom_integration_sdk.schemas import DeviceCommand, Discovery, ProvidedCredentials
from majordom_integration_sdk.schemas.device import CredentialsType, NonEmptyStr
from majordom_integration_sdk.schemas.event import DeviceParameterChange
from majordom_integration_sdk.schemas.parameter import ParameterRole
from zwave_js_server.client import Client as ZwaveClient
from zwave_js_server.const import CommandClass, InclusionStrategy, NodeStatus, SecurityClass, SetValueStatus
from zwave_js_server.model.controller import Controller
from zwave_js_server.model.controller.inclusion_and_provisioning import InclusionGrant
from zwave_js_server.model.node import Node
from zwave_js_server.model.value import Value

from . import config, mapper
from .model import (
    ZwaveDevice,
    ZwaveDeviceIntegrationData,
    ZwaveParameter,
    ZwaveParameterIntegrationData,
)

log = logging.getLogger(__name__)

PIN = re.compile(r"\d{5}")  # the S2 PIN: the first 5 digits of the DSK, printed on the device
DSK = re.compile(r"\d{5}(-\d{5}){7}")  # the full DSK
SMART_START_QR = re.compile(r"9001\d+")  # a QR code's version digits: 00 is S2, 01 is SmartStart
APPLIED = {SetValueStatus.SUCCESS, SetValueStatus.SUCCESS_UNSUPERVISED, SetValueStatus.WORKING}
# Security classes that need the device's PIN; granted only when the PIN (or DSK) was given
AUTHENTICATED = {SecurityClass.S2_AUTHENTICATED, SecurityClass.S2_ACCESS_CONTROL}


class ZwaveController(AbstractController):
    """Bridges the Hub to Z-Wave devices through zwave-js-server."""

    name: ClassVar[str] = "ZWave"

    RECONNECT_DELAYS: ClassVar[tuple[float, ...]] = (1, 2, 5, 10, 30)  # then 30 s between attempts
    READY_TIMEOUT: ClassVar[float] = 120  # a device's interview; a sleeping device finishes it when it wakes up
    EXCLUSION_TIMEOUT: ClassVar[float] = 60  # for the user to put the device into exclusion mode
    IDENTIFY_BLINKS: ClassVar[int] = 5
    IDENTIFY_PERIOD: ClassVar[float] = 0.6
    # After an unsupervised set (delivered, not confirmed), zwave-js re-reads some values ~5 s later; past this delay
    # the value is read back here when it has not changed, so the Hub learns what the device actually did
    VERIFY_DELAY: ClassVar[float] = 6

    def __init__(self, dependencies: AbstractController.Dependencies):
        super().__init__(dependencies)
        self._session: ClientSession | None = None
        self._zwave_client: ZwaveClient | None = None
        self._supervisor: asyncio.Task | None = None
        self._first_attempt = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._discoveries: dict[UUID, Discovery] = {}
        self._joined: dict[UUID, Node] = {}  # nodes behind the discoveries
        self._nodes: dict[UUID, Node] = {}  # nodes of paired devices
        self._routes: dict[UUID, dict[str, str | None]] = {}  # value id → value id of the parameter it reports
        self._events: dict[UUID, dict[str, Any]] = {}  # event parameters' value ids → their enum labels (or None)
        self._unsubscribe: dict[UUID, list[Callable[[], None]]] = {}  # per paired device
        self._listeners: list[Callable[[], None]] = []  # on the driver's controller, gone with the connection
        self._available: dict[UUID, bool] = {}
        self._credentials: ProvidedCredentials | None = None  # of the open pairing window
        self._closing_window: asyncio.Task | None = None
        self._removal: asyncio.Future[int] | None = None  # the node id the running exclusion removed

    # -------------------------------------------------------------------------
    # AbstractController interface
    # -------------------------------------------------------------------------

    @property
    def discoveries(self) -> dict[UUID, Discovery]:
        return self._discoveries

    @property
    @override
    def device_type(self) -> type[ZwaveDevice]:
        return ZwaveDevice

    @property
    @override
    def parameter_type(self) -> type[ZwaveParameter]:
        return ZwaveParameter

    @property
    def connected(self) -> bool:
        return self._zwave_client is not None and self._zwave_client.connected

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def start(self):
        """Connects to zwave-js-server and keeps reconnecting; an unreachable server is reported, not raised."""
        self._session = ClientSession()
        self._first_attempt.clear()
        self._supervisor = asyncio.create_task(self._run(config.server_url(), self._session))
        await self._first_attempt.wait()

    async def stop(self):
        for task in [self._supervisor, *self._tasks]:
            if task is not None:
                task.cancel()
        await asyncio.gather(*[t for t in [self._supervisor, *self._tasks] if t is not None], return_exceptions=True)
        self._supervisor = None
        self._tasks.clear()
        await self._disconnect()
        if self._session is not None:
            await self._session.close()
            self._session = None
        self._discoveries.clear()
        self._joined.clear()
        self._available.clear()

    async def _run(self, url: str, session: ClientSession) -> None:
        attempt = 0
        while True:
            listening: asyncio.Task | None = None
            try:
                client = ZwaveClient(url, session)
                await client.connect()
                ready = asyncio.Event()
                listening = asyncio.create_task(client.listen(ready))
                waiting = asyncio.create_task(ready.wait())
                await asyncio.wait({listening, waiting}, return_when=asyncio.FIRST_COMPLETED)
                waiting.cancel()
                if listening.done():
                    listening.result()  # raises what made it stop
                    raise ConnectionError("the connection closed before the driver was ready")
                self._zwave_client = client
                await self._attach()
                log.info("[READY] connected to %s", url)
                attempt = 0
                self._first_attempt.set()
                await listening
                raise ConnectionError("the connection to zwave-js-server closed")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001  any failure means: reconnect
                reason = f"zwave-js-server at {url} is unreachable: {exc or type(exc).__name__}"
                log.warning("[CONNECT] %s", reason)
                await self._detach(reason)
                if not self._first_attempt.is_set():
                    await self.dependencies.output.controller_did_encounter_error(self, reason, True)
                    self._first_attempt.set()
            finally:
                if listening is not None:
                    listening.cancel()
            await asyncio.sleep(self.RECONNECT_DELAYS[min(attempt, len(self.RECONNECT_DELAYS) - 1)])
            attempt += 1

    async def _disconnect(self) -> None:
        client, self._zwave_client = self._zwave_client, None
        if client is not None and client.connected:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                log.debug("[CONNECT] disconnect failed", exc_info=True)

    async def _attach(self) -> None:
        """Binds the paired devices to the (new) driver's nodes and offers the other nodes as discoveries."""
        controller = self._controller()
        self._available.clear()  # report every device's availability afresh
        self._track(controller.on("node added", lambda data: self._spawn(self._node_added(data["node"], data))))
        self._track(controller.on("node removed", lambda data: self._spawn(self._node_removed(data["node"]))))
        self._track(
            controller.on("grant security classes", lambda data: self._spawn(self._grant(data["requested_grant"])))
        )
        self._track(controller.on("validate dsk and enter pin", lambda data: self._spawn(self._enter_pin())))

        async with self.dependencies.make_device_repository() as repo:
            devices = [d for d in await repo.get_all(as_=ZwaveDevice) if d.integration_data is not None]
        claimed: set[int] = set()
        for device in devices:
            data = device.integration_data
            assert data is not None
            node = controller.nodes.get(data.node_id) if data.home_id == controller.home_id else None
            if data.home_id == controller.home_id:
                claimed.add(data.node_id)  # its id is taken even when another device now has the node
            if node is None:
                await self._set_available(device.id, False, "The device is no longer on this Z-Wave network")
            elif data.fingerprint and (found := self._fingerprint(node)) and found != data.fingerprint:
                await self._set_available(
                    device.id, False, f"Node {data.node_id} is now another device ({found}): pair that one anew"
                )
            else:
                events = {
                    p.integration_data.value_id: p.valid_values
                    for p in device.parameters
                    if p.integration_data.value_id not in node.values  # an event parameter (of a notification)
                }
                self._bind(device.id, node, events)
                await self._update_availability(device.id, node)
                if node.status != NodeStatus.DEAD:
                    await self._report_snapshot(device.id, node)
        for node in controller.nodes.values():  # on the network, not paired (yet): offered for pairing
            if node.node_id != controller.own_node_id and node.node_id not in claimed:
                await self._offer(node)

    async def _detach(self, reason: str) -> None:
        for device_id in list(self._nodes):
            self._unbind(device_id)
            await self._set_available(device_id, False, reason)
        for unsubscribe in self._listeners:
            unsubscribe()
        self._listeners.clear()
        self._joined.clear()
        await self._disconnect()

    # -------------------------------------------------------------------------
    # Hub -> device operations
    # -------------------------------------------------------------------------

    async def start_pairing_window(self, duration_sec: int, credentials: ProvidedCredentials | None = None) -> None:
        controller = self._controller()
        kind = credentials.type if credentials else CredentialsType.none
        value = (credentials.value if credentials else None) or ""
        if kind == CredentialsType.secret:
            raise ValueError("Z-Wave devices are paired with their PIN, DSK or QR code, not a secret")
        if kind == CredentialsType.code and not DSK.fullmatch(value) and not PIN.fullmatch(value):
            raise ValueError("The PIN is the first 5 digits of the device's DSK (or give the whole DSK)")
        if kind == CredentialsType.qr and SMART_START_QR.fullmatch(value):
            # SmartStart: no window to open. zwave-js keeps the device on its provisioning list and includes it,
            # securely, whenever it is powered on — hours later, after installation; it then joins as a discovery
            await controller.async_provision_smart_start_node(value)
            log.debug("[PAIRING] SmartStart device provisioned: it joins when powered on")
            return
        self._credentials = credentials  # before inclusion starts: a device can ask for its grant right away
        try:
            if kind == CredentialsType.qr:
                # a malformed code is rejected here (ValueError); the server parses the rest
                await controller.async_begin_inclusion(InclusionStrategy.SECURITY_S2, provisioning=value)
            elif kind == CredentialsType.code and DSK.fullmatch(value):
                await controller.async_begin_inclusion(InclusionStrategy.SECURITY_S2, dsk=value)
            elif kind == CredentialsType.code:
                await controller.async_begin_inclusion(InclusionStrategy.SECURITY_S2)  # the PIN is entered when asked
            else:
                await controller.async_begin_inclusion(InclusionStrategy.DEFAULT)
        except Exception:
            self._credentials = None
            raise
        log.debug("[PAIRING] inclusion window opened for %ds (%s)", duration_sec, kind)
        if self._closing_window is not None:
            self._closing_window.cancel()
        self._closing_window = self._spawn(self._close_pairing_window(duration_sec))

    async def pair_device(self, discovery: Discovery, credentials: ProvidedCredentials | None) -> UUID:
        known = self._discoveries.get(discovery.id)
        node = self._joined.get(discovery.id)
        if known is None or node is None:
            raise ValueError("Unknown device: it is no longer discovered")
        try:
            if credentials is not None and credentials.type != CredentialsType.none:
                raise ValueError("Z-Wave credentials are given when opening the pairing window")
            await self._wait_until_ready(node)
            async with self.dependencies.make_device_repository() as repo:
                hub_device = await repo.get(discovery.id, as_=ZwaveDevice)  # the Hub creates it before pairing
            if hub_device is None:
                raise LookupError("The Hub has not created a device for this discovery")

            events = mapper.event_parameters(node, await self._supported_notification_events(node))
            parameters = self._build_parameters(discovery.id, node, events)
            main = mapper.main_value(node)
            main_id = self._parameter_id(discovery.id, main[0].value_id) if main else None
            for parameter in parameters:
                if main and parameter.id == main_id:
                    parameter.default_value = main[1]
            device = hub_device.model_copy(
                update={
                    "parameters": parameters,
                    "main_parameter": main_id
                    if any(p.id == main_id and p.can_be_main_parameter for p in parameters)
                    else None,
                    "available": True,
                    "last_error": None,
                    "integration_data": ZwaveDeviceIntegrationData(
                        home_id=self._controller().home_id or 0,
                        node_id=node.node_id,
                        fingerprint=self._fingerprint(node),
                    ),
                }
            )
            async with self.dependencies.make_device_repository() as repo:
                await repo.save(device)
            log.debug(
                "[PAIR] node_id=%s mapped schema\n\t%s",
                node.node_id,
                "\n\t".join(
                    f"{p.role:8} {p.visibility:8} {p.data_type:8} {p.name} ({p.integration_data.value_id})"
                    for p in parameters
                ),
            )
        except Exception as exc:
            log.warning("[PAIR] pairing %s failed: %s", discovery.id, exc)
            failed = known.model_copy(update={"last_error": str(exc)})
            self._discoveries[discovery.id] = failed
            await self.dependencies.output.controller_did_update_discovery(self, failed)
            raise

        self._discoveries.pop(discovery.id, None)
        self._joined.pop(discovery.id, None)
        self._bind(discovery.id, node, {event.value_id: event.valid_values for event in events})
        await self._set_available(discovery.id, True)
        await self._report_snapshot(discovery.id, node)
        return discovery.id

    async def unpair(self, device: ZwaveDevice):
        controller = self._controller()
        node = self._nodes.get(device.id)
        if node is None:  # not on the network anymore: nothing to remove
            self._unbind(device.id)
            return
        # A SmartStart device stays provisioned unless removed from the list: it would join again when powered on
        provisioning = await controller.async_get_provisioning_entry(node.node_id)
        if await controller.async_is_failed_node(node):
            await controller.async_remove_failed_node(node)
        else:
            # A live node leaves only when the device itself confirms (its button, per the manufacturer)
            await self._update_device(device.id, last_error="Put the device into exclusion mode to remove it")
            self._removal = asyncio.get_running_loop().create_future()
            try:
                await controller.async_begin_exclusion()
                removed = await asyncio.wait_for(self._removal, self.EXCLUSION_TIMEOUT)
            except TimeoutError:
                reason = "The device was not put into exclusion mode in time: it is still on the network"
                await self._update_device(device.id, last_error=reason)
                raise TimeoutError(reason) from None
            finally:
                self._removal = None
                try:
                    await controller.async_stop_exclusion()
                except Exception:  # noqa: BLE001  already stopped by the removal
                    log.debug("[UNPAIR] stop exclusion failed", exc_info=True)
            if removed != node.node_id:
                reason = f"another device (node {removed}) was excluded instead: it left the network"
                await self._update_device(device.id, last_error=f"Not removed: {reason}")
                raise LookupError(reason)
        if provisioning is not None:
            await controller.async_unprovision_smart_start_node(provisioning.dsk)
        self._unbind(device.id)
        self._available.pop(device.id, None)

    async def identify(self, device: ZwaveDevice):
        node = self._require_node(device)
        indicator = next(  # Indicator CC v3 "identify": the device's own identify pattern, cross-vendor
            (
                v
                for v in node.values.values()
                if v.command_class == CommandClass.INDICATOR and v.property_ == "identify"
            ),
            None,
        )
        if indicator is not None:
            await node.async_set_value(indicator, True)
            log.debug("[IDENTIFY] node_id=%s via Indicator CC", node.node_id)
            return
        if any(v.command_class == CommandClass.SWITCH_COLOR for v in node.values.values()):
            await self._blink(node)  # a light: blinking it is harmless, unlike toggling a relay's load
            return
        log.info("[IDENTIFY] node_id=%s has no identify indicator and is not a light: nothing to show", node.node_id)

    async def _blink(self, node: Node) -> None:
        level = next(
            (
                v
                for v in node.values.values()
                if v.command_class == CommandClass.SWITCH_MULTILEVEL and v.property_ == "targetValue"
            ),
            None,
        )
        if level is None:
            return
        current = node.values.get(level.value_id.replace("targetValue", "currentValue"))
        restore = current.value if current is not None and isinstance(current.value, int) else 0
        for _ in range(self.IDENTIFY_BLINKS):
            await node.async_set_value(level, 99 if restore == 0 else 0)
            await asyncio.sleep(self.IDENTIFY_PERIOD)
            await node.async_set_value(level, restore)
            await asyncio.sleep(self.IDENTIFY_PERIOD)
        log.debug("[IDENTIFY] node_id=%s blinked", node.node_id)

    async def fetch(self, device: ZwaveDevice):
        await self._report_snapshot(device.id, self._require_node(device))

    async def send_command(self, command: DeviceCommand, device: ZwaveDevice, parameter: ZwaveParameter):
        node = self._nodes.get(device.id)
        if node is None:
            reason = f"{parameter.name} could not be set: the device is not connected"
            await self._update_device(device.id, last_error=reason)
            raise ConnectionError(reason)
        value = node.values.get(parameter.integration_data.value_id)
        if value is None:
            raise ValueError(f"{parameter.name} is not a value of this device")
        if not value.metadata.writeable:
            raise ValueError(f"{parameter.name} is read-only")

        awake = node.status != NodeStatus.ASLEEP  # a sleeping device gets the command when it wakes up
        try:
            result = await node.async_set_value(value, mapper.to_device(value, command.value), wait_for_result=awake)
        except Exception as exc:
            reason = f"{parameter.name} could not be set: {exc or type(exc).__name__}"
            await self._update_device(device.id, last_error=reason)
            raise ConnectionError(reason) from exc
        if awake and (result is None or result.status not in APPLIED):
            reason = f"{parameter.name} could not be set: the device refused it ({result})"
            await self._update_device(device.id, last_error=reason)
            raise RuntimeError(reason)
        # no echo: the device's report (or zwave-js's verification of it) comes back as "value updated"
        await self._update_device(device.id, last_error=None)
        if awake and result is not None and result.status == SetValueStatus.SUCCESS_UNSUPERVISED:
            state = node.values.get(parameter.integration_data.state_value_id or value.value_id, value)
            self._spawn(self._verify(node, state, mapper.to_device(value, command.value)))

    async def _verify(self, node: Node, state: Value, sent: Any) -> None:
        """Reads a value back after an unconfirmed set, unless zwave-js already did (its value then is the sent one)."""
        await asyncio.sleep(self.VERIFY_DELAY)
        if state.metadata.readable and state.value != sent and node.status != NodeStatus.DEAD:
            await node.async_poll_value(state)

    # =========================================================================
    # Private helpers
    # =========================================================================

    def _controller(self) -> Controller:
        if self._zwave_client is None or self._zwave_client.driver is None:
            raise ConnectionError("Not connected to zwave-js-server")
        return self._zwave_client.driver.controller

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
        """Runs a handler in the background; its failure is logged, never lost or raised into the library."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (exc := task.exception()) is not None:
            log.error("[TASK] %s failed", task.get_coro(), exc_info=exc)

    def _track(self, unsubscribe: Callable[[], None]) -> None:
        self._listeners.append(unsubscribe)

    def _require_node(self, device: ZwaveDevice) -> Node:
        node = self._nodes.get(device.id)
        if node is None:
            raise ConnectionError(f"Device {device.name} is not connected")
        return node

    def _parameter_id(self, device_id: UUID, value_id: str) -> UUID:
        return self.parameter_uuid(device_id, value_id)

    @staticmethod
    def _fingerprint(node: Node) -> str | None:
        ids = (node.manufacturer_id, node.product_type, node.product_id)
        return ":".join(f"{i:04x}" for i in ids) if all(i is not None for i in ids) else None

    async def _update_device(self, device_id: UUID, **changes: Any) -> None:
        async with self.dependencies.make_device_repository() as repo:
            device = await repo.get(device_id, as_=ZwaveDevice)
            if device is not None and any(getattr(device, k) != v for k, v in changes.items()):
                await repo.save(device.model_copy(update=changes))

    # -------------------------------------------------------------------------
    # Pairing
    # -------------------------------------------------------------------------

    async def _offer(self, node: Node, low_security: bool = False) -> None:
        device_id = self.device_uuid(f"{self._controller().home_id or 0:08x}-{node.node_id}")
        self._joined[device_id] = node
        if device_id in self._discoveries:
            return
        discovery = Discovery(
            id=device_id,
            integration=NonEmptyStr(self.name),
            expected_credentials_options=[CredentialsType.none],
            expiration=None,
            transport=NonEmptyStr("ZWAVE"),
            device_manufacturer=None,
            device_name=NonEmptyStr(node.name or node.device_config.description or f"Z-Wave node {node.node_id}"),
            device_category=None,
            device_icon=None,
            last_error=(
                "Joined without S2 authentication: open the pairing window with the device's PIN to include it securely"
                if low_security
                else None
            ),
        )
        self._discoveries[device_id] = discovery
        log.debug("[DISCOVERY] node_id=%s discovery_id=%s", node.node_id, device_id)
        await self.dependencies.output.controller_did_receive_discovery(self, discovery)

    async def _close_pairing_window(self, duration_sec: int) -> None:
        await asyncio.sleep(duration_sec)
        self._credentials = None
        controller = self._controller()
        await controller.async_stop_inclusion()
        log.debug("[PAIRING] inclusion window closed")

        # Joined but never paired: a node that failed is removed (it can't be paired anymore); a live one stays a
        # discovery: it is a real Z-Wave node, and the user must still be able to pair or remove it
        for node in list(self._joined.values()):
            if await controller.async_is_failed_node(node):
                await controller.async_remove_failed_node(node)
                log.debug("[PAIRING] node_id=%s removed after failing before it was paired", node.node_id)

    async def _wait_until_ready(self, node: Node) -> None:
        """Waits for the interview that fills node.values."""
        if node.ready:
            return
        became_ready = asyncio.Event()
        unsubscribe = node.on("ready", lambda _: became_ready.set())
        try:
            await asyncio.wait_for(became_ready.wait(), self.READY_TIMEOUT)
        except TimeoutError:
            raise TimeoutError(
                "The device did not finish its interview: wake it up (or move it closer) and pair it again"
            ) from None
        finally:
            unsubscribe()

    async def _supported_notification_events(self, node: Node) -> list[dict[str, Any]]:
        """The keypad and Notification CC events the node supports, as zwave-js knows them from its interview."""
        assert self._zwave_client is not None
        try:
            result = await self._zwave_client.async_send_command(
                {"command": "node.get_supported_notification_events", "nodeId": node.node_id}, require_schema=43
            )
        except Exception:  # noqa: BLE001  an older server: no keypad or Notification CC event parameters
            log.warning("[PAIR] node_id=%s: supported notification events unknown", node.node_id, exc_info=True)
            return []
        return result.get("events", [])

    def _build_parameters(
        self, device_id: UUID, node: Node, events: list[mapper.EventParameter]
    ) -> list[ZwaveParameter]:
        """The device's parameters; their values reach the Hub as events (the snapshot after pairing)."""
        parameters: list[ZwaveParameter] = []
        pairs = mapper.parameter_values(node)
        for (value, state), name in zip(pairs, mapper.names(pairs), strict=True):
            low, high, step = mapper.limits(value)
            parameters.append(
                ZwaveParameter(
                    id=self._parameter_id(device_id, value.value_id),
                    name=name,
                    data_type=mapper.data_type(value),
                    role=mapper.role(value),
                    visibility=mapper.visibility(value, node),
                    min_value=low,
                    max_value=high,
                    min_step=step,
                    unit=mapper.unit(value),
                    valid_values=mapper.valid_values(value),
                    integration_data=ZwaveParameterIntegrationData(
                        value_id=value.value_id, state_value_id=state.value_id if state else None
                    ),
                )
            )
        parameters += [
            ZwaveParameter(
                id=self._parameter_id(device_id, event.value_id),
                name=event.name,
                data_type=event.data_type,
                role=ParameterRole.event,
                visibility=event.visibility,
                unit=event.unit,
                valid_values=event.valid_values,
                integration_data=ZwaveParameterIntegrationData(value_id=event.value_id),
            )
            for event in events
        ]
        return parameters

    async def _grant(self, requested: InclusionGrant) -> None:
        """Grants what the joining device requested, except what needs a PIN nobody gave: then it joins with less
        security, and says so, instead of waiting for a PIN that never comes."""
        classes = requested.security_classes
        if self._credentials is None:
            classes = [c for c in classes if c not in AUTHENTICATED]
        grant = InclusionGrant(security_classes=classes, client_side_auth=requested.client_side_auth)
        await self._controller().async_grant_security_classes(grant)
        log.debug("[S2] granted %s of %s", classes, requested.security_classes)

    async def _enter_pin(self) -> None:
        credentials = self._credentials
        if credentials is None or credentials.type != CredentialsType.code or not credentials.value:
            log.warning("[S2] the device asks for its PIN, but none was given")
            return
        await self._controller().async_validate_dsk_and_enter_pin(credentials.value[:5])

    # -------------------------------------------------------------------------
    # Device <-> Hub: Z-Wave network events & availability
    # -------------------------------------------------------------------------

    async def _node_added(self, node: Node, data: dict) -> None:
        log.debug("[JOIN] node_id=%s", node.node_id)
        result = data.get("result") or {}
        await self._offer(node, low_security=bool(result.get("lowSecurity")))

    async def _node_removed(self, node: Node) -> None:
        log.debug("[REMOVED] node_id=%s", node.node_id)
        if self._removal is not None and not self._removal.done():
            self._removal.set_result(node.node_id)
        for device_id, joined in list(self._joined.items()):
            if joined.node_id == node.node_id:
                self._joined.pop(device_id)
                if self._discoveries.pop(device_id, None) is not None:
                    await self.dependencies.output.controller_did_lose_discovery(self, device_id)
        for device_id, bound in list(self._nodes.items()):
            if bound.node_id == node.node_id:
                self._unbind(device_id)
                await self._set_available(device_id, False, "The device was removed from the Z-Wave network")

    def _bind(self, device_id: UUID, node: Node, events: dict[str, Any]) -> None:
        self._unbind(device_id)
        self._nodes[device_id] = node
        self._routes[device_id] = mapper.reported_parameters(node)
        self._events[device_id] = events
        self._unsubscribe[device_id] = [
            node.on("notification", lambda data: self._spawn(self._notified(device_id, data["notification"]))),
            node.on("value updated", lambda data: self._spawn(self._value_updated(device_id, data["value"]))),
            node.on(
                "value notification",
                lambda data: self._spawn(self._value_updated(device_id, data["value_notification"])),
            ),
            node.on("dead", lambda _: self._spawn(self._update_availability(device_id, node))),
            node.on("alive", lambda _: self._spawn(self._update_availability(device_id, node))),
        ]

    def _unbind(self, device_id: UUID) -> None:
        self._nodes.pop(device_id, None)
        self._routes.pop(device_id, None)
        self._events.pop(device_id, None)
        for unsubscribe in self._unsubscribe.pop(device_id, []):
            unsubscribe()

    async def _update_availability(self, device_id: UUID, node: Node) -> None:
        dead = node.status == NodeStatus.DEAD
        await self._set_available(device_id, not dead, "The device does not respond" if dead else None)

    async def _set_available(self, device_id: UUID, available: bool, reason: str | None = None) -> None:
        """Reports a change of availability (with its reason as the device's last error)."""
        if self._available.get(device_id) == available:
            return
        self._available[device_id] = available
        await self._update_device(device_id, available=available, last_error=None if available else reason)
        if available:
            await self.dependencies.output.controller_did_connect_device(self, device_id)
        else:
            await self.dependencies.output.controller_did_lose_device(self, device_id)

    async def _value_updated(self, device_id: UUID, value: Value) -> None:
        routes = self._routes.get(device_id, {})
        parameter_value_id = routes.get(value.value_id, value.value_id)
        if parameter_value_id is None:  # a target: the state is its current value
            return
        if value.value_id not in routes:  # appeared after pairing: no parameter for it
            log.debug("[VALUE] %s has no parameter", value.value_id)
            return
        event = DeviceParameterChange(
            device_id=device_id,
            parameter_id=self._parameter_id(device_id, parameter_value_id),
            value=mapper.to_hub(value, value.value),
        )
        await self.dependencies.output.controller_did_receive_events(self, [event])

    async def _notified(self, device_id: UUID, notification: Any) -> None:
        known = self._events.get(device_id, {})
        changes = []
        for value_id, value in mapper.notification_events(notification):
            if value_id not in known or (known[value_id] and value not in known[value_id]):
                log.debug("[EVENT] %s=%r: not an event the device announced", value_id, value)
                continue
            parameter_id = self._parameter_id(device_id, value_id)
            changes.append(DeviceParameterChange(device_id=device_id, parameter_id=parameter_id, value=value))
        if changes:
            await self.dependencies.output.controller_did_receive_events(self, changes)

    async def _report_snapshot(self, device_id: UUID, node: Node) -> None:
        events = [
            DeviceParameterChange(
                device_id=device_id,
                parameter_id=self._parameter_id(device_id, value.value_id),
                value=mapper.to_hub(state or value, (state or value).value),
            )
            for value, state in mapper.parameter_values(node)
            if mapper.role(value) != ParameterRole.event and (value.metadata.readable or state is not None)
        ]
        if events:
            await self.dependencies.output.controller_did_receive_events(self, events)
