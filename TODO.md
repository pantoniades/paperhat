# TODO

## v1.0
- [ ] Partial refresh — load SSD1680 LUT for partial update, eliminates screen blink on page changes and refreshes (~0.3s vs ~2s). Needs periodic full refresh to clear ghosting.
- [x] Systemd service installer — `./install.sh` and `./uninstall.sh`

## Polish
- [ ] Review fonts and text sizes across all screens for readability on the physical display

## v1.1+
- [ ] Auto-refresh — re-render current screen periodically so stale data updates without a tap
- [ ] WiFi error resilience — show last cached data with "stale" indicator instead of error screen
- [ ] Hardware auto-detection — read GT product ID and adjust touch parsing automatically
