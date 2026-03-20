# PaperHat

Touch e-Paper dashboard for Raspberry Pi Zero W — weather and NYC subway arrivals on a [Waveshare 2.13" Touch e-Paper HAT](https://www.waveshare.com/wiki/2.13inch_Touch_e-Paper_HAT_Manual) (250×122, black/white).

## What it does

Tap-driven home screen with two icons:

- **Weather** — current conditions and hourly forecast via the free [NWS API](https://www.weather.gov/documentation/services-web-api)
- **Subway** — 3 nearest stations (by lat/lon), tap a station to see real-time arrivals grouped by direction via [MTA GTFS-RT](https://api.mta.info/)

Navigation is stack-based: back arrow returns to the previous screen.

## Hardware

- Raspberry Pi Zero W (or any 40-pin Pi)
- [Waveshare 2.13" Touch e-Paper HAT](https://www.waveshare.com/2.13inch-touch-e-paper-hat.htm) — SSD1680 display + GT1151 capacitive touch over I2C

## Setup

Enable SPI and I2C:

```bash
sudo raspi-config   # Interface Options → SPI → Yes, I2C → Yes
```

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Edit `config.py` to set your location (defaults to Grand Army Plaza, Brooklyn):

```python
@dataclass(frozen=True, slots=True)
class AppConfig:
    lat: float = 40.6742
    lon: float = -73.9708
```

Weather and subway station discovery both key off this single `(lat, lon)`.

## Run

```bash
python main.py
```

## Project structure

```
├── main.py              App + nav stack + entry point
├── config.py            Frozen dataclass configs
├── drivers/
│   ├── epd.py           SSD1680 e-Paper driver (context manager)
│   └── touch.py         GT1151 touch driver (context manager)
├── services/
│   ├── weather.py       NWS hourly forecast
│   └── mta.py           Station finder + GTFS-RT arrivals
└── ui.py                Screen ABC + Home/Weather/Subway/Station screens
```

## License

MIT
