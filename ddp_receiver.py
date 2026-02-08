"""UDP pixel data receiver supporting both WLED native protocols and DDP.

SignalRGB sends pixel data via WLED's native UDP protocol (DNRGB) when
it discovers a device through the WLED JSON API. It can also send DDP.

WLED UDP Protocols (on the port specified in /json/info udpport):
  - 0x01 WARLS: [idx, R, G, B] pairs (max 255 LEDs)
  - 0x02 DRGB:  sequential RGB from LED 0
  - 0x03 DRGBW: sequential RGBW from LED 0
  - 0x04 DNRGB: start index + sequential RGB (used by SignalRGB)

DDP Protocol (Distributed Display Protocol):
  - 10-byte header with offset, length, push flag
  - Used when SignalRGB is configured for DDP mode

Reference: https://kno.wled.ge/interfaces/udp-realtime/
"""

import asyncio
import logging
import struct
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT = 4048

# WLED native UDP protocol types
WLED_WARLS = 0x01
WLED_DRGB = 0x02
WLED_DRGBW = 0x03
WLED_DNRGB = 0x04

# DDP constants
DDP_HEADER_SIZE = 10
DDP_VER_MASK = 0xC0
DDP_VER1 = 0x40
DDP_PUSH_FLAG = 0x01


class _UDPProtocol(asyncio.DatagramProtocol):
    """asyncio UDP protocol handler."""

    def __init__(self, receiver: "PixelReceiver"):
        self._receiver = receiver

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        pass

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        self._receiver._handle_packet(data, addr)

    def error_received(self, exc: Exception) -> None:
        logger.error("UDP error: %s", exc)


