import asyncio
import logging
from typing import ClassVar, override
from uuid import UUID

from aiohttp import ClientSession
from zwave_js_server.client import Client as ZwaveClient
from zwave_js_server.const import CommandClass, InclusionStrategy, NodeStatus, SecurityClass
from zwave_js_server.model.controller.inclusion_and_provisioning import InclusionGrant
from zwave_js_server.model.node import Node
from zwave_js_server.model.value import Value
from zwave_js_server.model.utils import async_parse_qr_code_string
from majordom_integration_sdk.controller import AbstractController
from majordom_integration_sdk.schemas import DeviceCommand, Discovery, ProvidedCredentials
from majordom_integration_sdk.schemas.device import CredentialsType, NonEmptyStr
from majordom_integration_sdk.schemas.event import DeviceParameterChange
from majordom_integration_sdk.schemas.parameter import ParameterUnit

from .config import zwave_server_url
from .model import (
    ZwaveDevice,
    ZwaveDeviceState,
    ZwaveDeviceIntegrationData,
    ZwaveParameter,
    ZwaveParameterIntegrationData,
    ZwaveParameterState,
)
from .exceptions import ZwaveConnectionError, ZwaveUnexpectedError
from .mapper import ZwaveMapper
from .zwave_spec import IDENTIFY_INDICATOR_ID

log = logging.getLogger(__name__)

#TODO: заполнить ридми под интеграцию по примерам меттера и зигби

