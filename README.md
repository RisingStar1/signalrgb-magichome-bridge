# SignalRGB &rarr; Magic Home Bridge

[![Publish to PyPI](https://github.com/RisingStar1/signalrgb-magichome-bridge/actions/workflows/publish.yml/badge.svg)](https://github.com/RisingStar1/signalrgb-magichome-bridge/actions/workflows/publish.yml)

**`pip install signalrgb-magichome-bridge` → run one command → your Magic Home LEDs show up in SignalRGB.**

> Use **SignalRGB** to control **Magic Home WiFi SPI LED controllers** in real-time — rainbow waves, audio-reactive effects, game integrations, and every other SignalRGB effect on your Magic Home LED strips and panels.

Magic Home's addressable WiFi controllers (model 0xA3) are cheap and widely available, but SignalRGB doesn't support them natively. This bridge fixes that by emulating a WLED device on your LAN. SignalRGB discovers it automatically, streams pixel data over UDP, and the bridge forwards every frame to the controller via [flux_led](https://github.com/lightinglibs/flux_led) — no flashing, no custom firmware, fully reversible.

---

## Prerequisites

Before using the bridge, connect your Magic Home controller to your WiFi network using the **Magic Home app**. The controller needs to be on the network so the bridge can reach it.

---

## Quick Start

**Install** the bridge, **find** your controller, **run** it. Three steps, two minutes.

### 1. Install

```bash
pip install signalrgb-magichome-bridge
```

### 2. Find your controller

```bash
signalrgb-bridge --discover
```

```
Searching for Magic Home controllers on the network...

Found 1 device(s):

  IP Address           MAC Address          Model
  ------------------   -----------------    --------------------
  192.168.10.22        AABBCCDDEEFF         HF-LPB100-ZJ200

Use: signalrgb-bridge --ip <IP> --leds <COUNT>
```

### 3. Start the bridge

```bash
signalrgb-bridge --ip 192.168.10.22 --leds 300
```

```
============================================================
SignalRGB-to-MagicHome Bridge
============================================================
  Magic Home : 192.168.10.22:5577
  LEDs       : 300
  Max FPS    : 5
  Color Order: auto
  WLED HTTP  : http://192.168.1.50:80
  DDP Port   : 4048
============================================================
Bridge is READY. Waiting for SignalRGB to connect...
```

Now open **SignalRGB** &rarr; **Devices**. The bridge appears as a WLED device named **"MagicHome Bridge"**. Click on it, map it to your canvas, apply any effect — pixels stream to your LEDs in real-time.

---

## Run at Startup (Windows)

Want the bridge running every time you log in — silently, in the system tray, no console window?

```bash
signalrgb-bridge-install --ip 192.168.10.22 --leds 300
```

> Run this as **Administrator**. It registers a Windows scheduled task.

That's it. On every logon:
- A hexagon tray icon appears in your system tray
- The bridge starts automatically in the background
- If it crashes, Windows restarts it (up to 3 times)
- Right-click the tray icon for status, restart, log file, or quit

To start the task right now (without rebooting):

```bash
signalrgb-bridge-install --start
```

To remove it:

```bash
signalrgb-bridge-install --uninstall
```

---

## How It Works

```
                      Your PC                              WiFi Network
            ┌─────────────────────────┐              ┌─────────────────────┐
            │                         │   mDNS       │                     │
            │  SignalRGB  ────────────────────────►   │  Bridge             │
            │             ◄────────────────────────   │  (this app)         │
            │                         │   WLED HTTP   │                     │
            │                         │              │         │            │
            │  SignalRGB  ─── UDP ────────────────►   │  Pixel Receiver     │
            │             (DNRGB/DDP) │   :4048      │         │            │
            │                         │              │    Frame Buffer      │
            │                         │              │    (latest wins)     │
            │                         │              │         │            │
            └─────────────────────────┘              │  Magic Home Client   │
                                                     │  (via flux_led)     │
                                                     │         │ TCP :5577  │
                                                     └─────────┼───────────┘
                                                               │
                                                     ┌─────────▼───────────┐
                                                     │  Magic Home 0xA3    │
                                                     │  WiFi Controller    │
                                                     │         │ SPI       │
                                                     │    LED Strip /      │
                                                     │    Hex Panels       │
                                                     └─────────────────────┘
```

1. **Discovery** — The bridge advertises itself via mDNS as a WLED device (`_wled._tcp` and `_http._tcp`). SignalRGB finds it automatically, just like a real WLED controller. Initial burst announcements ensure fast discovery on startup.

2. **Pixel Streaming** — SignalRGB streams RGB pixel data over UDP using WLED's DNRGB protocol (also supports DDP, DRGB, and WARLS). The bridge reassembles multi-packet frames into a contiguous pixel buffer.

3. **Protocol Translation** — Complete frames are translated into Magic Home's 0xA3 addressable protocol via [flux_led](https://github.com/lightinglibs/flux_led) and sent over a persistent TCP connection. flux_led handles protocol detection, checksums, counters, and auto-reconnect.

4. **Controller Protection** — The ESP8266-based controllers have very limited TCP stacks. The bridge protects them with multiple layers:
   - **Proactive throttle** — First 8 frames at max FPS for instant response, then auto-decelerate to 2 FPS during sustained animation
   - **Fuzzy dedup** — Skip frames where no channel differs by more than 50 from the last sent frame. Static colors generate zero TCP traffic.
   - **Breathing pauses** — 3-second silence every 15 frames (TCP stays open) gives the controller's lwIP stack time to drain buffers

5. **Zone Mapping** — If the controller has fewer addressable points than input pixels (e.g., 10 hex panels driven by 300 pixels), the bridge auto-detects the controller's zone count and downsamples by sampling the center pixel of each zone. Color byte order (RGB/GRB) is auto-detected from the IC type.

---

## Features

- **Zero-config discovery** — mDNS advertisement with burst announcements, SignalRGB finds the bridge automatically
- **Full WLED protocol support** — DNRGB, DDP, DRGB, WARLS auto-detected from packet headers
- **flux_led transport** — Protocol-correct communication via [flux_led](https://github.com/lightinglibs/flux_led) (checksums, counters, 0xA3 wrapping, auto-reconnect)
- **Auto zone detection** — Queries the controller for its `pixels_per_segment` and downsamples accordingly. Results cached for fast restarts.
- **Color order auto-detection** — Reads IC type from the controller (WS2812B → GRB, etc.) and reorders bytes automatically
- **Controller stability** — Proactive throttle, fuzzy dedup, and breathing pauses prevent the ESP8266 from freezing
- **Persistent TCP with SO_LINGER(0)** — Immediate RST on close prevents ghost connections from crashing the controller on rapid restarts
- **Frame throttling** — Configurable max FPS with latest-frame-wins strategy
- **Power control passthrough** — SignalRGB on/off commands forwarded to the controller
- **System tray mode** — Runs as a Windows tray icon with status, restart, and log file access
- **File logging** — Always logs to `~/signalrgb-bridge.log` (essential for tray mode debugging)
- **One-command auto-start** — `signalrgb-bridge-install` sets up a Windows scheduled task
- **Controller discovery** — Find Magic Home controllers on your network via UDP broadcast

---

## Requirements

- **Python 3.10+**
- **Magic Home WiFi SPI controller** — Addressable v3 / model 0xA3 (the ones with `HF-LPB100` or similar WiFi modules)
- **SignalRGB** — installed on the same LAN

> **Note:** This bridge works with Magic Home controllers that use the 0xA3 addressable protocol. These are typically the WiFi SPI controllers for addressable LED strips (WS2812B, WS2811, etc.) sold under brands like Magic Home, MagicLight, or Zengge. If your controller shows up in the Magic Home app with individually addressable LEDs, it's likely compatible.

---

## Example: Hexagonal LED Panels

This bridge was originally built to control **hexagonal LED wall panels** (like Nanoleaf-style hex lights) powered by a Magic Home WiFi SPI controller. Here's how that setup works:

### The Setup

```
Magic Home 0xA3 Controller ──[SPI]──► 10 Hexagonal LED Panels (daisy-chained)
         ▲                             Each panel = ~30 LEDs wired in series
         │ TCP :5577                   Total: 300 physical LEDs
         │
    WiFi Network
         │
    This Bridge (on your PC)
         ▲
         │ UDP :4048
         │
    SignalRGB
```

Each hexagonal panel contains ~30 individually wired LEDs, but the Magic Home controller treats each panel as **one addressable zone**. The controller has 10 zones (`pixels_per_segment=10`), one per panel — this is a firmware limitation, not a bridge limitation.

### What This Means in Practice

- **10 zones = 10 independent colors** — Each hexagonal panel lights up as a single solid color
- **Rainbow effects work** — A rainbow spread across your 10 panels shows 10 distinct colors, shifting smoothly over time
- **Audio-reactive effects work** — Panels react to music with per-panel color changes
- **You won't get per-LED gradients within a single panel** — All 30 LEDs inside one hexagon show the same color

### How to Set It Up

1. **Start the bridge** with your total physical LED count:

   ```bash
   signalrgb-bridge --ip 192.168.10.22 --leds 300
   ```

2. The bridge **auto-detects** that the controller only has 10 addressable zones and logs it at startup:

   ```
   Controller config: 10 points, 10 segments, IC=WS2812B, color_order=GRB
   ```

3. **In SignalRGB**, add the device and set it to **300 LEDs** (matching `--leds`). Map it on the canvas to cover your wall layout.

4. SignalRGB sends 300 pixels of color data. The bridge **downsamples** this to 10 zone colors by sampling the center pixel of each 30-pixel group. This gives the truest color match to what SignalRGB previews on screen.

### Tips for Hex Panel Users

- **Layout matters** — In SignalRGB's canvas editor, arrange the device strip to roughly match how your hex panels are physically mounted. This way the rainbow direction and effect flow match your wall.
- **Use wide effects** — Effects with broad color gradients (Rainbow Wave, Color Cycle, Gradient) look best. Fine-grained effects (Matrix rain, detailed patterns) will be simplified to 10 colors.
- **Lower FPS is fine** — With only 10 zones, the default `--fps 5` is plenty. The color transitions are smooth since each zone is a solid color anyway.

---

## Configuration

All options can be set via CLI flags, a `config.json` file, or both (CLI overrides JSON).

| CLI Flag | JSON Key | Default | Description |
|---|---|---|---|
| `--ip` | `magic_home_ip` | *(required)* | Magic Home controller IP address |
| `--port` | `magic_home_port` | `5577` | Magic Home TCP port |
| `--leds` | `num_leds` | `300` | Number of physical LEDs on your strip |
| `--fps` | `max_fps` | `5` | Max frames per second sent to controller |
| `--color-order` | `color_order` | `auto` | LED color byte order (`auto`, `RGB`, `GRB`, `BRG`, `BGR`) |
| `--name` | `wled_name` | `"MagicHome Bridge"` | Device name shown in SignalRGB |
| `--http-port` | `wled_http_port` | `80` | HTTP port for WLED API emulation |
| `--bind` | `bind_ip` | `0.0.0.0` | Bind address for all listeners |
| `--ddp-port` | `ddp_port` | `4048` | UDP port for pixel data |
| `--log-level` | `log_level` | `INFO` | Logging verbosity (`DEBUG` `INFO` `WARNING` `ERROR`) |
| `--discover` | — | — | Scan the network for controllers and exit |
| `--config` | — | `config.json` | Path to config file |

### Using a config file

Copy the example and edit it:

```bash
cp config.example.json config.json
```

```json
{
    "magic_home_ip": "192.168.10.22",
    "num_leds": 300,
    "max_fps": 5,
    "wled_name": "My Hex Panels",
    "wled_http_port": 80,
    "log_level": "INFO"
}
```

Then just:

```bash
signalrgb-bridge
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **Device not found in SignalRGB** | Check Windows Firewall allows inbound UDP 4048 and TCP 80. Try `--http-port 8080` if port 80 is blocked. |
| **"Connection refused" to controller** | Verify the IP with `--discover`. Make sure the controller is powered on and on the same subnet. |
| **Port 80 requires admin** | Use `--http-port 8080` instead. SignalRGB can find the device via mDNS regardless of port. |
| **All LEDs show the same color** | The controller has fewer addressable zones than your LED count. The bridge auto-detects zones — check the startup log for "Controller config: N points". Each zone is one color. |
| **LEDs show wrong colors** | Try `--color-order RGB` or `--color-order GRB`. Auto-detection works for most WS2812B strips but may need manual override. |
| **Controller freezes after a while** | This is normal for ESP8266 controllers under sustained traffic. The bridge's breathing pauses handle this — check the log for "Breathing pause" messages. Power-cycle the controller if it stops responding. |
| **Flickering or stuttering** | Reduce `--fps` (default 5 is safe). Check WiFi signal quality to the controller. |
| **High latency** | Magic Home uses TCP over WiFi — expect 30-100ms. The bridge throttles to 2 FPS during sustained animation to protect the controller. |
| **mDNS discovery fails** | Some networks block multicast. In SignalRGB, add the device manually by entering your PC's LAN IP. |
| **Logs say "TimeoutError"** | The controller stopped responding (ESP8266 limitation). The bridge will auto-reconnect. Power-cycle the controller if errors persist. |
| **Where are the logs?** | Always written to `~/signalrgb-bridge.log`. In tray mode, right-click the icon → **Open Log File**. |

---

## Architecture

| Module | Purpose |
|---|---|
| `bridge.py` | Main entry point — wires all components together, periodic stats logging |
| `wled_emulator.py` | WLED HTTP JSON API + mDNS advertisement (both `_wled._tcp` and `_http._tcp`) |
| `ddp_receiver.py` | UDP pixel receiver — DNRGB, DDP, DRGB, WARLS protocols |
| `magichome_client.py` | `BridgeBulb` (flux_led subclass with SO_LINGER) + send loop with throttle, dedup, breathing |
| `protocol.py` | Pixel processing utilities — color reorder, downsample, gamma LUT (no protocol I/O) |
| `discovery.py` | UDP broadcast controller discovery |
| `config.py` | Configuration management (JSON + CLI args + auto-detection) |
| `tray.py` | System tray with status, restart, log viewer |
| `install.py` | Windows auto-start scheduled task registration |

---

## Running Tests

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

---

## Known Limitations

- **ESP8266 stability** — The controller's cheap WiFi chip (ESP8266/ESP32) has a limited TCP stack (~4 sockets, small buffers). The bridge works around this with breathing pauses, throttling, and fuzzy dedup, but sustained animation at high FPS can still eventually overwhelm it. The default settings are tuned for long-term stability.
- **Latency** — Expect 30-100ms end-to-end (WiFi + TCP). Not suitable for rhythm games.
- **Addressable zones** — Some controllers only support a limited number of independently addressable zones (e.g., 10 zones for hex panel setups). The bridge auto-detects this and downsamples. Each zone displays one color.
- **Model support** — Only 0xA3 (Addressable v3) controllers. Legacy models use different protocols.
- **Single controller** — One bridge instance controls one controller. Run multiple instances on different `--http-port` values for multiple controllers.

---

## Protocol References

- [flux_led](https://github.com/lightinglibs/flux_led) — Magic Home protocol library (used as the transport layer)
- [WLED UDP Realtime](https://kno.wled.ge/interfaces/udp-realtime/) — DNRGB/DDP/DRGB protocol documentation
- [WLED JSON API](https://kno.wled.ge/interfaces/json-api/) — HTTP API that SignalRGB uses for discovery
- [DDP Protocol](https://www.3waylabs.com/ddp/) — Distributed Display Protocol specification

---

## Contributing

Contributions are welcome! Some ideas:

- **More controller models** — Add support for non-0xA3 Magic Home controllers
- **Linux/macOS tray** — Port the system tray to work cross-platform
- **Multi-controller** — Single bridge instance managing multiple controllers
- **Brightness mapping** — Pass SignalRGB brightness changes through to controller brightness
- **Web dashboard** — Status page showing FPS, latency, connection health

---

## License

[MIT](LICENSE)
