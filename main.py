import asyncio
import logging

from majordom_integration_sdk.dev import run_controller

import majordom_zwave

logging.getLogger("majordom_zwave").setLevel(logging.DEBUG)
# The runtime finds the stick and runs zwave-js-server for it; without Docker, pin a zwave-js-server you run instead:
# from majordom_integration_sdk import Endpoint
# run_controller(majordom_zwave.peripherals, pinned=[Endpoint("zwave", "zwave-js-ws", "ws://localhost:3000")])
asyncio.run(run_controller(majordom_zwave.peripherals))
