"""Kleinanzeigen Bridge - a small HTTP API around kleinanzeigen-bot.

The add-on image is based on the official kleinanzeigen-bot Docker image
(Chromium + KasmVNC desktop + the compiled bot). This process:

* runs the bot CLI one command at a time (there is only one browser
  profile, so jobs are strictly serialised),
* exposes the current online ads and the job state as JSON for the
  ``kleinanzeigen`` Home Assistant integration,
* re-publishes ads as a safe sequence: download (text + images) -> verify
  the local copy is complete -> publish the copy -> the bot deletes the
  old ad only AFTER the new one is online (``delete_old_ads:
  AFTER_PUBLISH``),
* serves the KasmVNC browser desktop through Home Assistant ingress, so a
  captcha or a login challenge can be solved by hand. When the bot waits
  for such input, the job state becomes ``waiting_for_user`` and
  ``POST /api/continue`` sends the ENTER the bot is waiting for.
"""
from __future__ import annotations

import asyncio
import codecs
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any

from aiohttp import ClientSession, WSMsgType, web
import yaml

OPTIONS_PATH = Path("/data/options.json")
STATE_PATH = Path("/data/state.json")
WORK_DIR = Path("/data/kab")
CONFIG_PATH = WORK_DIR / "config.yaml"
ADS_DIR = WORK_DIR / "downloaded-ads"
ARCHIVE_DIR = WORK_DIR / "archive"
PROFILE_DIR = WORK_DIR / "browser-profile"
BOT_BINARY = "/opt/kleinanzeigen-bot"
VNC_URL = "http://127.0.0.1:6080"
PORT = 8099
VERSION = "0.1.2"

ARCHIVE_KEEP = 5
JOB_TIMEOUT_S = 30 * 60
LOG_TAIL = 300
QUOTA_WINDOW = timedelta(days=30)

