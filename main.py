import asyncio
from majordom_integration_sdk.dev import run_controller
from majordom_zwave import ZwaveController
import logging

logging.getLogger("majordom_zwave").setLevel(logging.DEBUG)
asyncio.run(run_controller(ZwaveController))