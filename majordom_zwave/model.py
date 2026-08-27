from pydantic import BaseModel
from majordom_integration_sdk.schemas import Device, DeviceState, Parameter, ParameterState


class ZwaveDeviceIntegrationData(BaseModel):
    node_id: int = 0


class ZwaveParameterIntegrationData(BaseModel):
    value_id: str


class ZwaveDevice(Device):
    integration_data: ZwaveDeviceIntegrationData | None = None

    @property
    def node_id(self) -> int:
        assert self.integration_data
        if isinstance(self.integration_data, dict):
            return self.integration_data.get("node_id", -1)
        return self.integration_data.node_id


class ZwaveParameter(Parameter):
    integration_data: ZwaveParameterIntegrationData


class ZwaveParameterState(ParameterState):
    integration_data: ZwaveParameterIntegrationData


class ZwaveDeviceState(ZwaveDevice, DeviceState):
    parameters: list[ZwaveParameterState]