from majordom_integration_sdk.schemas import Device, Parameter
from pydantic import BaseModel, Field


class ZwaveDeviceIntegrationData(BaseModel):
    home_id: int
    node_id: int
    # manufacturer:product type:product id: tells a node id reused by another device from the paired one
    fingerprint: str | None = None
    dsk: str | None = None  # an S2 device's key: its SmartStart entry outlives the node when it leaves by itself


class ZwaveParameterIntegrationData(BaseModel):
    value_id: str  # the value commands go to (and the parameter's identity)
    state_value_id: str | None = None  # the value the state is read from, when it is another one (current vs target)


class ZwaveDevice(Device[ZwaveDeviceIntegrationData | None]):  # None until paired: the Hub creates the device first
    parameters: list["ZwaveParameter"] = Field(default_factory=list)


class ZwaveParameter(Parameter[ZwaveParameterIntegrationData]):
    integration_data: ZwaveParameterIntegrationData
