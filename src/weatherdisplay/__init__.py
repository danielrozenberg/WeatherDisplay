"""WeatherDisplay: a battery-powered e-ink weather display for the Raspberry Pi.

See the project README for hardware setup. The two entry points are exposed via
the ``weatherdisplay`` console script:

* ``weatherdisplay update`` — the periodic job (fetch, render, show, sleep).
* ``weatherdisplay dev``    — a local design-preview web server (no hardware).
"""

__version__ = "0.1.0"
