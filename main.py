import asyncio
import logging

from majordom_integration_sdk.dev import run_controller

from majordom_zwave import ZwaveController

logging.getLogger("majordom_zwave").setLevel(logging.DEBUG)
# The runtime finds the stick and runs zwave-js-server for it; without Docker, pin a zwave-js-server you run instead:
# run_controller(ZwaveController, docker=False, pinned={"zwave": Endpoint("zwave", "zwave-js-ws", "ws://localhost:3000")})
asyncio.run(run_controller(ZwaveController))
