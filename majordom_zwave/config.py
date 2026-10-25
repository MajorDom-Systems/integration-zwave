"""zwave-js-server: the service that owns the Z-Wave stick; this integration drives it over WebSocket."""

import secrets
from pathlib import Path

from majordom_integration_sdk import Endpoint, Need, Service
from pydantic import BaseModel, Field


def _key() -> str:
    return secrets.token_hex(16).upper()


class ZwaveNetwork(BaseModel):
    """Security keys of the Z-Wave network, generated once. Back them up: without them, securely
    included devices have to be re-included on a new controller."""

    s0_legacy: str = Field(default_factory=_key, title="S0 Legacy key")
    s2_unauthenticated: str = Field(default_factory=_key, title="S2 Unauthenticated key")
    s2_authenticated: str = Field(default_factory=_key, title="S2 Authenticated key")
    s2_access_control: str = Field(default_factory=_key, title="S2 Access Control key")
    lr_s2_authenticated: str = Field(default_factory=_key, title="Long Range S2 Authenticated key")
    lr_s2_access_control: str = Field(default_factory=_key, title="Long Range S2 Access Control key")


def zwave_js_server() -> Service[ZwaveNetwork]:
    """One for each runtime, which keeps on it what it is bound to and its settings."""
    return Service(
        "zwave-js-server",
        needs=[Need("zwave", ["serial-api"])],
        provides=[Endpoint("zwave", "zwave-js-ws", "ws://127.0.0.1:{ports.api}")],
        ports={"api": 3000},
        settings=ZwaveNetwork,
        compose={
            # :latest pinned by digest (2026-10-08); bump on purpose
            "image": "ghcr.io/kpine/zwave-js-server@sha256:19592f8e979525ac6f4e6cac22b28324edfaa757c9d2da3d6fec9c4b2ddd18a8",  # noqa: E501
            "network_mode": "host",
            # the image's own command, with a port it doesn't take from the environment
            "command": ["server", "/dev/zwave", "--config", "options.js", "--disable-dns-sd", "--port", "{ports.api}"],
            "userns_mode": "host",  # a remapped user can't open the stick on hosts with userns-remap
            "devices": ["{peripherals.zwave.url}:/dev/zwave"],
            # our device files take precedence over zwave-js's own (the image's priority dir)
            "volumes": ["{data}:/cache", f"{Path(__file__).parent / 'device_configs'}:/cache/config:ro"],
            "environment": {
                "S0_LEGACY_KEY": "{settings.s0_legacy}",
                "S2_UNAUTHENTICATED_KEY": "{settings.s2_unauthenticated}",
                "S2_AUTHENTICATED_KEY": "{settings.s2_authenticated}",
                "S2_ACCESS_CONTROL_KEY": "{settings.s2_access_control}",
                "LR_S2_AUTHENTICATED_KEY": "{settings.lr_s2_authenticated}",
                "LR_S2_ACCESS_CONTROL_KEY": "{settings.lr_s2_access_control}",
                "RF_REGION": "{context.region}",
            },
        },
    )
