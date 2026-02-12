"""Pixel processing utilities for MagicHome LED controllers.

Pure functions for color reordering, downsampling, and format conversion.
Protocol-level packet construction is handled by flux_led.
"""

# WLED-compatible gamma correction LUT (gamma=2.8)
# WLED applies gamma correction to all incoming pixel data by default
# (see setRealtimePixel in WLED source). Without this, low-value channels
# appear much brighter than intended on WS2812B LEDs (e.g. red looks pink).
GAMMA_LUT = bytes(
    round(pow(i / 255.0, 2.8) * 255.0) for i in range(256)
)


def apply_gamma(pixels: bytes) -> bytes:
    """Apply WLED-compatible gamma correction (gamma=2.8) to pixel data.

    WLED applies gamma correction to all incoming realtime pixel data by
    default. This crushes low channel values (e.g. G=26 -> 1, B=41 -> 2),
    preventing color bleed that makes red look pink on WS2812B LEDs.
    """
    return bytes(GAMMA_LUT[b] for b in pixels)


def reorder_pixels(pixels: bytes, num_pixels: int, color_order: str) -> bytes:
    """Reorder RGB pixel bytes to match the controller's native color order.

    SignalRGB always sends RGB. The controller's LED IC may expect a
    different order (e.g. WS2812B expects GRB). This swaps bytes so
    the LEDs display the correct colors.

    Args:
        pixels: RGB pixel data from SignalRGB (num_pixels * 3 bytes)
        num_pixels: Number of pixels
        color_order: Target byte order, e.g. "GRB", "RGB", "BRG"

    Returns:
        Pixel bytes in the controller's native order.
    """
    if color_order == "RGB":
        return pixels

    # Map: for each output position, which input byte index to read.
    # Input is always [R=0, G=1, B=2].
    rgb_index = {"R": 0, "G": 1, "B": 2}
    mapping = tuple(rgb_index[ch] for ch in color_order)

    result = bytearray(len(pixels))
    for i in range(num_pixels):
        base = i * 3
        result[base] = pixels[base + mapping[0]]
        result[base + 1] = pixels[base + mapping[1]]
        result[base + 2] = pixels[base + mapping[2]]

    return bytes(result)


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
        RGB bytes for num_points pixels.
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


def bytes_to_rgb_list(pixel_bytes: bytes, num_pixels: int) -> list[tuple[int, int, int]]:
    """Convert flat RGB bytes to list of (R, G, B) tuples for flux_led."""
    return [
        (pixel_bytes[i * 3], pixel_bytes[i * 3 + 1], pixel_bytes[i * 3 + 2])
        for i in range(num_pixels)
    ]
