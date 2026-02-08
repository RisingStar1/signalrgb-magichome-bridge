"""Tests for DDP packet parsing and frame assembly."""

import struct

from signalrgb_magichome_bridge.ddp_receiver import PixelReceiver, DDP_HEADER_SIZE


def _make_ddp_packet(
    pixel_data: bytes,
    offset: int = 0,
    push: bool = True,
    version: int = 1,
    sequence: int = 1,
) -> bytes:
    """Build a DDP packet with given parameters."""
    flags = (version << 6) | (0x01 if push else 0x00)
    header = struct.pack(
        "!BBBBIH",
        flags,
        sequence & 0xFF,
        0x00,  # data type
        0x01,  # source ID
        offset,
        len(pixel_data),
    )
    return header + pixel_data


class TestDDPPacketParsing:
    def _make_receiver(self, num_leds: int = 10):
        self.received_frames = []

        def on_frame(data: bytes, num_pixels: int):
            self.received_frames.append((data, num_pixels))

        return PixelReceiver(num_leds=num_leds, on_frame=on_frame)

    def test_single_packet_frame(self):
        """One packet with push flag delivers a frame."""
        receiver = self._make_receiver(num_leds=3)
        pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])
        packet = _make_ddp_packet(pixels, offset=0, push=True)
        receiver._handle_packet(packet, ("127.0.0.1", 12345))

        assert len(self.received_frames) == 1
        data, num = self.received_frames[0]
        assert num == 3
        assert data[:9] == pixels

    def test_push_flag_triggers_callback(self):
        """No callback without push flag."""
        receiver = self._make_receiver(num_leds=3)
        pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])

        # Send without push
        packet = _make_ddp_packet(pixels, offset=0, push=False)
        receiver._handle_packet(packet, ("127.0.0.1", 12345))
        assert len(self.received_frames) == 0

        # Now send with push
        packet = _make_ddp_packet(b"", offset=9, push=True)
        receiver._handle_packet(packet, ("127.0.0.1", 12345))
        assert len(self.received_frames) == 1

    def test_multi_packet_frame(self):
        """Two packets with push on second assembles complete frame."""
        receiver = self._make_receiver(num_leds=4)

        # First 2 pixels in packet 1 (no push)
        pkt1_data = bytes([255, 0, 0, 0, 255, 0])
        pkt1 = _make_ddp_packet(pkt1_data, offset=0, push=False)
        receiver._handle_packet(pkt1, ("127.0.0.1", 12345))
        assert len(self.received_frames) == 0

        # Last 2 pixels in packet 2 (push)
        pkt2_data = bytes([0, 0, 255, 128, 128, 128])
        pkt2 = _make_ddp_packet(pkt2_data, offset=6, push=True)
        receiver._handle_packet(pkt2, ("127.0.0.1", 12345))

        assert len(self.received_frames) == 1
        data, num = self.received_frames[0]
        assert num == 4
        # First 6 bytes from pkt1, next 6 bytes from pkt2
        assert data[:6] == pkt1_data
        assert data[6:12] == pkt2_data

    def test_offset_beyond_buffer_ignored(self):
        """Packet with offset beyond buffer size is safely handled."""
        receiver = self._make_receiver(num_leds=2)
        far_pixels = bytes([255, 255, 255])
        packet = _make_ddp_packet(far_pixels, offset=1000, push=True)
        receiver._handle_packet(packet, ("127.0.0.1", 12345))

        # Frame still delivered (buffer unchanged = zeros)
        assert len(self.received_frames) == 1
        data, _ = self.received_frames[0]
        assert data == bytes(6)  # all zeros

    def test_partial_write_at_buffer_end(self):
        """Packet that extends past buffer is truncated."""
        receiver = self._make_receiver(num_leds=2)  # buffer = 6 bytes
        pixels = bytes([255, 128, 64, 32, 16, 8, 4, 2, 1])  # 9 bytes
        packet = _make_ddp_packet(pixels, offset=3, push=True)
        receiver._handle_packet(packet, ("127.0.0.1", 12345))

        assert len(self.received_frames) == 1
        data, _ = self.received_frames[0]
        # Offset=3, buffer=6, so only 3 bytes fit
        assert data[3:6] == bytes([255, 128, 64])
        assert data[:3] == bytes(3)  # untouched = zeros

    def test_short_packet_dropped(self):
        """Packet shorter than header is silently dropped."""
        receiver = self._make_receiver(num_leds=3)
        receiver._handle_packet(bytes(5), ("127.0.0.1", 12345))
        assert len(self.received_frames) == 0

    def test_wrong_version_dropped(self):
        """Non-version-1 packet is dropped."""
        receiver = self._make_receiver(num_leds=3)
        pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])
        packet = _make_ddp_packet(pixels, offset=0, push=True, version=2)
        receiver._handle_packet(packet, ("127.0.0.1", 12345))
        assert len(self.received_frames) == 0

    def test_stats_tracking(self):
        """Stats are updated on packet and frame receipt."""
        receiver = self._make_receiver(num_leds=3)
        pixels = bytes(9)

        # Packet without push
        pkt1 = _make_ddp_packet(pixels, offset=0, push=False)
        receiver._handle_packet(pkt1, ("127.0.0.1", 12345))
        assert receiver._packets_received == 1
        assert receiver._frames_completed == 0

        # Packet with push
        pkt2 = _make_ddp_packet(b"", offset=9, push=True)
        receiver._handle_packet(pkt2, ("127.0.0.1", 12345))
        assert receiver._packets_received == 2
        assert receiver._frames_completed == 1

    def test_frame_snapshot_is_independent(self):
        """Delivered frame is a copy, not a reference to the internal buffer."""
        receiver = self._make_receiver(num_leds=1)
        pixels = bytes([100, 200, 50])
        pkt = _make_ddp_packet(pixels, offset=0, push=True)
        receiver._handle_packet(pkt, ("127.0.0.1", 12345))

        frame1_data = self.received_frames[0][0]

        # Send another frame with different data
        pixels2 = bytes([10, 20, 30])
        pkt2 = _make_ddp_packet(pixels2, offset=0, push=True)
        receiver._handle_packet(pkt2, ("127.0.0.1", 12345))

        # First frame should be unchanged
        assert frame1_data[:3] == bytes([100, 200, 50])
