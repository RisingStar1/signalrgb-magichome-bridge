"""Tests for pixel processing utilities.

Protocol-level packet construction is now handled by flux_led.
These tests cover the remaining pixel processing functions.
"""

from signalrgb_magichome_bridge.protocol import (
    apply_gamma,
    bytes_to_rgb_list,
    downsample_to_zones,
    reorder_pixels,
    GAMMA_LUT,
)


class TestReorderPixels:
    def test_rgb_passthrough(self):
        pixels = bytes([255, 128, 64, 10, 20, 30])
        assert reorder_pixels(pixels, 2, "RGB") == pixels

    def test_grb_reorder(self):
        # RGB (255, 128, 64) -> GRB (128, 255, 64)
        pixels = bytes([255, 128, 64])
        result = reorder_pixels(pixels, 1, "GRB")
        assert result == bytes([128, 255, 64])

    def test_brg_reorder(self):
        # RGB (255, 128, 64) -> BRG (64, 255, 128)
        pixels = bytes([255, 128, 64])
        result = reorder_pixels(pixels, 1, "BRG")
        assert result == bytes([64, 255, 128])

    def test_multiple_pixels(self):
        pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])
        result = reorder_pixels(pixels, 3, "GRB")
        assert result == bytes([0, 255, 0, 255, 0, 0, 0, 0, 255])

    def test_identity_round_trip(self):
        pixels = bytes([100, 150, 200])
        grb = reorder_pixels(pixels, 1, "GRB")
        # GRB -> back to RGB by applying GRB mapping again?
        # No, to go back we need the inverse mapping.
        # GRB output is (150, 100, 200), applying GRB again gives (100, 150, 200)
        back = reorder_pixels(grb, 1, "GRB")
        assert back == pixels


class TestDownsampleToZones:
    def test_no_downsample_needed(self):
        pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])
        result = downsample_to_zones(pixels, 3, 3)
        assert result == pixels

    def test_2x_downsample(self):
        # 6 input pixels -> 3 output points
        # Center pixels: 1, 3, 5 (0-indexed)
        pixels = bytes([
            10, 20, 30,   # pixel 0
            40, 50, 60,   # pixel 1 (center of zone 0)
            70, 80, 90,   # pixel 2
            100, 110, 120,  # pixel 3 (center of zone 1)
            130, 140, 150,  # pixel 4
            160, 170, 180,  # pixel 5 (center of zone 2)
        ])
        result = downsample_to_zones(pixels, 6, 3)
        assert result == bytes([40, 50, 60, 100, 110, 120, 160, 170, 180])

    def test_300_to_10(self):
        # 300 input -> 10 output, input_per_point = 30
        # Center of zone 0: pixel 15, zone 1: pixel 45, etc.
        pixels = bytearray(300 * 3)
        for i in range(300):
            pixels[i * 3] = i % 256
        result = downsample_to_zones(bytes(pixels), 300, 10)
        assert len(result) == 30  # 10 * 3

    def test_output_length(self):
        pixels = bytes(100 * 3)
        result = downsample_to_zones(pixels, 100, 5)
        assert len(result) == 15  # 5 * 3


class TestBytesToRgbList:
    def test_single_pixel(self):
        result = bytes_to_rgb_list(bytes([255, 128, 64]), 1)
        assert result == [(255, 128, 64)]

    def test_multiple_pixels(self):
        result = bytes_to_rgb_list(bytes([255, 0, 0, 0, 255, 0, 0, 0, 255]), 3)
        assert result == [(255, 0, 0), (0, 255, 0), (0, 0, 255)]

    def test_all_black(self):
        result = bytes_to_rgb_list(bytes(9), 3)
        assert result == [(0, 0, 0), (0, 0, 0), (0, 0, 0)]

    def test_all_white(self):
        result = bytes_to_rgb_list(bytes([255] * 6), 2)
        assert result == [(255, 255, 255), (255, 255, 255)]

    def test_empty(self):
        result = bytes_to_rgb_list(b"", 0)
        assert result == []


class TestApplyGamma:
    def test_zero_stays_zero(self):
        assert apply_gamma(bytes([0]))[0] == 0

    def test_max_stays_max(self):
        assert apply_gamma(bytes([255]))[0] == 255

    def test_low_values_crushed(self):
        # Gamma 2.8 crushes low values significantly
        result = apply_gamma(bytes([26]))
        assert result[0] < 5  # 26/255 ^ 2.8 * 255 ≈ 0.5

    def test_mid_values_reduced(self):
        result = apply_gamma(bytes([128]))
        assert result[0] < 128  # gamma > 1 reduces mid-range

    def test_length_preserved(self):
        data = bytes(range(256))
        result = apply_gamma(data)
        assert len(result) == 256

    def test_monotonic(self):
        """Gamma LUT should be monotonically non-decreasing."""
        for i in range(255):
            assert GAMMA_LUT[i] <= GAMMA_LUT[i + 1]
