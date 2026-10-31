"""Our device files, mounted as zwave-js's priority dir: what zwave-js reads from them."""

import json
import subprocess
from pathlib import Path

import pytest

import majordom_zwave

CONFIGS = Path(majordom_zwave.__file__).parent / "device_configs"
SHELLY_WAVE_1 = (0x0460, 0x0002, 0x0083)


def parameter(device: tuple[int, int, int], firmware: str, number: int) -> dict:
    args = ["node", "device_config.mjs", str(CONFIGS), *map(str, device), firmware, str(number)]
    done = subprocess.run(args, cwd=Path(__file__).parent / "mock", capture_output=True, text=True, check=True)
    return json.loads(done.stdout.splitlines()[-1])


@pytest.mark.parametrize(
    ("firmware", "size", "reset"),
    [
        ("10.13", 4, 0x55555555),
        ("10.14", 1, 1),
        ("11.5", 1, 1),
        ("11.6", 4, 0x55555555),
        ("12.1", 4, 0x55555555),
        ("12.2", 1, 1),
        ("13.1", 1, 1),
    ],
)
def test_the_shelly_wave_1_factory_reset_follows_its_firmware(firmware: str, size: int, reset: int):
    factory_reset = parameter(SHELLY_WAVE_1, firmware, 120)

    assert str(CONFIGS) in factory_reset["file"]
    assert (factory_reset["valueSize"], max(factory_reset["options"])) == (size, reset)
