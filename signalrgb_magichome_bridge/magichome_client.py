"""Persistent async TCP client for Magic Home 0xA3 controllers.

Manages connection lifecycle, frame throttling, and auto-reconnect.
Uses a "latest frame wins" strategy — only the most recent pixel data
is ever sent, stale frames are discarded.

All TCP writes are serialized through a single send loop to prevent
concurrent writes from corrupting the stream.
"""

import asyncio
import logging
import socket
import time
from typing import Optional

from .protocol import (
    build_power_off,
    build_power_on,
    build_state_query,
    build_zone_change,
    downsample_to_zones,
    parse_state_response,
    wrap_message,
)

logger = logging.getLogger(__name__)


class MagicHomeClient:
    def __init__(self, host: str, port: int = 5577, max_fps: int = 30):
        self._host = host
        self._port = port
        self._max_fps = max_fps
        self._min_interval = 1.0 / max_fps if max_fps > 0 else 0.033

        # Controller point count (auto-detected from pixels_per_segment)
        self._num_points: int = 0

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._counter: int = 0
        self._connected: bool = False

        # Frame buffer (latest-wins)
        self._frame_pixels: Optional[bytes] = None
        self._frame_num_pixels: int = 0
        self._frame_dirty: bool = False
        self._frame_event = asyncio.Event()

        # Command queue for power/state commands (serialized with frames)
        self._command_queue: asyncio.Queue = asyncio.Queue(maxsize=4)

        # Reconnect backoff
        self._reconnect_delay: float = 1.0
        self._max_reconnect_delay: float = 8.0

        # Post-reconnect cooldown: wait before sending frames
        self._reconnect_time: float = 0.0
        self._reconnect_cooldown: float = 0.5  # seconds

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
        return self._connected

    async def connect(self) -> bool:
        """Establish TCP connection with TCP_NODELAY."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=5.0,
            )
            # Disable Nagle's algorithm for low-latency sends
            sock = self._writer.transport.get_extra_info("socket")
            if sock:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            self._connected = True
            self._reconnect_delay = 1.0
            self._reconnect_time = time.monotonic()
            logger.info("Connected to Magic Home at %s:%d", self._host, self._port)
            return True
        except (OSError, asyncio.TimeoutError) as e:
            logger.warning("Failed to connect to %s:%d: %s", self._host, self._port, e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close the TCP connection."""
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            self._writer = None
            self._reader = None
        logger.info("Disconnected from Magic Home")

    async def start(self) -> None:
        """Connect and start the background send loop."""
        self._running = True
        self._command_queue = asyncio.Queue(maxsize=4)
        await self.connect()
        self._send_task = asyncio.create_task(self._send_loop())
        logger.info("MagicHome client started (max %d FPS)", self._max_fps)

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
        await self.disconnect()

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
        """Background loop: send commands and frames, all serialized."""
        while self._running:
            # Wait for a new frame or timeout at frame interval
            try:
                await asyncio.wait_for(
                    self._frame_event.wait(),
                    timeout=self._min_interval,
                )
            except asyncio.TimeoutError:
                pass

            self._frame_event.clear()

            if not self._running:
                break

            # Ensure connected
            if not self._connected:
                await self._reconnect()
                if not self._connected:
                    continue

            # Process any queued commands FIRST (power on/off)
            commands_sent = 0
            while not self._command_queue.empty() and commands_sent < 2:
                try:
                    cmd_inner = self._command_queue.get_nowait()
                    success = await self._send_wrapped(cmd_inner)
                    if not success:
                        await self._reconnect()
                        break
                    commands_sent += 1
                    # Small delay between command and next send
                    await asyncio.sleep(0.05)
                except asyncio.QueueEmpty:
                    break

            # Skip frame if no dirty data
            if not self._frame_dirty or self._frame_pixels is None:
                continue

            # Skip frame if we just reconnected (give controller time)
            now = time.monotonic()
            if now - self._reconnect_time < self._reconnect_cooldown:
                continue

            # Grab current frame data
            pixels = self._frame_pixels
            num_pixels = self._frame_num_pixels
            self._frame_dirty = False

            # Throttle: ensure minimum interval between sends
            elapsed = now - self.last_send_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

            # Build and send the packet
            if not self._connected:
                continue

            # Downsample to controller points if configured
            if self._num_points > 0 and num_pixels != self._num_points:
                zone_pixels = downsample_to_zones(
                    pixels, num_pixels, self._num_points,
                )
                inner = build_zone_change(zone_pixels, self._num_points)
            else:
                inner = build_zone_change(pixels, num_pixels)
            success = await self._send_wrapped(inner)
            if success:
                self.frames_sent += 1
                self.last_send_time = time.monotonic()
                if self.frames_sent <= 3 or self.frames_sent % 300 == 0:
                    logger.info("MH: frame #%d sent (%d pixels, %d bytes over TCP)",
                                self.frames_sent, num_pixels, len(inner) + 10)
            else:
                self.send_errors += 1
                logger.warning("MH: frame send FAILED (error #%d)", self.send_errors)
                await self._reconnect()

    async def _send_raw(self, data: bytes) -> bool:
        """Send raw bytes over TCP. Returns True on success."""
        if not self._writer or not self._connected:
            return False
        try:
            self._writer.write(data)
            await self._writer.drain()
            return True
        except OSError as e:
            logger.warning("TCP send failed: %s", e)
            self._connected = False
            return False

    async def _send_wrapped(self, inner: bytes) -> bool:
        """Wrap inner message with protocol header, send over TCP."""
        counter = self._next_counter()
        packet = wrap_message(counter, inner)
        return await self._send_raw(packet)

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        if self._connected:
            return
        await self.disconnect()
        logger.info(
            "Reconnecting in %.1fs to %s:%d...",
            self._reconnect_delay, self._host, self._port,
        )
        await asyncio.sleep(self._reconnect_delay)
        success = await self.connect()
        if not success:
            self._reconnect_delay = min(
                self._reconnect_delay * 2,
                self._max_reconnect_delay,
            )

    def _next_counter(self) -> int:
        """Return current counter value and increment (wrapping 0-255)."""
        val = self._counter
        self._counter = (self._counter + 1) & 0xFF
        return val

    async def power_on(self) -> bool:
        """Queue power-on command (sent by the send loop)."""
        logger.info("Queueing power ON")
        try:
            self._command_queue.put_nowait(build_power_on())
            self._frame_event.set()  # wake up send loop
            return True
        except asyncio.QueueFull:
            logger.warning("Command queue full, dropping power ON")
            return False

    async def power_off(self) -> bool:
        """Queue power-off command (sent by the send loop)."""
        logger.info("Queueing power OFF")
        try:
            self._command_queue.put_nowait(build_power_off())
            self._frame_event.set()  # wake up send loop
            return True
        except asyncio.QueueFull:
            logger.warning("Command queue full, dropping power OFF")
            return False

    async def detect_zones(self) -> bool:
        """Auto-detect controller point count using flux_led.

        The controller's pixels_per_segment is the number of addressable
        "points". Each point maps to a segment of physical LEDs.
        For example: 10 points with 300 physical LEDs = 30 LEDs per point.
        """
        try:
            from flux_led.aiodevice import AIOWifiLedBulb
            bulb = AIOWifiLedBulb(self._host)
            await bulb.async_setup(lambda: None)
            self._num_points = bulb.pixels_per_segment
            logger.info(
                "Controller config: %d points (pixels_per_segment), %d segments",
                self._num_points, bulb.segments,
            )
            return True
        except Exception as e:
            logger.warning("Zone detection failed: %s (will send raw pixels)", e)
            return False

    async def query_state(self) -> Optional[dict]:
        """Send state query, read and parse the 14-byte response."""
        if not self._connected:
            return None
        if not await self._send_wrapped(build_state_query()):
            return None
        try:
            data = await asyncio.wait_for(self._reader.read(14), timeout=2.0)
            return parse_state_response(data)
        except (asyncio.TimeoutError, OSError) as e:
            logger.warning("State query failed: %s", e)
            return None
