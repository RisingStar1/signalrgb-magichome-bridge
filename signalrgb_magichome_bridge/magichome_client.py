"""Persistent async client for Magic Home addressable LED controllers.

Uses flux_led's AIOWifiLedBulb as the transport layer, adding
application-level throttling, fuzzy dedup, and breathing pauses on top.
The BridgeBulb subclass sets SO_LINGER(0) on every connection (including
auto-reconnects) to prevent ghost TCP connections from crashing the
controller's limited socket pool.
"""

import asyncio
import json
import logging
import socket
import struct
import time
from pathlib import Path
from typing import Optional

from flux_led.aiodevice import AIOWifiLedBulb
from flux_led.base_device import DeviceUnavailableException

from .protocol import (
    bytes_to_rgb_list,
    downsample_to_zones,
    reorder_pixels,
)

logger = logging.getLogger(__name__)

_ZONE_CACHE = Path.home() / ".signalrgb-bridge-zones.json"


class BridgeBulb(AIOWifiLedBulb):
    """AIOWifiLedBulb with SO_LINGER(0) for safe disconnects.

    Overrides _async_connect() to set SO_LINGER(0) + TCP_NODELAY after
    every connection (initial + auto-reconnect), preventing ghost TCP
    connections that crash the controller's limited socket pool.
    """

    def __init__(self, ipaddr: str, port: int = 0, **kwargs):
        super().__init__(ipaddr, port=port, **kwargs)
        self.last_connect_time: float = 0.0

    async def _async_connect(self) -> None:
        """Connect and set SO_LINGER(0) + TCP_NODELAY on the socket."""
        await super()._async_connect()
        self.last_connect_time = time.monotonic()
        if self._aio_protocol and self._aio_protocol.transport:
            sock = self._aio_protocol.transport.get_extra_info("socket")
            if sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # Immediate RST on close — prevents ghost TCP connections
                # from crashing the controller on rapid bridge restarts.
                sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER,
                    struct.pack('ii', 1, 0),
                )


