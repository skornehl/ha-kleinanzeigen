# Multi-arch manifest (amd64 + arm64): buildx picks the matching image.
FROM ghcr.io/second-hand-friends/kleinanzeigen-bot:latest

# The base image is the official kleinanzeigen-bot image: Debian trixie with
# Chromium, KasmVNC, openbox and the compiled bot at /opt/kleinanzeigen-bot.
# The bridge only needs Python with aiohttp and PyYAML from Debian, and tini
# to reap Chromium's child processes (add-on runs with init: false).
USER root
RUN apt-get update \
 && apt-get install --no-install-recommends -y python3 python3-aiohttp python3-yaml tini \
 && rm -rf /var/lib/apt/lists/*

COPY app/ /opt/bridge/

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash", "/opt/bridge/start.sh"]