# Requests from these addresses only: HA Core (integration) and the
# Supervisor's ingress proxy. Every other add-on on the hassio network
# could otherwise drive the bot or open the logged-in browser desktop.
ALLOWED_PEERS = {"172.30.32.1", "172.30.32.2", "127.0.0.1"}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PROMPT_RE = re.compile(r"(Press a key|Press ENTER|press Enter)", re.IGNORECASE)
LIST_RE = re.compile(
    r"ID:\s*(\d+)\s*\n\s*title:\s*(.*?)\s*\n\s*status:\s*(.*?)\s*\n\s*expires:\s*(.*?)\s*(?:\n|$)"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger("kleinanzeigen_bridge")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_options() -> dict[str, Any]:
    with OPTIONS_PATH.open() as f:
        return json.load(f)


class JobError(Exception):
    """A job step failed; the message is shown to the user."""


class Bridge:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options
        self.min_days = int(options.get("min_days_between_republish", 7))
        self.lock = asyncio.Lock()
        self.process: asyncio.subprocess.Process | None = None
        self.job: dict[str, Any] = {"status": "idle"}
        self.state = self._load_state()

    # ------------------------------------------------------------------ state
    def _load_state(self) -> dict[str, Any]:
        try:
            state = json.loads(STATE_PATH.read_text())
        except (OSError, ValueError):
            state = {}
        state.setdefault("ads", [])
        state.setdefault("ads_updated", None)
        state.setdefault("republished", {})  # title -> {at, old_id, new_id}
        state.setdefault("history", [])  # ISO timestamps of every new publication
        return state

    def _save_state(self) -> None:
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=1, ensure_ascii=False))
        tmp.replace(STATE_PATH)

    def history_30d(self) -> int:
        cutoff = utcnow() - QUOTA_WINDOW
        return sum(1 for ts in self.state["history"] if datetime.fromisoformat(ts) >= cutoff)

    def next_allowed(self, title: str) -> datetime | None:
        entry = self.state["republished"].get(title)
        if not entry:
            return None
        return datetime.fromisoformat(entry["at"]) + timedelta(days=self.min_days)

    def ads_view(self) -> list[dict[str, Any]]:
        out = []
        for ad in self.state["ads"]:
            entry = self.state["republished"].get(ad["title"], {})
            allowed = self.next_allowed(ad["title"])
            out.append(
                {
                    **ad,
                    "url": f"https://www.kleinanzeigen.de/s-anzeige/{ad['id']}",
                    "last_republished": entry.get("at"),
                    "next_allowed": allowed.isoformat() if allowed else None,
                    "republish_allowed": allowed is None or allowed <= utcnow(),
                }
            )
        return out

    def status(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "ready": True,
            "busy": self.lock.locked(),
            "job": self.job,
            "ads": self.ads_view(),
            "ads_updated": self.state["ads_updated"],
            "republished_30d": self.history_30d(),
            "min_days_between_republish": self.min_days,
        }

    # ----------------------------------------------------------- bot config
    def write_bot_config(self) -> None:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        config = {
            "ad_files": ["./downloaded-ads/**/ad_*.yaml"],
            "download": {"dir": "./downloaded-ads"},
            "publishing": {
                "delete_old_ads": "AFTER_PUBLISH",
                # Always delete by ID. Matching by title could hit another
                # ad of the same name.
                "delete_old_ads_by_title": False,
            },
            "login": {
                # Credentials come from the environment, never from this file.
                "username": "${KLEINANZEIGEN_BOT_USERNAME}",
                "password": "${KLEINANZEIGEN_BOT_PASSWORD}",
            },
            "browser": {
                "arguments": ["--no-sandbox", "--disable-dev-shm-usage"],
                # Keep cookies between runs, so the bot does not log in
                # (and risk a captcha) every single time.
                "use_private_window": False,
                "user_data_dir": str(PROFILE_DIR),
            },
            "captcha": {"auto_restart": False},
            "update_check": {"enabled": False},
        }
        CONFIG_PATH.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))

    # ------------------------------------------------------------ run bot
    async def run_bot(self, step: str, *args: str) -> tuple[int, str]:
        """Run one bot command, streaming its output into the job log."""
        cmd = [
            BOT_BINARY,
            "--config", str(CONFIG_PATH),
            "--workspace-mode=portable",
            "--lang=en",
            *args,
        ]
        env = {
            **os.environ,
            "KLEINANZEIGEN_BOT_USERNAME": self.options.get("username", ""),
            "KLEINANZEIGEN_BOT_PASSWORD": self.options.get("password", ""),
            "DISPLAY": ":99",
        }
        self.job["step"] = step
        self._log(f"$ kleinanzeigen-bot {' '.join(args)}")
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=WORK_DIR,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output: list[str] = []
        buf = ""
        # Decode incrementally and strip colour codes only from joined text:
        # a 4096-byte read can split a multi-byte character (ß, ä) or an
        # ANSI sequence, and handling each piece on its own garbles both.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            async with asyncio.timeout(JOB_TIMEOUT_S):
                assert self.process.stdout is not None
                while True:
                    chunk = await self.process.stdout.read(4096)
                    if not chunk:
                        break
                    text = decoder.decode(chunk)
                    output.append(text)
                    buf += text
                    *lines, buf = buf.split("\n")
                    for line in lines:
                        self._log(line)
                    # input() prompts end without a newline - check the rest too.
                    rest = ANSI_RE.sub("", buf)
                    if PROMPT_RE.search(rest) or any(PROMPT_RE.search(ANSI_RE.sub("", line)) for line in lines):
                        self.job["status"] = "waiting_for_user"
                        self.job["message"] = (
                            "Der Bot wartet auf dich (Captcha oder Bestätigung). Im "
                            "Kleinanzeigen-Panel lösen, dann „Weiter“ drücken."
                        )
                        if buf:
                            self._log(buf)
                            buf = ""
                rc = await self.process.wait()
        except TimeoutError:
            self.process.kill()
            await self.process.wait()
            raise JobError(f"{step}: Zeitüberschreitung nach {JOB_TIMEOUT_S // 60} min")
        finally:
            if buf:
                self._log(buf)
            self.process = None
        tail = decoder.decode(b"", final=True)
        if tail:
            output.append(tail)
        return rc, ANSI_RE.sub("", "".join(output))

    def _log(self, line: str) -> None:
        line = ANSI_RE.sub("", line).rstrip()
        if not line:
            return
        _LOGGER.info("bot: %s", line)
        log = self.job.setdefault("log", [])
        log.append(line)
        del log[:-LOG_TAIL]

    async def send_continue(self) -> bool:
        proc = self.process
        if proc is None or proc.stdin is None or self.job.get("status") != "waiting_for_user":
            return False
        proc.stdin.write(b"\n")
        await proc.stdin.drain()
        self.job["status"] = "running"
        self.job["message"] = "Fortgesetzt"
        return True

    async def cancel(self) -> bool:
        if self.process is None:
            return False
        self.process.kill()
        return True

    # ---------------------------------------------------------------- jobs
    async def _job(self, action: str, coro) -> None:
        self.job = {"status": "running", "action": action, "started": utcnow().isoformat(), "log": []}
        try:
            result = await coro
            self.job.update(status="success", message=result)
        except JobError as err:
            self.job.update(status="error", message=str(err))
            _LOGGER.error("%s fehlgeschlagen: %s", action, err)
        except Exception as err:  # noqa: BLE001
            self.job.update(status="error", message=f"Unerwarteter Fehler: {err}")
            _LOGGER.exception("%s: unerwarteter Fehler", action)
        finally:
            self.job["finished"] = utcnow().isoformat()

    def start_job(self, action: str, factory) -> bool:
        if self.lock.locked():
            return False

        async def runner() -> None:
            async with self.lock:
                await self._job(action, factory())

        asyncio.create_task(runner())
        return True

    async def do_refresh(self) -> str:
        rc, out = await self.run_bot("Anzeigen abrufen", "list")
        if rc != 0:
            raise JobError(f"Anzeigenliste konnte nicht geladen werden (Exit {rc})")
        ads = [
            {"id": m[1], "title": m[2].strip(), "status": m[3].strip(), "expires": m[4].strip()}
            for m in LIST_RE.finditer(out)
        ]
        if not ads and "No online ads found" not in out:
            raise JobError("Anzeigenliste nicht lesbar - Ausgabe des Bots hat sich geändert?")
        self.state["ads"] = ads
        self.state["ads_updated"] = utcnow().isoformat()
        self._save_state()
        return f"{len(ads)} Anzeige(n) online"

    def _archive_downloads(self) -> None:
        if ADS_DIR.exists() and any(ADS_DIR.iterdir()):
            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            target = ARCHIVE_DIR / utcnow().strftime("%Y%m%d-%H%M%S")
            shutil.move(str(ADS_DIR), target)
            for old in sorted(ARCHIVE_DIR.iterdir())[:-ARCHIVE_KEEP]:
                shutil.rmtree(old, ignore_errors=True)
        ADS_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _local_ads() -> dict[str, tuple[Path, dict[str, Any]]]:
        found: dict[str, tuple[Path, dict[str, Any]]] = {}
        for path in ADS_DIR.glob("**/ad_*.yaml"):
            try:
                data = yaml.safe_load(path.read_text()) or {}
            except (OSError, yaml.YAMLError):
                continue
            if data.get("id") is not None:
                found[str(data["id"])] = (path, data)
        return found

    def _verify_copy(self, ad_id: str, local: dict[str, tuple[Path, dict[str, Any]]]) -> str:
        """Fail unless the local copy has a title, a description and every image."""
        if ad_id not in local:
            raise JobError(f"Anzeige {ad_id}: keine lokale Kopie heruntergeladen - nichts gelöscht")
        path, data = local[ad_id]
        if not str(data.get("title") or "").strip():
            raise JobError(f"Anzeige {ad_id}: Kopie ohne Titel - nichts gelöscht")
        if not str(data.get("description") or "").strip():
            raise JobError(f"Anzeige {ad_id}: Kopie ohne Beschreibung - nichts gelöscht")
        images = data.get("images") or []
        for image in images:
            file = (path.parent / image) if not os.path.isabs(image) else Path(image)
            if not file.is_file() or file.stat().st_size == 0:
                raise JobError(f"Anzeige {ad_id}: Bild {image} fehlt in der Kopie - nichts gelöscht")
        return f"{data['title']} ({len(images)} Bild(er))"

    async def do_republish(self, ids: list[str]) -> str:
        titles = {ad["id"]: ad["title"] for ad in self.state["ads"]}
        ids = [i for i in ids if i in titles]
        if not ids:
            raise JobError("Keine passende Anzeige online")

        self._archive_downloads()
        rc, _ = await self.run_bot("Kopie herunterladen", "download", f"--ads={','.join(ids)}")
        if rc != 0:
            raise JobError(f"Download fehlgeschlagen (Exit {rc}) - nichts gelöscht")

        local = self._local_ads()
        checked = [self._verify_copy(ad_id, local) for ad_id in ids]
        self._log("Kopie vollständig: " + "; ".join(checked))

        rc, _ = await self.run_bot("Neu einstellen", "publish", f"--ads={','.join(ids)}")

        # The bot rewrites `id` in the local file after a successful
        # publication - that is the reliable signal which ads made it.
        now = utcnow().isoformat()
        after = {str(data.get("title")): str(data.get("id")) for _, data in self._local_ads().values()}
        done, failed = [], []
        for old_id in ids:
            title = titles[old_id]
            new_id = after.get(title)
            if new_id and new_id != old_id:
                self.state["republished"][title] = {"at": now, "old_id": old_id, "new_id": new_id}
                self.state["history"].append(now)
                done.append(title)
            else:
                failed.append(title)
        cutoff = utcnow() - QUOTA_WINDOW
        self.state["history"] = [t for t in self.state["history"] if datetime.fromisoformat(t) >= cutoff]
        self._save_state()

        try:
            await self.do_refresh()
        except JobError as err:
            self._log(f"Liste danach nicht aktualisiert: {err}")

        if failed:
            raise JobError(
                f"Nicht neu eingestellt: {', '.join(failed)} (Exit {rc}). "
                f"Erfolgreich: {', '.join(done) or '-'}. Alte Anzeige bleibt bestehen, "
                "solange die neue nicht online ist."
            )
        return f"Neu eingestellt: {', '.join(done)}"

    def eligible(self, ids: list[str]) -> tuple[list[str], list[str]]:
        ok, blocked = [], []
        for ad in self.state["ads"]:
            if ad["id"] not in ids:
                continue
            allowed = self.next_allowed(ad["title"])
            if allowed and allowed > utcnow():
                blocked.append(f"{ad['title']} (erst ab {allowed.astimezone().strftime('%d.%m. %H:%M')})")
            elif ad["status"] != "active":
                blocked.append(f"{ad['title']} (Status {ad['status']})")
            else:
                ok.append(ad["id"])
        return ok, blocked


