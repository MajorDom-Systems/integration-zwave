from majordom_zwave import ZwaveController


async def test_starts_and_stops(controller: ZwaveController) -> None:
    await controller.start()
    await controller.stop() 


async def test_name_and_slug(controller: ZwaveController) -> None:
    assert controller.name == "ZWave"
    assert controller.name_slug == "zwave"
