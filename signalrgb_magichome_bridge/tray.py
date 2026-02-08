"""System tray wrapper for the SignalRGB-MagicHome Bridge.

Runs the bridge in a background thread and shows a system tray icon
with status info and quit option.
"""

import sys
import threading

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem


class BridgeTray:
    def __init__(self):
        self._bridge_process = None
        self._status = "Starting..."
        self._icon = None

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

    def _run_bridge(self):
        """Run the bridge in a subprocess."""
        import subprocess
        self._status = "Running"
        if self._icon:
            self._icon.icon = self._create_icon_image("green")
            self._icon.title = "MagicHome Bridge - Running"

        args = [sys.executable, "-m", "signalrgb_magichome_bridge"] + sys.argv[1:]
        try:
            self._bridge_process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._bridge_process.wait()
            if self._status != "Quitting":
                self._status = "Stopped (crashed)"
                if self._icon:
                    self._icon.icon = self._create_icon_image("red")
                    self._icon.title = "MagicHome Bridge - Stopped"
        except Exception as e:
            self._status = f"Error: {e}"
            if self._icon:
                self._icon.icon = self._create_icon_image("red")

    def _on_quit(self, icon, item):
        self._status = "Quitting"
        if self._bridge_process and self._bridge_process.poll() is None:
            self._bridge_process.terminate()
            try:
                self._bridge_process.wait(timeout=5)
            except Exception:
                self._bridge_process.kill()
        icon.stop()

    def _get_status(self, item):
        return self._status

    def run(self):
        menu = Menu(
            MenuItem("SignalRGB-MagicHome Bridge", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(lambda item: f"Status: {self._status}", None, enabled=False),
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
        bridge_thread = threading.Thread(target=self._run_bridge, daemon=True)
        bridge_thread.start()

        # Run tray icon (blocks until quit)
        self._icon.run()


def main():
    tray = BridgeTray()
    tray.run()


if __name__ == "__main__":
    main()
