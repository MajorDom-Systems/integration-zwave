"""zwave-js-server: the service that owns the Z-Wave stick; this integration drives it over WebSocket."""

import secrets

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


ZWAVE_JS = Service(
    "zwave-js",
    needs=[Need("zwave", ["serial"])],
    provides=[Endpoint("zwave", "ws", "ws://127.0.0.1:3000")],
    settings=ZwaveNetwork,
    compose={
        # :latest pinned by digest (2026-10-08); bump on purpose
        "image": "ghcr.io/kpine/zwave-js-server@sha256:19592f8e979525ac6f4e6cac22b28324edfaa757c9d2da3d6fec9c4b2ddd18a8",  # noqa: E501
        "network_mode": "host",
        "userns_mode": "host",  # a remapped user can't open the stick on hosts with userns-remap
        "devices": ["{links.zwave.url}:/dev/zwave"],
        "volumes": ["{data}:/cache"],
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