class PixelReceiver:
    """Receives pixel data over UDP from SignalRGB.

    Auto-detects the protocol from byte 0:
    - 0x01-0x04: WLED native UDP (WARLS/DRGB/DRGBW/DNRGB)
    - 0x40+: DDP (version 1, flags byte has bit 6 set)
    """

    def __init__(
        self,
        num_leds: int,
        on_frame: Callable[[bytes, int], None],
        bind_ip: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
    ):
        self._num_leds = num_leds
        self._buffer_size = num_leds * 3
        self._on_frame = on_frame
        self._bind_ip = bind_ip
        self._port = port

        # Pre-allocated frame buffer
        self._frame_buffer = bytearray(self._buffer_size)

        # Stats
        self._packets_received: int = 0
        self._frames_completed: int = 0
        self._last_packet_time: float = 0.0
        self._protocol_name: str = "unknown"

        self._transport: Optional[asyncio.DatagramTransport] = None

    async def start(self) -> None:
        """Bind UDP socket and begin receiving."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self),
            local_addr=(self._bind_ip, self._port),
        )
        self._transport = transport
        logger.info("Pixel receiver listening on UDP %s:%d", self._bind_ip, self._port)

    async def stop(self) -> None:
        """Close UDP socket."""
        if self._transport:
            self._transport.close()
            self._transport = None
        logger.info("Pixel receiver stopped")

    def _handle_packet(self, data: bytes, addr: tuple) -> None:
        """Route packet to the correct protocol handler."""
        if len(data) < 2:
            return

        protocol_byte = data[0]

        # Log first few packets for debugging
        if self._packets_received < 5:
            logger.info(
                "UDP pkt from %s: byte0=0x%02X len=%d first_bytes=%s",
                addr, protocol_byte, len(data), data[:min(20, len(data))].hex(),
            )

        self._packets_received += 1
        self._last_packet_time = time.monotonic()

        if protocol_byte == WLED_DNRGB:
            self._handle_dnrgb(data)
        elif protocol_byte == WLED_DRGB:
            self._handle_drgb(data)
        elif protocol_byte == WLED_WARLS:
            self._handle_warls(data)
        elif (protocol_byte & DDP_VER_MASK) == DDP_VER1:
            self._handle_ddp(data)
        else:
            # Try DNRGB as fallback (SignalRGB's primary protocol)
            if protocol_byte <= 0x05 and len(data) > 4:
                self._handle_dnrgb(data)
            elif self._packets_received <= 5:
                logger.warning("Unknown UDP protocol byte: 0x%02X from %s", protocol_byte, addr)

    def _handle_dnrgb(self, data: bytes) -> None:
        """Handle WLED DNRGB protocol (0x04).

        Format:
          Byte 0:    0x04 (protocol type)
          Byte 1:    Timeout (seconds, 0=default)
          Bytes 2-3: Start LED index (big-endian uint16)
          Bytes 4+:  R, G, B triplets
        """
        if len(data) < 7:  # minimum: header + 1 pixel
            return

        start_index = struct.unpack("!H", data[2:4])[0]
        rgb_data = data[4:]
        num_pixels_in_packet = len(rgb_data) // 3
        byte_offset = start_index * 3

        if self._protocol_name != "DNRGB":
            self._protocol_name = "DNRGB"
            logger.info(
                "Protocol: DNRGB — start_led=%d, pixels_in_pkt=%d, total_configured=%d",
                start_index, num_pixels_in_packet, self._num_leds,
            )

        # Copy into frame buffer with bounds checking
        usable_bytes = num_pixels_in_packet * 3  # only use complete triplets
        if byte_offset < self._buffer_size:
            end = min(byte_offset + usable_bytes, self._buffer_size)
            copy_len = end - byte_offset
            if copy_len > 0:
                self._frame_buffer[byte_offset:end] = rgb_data[:copy_len]

        # Deliver frame after each packet (Magic Home send loop throttles)
        self._frames_completed += 1
        frame_snapshot = bytes(self._frame_buffer)

        if self._frames_completed <= 3 or self._frames_completed % 300 == 0:
            # Sample pixels at different positions to check color diversity
            buf = self._frame_buffer
            samples = []
            for i in range(0, min(self._buffer_size, self._num_leds * 3), max(1, self._num_leds * 3 // 5)):
                if i + 2 < len(buf):
                    samples.append(f"px{i//3}=({buf[i]},{buf[i+1]},{buf[i+2]})")
            logger.info(
                "Frame #%d: DNRGB start=%d pixels=%d  %s",
                self._frames_completed, start_index, num_pixels_in_packet,
                "  ".join(samples),
            )

        self._on_frame(frame_snapshot, self._num_leds)

    def _handle_drgb(self, data: bytes) -> None:
        """Handle WLED DRGB protocol (0x02).

        Format:
          Byte 0:   0x02 (protocol type)
          Byte 1:   Timeout
          Bytes 2+: R, G, B triplets from LED 0
        """
        if len(data) < 5:
            return

        rgb_data = data[2:]
        usable_bytes = (len(rgb_data) // 3) * 3
        end = min(usable_bytes, self._buffer_size)
        if end > 0:
            self._frame_buffer[:end] = rgb_data[:end]

        if self._protocol_name != "DRGB":
            self._protocol_name = "DRGB"
            logger.info("Protocol: DRGB — %d pixels", end // 3)

        self._frames_completed += 1
        self._on_frame(bytes(self._frame_buffer), self._num_leds)

    def _handle_warls(self, data: bytes) -> None:
        """Handle WLED WARLS protocol (0x01).

        Format:
          Byte 0:   0x01 (protocol type)
          Byte 1:   Timeout
          Bytes 2+: [index, R, G, B] groups
        """
        if len(data) < 6:
            return

        if self._protocol_name != "WARLS":
            self._protocol_name = "WARLS"
            logger.info("Protocol: WARLS")

        pos = 2
        while pos + 3 < len(data):
            idx = data[pos]
            r, g, b = data[pos + 1], data[pos + 2], data[pos + 3]
            byte_offset = idx * 3
            if byte_offset + 2 < self._buffer_size:
                self._frame_buffer[byte_offset] = r
                self._frame_buffer[byte_offset + 1] = g
                self._frame_buffer[byte_offset + 2] = b
            pos += 4

        self._frames_completed += 1
        self._on_frame(bytes(self._frame_buffer), self._num_leds)

    def _handle_ddp(self, data: bytes) -> None:
        """Handle DDP protocol (version 1).

        Header (10 bytes):
          Byte 0:    Flags [VV TT D RR P]
          Byte 1:    Sequence
          Byte 2:    Data type
          Byte 3:    Source ID
          Bytes 4-7: Offset (big-endian uint32, byte offset)
          Bytes 8-9: Length (big-endian uint16)
          Bytes 10+: Pixel data
        """
        if len(data) < DDP_HEADER_SIZE:
            return

        flags = data[0]
        offset = struct.unpack("!I", data[4:8])[0]
        payload = data[DDP_HEADER_SIZE:]

        if self._protocol_name != "DDP":
            self._protocol_name = "DDP"
            logger.info("Protocol: DDP")

        if offset < self._buffer_size:
            end = min(offset + len(payload), self._buffer_size)
            copy_len = end - offset
            if copy_len > 0:
                self._frame_buffer[offset:end] = payload[:copy_len]

        if flags & DDP_PUSH_FLAG:
            self._frames_completed += 1
            self._on_frame(bytes(self._frame_buffer), self._num_leds)

    @property
    def is_receiving(self) -> bool:
        """True if packets received in the last 2 seconds."""
        if self._last_packet_time == 0.0:
            return False
        return (time.monotonic() - self._last_packet_time) < 2.0

    @property
    def protocol(self) -> str:
        return self._protocol_name

    @property
    def stats(self) -> dict:
        return {
            "packets_received": self._packets_received,
            "frames_completed": self._frames_completed,
            "is_receiving": self.is_receiving,
            "protocol": self._protocol_name,
        }
