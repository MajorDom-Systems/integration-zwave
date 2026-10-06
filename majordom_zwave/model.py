from majordom_integration_sdk.schemas import Device, Parameter
from pydantic import BaseModel, Field, field_validator


class ZwaveDeviceIntegrationData(BaseModel):
    home_id: int
    node_id: int
    # manufacturer:product type:product id: tells a node id reused by another device from the paired one
    fingerprint: str | None = None


class ZwaveParameterIntegrationData(BaseModel):
    value_id: str  # the value commands go to (and the parameter's identity)
    state_value_id: str | None = None  # the value the state is read from, when it is another one (current vs target)


class ZwaveDevice(Device):
    integration_data: ZwaveDeviceIntegrationData | None = None  # None until paired: the Hub creates the device first
    parameters: list["ZwaveParameter"] = Field(default_factory=list)

    @field_validator("integration_data", mode="before")
    @classmethod
    def _empty_is_unpaired(cls, value: object) -> object:
        return value or None  # the device the Hub creates before pairing carries `{}`


class ZwaveParameter(Parameter):
    integration_data: ZwaveParameterIntegrationData
