"""WLED device emulation — HTTP JSON API and mDNS advertisement.

Emulates a WLED device so SignalRGB discovers the bridge and streams
DDP pixel data to it. Serves the WLED JSON API over HTTP and advertises
via mDNS as a _wled._tcp service.
"""

import asyncio
import hashlib
import logging
import socket
import time
from typing import Callable, Optional

from aiohttp import web
from zeroconf import ServiceInfo, Zeroconf

logger = logging.getLogger(__name__)


class WLEDEmulator:
    def __init__(
        self,
        name: str,
        num_leds: int,
        local_ip: str,
        http_port: int = 80,
        bind_ip: str = "0.0.0.0",
        ddp_receiver=None,
        power_callback: Optional[Callable[[bool], asyncio.Future]] = None,
    ):
        self._name = name
        self._num_leds = num_leds
        self._local_ip = local_ip
        self._http_port = http_port
        self._bind_ip = bind_ip
        self._ddp_receiver = ddp_receiver
        self._power_callback = power_callback

        # Emulated state
        self._on: bool = True
        self._brightness: int = 255
        self._start_time: float = time.monotonic()

        # Power command debounce (prevent rapid-fire from duplicate SignalRGB entries)
        self._last_power_time: float = 0.0
        self._power_debounce: float = 2.0  # seconds

        # Generate a stable fake MAC from hostname
        self._mac = self._generate_mac()

        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._zeroconf: Optional[Zeroconf] = None
        self._service_info: Optional[ServiceInfo] = None
        self._http_service_info: Optional[ServiceInfo] = None
        self._mdns_refresh_task: Optional[asyncio.Task] = None

    def _generate_mac(self) -> str:
        """Generate a stable fake MAC address based on machine hostname.

        Returns uppercase hex to match real WLED firmware format.
        """
        hostname = socket.gethostname()
        h = hashlib.md5(hostname.encode()).hexdigest()
        return h[:12].upper()

    # ── HTTP Route Handlers ──────────────────────────────────────────────

    async def handle_json_info(self, request: web.Request) -> web.Response:
        """GET /json/info — device capabilities for SignalRGB discovery."""
        is_live = self._ddp_receiver.is_receiving if self._ddp_receiver else False
        uptime = int(time.monotonic() - self._start_time)

        info = {
            "ver": "0.14.0",
            "vid": 2312080,
            "leds": {
                "count": self._num_leds,
                "fps": 30,
                "rgbw": False,
                "wv": False,
                "cct": False,
                "pwr": 0,
                "maxpwr": 0,
                "maxseg": 1,
                "lc": 1,
                "seglc": [self._num_leds],
            },
            "str": False,
            "name": self._name,
            "udpport": 4048,
            "live": is_live,
            "lm": "DDP" if is_live else "",
            "lip": "",
            "ws": 0,
            "fxcount": 1,
            "palcount": 1,
            "wifi": {
                "bssid": "",
                "rssi": -50,
                "signal": 80,
                "channel": 1,
            },
            "fs": {"u": 0, "t": 0, "pmt": 0},
            "ndc": 0,
            "arch": "esp32",
            "core": "v4.4.7",
            "lwip": 0,
            "freeheap": 200000,
            "uptime": uptime,
            "opt": 0,
            "brand": "WLED",
            "product": "FOSS",
            "mac": self._mac,
            "ip": self._local_ip,
        }
        return web.json_response(info)

    async def handle_json_state(self, request: web.Request) -> web.Response:
        """GET /json/state — current device state."""
        state = self._build_state()
        return web.json_response(state)

    async def handle_json(self, request: web.Request) -> web.Response:
        """GET /json — combined info + state + effects + palettes."""
        is_live = self._ddp_receiver.is_receiving if self._ddp_receiver else False
        uptime = int(time.monotonic() - self._start_time)

        combined = {
            "state": self._build_state(),
            "info": {
                "ver": "0.14.0",
                "vid": 2312080,
                "leds": {
                    "count": self._num_leds,
                    "fps": 30,
                    "rgbw": False,
                    "wv": False,
                    "cct": False,
                    "pwr": 0,
                    "maxpwr": 0,
                    "maxseg": 1,
                    "lc": 1,
                    "seglc": [self._num_leds],
                },
                "str": False,
                "name": self._name,
                "udpport": 4048,
                "live": is_live,
                "lm": "DDP" if is_live else "",
                "lip": "",
                "ws": 0,
                "fxcount": 1,
                "palcount": 1,
                "wifi": {
                    "bssid": "",
                    "rssi": -50,
                    "signal": 80,
                    "channel": 1,
                },
                "fs": {"u": 0, "t": 0, "pmt": 0},
                "ndc": 0,
                "arch": "esp32",
                "core": "v4.4.7",
                "lwip": 0,
                "freeheap": 200000,
                "uptime": uptime,
                "opt": 0,
                "brand": "WLED",
                "product": "FOSS",
                "mac": self._mac,
                "ip": self._local_ip,
            },
            "effects": ["Solid"],
            "palettes": ["Default"],
        }
        return web.json_response(combined)

    async def handle_json_state_post(self, request: web.Request) -> web.Response:
        """POST /json/state — accept state changes (brightness, on/off)."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        if "on" in body:
            new_state = bool(body["on"])
            now = time.monotonic()
            # Only send power command if state changed or debounce expired
            if self._power_callback and (new_state != self._on or now - self._last_power_time > self._power_debounce):
                self._last_power_time = now
                asyncio.create_task(self._power_callback(new_state))
            self._on = new_state

        if "bri" in body:
            self._brightness = max(0, min(255, int(body["bri"])))

        return web.json_response(self._build_state())

    def _build_state(self) -> dict:
        return {
            "on": self._on,
            "bri": self._brightness,
            "transition": 7,
            "ps": -1,
            "pl": -1,
            "nl": {"on": False, "dur": 60, "fade": True, "tbri": 0},
            "udpn": {"send": False, "recv": True},
            "lor": 0,
            "mainseg": 0,
            "seg": [
                {
                    "id": 0,
                    "start": 0,
                    "stop": self._num_leds,
                    "len": self._num_leds,
                    "grp": 1,
                    "spc": 0,
                    "of": 0,
                    "on": True,
                    "frz": False,
                    "bri": 255,
                    "cct": 127,
                    "col": [[255, 160, 0], [0, 0, 0], [0, 0, 0]],
                    "fx": 0,
                    "sx": 128,
                    "ix": 128,
                    "pal": 0,
                    "sel": True,
                    "rev": False,
                    "mi": False,
                }
            ],
        }

    # ── mDNS ─────────────────────────────────────────────────────────────

    async def _register_mdns(self) -> None:
        """Register mDNS services for WLED discovery.

        Real WLED registers two services:
          1. _wled._tcp  — with a TXT record containing the MAC address
          2. _http._tcp  — standard HTTP service

        SignalRGB uses the MAC from the TXT record to recognize a previously
        paired device across restarts.  Without it every restart looks like
        a brand-new device and the pairing is lost.
        """
        ip_bytes = socket.inet_aton(self._local_ip)
        server_name = f"wled-{self._mac[:6]}.local."

        # _wled._tcp with MAC TXT record (matches real WLED firmware)
        self._service_info = ServiceInfo(
            type_="_wled._tcp.local.",
            name=f"{self._name}._wled._tcp.local.",
            addresses=[ip_bytes],
            port=self._http_port,
            server=server_name,
            properties={"mac": self._mac},
        )

        # _http._tcp (real WLED also advertises this)
        self._http_service_info = ServiceInfo(
            type_="_http._tcp.local.",
            name=f"{self._name}._http._tcp.local.",
            addresses=[ip_bytes],
            port=self._http_port,
            server=server_name,
        )

        self._zeroconf = Zeroconf()
        await asyncio.to_thread(self._zeroconf.register_service, self._service_info)
        await asyncio.to_thread(self._zeroconf.register_service, self._http_service_info)
        logger.info("mDNS: registered %s on %s:%d (mac=%s)", self._name, self._local_ip, self._http_port, self._mac)

        # Periodic re-announcement so SignalRGB finds us after restart
        self._mdns_refresh_task = asyncio.create_task(self._mdns_refresh_loop())

    async def _mdns_refresh_loop(self) -> None:
        """Re-announce mDNS services periodically.

        Sends an initial burst of 3 announcements (at 3s intervals) so
        SignalRGB's mDNS browser picks us up quickly on startup, then
        continues every 30 seconds.  Refreshes BOTH _wled._tcp and
        _http._tcp services.
        """
        try:
            # Initial burst: 3 rapid re-announcements to ensure visibility
            for _ in range(3):
                await asyncio.sleep(3)
                await self._refresh_mdns_services()

            # Steady-state: re-announce every 30 seconds
            while True:
                await asyncio.sleep(30)
                await self._refresh_mdns_services()
        except asyncio.CancelledError:
            pass

    async def _refresh_mdns_services(self) -> None:
        """Re-announce both mDNS services."""
        if not self._zeroconf:
            return
        for svc in (self._service_info, self._http_service_info):
            if svc:
                try:
                    await asyncio.to_thread(self._zeroconf.update_service, svc)
                except Exception as e:
                    logger.debug("mDNS refresh failed for %s: %s", svc.name, e)

    async def _unregister_mdns(self) -> None:
        """Unregister mDNS services."""
        if self._mdns_refresh_task:
            self._mdns_refresh_task.cancel()
            try:
                await self._mdns_refresh_task
            except asyncio.CancelledError:
                pass
            self._mdns_refresh_task = None
        if self._zeroconf and self._service_info:
            await asyncio.to_thread(self._zeroconf.unregister_service, self._service_info)
        if self._zeroconf and self._http_service_info:
            await asyncio.to_thread(self._zeroconf.unregister_service, self._http_service_info)
        if self._zeroconf:
            await asyncio.to_thread(self._zeroconf.close)
            self._zeroconf = None
        logger.info("mDNS: unregistered")

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start HTTP server and register mDNS."""
        self._app = web.Application()
        self._app.add_routes(
            [
                web.get("/json/info", self.handle_json_info),
                web.get("/json/info/", self.handle_json_info),
                web.get("/json/state", self.handle_json_state),
                web.get("/json/state/", self.handle_json_state),
                web.get("/json", self.handle_json),
                web.get("/json/", self.handle_json),
                web.post("/json/state", self.handle_json_state_post),
                web.post("/json/state/", self.handle_json_state_post),
                web.post("/json", self.handle_json_state_post),
                web.post("/json/", self.handle_json_state_post),
            ]
        )
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._bind_ip, self._http_port)
        await site.start()
        logger.info("WLED HTTP API on http://%s:%d", self._bind_ip, self._http_port)

        await self._register_mdns()

    async def stop(self) -> None:
        """Stop HTTP server and unregister mDNS."""
        await self._unregister_mdns()
        if self._runner:
            await self._runner.cleanup()
        logger.info("WLED emulator stopped")
