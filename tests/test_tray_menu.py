"""The tray menu must only hand pystray callbacks it accepts (0, 1 or 2 parameters)."""

import pystray

from pm_infra.tray import TrayApp


def test_bound_callback_is_accepted_by_pystray_and_passes_the_space():
    seen = []
    item = pystray.MenuItem("Space A", TrayApp._bound(seen.append, "space-a"))
    item(None)  # pystray calls the action with the icon (and the item)
    assert seen == ["space-a"]