# --------------------------------------------------------------------- HTTP
@web.middleware
async def peer_filter(request: web.Request, handler):
    peer = request.remote or ""
    if peer not in ALLOWED_PEERS:
        _LOGGER.warning("Abgewiesen: %s %s von %s", request.method, request.path, peer)
        raise web.HTTPForbidden()
    return await handler(request)


def build_app(bridge: Bridge) -> web.Application:
    app = web.Application(middlewares=[peer_filter], client_max_size=1024**2)
    routes = web.RouteTableDef()

    @routes.get("/health")
    async def health(_: web.Request) -> web.Response:
        return web.json_response({"ready": True, "version": VERSION})

    @routes.get("/api/status")
    async def status(_: web.Request) -> web.Response:
        return web.json_response(bridge.status())

    @routes.post("/api/refresh")
    async def refresh(_: web.Request) -> web.Response:
        if not bridge.start_job("refresh", bridge.do_refresh):
            return web.json_response({"error": "busy"}, status=409)
        return web.json_response({"started": True})

    @routes.post("/api/republish")
    async def republish(request: web.Request) -> web.Response:
        body = await request.json()
        if body.get("all"):
            ids = [ad["id"] for ad in bridge.state["ads"]]
        else:
            ids = [str(i) for i in body.get("ids", [])]
        ok, blocked = bridge.eligible(ids)
        if not ok:
            return web.json_response({"error": "not_allowed", "blocked": blocked}, status=422)
        if not bridge.start_job("republish", lambda: bridge.do_republish(ok)):
            return web.json_response({"error": "busy"}, status=409)
        return web.json_response({"started": True, "ids": ok, "blocked": blocked})

    @routes.post("/api/continue")
    async def cont(_: web.Request) -> web.Response:
        return web.json_response({"sent": await bridge.send_continue()})

    @routes.post("/api/cancel")
    async def cancel(_: web.Request) -> web.Response:
        return web.json_response({"cancelled": await bridge.cancel()})

    # ------------------------------------------------ ingress: VNC desktop
    @routes.get("/")
    async def index(request: web.Request) -> web.Response:
        prefix = request.headers.get("X-Ingress-Path", "").strip("/")
        ws_path = f"{prefix}/vnc/websockify" if prefix else "vnc/websockify"
        job = bridge.job
        html = INDEX_HTML.format(
            status=job.get("status", "idle"),
            message=job.get("message", ""),
            ws_path=ws_path,
        )
        return web.Response(text=html, content_type="text/html")

    @routes.route("*", "/vnc/{tail:.*}")
    async def vnc_proxy(request: web.Request) -> web.StreamResponse:
        tail = request.match_info["tail"]
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await _ws_proxy(request, f"ws://127.0.0.1:6080/{tail}")
        async with ClientSession() as session:
            async with session.request(
                request.method, f"{VNC_URL}/{tail}", params=request.query, data=await request.read()
            ) as resp:
                body = await resp.read()
                headers = {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "cache-control")}
                return web.Response(body=body, status=resp.status, headers=headers)

    app.add_routes(routes)
    return app


