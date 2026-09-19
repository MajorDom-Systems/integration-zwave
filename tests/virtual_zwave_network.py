"""In-memory zwave-js-server stub. Patches zwave_js_server.client.Client so any
Client the controller creates becomes an in-memory stub instead of hitting a
real server. Everything else (Driver/Controller/Node/Value) is the real library.
"""

from __future__ import annotations

import asyncio
from typing import Any, Self, cast
from unittest.mock import AsyncMock, Mock, patch

from zwave_js_server.client import Client
from zwave_js_server.event import Event
from zwave_js_server.model.driver import Driver
from zwave_js_server.model.log_config import LogConfigDataType
from zwave_js_server.model.node import Node
from zwave_js_server.model.node.data_model import NodeDataType

_LOG_CONFIG: LogConfigDataType = {
    "enabled": True,
    "level": "info",
    "logToFile": False,
    "filename": "",
    "forceConsole": False,
}

_DEFAULT_CONTROLLER_STATE: dict[str, Any] = {
    "controller": {
        "sdkVersion": "Z-Wave 3.95",
        "type": 1,
        "homeId": 1,
        "ownNodeId": 1,
        "isSecondary": False,
        "isUsingHomeIdFromOtherNetwork": False,
        "isSISPresent": True,
        "wasRealPrimary": True,
        "isStaticUpdateController": True,
        "isSlave": False,
        "firmwareVersion": "1.0",
        "manufacturerId": 1,
        "productType": 1,
        "productId": 1,
        "supportedFunctionTypes": [],
        "sucNodeId": 1,
        "supportsTimers": False,
        "isRebuildingRoutes": False,
        "inclusionState": 0,
    },
    "nodes": [],
}

_DEFAULT_VALUE_METADATA = {"type": "boolean", "readable": True, "writeable": True}

_DEFAULT_NODE_VALUES: list[dict[str, Any]] = [
    {
        "commandClass": 37,
        "commandClassName": "Binary Switch",
        "endpoint": 0,
        "property": "currentValue",
        "propertyName": "currentValue",
        "value": False,
        "ccVersion": 1,
        "metadata": {
            "type": "boolean",
            "readable": True,
            "writeable": False,
            "label": "Current value",
        },
    },
    {
        "commandClass": 37,
        "commandClassName": "Binary Switch",
        "endpoint": 0,
        "property": "targetValue",
        "propertyName": "targetValue",
        "value": False,
        "ccVersion": 1,
        "metadata": {
            "type": "boolean",
            "readable": True,
            "writeable": True,
            "label": "Target value",
        },
    },
]

_DEFAULT_NODE_ENDPOINTS: list[dict[str, Any]] = [
    {
        "index": 0,
        "deviceClass": None,
        "commandClasses": [
            {"id": 37, "name": "Binary Switch", "version": 1, "isSecure": False},
        ],
    },
]

# Client.async_send_command's return value IS the server message's "result"
# field already unwrapped once -- each command needs the exact key(s) its
# caller reads off that dict (e.g. is_failed_node reads data["failed"]).
_DEFAULT_COMMAND_RESPONSES: dict[str, dict[str, Any]] = {
    "controller.begin_inclusion": {"success": True},
    "controller.stop_inclusion": {"success": True},
    "controller.begin_exclusion": {"success": True},
    "controller.stop_exclusion": {"success": True},
    "controller.is_failed_node": {"failed": False},
    "controller.remove_failed_node": {},
    "controller.replace_failed_node": {"success": True},
    "node.set_value": {"result": {"status": 255}},
    "node.refresh_info": {},
    "node.refresh_values": {},
}


class VirtualZwaveNetwork:
    def __init__(self, controller_state: dict | None = None) -> None:
        self.controller_state = controller_state or _DEFAULT_CONTROLLER_STATE
        self._command_responses = dict(_DEFAULT_COMMAND_RESPONSES)
        self.async_send_command = AsyncMock(side_effect=self._handle_send_command)
        self.async_send_command_no_wait = AsyncMock(return_value=None)
        self._client: Client | None = None
        self._patches: list[Any] = []

    async def _handle_send_command(self, message: dict, **_kwargs: Any) -> dict:
        return self._command_responses.get(message.get("command", ""), {"success": True})

    def set_response(self, command: str, response: dict) -> None:
        self._command_responses[command] = response

    def __enter__(self) -> Self:
        network = self

        async def fake_connect(client_self: Client) -> None:
            # Client.connected checks `_client is not None and not _client.closed`.
            client_self._client = Mock(closed=False)

        async def fake_listen(client_self: Client, driver_ready: asyncio.Event) -> None:
            client_self.driver = Driver(client_self, network.controller_state, _LOG_CONFIG)
            network._client = client_self
            driver_ready.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass

        async def fake_disconnect(client_self: Client) -> None:
            client_self.driver = None
            # Don't touch `_client.closed` (read-only on the real
            # ClientWebSocketResponse) -- dropping the reference entirely
            # makes `.connected` False too, which is what matters here.
            client_self._client = None

        self._patches = [
            patch.object(Client, "connect", new=fake_connect),
            patch.object(Client, "listen", new=fake_listen),
            patch.object(Client, "disconnect", new=fake_disconnect),
            patch.object(Client, "async_send_command", new=self.async_send_command),
            patch.object(
                Client,
                "async_send_command_no_wait",
                new=self.async_send_command_no_wait,
            ),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        for p in reversed(self._patches):
            p.stop()

    def _connected_client(self) -> Client:
        assert self._client is not None, "virtual_zwave used before controller.start() ran"
        return self._client

    @property
    def controller(self):
        client = self._connected_client()
        assert client.driver is not None, "virtual_zwave.controller accessed before controller.start() ran"
        return client.driver.controller

    def node_found(self, node_id: int) -> None:
        self.controller.emit("node found", {"node": {"nodeId": node_id}})

    def node_joined(self, node_data: dict) -> Node:
        payload: dict[str, Any] = {
            "status": 4,  # NodeStatus.ALIVE, not 1 (ASLEEP) -- ASLEEP makes
            # async_send_command silently switch to no_wait
            "ready": True,
            "interviewStage": "Complete",
            "endpoints": _DEFAULT_NODE_ENDPOINTS,
            "values": _DEFAULT_NODE_VALUES,
            **node_data,
        }
        node = Node(self._connected_client(), cast(NodeDataType, payload))
        self.controller.nodes[node.node_id] = node
        self.controller.emit("node added", {"node": node})
        return node

    def node_removed(self, node_id: int, reason: int = 0) -> None:
        node = self.controller.nodes.pop(node_id, None)
        if node is not None:
            self.controller.emit("node removed", {"node": node, "reason": reason})

    def emit_value_updated(
        self,
        node_id: int,
        *,
        command_class: int,
        command_class_name: str,
        property: int | str,
        new_value: Any,
        prev_value: Any = None,
        property_name: str | None = None,
        endpoint: int = 0,
        metadata: dict | None = None,
    ) -> None:
        node = self.controller.nodes[node_id]
        event = Event(
            "value updated",
            {
                "source": "node",
                "event": "value updated",
                "nodeId": node_id,
                "args": {
                    "commandClass": command_class,
                    "commandClassName": command_class_name,
                    "endpoint": endpoint,
                    "property": property,
                    "propertyName": property_name or str(property),
                    "newValue": new_value,
                    "prevValue": prev_value,
                    "metadata": metadata or _DEFAULT_VALUE_METADATA,
                },
            },
        )
        node.receive_event(event)