class MagicHomeClient:
    def __init__(self, host: str, port: int = 5577, max_fps: int = 30,
                 color_order: str = "auto"):
        self._host = host
        self._port = port
        self._max_fps = max_fps
        self._min_interval = 1.0 / max_fps if max_fps > 0 else 0.033

        # Proactive throttle: auto-decelerate during sustained animation.
        # First few frames go at max FPS (responsive to color changes),
        # then progressively slower to protect the controller.
        # On dedup (static color): reset to fast mode instantly.
        self._send_interval: float = self._min_interval
        self._consecutive_sends: int = 0         # non-dedup frames in a row
        self._throttle_after: int = 8            # frames before slowing down
        self._throttled_interval: float = 0.5    # 2 FPS during sustained animation

        # Controller point count (auto-detected from pixels_per_segment)
        self._num_points: int = 0
        # Color byte order: "auto" defaults to GRB (most addressable strips use GRB).
        # detect_zones() may refine this based on the IC type.
        self._color_order_cfg: str = color_order
        self._color_order: str = "GRB" if color_order == "auto" else color_order

        # flux_led transport
        self._bulb: Optional[BridgeBulb] = None

        # Frame buffer (latest-wins)
        self._frame_pixels: Optional[bytes] = None
        self._frame_num_pixels: int = 0
        self._frame_dirty: bool = False
        self._frame_event = asyncio.Event()

        # Deduplication: skip sending if frame data hasn't changed enough.
        # Fuzzy threshold prevents sustained streaming during slow animations
        # (e.g. rainbow) where downsampled frames differ by only a few values.
        self._last_sent_pixels: Optional[bytes] = None
        self.frames_skipped_dedup: int = 0
        self._dedup_threshold: int = 50   # per-channel max diff to consider "same"

        # Reconnect backoff
        self._reconnect_delay: float = 1.0
        self._max_reconnect_delay: float = 8.0

        # Post-reconnect cooldown: wait before sending frames
        self._reconnect_cooldown: float = 3.0  # seconds
        self._next_retry_time: float = 0.0

        # Breathing pauses: the ESP8266 TCP stack accumulates state with
        # every frame. Shorter active bursts + longer pauses prevent
        # cumulative stress buildup. At 2 FPS: 15 frames = 7.5s active,
        # then 3s silence = 29% recovery ratio.
        self._breathing_every: int = 15      # frames between breathing pauses
        self._breathing_duration: float = 3.0  # seconds to pause
        self._frames_since_breath: int = 0   # frames since last breathing pause

        self._health_status: str = "unknown"  # healthy/breathing/error

        # Track consecutive dedup hits for stats
        self._consecutive_dedup: int = 0

        # Lifecycle
        self._send_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._first_frame_logged: bool = False

        # Stats
        self.frames_sent: int = 0
        self.send_errors: int = 0
        self.last_send_time: float = 0.0

    @property
    def connected(self) -> bool:
        return self._bulb is not None and bool(self._bulb.available)

    @property
    def health_status(self) -> str:
        return self._health_status

    # IC types whose native LED order is GRB (covers most addressable strips)
    _GRB_IC_NAMES = frozenset({
        "WS2812B", "WS2812", "WS2811", "WS2815", "WS2813",
        "SK6812", "SK6812RGBW", "SK6813",
    })

    def _load_zone_cache(self) -> bool:
        """Load cached zone detection results if they match current host."""
        try:
            if not _ZONE_CACHE.exists():
                return False
            data = json.loads(_ZONE_CACHE.read_text(encoding="utf-8"))
            if data.get("host") != self._host:
                return False
            self._num_points = data.get("num_points", 0)
            if self._color_order_cfg == "auto":
                self._color_order = data.get("color_order", "GRB")
            logger.info(
                "Zone cache: %d points, color_order=%s (delete %s to re-detect)",
                self._num_points, self._color_order, _ZONE_CACHE,
            )
            return True
        except Exception:
            return False

    def _save_zone_cache(self) -> None:
        """Save zone detection results for faster restarts."""
        try:
            data = {
                "host": self._host,
                "num_points": self._num_points,
                "color_order": self._color_order,
            }
            _ZONE_CACHE.write_text(
                json.dumps(data, indent=2), encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save zone cache: %s", e)

    async def _create_bulb(self) -> None:
        """Create BridgeBulb and run async_setup (protocol detection + config)."""
        self._bulb = BridgeBulb(self._host, port=self._port)
        await self._bulb.async_setup(lambda: None)
        logger.info("Connected to Magic Home at %s:%d", self._host, self._port)

    async def detect_zones(self) -> bool:
        """Auto-detect controller point count and color order.

        Uses cached results when available to avoid creating an extra TCP
        connection that can overwhelm the controller on rapid restarts.
        Falls back to live detection via flux_led. On live detection, the
        bulb stays alive as the permanent transport (no close + reopen).
        """
        if self._load_zone_cache():
            return True

        try:
            await self._create_bulb()
            self._num_points = self._bulb.pixels_per_segment or 0

            # Detect color order from IC type (only if set to "auto")
            ic_name = self._bulb.ic_type or ""

            if self._color_order_cfg == "auto":
                if ic_name:
                    # Normalize: "WS2812B" from "WS2812B (GRB)" etc.
                    ic_base = ic_name.split("(")[0].split("/")[0].strip().upper()
                    if ic_base in self._GRB_IC_NAMES:
                        self._color_order = "GRB"
                elif self._num_points > 0:
                    # IC unknown but controller is addressable — almost
                    # certainly GRB (WS2812B is the dominant IC).
                    self._color_order = "GRB"

            logger.info(
                "Controller config: %d points, %d segments, IC=%s, color_order=%s",
                self._num_points, self._bulb.segments or 0,
                ic_name or "unknown", self._color_order,
            )
            self._save_zone_cache()
            return True
        except Exception as e:
            logger.warning("Zone detection failed: %s (will send raw pixels)", e)
            if self._bulb:
                try:
                    await self._bulb.async_stop()
                except Exception:
                    pass
            self._bulb = None
            return False

    async def start(self) -> None:
        """Connect (if needed), probe controller, and start the background send loop."""
        self._running = True

        # If detect_zones() already connected, reuse the bulb.
        # Otherwise create a new one (e.g. cache hit, or detection skipped).
        if self._bulb is None:
            try:
                await self._create_bulb()
            except Exception as e:
                logger.warning(
                    "Initial connection failed: %s — will retry in background", e,
                )

        # Sync num_points from bulb if not already set (e.g. cache was used)
        if self._bulb and self._num_points == 0:
            self._num_points = self._bulb.pixels_per_segment or 0

        self._send_task = asyncio.create_task(self._send_loop())
        logger.info("MagicHome client started (max %d FPS, breathing every %d frames)",
                     self._max_fps, self._breathing_every)

    async def stop(self) -> None:
        """Stop send loop and disconnect."""
        self._running = False
        self._frame_event.set()  # unblock the send loop
        if self._send_task:
            self._send_task.cancel()
            try:
                await self._send_task
            except asyncio.CancelledError:
                pass
            self._send_task = None
        if self._bulb:
            try:
                await self._bulb.async_stop()
            except Exception:
                pass
            self._bulb = None
        logger.info("Disconnected from Magic Home")

    def _pixels_similar(self, a: bytes, b: bytes) -> bool:
        """Check if two pixel buffers are similar enough to skip sending.

        Returns True if no single byte differs by more than _dedup_threshold.
        This filters out gradual animation shifts (rainbow) while still
        responding instantly to deliberate color changes.
        """
        if len(a) != len(b):
            return False
        threshold = self._dedup_threshold
        for i in range(len(a)):
            if abs(a[i] - b[i]) > threshold:
                return False
        return True

    def update_frame(self, pixel_data: bytes, num_pixels: int) -> None:
        """Update frame buffer with new pixel data. Non-blocking, latest-wins."""
        self._frame_pixels = pixel_data
        self._frame_num_pixels = num_pixels
        self._frame_dirty = True
        self._frame_event.set()
        if not self._first_frame_logged:
            self._first_frame_logged = True
            logger.info("First frame received (%d pixels, %d bytes)",
                        num_pixels, len(pixel_data))

    async def _send_loop(self) -> None:
        """Background loop: send frames with throttle, dedup, and breathing pauses.

        The ESP8266 TCP stack accumulates state with every frame sent. After
        ~30 frames it starts to silently freeze. Breathing pauses (keep TCP
        open, just stop sending for 1s) give the lwIP stack time to drain
        buffers and free memory — proven more effective than reactive health
        monitoring which adds TCP load to an already struggling controller.

        Strategy:
        - First few frames: send at max FPS (instant response to changes)
        - After sustained sends: auto-throttle to 2 FPS
        - Every 30 frames: breathing pause (1s, TCP stays open)
        - On dedup (static color): reset to fast mode + reset breath counter
        - On TCP error: back off heavily
        """
        while self._running:
            # Wait for a new frame or timeout at current send interval
            try:
                await asyncio.wait_for(
                    self._frame_event.wait(),
                    timeout=self._send_interval,
                )
            except asyncio.TimeoutError:
                pass

            self._frame_event.clear()

            if not self._running:
                break

            # Ensure bulb exists (create on first run or after fatal error)
            if self._bulb is None:
                try:
                    await self._create_bulb()
                    # Sync num_points from bulb if needed
                    if self._num_points == 0:
                        self._num_points = self._bulb.pixels_per_segment or 0
                except Exception:
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2, self._max_reconnect_delay,
                    )
                    continue

            # If bulb is disconnected, respect backoff before retry.
            # Auto-reconnect happens inside async_set_zones when we send.
            if not self._bulb.available:
                now = time.monotonic()
                if now < self._next_retry_time:
                    continue

            # Skip frame if no dirty data
            if not self._frame_dirty or self._frame_pixels is None:
                continue

            # Skip frame if we just (re)connected (give controller time)
            if self._bulb.last_connect_time > 0:
                now = time.monotonic()
                if now - self._bulb.last_connect_time < self._reconnect_cooldown:
                    continue

            # Grab current frame data
            pixels = self._frame_pixels
            num_pixels = self._frame_num_pixels
            self._frame_dirty = False

            # Throttle: ensure minimum interval between sends (send-END timing)
            now = time.monotonic()
            elapsed = now - self.last_send_time
            if elapsed < self._send_interval:
                await asyncio.sleep(self._send_interval - elapsed)

            if self._bulb is None:
                continue

            # Reorder color bytes if controller expects non-RGB order
            if self._color_order != "RGB":
                pixels = reorder_pixels(pixels, num_pixels, self._color_order)

            # Downsample to controller points if configured
            if self._num_points > 0 and num_pixels != self._num_points:
                final_pixels = downsample_to_zones(
                    pixels, num_pixels, self._num_points,
                )
                final_count = self._num_points
            else:
                final_pixels = pixels
                final_count = num_pixels

            # Fuzzy dedup: skip if pixels haven't changed enough.
            if (
                self._last_sent_pixels is not None
                and self._pixels_similar(final_pixels, self._last_sent_pixels)
            ):
                self.frames_skipped_dedup += 1
                self._consecutive_dedup += 1
                # Do NOT reset throttle or breath counters here. During
                # animations, fuzzy dedup fires between real sends (~16:1
                # ratio). Resetting on every dedup prevents throttle and
                # breathing from ever triggering. These counters must only
                # track actual TCP sends.
                continue

            self._consecutive_dedup = 0

            # Quiet-period detection: if no frame was sent for 2+ seconds,
            # the color was static (all dedup). Reset to fast mode so the
            # first frames of a new animation are responsive.
            if self.last_send_time > 0:
                quiet = time.monotonic() - self.last_send_time
                if quiet > 2.0:
                    self._consecutive_sends = 0
                    self._send_interval = self._min_interval
                    self._frames_since_breath = 0

            # Breathing pause: the ESP8266 lwIP stack accumulates state with
            # every TCP message. After ~30 frames it starts to choke. Pausing
            # for 1s (keeping TCP open!) gives it time to drain buffers.
            # No extra TCP traffic — just silence. This is the #1 stability
            # mechanism, proven more effective than reactive health monitoring.
            if self._frames_since_breath >= self._breathing_every:
                self._frames_since_breath = 0
                self._health_status = "breathing"
                logger.info(
                    "Breathing pause: %d frames sent, pausing %.1fs",
                    self.frames_sent, self._breathing_duration,
                )
                await asyncio.sleep(self._breathing_duration)
                self._health_status = "healthy"

            # Send frame via flux_led
            try:
                rgb_list = bytes_to_rgb_list(final_pixels, final_count)
                await self._bulb.async_set_zones(rgb_list)

                self._last_sent_pixels = final_pixels
                self.frames_sent += 1
                self._frames_since_breath += 1
                self.last_send_time = time.monotonic()
                self._reconnect_delay = 1.0
                self._next_retry_time = 0.0
                self._health_status = "healthy"

                # Proactive throttle: slow down during sustained animation
                self._consecutive_sends += 1
                if self._consecutive_sends >= self._throttle_after:
                    self._send_interval = self._throttled_interval

                if self.frames_sent <= 3 or self.frames_sent % 300 == 0:
                    logger.info(
                        "MH: frame #%d sent (%d pixels, "
                        "interval %.0fms, breath_in=%d, dedup_skipped=%d)",
                        self.frames_sent, final_count,
                        self._send_interval * 1000,
                        self._breathing_every - self._frames_since_breath,
                        self.frames_skipped_dedup,
                    )
            except (DeviceUnavailableException, OSError,
                    asyncio.TimeoutError, ValueError) as e:
                self.send_errors += 1
                self._frames_since_breath = 0
                self._consecutive_sends = 0
                self._health_status = "error"
                # Heavy backoff on error
                self._send_interval = 2.0
                self._next_retry_time = time.monotonic() + self._reconnect_delay
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay,
                )
                logger.warning(
                    "MH: frame send FAILED (error #%d): %s(%s) — backoff to %.0fms",
                    self.send_errors, type(e).__name__, e,
                    self._send_interval * 1000,
                )

    async def power_on(self) -> bool:
        """Turn on the controller."""
        if not self._bulb:
            logger.warning("Cannot power on: not connected")
            return False
        logger.info("Sending power ON")
        try:
            await self._bulb.async_turn_on()
            return True
        except (DeviceUnavailableException, OSError, asyncio.TimeoutError) as e:
            logger.warning("Power on failed: %s", e)
            return False

    async def power_off(self) -> bool:
        """Turn off the controller."""
        if not self._bulb:
            logger.warning("Cannot power off: not connected")
            return False
        logger.info("Sending power OFF")
        try:
            await self._bulb.async_turn_off()
            return True
        except (DeviceUnavailableException, OSError, asyncio.TimeoutError) as e:
            logger.warning("Power off failed: %s", e)
            return False

