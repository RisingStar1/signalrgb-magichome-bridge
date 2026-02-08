"""SignalRGB-to-MagicHome Bridge — main entry point.

Wires the WLED emulator, DDP receiver, and Magic Home TCP client together.
Runs a single asyncio event loop hosting all subsystems concurrently.

Usage:
    signalrgb-bridge --discover
    signalrgb-bridge --ip 192.168.10.22 --leds 300
    signalrgb-bridge --ip 192.168.10.22 --leds 70 --fps 20 --http-port 8080
"""

import asyncio
import logging
import sys
from typing import Optional

from .config import BridgeConfig
from .ddp_receiver import PixelReceiver
from .discovery import discover_devices
from .magichome_client import MagicHomeClient
from .wled_emulator import WLEDEmulator

logger = logging.getLogger(__name__)


class Bridge:
    """Orchestrates all bridge components.

    Data flow:
      PixelReceiver.on_frame() → MagicHomeClient.update_frame()
      MagicHomeClient._send_loop() → TCP to controller
    """

    def __init__(self, config: BridgeConfig):
        self._config = config
        self._running = False

        self._magic_home = MagicHomeClient(
            host=config.magic_home_ip,
            port=config.magic_home_port,
            max_fps=config.max_fps,
        )

        self._ddp = PixelReceiver(
            num_leds=config.num_leds,
            on_frame=self._on_ddp_frame,
            bind_ip=config.bind_ip,
            port=config.ddp_port,
        )

        local_ip = config.get_local_ip()

        self._wled = WLEDEmulator(
            name=config.wled_name,
            num_leds=config.num_leds,
            local_ip=local_ip,
            http_port=config.wled_http_port,
            bind_ip=config.bind_ip,
            ddp_receiver=self._ddp,
            power_callback=self._on_power_change,
        )

    def _on_ddp_frame(self, pixel_data: bytes, num_pixels: int) -> None:
        """Callback from PixelReceiver when a complete frame arrives."""
        self._magic_home.update_frame(pixel_data, num_pixels)

    async def _on_power_change(self, on: bool) -> None:
        """Callback from WLED emulator when SignalRGB changes power state."""
        if on:
            await self._magic_home.power_on()
        else:
            await self._magic_home.power_off()

    async def start(self) -> None:
        """Start all subsystems in order."""
        cfg = self._config
        local_ip = cfg.get_local_ip()

        logger.info("=" * 60)
        logger.info("SignalRGB-to-MagicHome Bridge")
        logger.info("=" * 60)
        logger.info("  Magic Home : %s:%d", cfg.magic_home_ip, cfg.magic_home_port)
        logger.info("  LEDs       : %d", cfg.num_leds)
        logger.info("  Max FPS    : %d", cfg.max_fps)
        logger.info("  WLED HTTP  : http://%s:%d", local_ip, cfg.wled_http_port)
        logger.info("  DDP Port   : %d", cfg.ddp_port)
        logger.info("=" * 60)

        # 1. Auto-detect controller zone configuration
        logger.info("Detecting controller configuration...")
        await self._magic_home.detect_zones()

        # 2. Connect to Magic Home controller
        await self._magic_home.start()

        # 3. Power on
        if self._magic_home.connected:
            await self._magic_home.power_on()
        else:
            logger.warning("Controller not reachable — will retry in background")

        # 3. Start DDP receiver
        await self._ddp.start()

        # 4. Start WLED emulator (advertise ourselves)
        await self._wled.start()

        self._running = True
        logger.info("")
        logger.info("Bridge is READY. Waiting for SignalRGB to connect...")
        logger.info("  In SignalRGB, look for device: \"%s\"", cfg.wled_name)

    async def stop(self) -> None:
        """Stop all subsystems in reverse order."""
        if not self._running:
            return
        self._running = False
        logger.info("Shutting down bridge...")
        await self._wled.stop()
        await self._ddp.stop()
        await self._magic_home.stop()
        logger.info("Bridge stopped.")

    async def run_forever(self) -> None:
        """Start and run until interrupted."""
        await self.start()
        try:
            # Print periodic stats
            while self._running:
                await asyncio.sleep(10)
                if self._ddp.is_receiving:
                    stats = self._ddp.stats
                    logger.info(
                        "Stats: DDP frames=%d, MH sent=%d, MH errors=%d",
                        stats["frames_completed"],
                        self._magic_home.frames_sent,
                        self._magic_home.send_errors,
                    )
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def async_main() -> None:
    config = BridgeConfig.from_cli()

    setup_logging(config.log_level)

    # Handle --discover mode
    if config.discover:
        print("Searching for Magic Home controllers on the network...")
        devices = await discover_devices()
        if devices:
            print(f"\nFound {len(devices)} device(s):\n")
            print(f"  {'IP Address':<20} {'MAC Address':<20} {'Model'}")
            print(f"  {'-'*18:<20} {'-'*17:<20} {'-'*20}")
            for ip, mac, model in devices:
                print(f"  {ip:<20} {mac:<20} {model}")
            print(f"\nUse: signalrgb-bridge --ip <IP> --leds <COUNT>")
        else:
            print("No Magic Home devices found on the network.")
            print("Make sure the controller is powered on and connected to WiFi.")
        return

    # Validate required config
    if not config.magic_home_ip:
        print("Error: Magic Home controller IP is required.")
        print("")
        print("  Use --discover to find controllers on your network:")
        print("    signalrgb-bridge --discover")
        print("")
        print("  Or specify the IP directly:")
        print("    signalrgb-bridge --ip 192.168.10.22 --leds 300")
        sys.exit(1)

    bridge = Bridge(config)

    # On Windows, signal handlers don't work — rely on KeyboardInterrupt
    if sys.platform != "win32":
        import signal
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bridge.stop()))

    await bridge.run_forever()


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nInterrupted.")


if __name__ == "__main__":
    main()
