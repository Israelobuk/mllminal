import pytest

from mllminal.client.app import MLLminalDesktopApp


@pytest.mark.asyncio
async def test_textual_client_mounts_keyboard_pages() -> None:
    app = MLLminalDesktopApp()

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#pages").active == "mil"
        await pilot.press("2")
        assert app.query_one("#pages").active == "status"
        await pilot.press("8")
        assert app.query_one("#pages").active == "policies"
