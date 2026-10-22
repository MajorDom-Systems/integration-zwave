"""zwave-js-server's port is the runtime's to choose: the compose and the endpoint follow it."""

from types import SimpleNamespace

from majordom_zwave.config import ZWAVE_JS_SERVER

PORTS = SimpleNamespace(api=45813)


def test_prefers_its_usual_port():
    assert ZWAVE_JS_SERVER.ports == {"api": 3000}


def test_listens_on_the_allocated_port():
    command = [part.format(ports=PORTS) for part in ZWAVE_JS_SERVER.compose["command"]]
    assert command[command.index("--port") + 1] == "45813"


def test_provides_its_url_on_the_allocated_port():
    assert ZWAVE_JS_SERVER.provides[0].url.format(ports=PORTS) == "ws://127.0.0.1:45813"