class ZwaveController(AbstractController):
    """Bridges the Hub to Z-Wave devices through zwave-js-server."""

    name: ClassVar[str] = "ZWave"

    _zwave_session: ClientSession
    _zwave_client: ZwaveClient

    _mapper: ZwaveMapper

    _majordom_discoveries: dict[UUID, Discovery]
    _awaiting_zw_discoveries: dict[UUID, Node]
    _connected_devices: dict[UUID, Node]
    _availability: dict[UUID, bool]
    _tasks: set[asyncio.Task]

    def __init__(self, dependencies: AbstractController.Dependencies):
        super().__init__(dependencies)
        self._mapper = ZwaveMapper()
        self._majordom_discoveries = {}
        self._awaiting_zw_discoveries = {}
        self._connected_devices = {}
        self._availability = {}
        self._tasks = set()

    # -------------------------------------------------------------------------
    # AbstractController interface
    # -------------------------------------------------------------------------

    @property
    def discoveries(self) -> dict[UUID, Discovery]:
        return self._majordom_discoveries

    @property
    @override
    def device_type(self) -> type[ZwaveDevice]:
        return ZwaveDevice

    @property
    @override
    def parameter_type(self) -> type[ZwaveParameter]:
        return ZwaveParameter

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def start(self):
        self._zwave_session = ClientSession()
        self._zwave_client = ZwaveClient(zwave_server_url, self._zwave_session)
        await self._zwave_client.connect()

        ready = asyncio.Event()
        self._create_task(self._zwave_client.listen(ready))
        await ready.wait()

        controller = self._zwave_client.driver.controller
        controller.on("node added", lambda data: self._create_task(self._node_added(data["node"])))
        controller.on("node removed", lambda data: self._create_task(self._node_removed(data["node"])))
        # S2 auto-grant only — no PIN prompt / no discovery raised for it.
        controller.on("grant security classes", lambda data: self._create_task(self._grant_security_classes(data["requested"])))

        log.debug("[READY] connected to %s", zwave_server_url)

        async with self.dependencies.make_device_repository() as device_repository:
            try:
                known_node_ids: set[int] = set()
                for raw_device in await device_repository.get_all():
                    try:
                        device = ZwaveDevice.model_validate(raw_device.model_dump())
                    except Exception:
                        log.debug("[SKIP] device_id=%s not paired yet, skipping", raw_device.id)
                        continue

                    node = controller.nodes.get(device.integration_data.node_id)
                    if node is None:
                        device.available = False
                        device.last_error = f"Device {device.name} is no longer connected to the Z-Wave network"
                        await device_repository.save(device, device.id)
                        log.debug("[MISSING] device_id=%s node_id=%s not on network", device.id, device.integration_data.node_id)
                        continue
                    known_node_ids.add(node.node_id)
                    self._connected_devices[device.id] = node
                    self._availability[device.id] = node.ready
                    self._subscribe(device.id, node)
                    log.debug("[KNOWN] node_id=%s", node.node_id)

                # Nodes already on the network but not ours yet (Hub restart, pre-existing node).
                log.debug("[RECONCILE] %d node(s) on network, own_node_id=%s", len(controller.nodes), controller.own_node_id)
                for node in controller.nodes.values():
                    if node.node_id == controller.own_node_id or node.node_id in known_node_ids:
                        continue
                    await self._node_added(node)
            except Exception:
                log.exception("[START] node reconciliation failed")
                raise

    async def stop(self):
        self._require_client()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self._zwave_client.disconnect()
        await self._zwave_session.close()

        self._majordom_discoveries.clear()
        self._awaiting_zw_discoveries.clear()
        self._connected_devices.clear()

    # -------------------------------------------------------------------------
    # Hub -> device operations
    # -------------------------------------------------------------------------

    async def start_pairing_window(self, duration_sec: int, credentials: ProvidedCredentials | None = None) -> None:
        self._require_client()
        controller = self._zwave_client.driver.controller

        if credentials and credentials.type is CredentialsType.qr:
            if not credentials.value:
                raise ZwaveUnexpectedError("QR credentials provided without QR data")
            provisioning_info = await async_parse_qr_code_string(self._zwave_client, credentials.value)
            await controller.async_begin_inclusion(InclusionStrategy.SECURITY_S2, provisioning=provisioning_info)
            log.debug("[PAIRING] inclusion window opened for %ds via QR", duration_sec)

        elif credentials and credentials.type is CredentialsType.code:
            if not credentials.value:
                raise ZwaveUnexpectedError("PIN credentials provided without a value")
            await controller.async_begin_inclusion(InclusionStrategy.SECURITY_S2, dsk=credentials.value)
            log.debug("[PAIRING] inclusion window opened for %ds with pre-supplied PIN", duration_sec)

        elif credentials and credentials.type is CredentialsType.secret:
            raise ZwaveUnexpectedError("Z-Wave does not support secret-based pairing credentials")

        else:
            await controller.async_begin_inclusion(InclusionStrategy.DEFAULT)
            log.debug("[PAIRING] inclusion window opened for %ds", duration_sec)

        self._create_task(self._close_pairing_window(duration_sec))

    async def pair_device(self, discovery: Discovery, credentials: ProvidedCredentials | None) -> UUID:
        """Waits for the pending node's interview to finish, then builds and saves the device."""
        self._require_client()

        node = self._awaiting_zw_discoveries.pop(discovery.id, None)
        if node is None:
            raise ZwaveUnexpectedError(f"No pending Z-Wave discovery for {discovery.id}")
        self._majordom_discoveries.pop(discovery.id, None)

        await self._wait_until_ready(node)

        device_id = self._mapper.device_uuid_from_node_id(node.node_id)
        self._connected_devices[device_id] = node

        async with self.dependencies.make_device_repository() as device_repository:
            device = await device_repository.state(discovery.id, ZwaveDeviceState)
            assert device
            device.id = device_id

            if device.integration_data:
                device.integration_data.node_id = node.node_id
            else:
                device.integration_data = ZwaveDeviceIntegrationData(node_id=node.node_id)

            parameters = self._build_parameters(device_id, node)
            device.parameters = parameters

            main_parameter_id, default_value = self._mapper.get_main_parameter(device_id, node)
            device.main_parameter = main_parameter_id
            if main_parameter_id and default_value is not None:
                main_parameter = next((p for p in parameters if p.id == main_parameter_id), None)
                if main_parameter is None:
                    device.main_parameter = None
                else:
                    main_parameter.default_value = default_value

            log.debug(
                f"[PAIR] node_id={node.node_id} mapped schema\n\t"
                + "\n\t".join(
                    f"  {p.role.value:8} {p.visibility.value:8} {p.data_type.value:10} {p.name}  id={p.id}"
                    for p in parameters
                ),
            )

            await device_repository.save(device, discovery.id)

        self._subscribe(device_id, node)
        await self._set_availability(device_id, True)
        await self.dependencies.output.controller_did_connect_device(self, device_id)
        return device_id

    async def unpair(self, device: ZwaveDevice):
        self._require_client()
        controller = self._zwave_client.driver.controller
        zwave_node = self._require_node(device)

        if await controller.async_is_failed_node(zwave_node):
            await controller.async_remove_failed_node(zwave_node)
        else:
            # Live node: requires interactive exclusion, confirmed by the device itself.
            async with self.dependencies.make_device_repository() as device_repository:
                stored = await device_repository.get(device.id, as_=ZwaveDevice)
                if stored:
                    stored.last_error = (
                        "Trigger exclusion mode on the device manually "
                        "(see manufacturer instructions) to complete removal"
                    )
                    await device_repository.save(stored, device.id)

            removed = asyncio.Event()

            def _on_node_removed(data: dict) -> None:
                if data["node"].node_id == zwave_node.node_id:
                    removed.set()

            unsubscribe = controller.on("node removed", _on_node_removed)
            try:
                await controller.async_begin_exclusion()
                try:
                    await asyncio.wait_for(removed.wait(), timeout=60)
                except asyncio.TimeoutError:
                    raise ZwaveUnexpectedError(
                        f"Node {zwave_node.node_id} was not excluded in time — make sure the "
                        f"device was put into exclusion mode"
                    ) from None
            finally:
                unsubscribe()
                await controller.async_stop_exclusion()

        self._connected_devices.pop(device.id, None)
        self._availability.pop(device.id, None)

    async def identify(self, device: ZwaveDevice):
        self._require_client()
        zwave_node = self._require_node(device)

        indicator_value = next(
            (
                v
                for v in zwave_node.values.values()
                if v.command_class == CommandClass.INDICATOR
                and v.property_ == "value"
                and v.property_key == IDENTIFY_INDICATOR_ID
            ),
            None,
        )
        if indicator_value is not None:
            await zwave_node.async_set_value(indicator_value, 0xFF)
            log.debug("[IDENTIFY] node_id=%s via Indicator CC", zwave_node.node_id)
            return

        switch_value = next(
            (
                v
                for v in zwave_node.values.values()
                if v.command_class in (CommandClass.SWITCH_BINARY, CommandClass.SWITCH_MULTILEVEL)
                and v.property_ == "targetValue"
            ),
            None,
        )
        if switch_value is None:
            raise ZwaveUnexpectedError(
                f"Node {zwave_node.node_id} supports neither Indicator CC nor a switch to blink"
            )

        current_value = zwave_node.values.get(
            switch_value.value_id.replace("targetValue", "currentValue")
        )
        restore_value = current_value.value if current_value and current_value.value is not None else 0

        on_value = 0xFF if switch_value.command_class == CommandClass.SWITCH_BINARY else 99
        for _ in range(10):
            await zwave_node.async_set_value(switch_value, 0)
            await asyncio.sleep(0.6)
            await zwave_node.async_set_value(switch_value, on_value)
            await asyncio.sleep(0.6)

        await zwave_node.async_set_value(switch_value, restore_value)
        log.debug("[IDENTIFY] node_id=%s via switch blink fallback", zwave_node.node_id)

    async def fetch(self, device: ZwaveDevice):
        self._require_client()

        zwave_node = self._require_node(device)
        parameters: list[DeviceParameterChange] = []
        for value_id, value in zwave_node.values.items():
            parameters.append(DeviceParameterChange(
                device_id=device.id,
                parameter_id=self._mapper.parameter_uuid(device.id, value_id),
                value=self._mapper.format_zwave_value(value),
            ))

        await self.dependencies.output.controller_did_receive_events(self, parameters)

    async def send_command(self, command: DeviceCommand, device: ZwaveDevice, parameter: ZwaveParameter):
        self._require_client()

        zwave_node = self._require_node(device)
        zwave_value = self._require_value(parameter.integration_data.value_id, zwave_node)
        if zwave_value.metadata.writeable is False:
            raise ZwaveUnexpectedError(f"Value {parameter.integration_data.value_id} is not writeable")
        try:
            awake = zwave_node.status != NodeStatus.ASLEEP
            result = await zwave_node.async_set_value(zwave_value, command.value, wait_for_result=awake)
            log.info(result)
        except Exception as e:
            raise ZwaveUnexpectedError(
                f"Failed to set value {parameter.integration_data.value_id} on node {zwave_node.node_id}: {e}"
            ) from None
        if awake and result is not None and not result.status:
            log.warning("[CMD] node_id=%s value_id=%s result=%s", zwave_node.node_id, parameter.integration_data.value_id, result)

        await self.dependencies.output.controller_did_receive_events(
            self, [DeviceParameterChange(device_id=device.id, parameter_id=parameter.id, value=command.value)]
        )

    # =========================================================================
    # Private helpers
    # =========================================================================

    # -------------------------------------------------------------------------
    # Generic guards / lookups
    # -------------------------------------------------------------------------

    def _create_task(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _require_client(self) -> ZwaveClient:
        if self._zwave_client and self._zwave_client.connected:
            return self._zwave_client
        raise ZwaveConnectionError("Zwave client is not started")

    def _require_node(self, device: ZwaveDevice) -> Node:
        node = self._zwave_client.driver.controller.nodes.get(device.integration_data.node_id)
        if not node:
            raise ZwaveUnexpectedError(f"Node for device {device.id} not found")
        return node

    def _require_value(self, value_id: str, node: Node) -> Value:
        value = node.values.get(value_id)
        if not value:
            raise ZwaveUnexpectedError(f"Value with {value_id} id for node {node.node_id} not found")
        return value

    # -------------------------------------------------------------------------
    # Pairing
    # -------------------------------------------------------------------------

    async def _close_pairing_window(self, duration_sec: int) -> None:
        await asyncio.sleep(duration_sec)
        controller = self._zwave_client.driver.controller
        await controller.async_stop_inclusion()
        log.debug("[PAIRING] inclusion window closed")

        # Anything discovered but never claimed via pair_device gets dropped.
        for device_id in list(self._majordom_discoveries):
            self._majordom_discoveries.pop(device_id, None)
            node = self._awaiting_zw_discoveries.pop(device_id, None)
            if node is None:
                continue
            if await controller.async_is_failed_node(node):
                await controller.async_remove_failed_node(node)
            else:
                log.warning(
                    "[PAIRING] node_id=%s joined but was never paired, can't force-remove while alive",
                    node.node_id,
                )

    async def _wait_until_ready(self, node: Node) -> None:
        """Waits for the background interview to populate node.values."""
        if node.ready:
            return
        became_ready = asyncio.Event()
        unsubscribe = node.on("ready", lambda data: became_ready.set())
        try:
            await asyncio.wait_for(became_ready.wait(), timeout=120)
        except asyncio.TimeoutError:
            log.warning("[PAIR] node_id=%s not ready after 120s, pairing with partial values", node.node_id)
        finally:
            unsubscribe()

    def _build_parameters(self, device_id: UUID, node: Node) -> list[ZwaveParameterState]:
        """Maps every Z-Wave value on a node into a majordom parameter state."""
        parameters: list[ZwaveParameterState] = []
        for value_id, value in node.values.items():
            metadata = value.metadata
            parameter = ZwaveParameterState(
                id=self._mapper.parameter_uuid(device_id, value_id),
                name=metadata.label or value.property_name or value.property_key_name or str(value.property_),
                data_type=self._mapper.parse_zwave_data_type(value),
                role=self._mapper.get_role(value.command_class, metadata),
                visibility=self._mapper.get_visibility(value.command_class, metadata),
                min_value=metadata.min,
                max_value=metadata.max,
                min_step=self._mapper.get_min_step(value),
                unit=self._mapper.get_unit(metadata.unit) or ParameterUnit.plain,
                valid_values=self._mapper.parse_zwave_valid_values(metadata),
                integration_data=ZwaveParameterIntegrationData(value_id=value_id),
                value=self._mapper.format_zwave_value(value),
            )
            parameters.append(parameter)
        return parameters

    async def _grant_security_classes(self, requested: dict) -> None:
        """Grants exactly what the joining device requested — no user choice involved."""
        grant = InclusionGrant(
            security_classes=[SecurityClass(c) for c in requested["securityClasses"]],
            client_side_auth=requested["clientSideAuth"],
        )
        await self._zwave_client.driver.controller.async_grant_security_classes(grant)
        log.debug("[S2] granted security classes=%s", requested["securityClasses"])

    # -------------------------------------------------------------------------
    # Device <-> Hub: Z-Wave network events & availability
    # -------------------------------------------------------------------------

    async def _node_added(self, node: Node):
        """New node joined — surfaces a discovery unless it's already known."""
        log.debug("[JOIN] node_id=%s", node.node_id)

        device_id = self._mapper.device_uuid_from_node_id(node.node_id)

        if device_id in self._connected_devices:
            self._connected_devices[device_id] = node
            self._subscribe(device_id, node)
            await self._set_availability(device_id, True)
            return

        if device_id in self._majordom_discoveries:
            self._awaiting_zw_discoveries[device_id] = node
            return

        discovery = Discovery(
            id=device_id,
            integration=NonEmptyStr(self.name),
            expected_credentials_options=[CredentialsType.none],
            expiration=None,
            transport=NonEmptyStr("ZWAVE"),
            device_manufacturer=None,
            device_name=NonEmptyStr(node.name or node.device_config.description or "Unknown"),
            device_category=None,
            device_icon=None,
        )
        self._majordom_discoveries[device_id] = discovery
        self._awaiting_zw_discoveries[device_id] = node
        log.debug("[DISCOVERY] node_id=%s discovery_id=%s", node.node_id, device_id)
        await self.dependencies.output.controller_did_receive_discovery(self, discovery)

    async def _node_removed(self, node: Node):
        device_id = self._mapper.device_uuid_from_node_id(node.node_id)
        log.debug("[REMOVED] node_id=%s", node.node_id)
        if device_id in self._connected_devices:
            self._connected_devices.pop(device_id, None)
            await self._set_availability(device_id, False)

    async def _set_availability(self, device_id: UUID, available: bool) -> None:
        """Only reports on actual change."""
        if self._availability.get(device_id) == available:
            return
        self._availability[device_id] = available
        if available:
            await self.dependencies.output.controller_did_connect_device(self, device_id)
        else:
            await self.dependencies.output.controller_did_lose_device(self, device_id)

    def _subscribe(self, device_id: UUID, node: Node) -> None:
        node.on("value updated", lambda data: self._create_task(self._value_updated(device_id, data["value"])))
        node.on("dead", lambda data: self._create_task(self._set_availability(device_id, False)))
        node.on("alive", lambda data: self._create_task(self._set_availability(device_id, True)))

    async def _value_updated(self, device_id: UUID, value: Value) -> None:
        parameter_id = self._mapper.parameter_uuid(device_id, value.value_id)
        event = DeviceParameterChange(device_id=device_id, parameter_id=parameter_id, value=self._mapper.format_zwave_value(value))
        await self.dependencies.output.controller_did_receive_events(self, [event])