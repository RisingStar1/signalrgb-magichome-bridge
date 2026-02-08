"""Tests for Magic Home 0xA3 protocol packet construction.

Verified against flux_led library output for byte-exact correctness.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from protocol import (
    checksum,
    wrap_message,
    build_zone_change,
    build_power_on,
    build_power_off,
    build_state_query,
    parse_state_response,
    EFFECT_STATIC,
)


class TestChecksum:
    def test_empty(self):
        assert checksum(b"") == 0

    def test_single_byte(self):
        assert checksum(b"\xFF") == 0xFF

    def test_overflow_wraps(self):
        assert checksum(b"\xFF\x01") == 0x00

    def test_two_bytes(self):
        assert checksum(b"\x10\x20") == 0x30

    def test_known_power_on(self):
        assert checksum(bytes([0x71, 0x23, 0x0F])) == 0xA3

    def test_known_power_off(self):
        assert checksum(bytes([0x71, 0x24, 0x0F])) == 0xA4


class TestWrapMessage:
    def test_magic_header(self):
        wrapped = wrap_message(0, bytes([0x01]))
        assert wrapped[:4] == bytes([0xB0, 0xB1, 0xB2, 0xB3])

    def test_wrapper_version(self):
        wrapped = wrap_message(0, bytes([0x01]))
        assert wrapped[4:6] == bytes([0x00, 0x01])

    def test_protocol_version_byte(self):
        """Byte 6 is the protocol version (0x01), NOT the counter."""
        wrapped = wrap_message(0, bytes([0x01]))
        assert wrapped[6] == 0x01  # protocol version

    def test_counter_byte_position(self):
        """Counter is at byte 7 (after protocol version)."""
        wrapped = wrap_message(42, bytes([0x01]))
        assert wrapped[7] == 42

    def test_counter_wraps(self):
        wrapped = wrap_message(256, bytes([0x01]))
        assert wrapped[7] == 0

    def test_length_includes_inner_checksum(self):
        """Inner length field includes the inner checksum byte."""
        inner = bytes([0x71, 0x23, 0x0F])  # 3 bytes
        wrapped = wrap_message(0, inner)
        length = struct.unpack("!H", wrapped[8:10])[0]
        assert length == 4  # 3 inner bytes + 1 inner checksum

    def test_inner_message_preserved(self):
        inner = bytes([0x71, 0x23, 0x0F])
        wrapped = wrap_message(0, inner)
        assert wrapped[10:13] == inner

    def test_inner_checksum_present(self):
        """Inner message has its own checksum before outer checksum."""
        inner = bytes([0x71, 0x23, 0x0F])
        wrapped = wrap_message(0, inner)
        inner_csum = wrapped[13]  # byte after inner message
        assert inner_csum == checksum(inner)  # 0xA3

    def test_outer_checksum_is_last_byte(self):
        inner = bytes([0x71, 0x23, 0x0F])
        wrapped = wrap_message(0, inner)
        expected = checksum(wrapped[:-1])
        assert wrapped[-1] == expected

    def test_total_length(self):
        inner = bytes(10)
        wrapped = wrap_message(0, inner)
        # 6 (wrapper) + 1 (version) + 1 (counter) + 2 (len) + 10 (inner) + 1 (inner csum) + 1 (outer csum) = 22
        assert len(wrapped) == 22

    def test_matches_flux_led_power_on(self):
        """Exact byte match against flux_led library output."""
        wrapped = wrap_message(0, build_power_on())
        assert wrapped.hex() == "b0b1b2b300010100000471230fa312"

    def test_matches_flux_led_state_query(self):
        """Exact byte match against flux_led library output (counter=0)."""
        wrapped = wrap_message(0, build_state_query())
        assert wrapped.hex() == "b0b1b2b3000101000004818a8b96f8"


class TestBuildZoneChange:
    def test_command_byte(self):
        pixels = bytes([255, 0, 0])
        inner = build_zone_change(pixels, num_pixels=1)
        assert inner[0] == 0x59

    def test_pixel_bits_one_pixel(self):
        pixels = bytes([255, 0, 0])
        inner = build_zone_change(pixels, num_pixels=1)
        pixel_bits = struct.unpack("!H", inner[1:3])[0]
        assert pixel_bits == 9 + 3

    def test_pixel_bits_three_pixels(self):
        pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])
        inner = build_zone_change(pixels, num_pixels=3)
        pixel_bits = struct.unpack("!H", inner[1:3])[0]
        assert pixel_bits == 9 + 9

    def test_pixel_data_preserved(self):
        pixels = bytes([255, 128, 64])
        inner = build_zone_change(pixels, num_pixels=1)
        assert inner[3:6] == pixels

    def test_footer_padding(self):
        pixels = bytes([255, 0, 0])
        inner = build_zone_change(pixels, num_pixels=1)
        data_end = 3 + 3
        assert inner[data_end] == 0x00
        assert inner[data_end + 1] == 0x1E

    def test_static_effect_default(self):
        pixels = bytes([255, 0, 0])
        inner = build_zone_change(pixels, num_pixels=1)
        data_end = 3 + 3 + 2
        assert inner[data_end] == EFFECT_STATIC  # 0x01

    def test_terminal_byte(self):
        pixels = bytes([255, 0, 0])
        inner = build_zone_change(pixels, num_pixels=1)
        assert inner[-1] == 0x00

    def test_total_inner_length(self):
        n = 10
        pixels = bytes(n * 3)
        inner = build_zone_change(pixels, num_pixels=n)
        expected = 1 + 2 + n * 3 + 2 + 1 + 1 + 1
        assert len(inner) == expected

    def test_wrapped_matches_flux_led(self):
        """3-pixel zone change matches flux_led output (counter=0)."""
        inner = build_zone_change(bytes([255, 0, 0, 0, 255, 0, 0, 0, 255]), num_pixels=3)
        wrapped = wrap_message(0, inner)
        # Verified against flux_led ProtocolLEDENETAddressableA3.construct_zone_change
        assert wrapped.hex() == "b0b1b2b3000101000012590012ff000000ff000000ff001e016400ebb0"

    def test_pixel_count_mismatch_raises(self):
        import pytest
        with pytest.raises(ValueError):
            build_zone_change(bytes([255, 0, 0]), num_pixels=2)

    def test_pixel_count_mismatch_too_many(self):
        import pytest
        with pytest.raises(ValueError):
            build_zone_change(bytes([255, 0, 0, 0, 255, 0]), num_pixels=1)

    def test_300_pixel_packet_size(self):
        pixels = bytes(300 * 3)
        inner = build_zone_change(pixels, num_pixels=300)
        wrapped = wrap_message(0, inner)
        assert len(wrapped) == 920


class TestPowerCommands:
    def test_power_on(self):
        assert build_power_on() == bytes([0x71, 0x23, 0x0F])

    def test_power_off(self):
        assert build_power_off() == bytes([0x71, 0x24, 0x0F])

    def test_power_on_checksum(self):
        assert checksum(build_power_on()) == 0xA3

    def test_power_off_checksum(self):
        assert checksum(build_power_off()) == 0xA4


class TestStateQuery:
    def test_query_bytes(self):
        assert build_state_query() == bytes([0x81, 0x8A, 0x8B])

    def test_parse_valid_response(self):
        resp = bytes([
            0x81, 0x04, 0xA3, 0x23, 0x00, 0x61, 0x20,
            0xFF, 0x80, 0x40, 0x00, 0x00, 0x0F, 0x00,
        ])
        result = parse_state_response(resp)
        assert result is not None
        assert result["model"] == 0xA3
        assert result["power_on"] is True
        assert result["red"] == 255
        assert result["green"] == 128
        assert result["blue"] == 64

    def test_parse_power_off(self):
        resp = bytes([0x81, 0x04, 0xA3, 0x24] + [0x00] * 10)
        result = parse_state_response(resp)
        assert result["power_on"] is False

    def test_parse_short_response_returns_none(self):
        assert parse_state_response(bytes([0x81, 0x04])) is None

    def test_parse_empty_returns_none(self):
        assert parse_state_response(b"") is None

    def test_parse_wrong_marker_returns_none(self):
        assert parse_state_response(bytes([0x82] + [0x00] * 13)) is None
