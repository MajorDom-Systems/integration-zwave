import os


def server_url() -> str:
    """The zwave-js-server to connect to, read when the integration starts."""
    return os.getenv("ZWAVE_SERVER_URL", "ws://localhost:3000")
