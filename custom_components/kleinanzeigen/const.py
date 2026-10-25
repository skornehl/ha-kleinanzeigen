"""Constants for the Kleinanzeigen integration."""
from __future__ import annotations

DOMAIN = "kleinanzeigen"

CONF_BRIDGE_URL = "bridge_url"
# Supervisor names add-ons from a custom repository "<sha1(repo url)[:8]>_<slug>";
# the hostname uses dashes. For https://github.com/skornehl/ha-kleinanzeigen
# that is c42de2d9.
DEFAULT_BRIDGE_URL = "http://c42de2d9-kleinanzeigen-bridge:8099"

# Polling the bridge is cheap (it only returns cached state); the bridge
# itself talks to kleinanzeigen.de only when a job runs.
SCAN_INTERVAL_SECONDS = 30
