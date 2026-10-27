# Kleinanzeigen Bridge

> **Moved:** this add-on is now published from
> [skornehl/ha-addons](https://github.com/skornehl/ha-addons). This copy
> gets no further updates - see the repository README for switching.


Backend for the `kleinanzeigen` integration (see the repository README).

## Options

| Option | Meaning |
| --- | --- |
| `username` | kleinanzeigen.de login (e-mail) |
| `password` | kleinanzeigen.de password - passed to the bot as an environment variable, never written to disk |
| `min_days_between_republish` | Minimum days between two re-publications of the same ad (0 = no limit) |
| `list_refresh_hours` | How often to re-read the online ad list (0 = only on demand). Each refresh starts the browser and logs in if needed. |

## Sidebar panel

Shows the bot's browser (KasmVNC). Only needed when the bot waits for you
(captcha, login confirmation). The desktop is reachable only through HA
ingress; the API only from HA Core and the ingress proxy.

## Data

`/data/kab/` holds the bot config (no password), the browser profile (login
cookies), the current local copies (`downloaded-ads/`) and the last five
copies (`archive/`). `/data/state.json` holds the online list, the last
re-publication per ad title and the 30-day history.
