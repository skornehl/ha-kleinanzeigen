# Kleinanzeigen for Home Assistant

Re-publish your own [kleinanzeigen.de](https://www.kleinanzeigen.de) ads as
1:1 copies (text **and** images) with one button press, so they show up at
the top of the search results again.

Two parts:

| Part | What it does |
| --- | --- |
| Kleinanzeigen Bridge (add-on, published from [skornehl/ha-addons](https://github.com/skornehl/ha-addons)) | Runs [kleinanzeigen-bot](https://github.com/Second-Hand-Friends/kleinanzeigen-bot) in a real Chromium, holds the login session, exposes a small local HTTP API. The bot's browser desktop is available in the HA sidebar for solving captchas. |
| `custom_components/kleinanzeigen/` (HACS integration) | One sensor + one "neu einstellen" button per ad, "Alle neu einstellen", job status, 30-day publication count. |

## How a re-publication works

1. `download` the ad (text, price, category, shipping, images) to a local copy.
2. Verify the copy: title and description present, every image file exists and is not empty. If not, **stop - nothing is deleted.**
3. `publish` the copy. The bot deletes the old ad only **after** the new one is online (`delete_old_ads: AFTER_PUBLISH`, by ID, never by title).
4. Refresh the list. The previous five local copies are kept in `/data/kab/archive/`.

A minimum interval per ad (default 7 days, add-on option) protects against
accidental double presses and the free quota.

## ⚠️ Read this first

- Automated access and frequent re-publishing may violate the kleinanzeigen.de
  terms of use and can get an account restricted. Use at your own risk -
  this project only triggers on a manual button press for that reason.
- Every re-publication counts as a **new ad** against the quota
  (private users: 50 free ads per 30 days).
- When kleinanzeigen.de changes its pages, the bot needs an upstream update:
  rebuild the add-on to pull the newest `kleinanzeigen-bot` image.

## Installation

1. Settings → Add-ons → Add-on Store → ⋮ → Repositories → add
   `https://github.com/skornehl/ha-addons`.
2. Install **Kleinanzeigen Bridge**, set `username` (e-mail) and `password`, start it.
3. HACS → Custom repositories → `https://github.com/skornehl/ha-kleinanzeigen`
   (type *Integration*) → install **Kleinanzeigen**, restart HA.
4. Settings → Devices & services → Add integration → *Kleinanzeigen*. The default
   bridge URL (`http://6dc2c37d-kleinanzeigen-bridge:8099`) matches the add-on
   installed from `skornehl/ha-addons`; **Reconfigure** on the entry changes it.

### Moving from the old add-on

Up to 0.1.2 the bridge was published from this repository. It now lives in
[skornehl/ha-addons](https://github.com/skornehl/ha-addons); the copy in
`kleinanzeigen_bridge/` here gets no further updates. To switch: add the new
add-on repository, install the bridge from there and enter the same
credentials, stop the old bridge, then open the integration and choose
**Reconfigure** - the default URL is the new bridge. Entities and history
stay. Finally uninstall the old add-on.

If the job sensor shows *Wartet auf dich*, open **Kleinanzeigen** in the
sidebar, solve the captcha in the browser shown there and press
*Weiter (Captcha gelöst)*.

## License

MIT for this repository. kleinanzeigen-bot itself (used as the add-on's
base image, not included here) is AGPL-3.0.
