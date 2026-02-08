"""Magic Home 0xA3 (Addressable v3) protocol packet construction.

Pure functions — no I/O, no state. Counter management is the caller's
responsibility. Packet format verified against flux_led library:
https://github.com/lightinglibs/flux_led

Key insight: every message has TWO checksums:
  1. Inner checksum on the inner message
  2. Outer checksum on the entire wrapped packet
"""

import struct
from typing import Optional

# Outer wrapper (6 bytes) — matches flux_led OUTER_MESSAGE_WRAPPER
OUTER_WRAPPER = bytes([0xB0, 0xB1, 0xB2, 0xB3, 0x00, 0x01])
PROTOCOL_VERSION = 0x01

# Inner command bytes
CMD_ZONE_CHANGE = 0x59
CMD_STATE_CHANGE = 0x71
CMD_STATE_QUERY = 0x81

# Power control
POWER_ON_BYTE = 0x23
POWER_OFF_BYTE = 0x24
STATE_CHANGE_SUFFIX = 0x0F

# Effects (values from flux_led MultiColorEffects enum)
EFFECT_STATIC = 0x01


def checksum(data: bytes | bytearray) -> int:
    """Sum all bytes, return lowest 8 bits."""
    return sum(data) & 0xFF


def _add_checksum(data: bytes | bytearray) -> bytes:
    """Append checksum byte to data."""
    raw = bytearray(data)
    raw.append(checksum(raw))
    return bytes(raw)


def wrap_message(counter: int, inner: bytes) -> bytes:
    """Wrap an inner message in the 0xA3 outer protocol frame.

    The inner message gets its own checksum first, then the outer
    wrapper adds another checksum. This matches flux_led's
    construct_wrapped_message() exactly.

    Layout:
      [0xB0 0xB1 0xB2 0xB3 0x00 0x01]  outer wrapper    (6 bytes)
      [0x01]                             protocol version (1 byte)
      [counter]                          msg counter      (1 byte, 0-255)
      [len_hi, len_lo]                   inner msg length (2 bytes, incl inner checksum)
      [inner... + inner_checksum]        inner message    (N+1 bytes)
      [outer_checksum]                   outer checksum   (1 byte)
    """
    # Add inner checksum
    inner_with_csum = _add_checksum(inner)
    inner_len = len(inner_with_csum)

    # Build outer packet (without outer checksum)
    outer = bytearray(OUTER_WRAPPER)
    outer.append(PROTOCOL_VERSION)
    outer.append(counter & 0xFF)
    outer.extend(struct.pack("!H", inner_len))
    outer.extend(inner_with_csum)

    # Add outer checksum
    return bytes(_add_checksum(outer))


def build_zone_change(
    pixels: bytes,
    num_pixels: int,
    effect: int = EFFECT_STATIC,
    speed: int = 100,
) -> bytes:
    """Build the inner zone-change message (0x59 command).

    NOTE: Returns the inner message WITHOUT checksum — wrap_message()
    adds the inner checksum.

    Layout:
      [0x59]              command               (1 byte)
      [pb_hi, pb_lo]      pixel_bits            (2 bytes, big-endian)
      [R,G,B x N]         per-pixel RGB data    (num_pixels * 3 bytes)
      [0x00, 0x1E]        padding               (2 bytes)
      [effect]            effect enum            (1 byte)
      [speed]             speed 0-255           (1 byte)
      [0x00]              terminal              (1 byte)

    pixel_bits = 9 + (num_pixels * 3)
    """
    expected_len = num_pixels * 3
    if len(pixels) != expected_len:
        raise ValueError(
            f"Pixel data length {len(pixels)} does not match "
            f"num_pixels={num_pixels} (expected {expected_len} bytes)"
        )

    pixel_bits = 9 + expected_len
    return (
        bytes([CMD_ZONE_CHANGE])
        + struct.pack("!H", pixel_bits)
        + pixels
        + bytes([0x00, 0x1E])
        + bytes([effect & 0xFF, speed & 0xFF, 0x00])
    )


def downsample_to_zones(
    pixels: bytes,
    num_input_pixels: int,
    num_points: int,
) -> bytes:
    """Downsample a full-resolution pixel buffer to controller points.

    The Magic Home 0xA3 controller has a fixed number of "points"
    (pixels_per_segment from its config). Each point maps to a segment
    of physical LEDs on the strip. This function samples the center
    pixel of each zone for the truest color match to the SignalRGB preview.

    For example: 300 input pixels -> 10 points means we sample pixel 15,
    45, 75, ... (center of each 30-pixel zone).

    Args:
        pixels: Full-resolution RGB pixel data (num_input_pixels * 3 bytes)
        num_input_pixels: Number of input pixels (e.g. 300 from SignalRGB)
        num_points: Number of points on the controller (pixels_per_segment)

    Returns:
        RGB bytes for num_points pixels, ready for build_zone_change().
    """
    input_per_point = num_input_pixels // num_points
    result = bytearray(num_points * 3)

    for p in range(num_points):
        # Sample the center pixel of this zone
        center = p * input_per_point + input_per_point // 2
        src = min(center, num_input_pixels - 1) * 3

        dst = p * 3
        result[dst] = pixels[src]
        result[dst + 1] = pixels[src + 1]
        result[dst + 2] = pixels[src + 2]

    return bytes(result)


def build_power_on() -> bytes:
    """Inner message to power on the controller (without checksum)."""
    return bytes([CMD_STATE_CHANGE, POWER_ON_BYTE, STATE_CHANGE_SUFFIX])


def build_power_off() -> bytes:
    """Inner message to power off the controller (without checksum)."""
    return bytes([CMD_STATE_CHANGE, POWER_OFF_BYTE, STATE_CHANGE_SUFFIX])


def build_state_query() -> bytes:
    """Inner message to query controller state (without checksum)."""
    return bytes([0x81, 0x8A, 0x8B])


def parse_state_response(data: bytes) -> Optional[dict]:
    """Parse the 14-byte state query response.

    Returns dict with device state, or None if data is invalid/too short.
    """
    if len(data) < 14:
        return None
    if data[0] != 0x81:
        return None

    return {
        "raw": data[:14].hex(),
        "device_type": data[1],
        "model": data[2],
        "power_on": data[3] == POWER_ON_BYTE,
        "preset": data[4],
        "mode": data[5],
        "speed": data[6],
        "red": data[7],
        "green": data[8],
        "blue": data[9],
        "warm_white": data[10],
        "version_or_cw": data[11],
        "color_mode": data[12],
    }