async def _ws_proxy(request: web.Request, target: str) -> web.WebSocketResponse:
    protocols = [p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()]
    ws_client = web.WebSocketResponse(protocols=protocols, max_msg_size=0)
    await ws_client.prepare(request)
    async with ClientSession() as session:
        # KasmVNC rejects websockets without an Origin header (404).
        async with session.ws_connect(
            target, protocols=protocols, max_msg_size=0, headers={"Origin": VNC_URL}
        ) as ws_server:

            async def pump(src, dst) -> None:
                async for msg in src:
                    if msg.type == WSMsgType.BINARY:
                        await dst.send_bytes(msg.data)
                    elif msg.type == WSMsgType.TEXT:
                        await dst.send_str(msg.data)
                    else:
                        break

            tasks = [asyncio.create_task(pump(ws_client, ws_server)), asyncio.create_task(pump(ws_server, ws_client))]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                task.cancel()
    return ws_client


INDEX_HTML = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kleinanzeigen</title>
<style>
 body {{ margin: 0; font-family: system-ui, sans-serif; background: #111; color: #eee; }}
 header {{ padding: 8px 16px; font-size: 14px; }}
 iframe {{ border: 0; width: 100%; height: calc(100vh - 40px); background: #000; }}
</style></head>
<body>
<header>Status: <b>{status}</b> {message} - Browser des Bots (nur zum Lösen von Captchas/Login nötig)</header>
<iframe src="vnc/index.html?autoconnect=1&resize=remote&path={ws_path}"></iframe>
</body></html>
"""


async def periodic_refresh(bridge: Bridge) -> None:
    hours = float(bridge.options.get("list_refresh_hours", 12))
    await asyncio.sleep(30)
    while True:
        if hours > 0:
            bridge.start_job("refresh", bridge.do_refresh)
            await asyncio.sleep(hours * 3600)
        else:
            await asyncio.sleep(3600)


async def main() -> None:
    options = load_options()
    bridge = Bridge(options)
    bridge.write_bot_config()
    if not options.get("username") or not options.get("password"):
        _LOGGER.warning("Benutzername/Passwort fehlen in den Add-on-Optionen")
    runner = web.AppRunner(build_app(bridge))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    _LOGGER.info("Kleinanzeigen Bridge %s läuft auf Port %s", VERSION, PORT)
    await periodic_refresh(bridge)


if __name__ == "__main__":
    asyncio.run(main())
