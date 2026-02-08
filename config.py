"""Configuration management for the SignalRGB-to-MagicHome bridge."""

import argparse
import json
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BridgeConfig:
    magic_home_ip: str = ""
    magic_home_port: int = 5577
    num_leds: int = 300
    max_fps: int = 30
    wled_name: str = "MagicHome Bridge"
    wled_http_port: int = 80
    bind_ip: str = "0.0.0.0"
    ddp_port: int = 4048
    log_level: str = "INFO"
    discover: bool = False

    @classmethod
    def load(cls, config_path: str = "config.json") -> "BridgeConfig":
        """Load from JSON file. Missing fields keep defaults."""
        config = cls()
        path = Path(config_path)
        if path.exists():
            with open(path, "r") as f:
                data = json.load(f)
            field_names = {f.name for f in config.__dataclass_fields__.values()}
            for key, value in data.items():
                if key in field_names:
                    setattr(config, key, value)
        return config

    @classmethod
    def from_cli(cls) -> "BridgeConfig":
        """Parse CLI args overlaid on JSON config."""
        parser = argparse.ArgumentParser(
            description="SignalRGB-to-MagicHome Bridge",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=(
                "Examples:\n"
                "  python bridge.py --discover\n"
                "  python bridge.py --ip 192.168.10.22 --leds 300\n"
                "  python bridge.py --ip 192.168.10.22 --leds 70 --fps 20 --http-port 8080\n"
            ),
        )
        parser.add_argument("--config", default="config.json", help="Path to config JSON file (default: config.json)")
        parser.add_argument("--ip", dest="magic_home_ip", help="Magic Home controller IP address")
        parser.add_argument("--port", dest="magic_home_port", type=int, help="Magic Home TCP port (default: 5577)")
        parser.add_argument("--leds", dest="num_leds", type=int, help="Number of addressable LEDs (default: 300)")
        parser.add_argument("--fps", dest="max_fps", type=int, help="Max frames per second to controller (default: 30)")
        parser.add_argument("--name", dest="wled_name", help='WLED device name shown in SignalRGB (default: "MagicHome Bridge")')
        parser.add_argument("--http-port", dest="wled_http_port", type=int, help="HTTP port for WLED API (default: 80)")
        parser.add_argument("--bind", dest="bind_ip", help="Bind address for listeners (default: 0.0.0.0)")
        parser.add_argument("--ddp-port", dest="ddp_port", type=int, help="DDP UDP port (default: 4048)")
        parser.add_argument("--log-level", dest="log_level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level (default: INFO)")
        parser.add_argument("--discover", action="store_true", help="Discover Magic Home controllers on the network and exit")

        args = parser.parse_args()

        # Load JSON config first
        config = cls.load(args.config)

        # Override with any CLI args that were explicitly provided
        for key, value in vars(args).items():
            if key == "config":
                continue
            if value is not None:
                setattr(config, key, value)

        return config

    def get_local_ip(self) -> str:
        """Determine this machine's LAN IP address."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            # Connect to a public DNS — doesn't actually send data
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"
