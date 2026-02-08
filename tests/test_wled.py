"""Tests for WLED emulator HTTP API responses."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wled_emulator import WLEDEmulator


class TestWLEDAPI(AioHTTPTestCase):
    """Test WLED HTTP API endpoints."""

    async def get_application(self) -> web.Application:
        self.emulator = WLEDEmulator(
            name="TestBridge",
            num_leds=100,
            local_ip="192.168.1.50",
            http_port=0,  # not used in test
            ddp_receiver=None,
        )
        app = web.Application()
        app.add_routes([
            web.get("/json/info", self.emulator.handle_json_info),
            web.get("/json/state", self.emulator.handle_json_state),
            web.get("/json", self.emulator.handle_json),
            web.post("/json/state", self.emulator.handle_json_state_post),
            web.post("/json", self.emulator.handle_json_state_post),
        ])
        return app

    @unittest_run_loop
    async def test_info_led_count(self):
        resp = await self.client.request("GET", "/json/info")
        assert resp.status == 200
        data = await resp.json()
        assert data["leds"]["count"] == 100

    @unittest_run_loop
    async def test_info_device_name(self):
        resp = await self.client.request("GET", "/json/info")
        data = await resp.json()
        assert data["name"] == "TestBridge"

    @unittest_run_loop
    async def test_info_version(self):
        resp = await self.client.request("GET", "/json/info")
        data = await resp.json()
        assert data["ver"] == "0.14.0"

    @unittest_run_loop
    async def test_info_udp_port(self):
        resp = await self.client.request("GET", "/json/info")
        data = await resp.json()
        assert data["udpport"] == 4048

    @unittest_run_loop
    async def test_info_mac_is_string(self):
        resp = await self.client.request("GET", "/json/info")
        data = await resp.json()
        assert isinstance(data["mac"], str)
        assert len(data["mac"]) == 12

    @unittest_run_loop
    async def test_info_brand(self):
        resp = await self.client.request("GET", "/json/info")
        data = await resp.json()
        assert data["brand"] == "WLED"

    @unittest_run_loop
    async def test_info_ip(self):
        resp = await self.client.request("GET", "/json/info")
        data = await resp.json()
        assert data["ip"] == "192.168.1.50"

    @unittest_run_loop
    async def test_info_live_false_no_ddp(self):
        resp = await self.client.request("GET", "/json/info")
        data = await resp.json()
        assert data["live"] is False

    @unittest_run_loop
    async def test_state_default_on(self):
        resp = await self.client.request("GET", "/json/state")
        assert resp.status == 200
        data = await resp.json()
        assert data["on"] is True

    @unittest_run_loop
    async def test_state_default_brightness(self):
        resp = await self.client.request("GET", "/json/state")
        data = await resp.json()
        assert data["bri"] == 255

    @unittest_run_loop
    async def test_state_segment_led_count(self):
        resp = await self.client.request("GET", "/json/state")
        data = await resp.json()
        assert len(data["seg"]) == 1
        assert data["seg"][0]["len"] == 100
        assert data["seg"][0]["stop"] == 100

    @unittest_run_loop
    async def test_state_udpn_recv_true(self):
        resp = await self.client.request("GET", "/json/state")
        data = await resp.json()
        assert data["udpn"]["recv"] is True

    @unittest_run_loop
    async def test_json_combined(self):
        resp = await self.client.request("GET", "/json")
        assert resp.status == 200
        data = await resp.json()
        assert "state" in data
        assert "info" in data
        assert "effects" in data
        assert "palettes" in data
        assert data["info"]["leds"]["count"] == 100
        assert data["state"]["on"] is True

    @unittest_run_loop
    async def test_post_state_brightness(self):
        resp = await self.client.request(
            "POST", "/json/state", json={"bri": 128}
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["bri"] == 128

    @unittest_run_loop
    async def test_post_state_power_off(self):
        resp = await self.client.request(
            "POST", "/json/state", json={"on": False}
        )
        data = await resp.json()
        assert data["on"] is False

    @unittest_run_loop
    async def test_post_state_power_on(self):
        # Turn off first
        await self.client.request("POST", "/json/state", json={"on": False})
        # Turn on
        resp = await self.client.request(
            "POST", "/json/state", json={"on": True}
        )
        data = await resp.json()
        assert data["on"] is True

    @unittest_run_loop
    async def test_post_state_brightness_clamp_max(self):
        resp = await self.client.request(
            "POST", "/json/state", json={"bri": 500}
        )
        data = await resp.json()
        assert data["bri"] == 255

    @unittest_run_loop
    async def test_post_state_brightness_clamp_min(self):
        resp = await self.client.request(
            "POST", "/json/state", json={"bri": -10}
        )
        data = await resp.json()
        assert data["bri"] == 0

    @unittest_run_loop
    async def test_post_state_persists(self):
        await self.client.request("POST", "/json/state", json={"bri": 50})
        resp = await self.client.request("GET", "/json/state")
        data = await resp.json()
        assert data["bri"] == 50

    @unittest_run_loop
    async def test_post_invalid_json(self):
        resp = await self.client.request(
            "POST", "/json/state",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
