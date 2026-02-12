"""System tray wrapper for the SignalRGB-MagicHome Bridge.

Runs the bridge in a background thread and shows a system tray icon
with status info and quit option.
"""

import os
import sys
import threading

from pathlib import Path
from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from .config import BridgeConfig

LOG_FILE = Path.home() / "signalrgb-bridge.log"


class BridgeTray:
    def __init__(self):
        self._bridge_process = None
        self._log_fh = None
        self._status = "Starting..."
        self._icon = None
        self._bridge_thread = None
        self._config = self._load_config()
        self._local_ip = self._config.get_local_ip()

    def _load_config(self) -> BridgeConfig:
        """Load config from JSON + CLI args (same logic as the bridge)."""
        # Strip the tray-specific executable name so BridgeConfig sees
        # only the bridge args (--ip, --leds, etc.)
        config = BridgeConfig.load()
        # Apply any CLI overrides that were passed to the tray
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg == "--ip" and i < len(sys.argv):
                config.magic_home_ip = sys.argv[i + 1]
            elif arg == "--leds" and i < len(sys.argv):
                config.num_leds = int(sys.argv[i + 1])
            elif arg == "--fps" and i < len(sys.argv):
                config.max_fps = int(sys.argv[i + 1])
            elif arg == "--http-port" and i < len(sys.argv):
                config.wled_http_port = int(sys.argv[i + 1])
        return config

    def _create_icon_image(self, color="green"):
        """Create a simple colored hex icon."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        colors = {
            "green": (0, 200, 80),
            "yellow": (220, 180, 0),
            "red": (200, 50, 50),
        }
        fill = colors.get(color, colors["green"])
        # Draw a filled hexagon
        cx, cy, r = 32, 32, 28
        import math
        points = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        draw.polygon(points, fill=fill, outline=(255, 255, 255, 200), width=2)
        # Draw "MH" text
        draw.text((18, 22), "MH", fill=(255, 255, 255))
        return img

    def _update_icon(self, color, title, status):
        """Thread-safe icon update."""
        self._status = status
        if self._icon:
            self._icon.icon = self._create_icon_image(color)
            self._icon.title = title

    # ── Bridge subprocess management ─────────────────────────────────

    def _start_bridge(self):
        """Start the bridge subprocess, redirecting output to log file."""
        import subprocess
        self._log_fh = open(LOG_FILE, "a", encoding="utf-8")
        args = [sys.executable, "-m", "signalrgb_magichome_bridge"] + sys.argv[1:]
        self._bridge_process = subprocess.Popen(
            args,
            stdout=self._log_fh,
            stderr=self._log_fh,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def _stop_bridge(self):
        """Stop the bridge subprocess if running."""
        if self._bridge_process and self._bridge_process.poll() is None:
            self._bridge_process.terminate()
            try:
                self._bridge_process.wait(timeout=5)
            except Exception:
                self._bridge_process.kill()
        self._bridge_process = None
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None

    def _run_bridge(self):
        """Run the bridge in a background thread."""
        import time
        try:
            self._start_bridge()
            time.sleep(3)
            if self._bridge_process and self._bridge_process.poll() is None:
                self._update_icon("green", "MagicHome Bridge - Running", "Running")
            else:
                self._update_icon("red", "MagicHome Bridge - Failed to start", "Failed to start")
                return
            self._bridge_process.wait()
            if self._status != "Quitting" and self._status != "Restarting":
                self._update_icon("red", "MagicHome Bridge - Stopped", "Stopped (crashed)")
        except Exception as e:
            self._update_icon("red", "MagicHome Bridge - Error", f"Error: {e}")

    # ── Menu actions ─────────────────────────────────────────────────

    def _on_restart(self, icon, item):
        """Restart the bridge subprocess."""
        self._status = "Restarting"
        self._update_icon("yellow", "MagicHome Bridge - Restarting...", "Restarting...")
        self._stop_bridge()
        self._bridge_thread = threading.Thread(target=self._run_bridge, daemon=True)
        self._bridge_thread.start()

    def _on_open_log(self, icon, item):
        """Open the log file in the default text editor."""
        if LOG_FILE.exists():
            os.startfile(str(LOG_FILE))

    def _on_quit(self, icon, item):
        self._status = "Quitting"
        self._stop_bridge()
        icon.stop()

    # ── Main ─────────────────────────────────────────────────────────

    def run(self):
        cfg = self._config
        controller_ip = cfg.magic_home_ip or "not set"

        menu = Menu(
            MenuItem("SignalRGB-MagicHome Bridge", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(lambda item: f"Status: {self._status}", None, enabled=False),
            MenuItem(f"Bridge IP: {self._local_ip}:{cfg.wled_http_port}", None, enabled=False),
            MenuItem(f"Controller: {controller_ip}:{cfg.magic_home_port}", None, enabled=False),
            MenuItem(f"LEDs: {cfg.num_leds}  |  Max FPS: {cfg.max_fps}", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Restart Bridge", self._on_restart),
            MenuItem("Open Log File", self._on_open_log),
            Menu.SEPARATOR,
            MenuItem("Quit", self._on_quit),
        )

        self._icon = Icon(
            name="MagicHome Bridge",
            icon=self._create_icon_image("yellow"),
            title="MagicHome Bridge - Starting...",
            menu=menu,
        )

        # Start bridge in background thread
        self._bridge_thread = threading.Thread(target=self._run_bridge, daemon=True)
        self._bridge_thread.start()

        # Run tray icon (blocks until quit)
        self._icon.run()


def main():
    tray = BridgeTray()
    tray.run()


if __name__ == "__main__":
    main()
