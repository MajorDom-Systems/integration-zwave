from majordom_zwave import ZwaveController


async def test_name_and_key(controller: ZwaveController):
    assert controller.name == "ZWave"
    assert controller.key == "zwave"  # its identity under the runtime: keep it stable
