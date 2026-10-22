import asyncio
import logging

from majordom_integration_sdk import Endpoint
from majordom_integration_sdk.dev import run_controller

from majordom_zwave import ZwaveController

logging.getLogger("majordom_zwave").setLevel(logging.DEBUG)
asyncio.run(run_controller(ZwaveController, links={"zwave": Endpoint("zwave", "zwave-js-ws", "ws://localhost:3000")}))
