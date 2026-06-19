# WeatherDisplay

A battery-powered e-ink weather station for the Raspberry Pi. A PiSugar RTC
wakes it every few hours; it reads the battery, fetches the forecast from
[Open-Meteo](https://open-meteo.com), draws an 800×480 dashboard with Pillow,
paints it onto a 6-colour e-ink panel, schedules the next wake-up, and powers
off to sip battery.

![WeatherDisplay screenshot](docs/screenshot.png)

The dashboard shows current conditions in °C and °F, a temperature/precipitation
chart, and a multi-day strip, with a battery gauge that turns red when low. If an
update fails, the last good screen is kept under an error banner.

> [![Made primarily by AI](docs/made-primarily-by-ai.svg)](https://ailabels.org/#made-primarily-by-ai)

## Hardware

Tested on a **Raspberry Pi 1 Model B+** with a **PiSugar 3 Plus**, but any
Raspberry Pi + PiSugar combination should work. The e-ink panel is the one fixed
part.

| Part                                                     | Notes                                                                 |
| -------------------------------------------------------- | --------------------------------------------------------------------- |
| Raspberry Pi                                             | Any model with a 40-pin header.                                       |
| Pimoroni Inky Impression 7.3" (2025, Spectra 6 / PIM773) | 800×480, 6-colour e-ink — **required**.                               |
| PiSugar 3 Plus                                           | Battery + RTC that powers the Pi on/off on a schedule; any PiSugar works. |

### Assembly

1. **Attach the PiSugar** to the back of the Pi and connect the battery, per
   [PiSugar's guide](https://github.com/PiSugar/PiSugar/wiki/PiSugar-3-series).
   Keep its **hardware power switch ON** — the RTC needs it to power the Pi back
   up.
2. **Install the PiSugar power manager** (provides the `pisugar-server` the app
   talks to):
   ```bash
   curl https://cdn.pisugar.com/release/pisugar-power-manager.sh | sudo bash
   ```
3. **Seat the Inky Impression** on the 40-pin header (no soldering). See
   [Pimoroni's guide](https://learn.pimoroni.com/article/getting-started-with-inky-impression).

> The e-ink display connects to the Pi's 40-pin header, and the Pi sits on the
> PiSugar behind it.

## Software install

Clone the repo onto the Pi and run the installer:

```bash
git clone <this-repo> ~/WeatherDisplay
cd ~/WeatherDisplay
./install.sh
```

It's idempotent — re-run it any time. It enables SPI, installs dependencies,
sets up the systemd service, and tells you what to edit when it finishes. See
[`install.sh`](install.sh) for details.

## Usage

The systemd service runs on each boot (the PiSugar provides the "every N
hours"). To run an update by hand:

```bash
.venv/bin/weatherdisplay --config config.toml update
```

While bringing it up, set `auto_shutdown = false` in `config.toml` so it doesn't
power off, and watch the journal:

```bash
journalctl -u weatherdisplay -f
```

Because the device powers off after each update, create a sentinel file to keep
it awake for SSH:

```bash
sudo touch /boot/firmware/weatherdisplay-stayawake   # skip auto-shutdown
sudo rm    /boot/firmware/weatherdisplay-stayawake   # resume normal operation
```

## Dev mode (design without a Raspberry Pi)

On any machine with Python 3.13+:

```bash
pip install -e ".[dev]"
weatherdisplay --config config.toml dev
```

Open <http://localhost:8080>. It shows the rendered panel as a faithful 6-colour
e-ink simulation, with buttons to switch between weather presets or a live fetch,
a battery field, and drag-and-drop `.ttf` font hot-swapping. The page refreshes
on code and asset changes.

![e-ink simulation](docs/screenshot-eink.png)

## Development

```bash
ruff check . && ruff format --check .   # lint + format
pyrefly check                           # type-check
pytest                                  # tests
```

The hardware-only `inky` dependency lives in the `[pi]` extra, so everything
except the final panel push runs and is tested on a normal machine.

## License

ISC — see [LICENSE](LICENSE).
