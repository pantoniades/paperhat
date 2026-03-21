# PaperHat

Touch e-Paper dashboard for Raspberry Pi Zero W — weather and NYC subway arrivals on a [Waveshare 2.13" Touch e-Paper HAT](https://www.waveshare.com/wiki/2.13inch_Touch_e-Paper_HAT_Manual) (250×122, black/white).

## What it does

Tap-driven home screen with two icons:

- **Weather** — current conditions, paginated hourly forecast, and 5-day outlook with weather icons via the free [NWS API](https://www.weather.gov/documentation/services-web-api)
- **Subway** — 6 nearest stations with live arrival times, tap a station for details, tap anywhere to refresh via [MTA GTFS-RT](https://api.mta.info/)

Navigation is stack-based: back arrow (top-left) returns to the previous screen. Paginated screens show ▲/▼ arrows on the right edge.

## Hardware

- Raspberry Pi Zero W (or any 40-pin Pi)
- [Waveshare 2.13" Touch e-Paper HAT](https://www.waveshare.com/2.13inch-touch-e-paper-hat.htm) — SSD1680 display + GT1158 capacitive touch over I2C

## Install

Clone and run the installer:

```bash
git clone https://github.com/pantoniades/paperhat.git
cd paperhat
./install.sh
```

The installer handles everything:
- Enables SPI/I2C (reboots if needed)
- Installs system packages (`libjpeg-dev`, `zlib1g-dev`, etc.)
- Creates a Python venv and installs dependencies
- Creates `config.toml` from the template (first run only)
- Installs and starts a systemd service

After install, PaperHat starts automatically on boot.

### Managing the service

```bash
sudo systemctl status paperhat     # check status
sudo journalctl -u paperhat -f     # tail logs
sudo systemctl restart paperhat    # restart
sudo systemctl stop paperhat       # stop
```

### Uninstall

```bash
./uninstall.sh
```

Stops the service and removes the systemd unit. Does not delete the project directory or your `config.toml`.

## Configuration

Edit `config.toml` (created by the installer):

```bash
nano config.toml
```

```toml
# Location — weather and nearby stations are based on this
lat = 40.6742
lon = -73.9708

# Hide departures arriving sooner than this (minutes)
min_departure_minutes = 3
```

All fields are optional — defaults (Grand Army Plaza, Brooklyn) are used for anything omitted. See `config.example.toml` for all options. `config.toml` is gitignored so your settings survive `git pull`.

## Manual run (development)

```bash
source .venv/bin/activate
python main.py           # normal mode
python main.py --debug   # verbose touch + API logging
```

## Project structure

```
├── main.py              App + nav stack + entry point
├── config.py            Dataclass defaults + TOML loader
├── config.example.toml  Template config (tracked in git)
├── config.toml          Your local config (gitignored)
├── install.sh           Installer (venv + systemd service)
├── uninstall.sh         Service removal
├── drivers/
│   ├── epd.py           SSD1680 e-Paper driver (context manager)
│   └── touch.py         GT1158 touch driver (context manager)
├── services/
│   ├── weather.py       NWS hourly + daily forecast
│   └── mta.py           Station finder + GTFS-RT arrivals
└── ui.py                Screen ABC + all screens + pagination
```

## License

MIT
