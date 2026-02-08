# SignalRGB &rarr; Magic Home Bridge

> Use **SignalRGB** to control **Magic Home WiFi SPI LED controllers** in real-time — rainbow waves, audio-reactive effects, game integrations, and every other SignalRGB effect on your Magic Home LED strips and panels.

Magic Home's addressable WiFi controllers (model 0xA3) are cheap and widely available, but SignalRGB doesn't support them natively. This bridge fixes that by emulating a WLED device on your LAN. SignalRGB discovers it automatically, streams pixel data over UDP, and the bridge translates every frame into Magic Home's native TCP protocol — no flashing, no custom firmware, fully reversible.

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

**Step by step:**

1. **Discovery** — The bridge advertises itself via mDNS as a WLED device (`_wled._tcp`). SignalRGB finds it automatically, just like a real WLED controller.

2. **Pixel Streaming** — SignalRGB streams RGB pixel data over UDP using WLED's DNRGB protocol (also supports DDP, DRGB, and WARLS). The bridge reassembles multi-packet frames into a contiguous pixel buffer.

3. **Protocol Translation** — Complete frames are translated into Magic Home's 0xA3 addressable protocol (zone change command `0x59`) and sent over a persistent TCP connection with automatic reconnect.

4. **Smart Throttling** — SignalRGB may push 60+ FPS. The bridge uses a "latest frame wins" strategy — only the most recent frame is sent at a configurable max FPS. Stale frames are discarded, not queued. All TCP writes are serialized through a single send loop to prevent stream corruption.

5. **Zone Mapping** — If the controller has fewer addressable points than input pixels (e.g., 10 hex panels driven by 300 pixels), the bridge auto-detects the controller's zone count and downsamples by sampling the center pixel of each zone.

---

## Features

- **Zero-config discovery** — mDNS advertisement, SignalRGB finds the bridge automatically
- **Full WLED protocol support** — DNRGB, DDP, DRGB, WARLS auto-detected from packet headers
- **Auto zone detection** — Queries the controller for its `pixels_per_segment` and downsamples accordingly
- **Persistent TCP with auto-reconnect** — Exponential backoff (1s → 8s), transparent to SignalRGB
- **Frame throttling** — Configurable max FPS with latest-frame-wins strategy
- **Power control passthrough** — SignalRGB on/off commands forwarded to the controller with debounce
- **System tray mode** — Runs as a Windows tray icon (no console window)
- **Scheduled task installer** — One-command auto-start on Windows logon
- **Controller discovery** — Find Magic Home controllers on your network via UDP broadcast

---

## Requirements

- **Python 3.10+**
- **Magic Home WiFi SPI controller** — Addressable v3 / model 0xA3 (the ones with `HF-LPB100` or similar WiFi modules)
- **SignalRGB** — installed on the same LAN

> **Note:** This bridge works with Magic Home controllers that use the 0xA3 addressable protocol. These are typically the WiFi SPI controllers for addressable LED strips (WS2812B, WS2811, etc.) sold under brands like Magic Home, MagicLight, or Zengge. If your controller shows up in the Magic Home app with individually addressable LEDs, it's likely compatible.

---

## Installation

### From PyPI (recommended)

```bash
pip install signalrgb-magichome-bridge
```

For system tray support (Windows):

```bash
pip install signalrgb-magichome-bridge[tray]
```

### From source

```bash
git clone https://github.com/RisingStar1/signalrgb-magichome-bridge.git
cd signalrgb-magichome-bridge
pip install -e .
```

---

## Quick Start

### 1. Find your controller

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

### 2. Start the bridge

```bash
signalrgb-bridge --ip 192.168.10.22 --leds 300
```

You should see:

```
============================================================
SignalRGB-to-MagicHome Bridge
============================================================
  Magic Home : 192.168.10.22:5577
  LEDs       : 300
  Max FPS    : 30
  WLED HTTP  : http://192.168.1.50:80
  DDP Port   : 4048
============================================================
Bridge is READY. Waiting for SignalRGB to connect...
```

### 3. Connect in SignalRGB

1. Open **SignalRGB** → **Devices**
2. The bridge appears as a WLED device named **"MagicHome Bridge"**
3. Click on it, map it to your canvas layout
4. Apply any effect — pixels stream to your LEDs in real-time

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
   Controller config: 10 points (pixels_per_segment), 10 segments
   ```

3. **In SignalRGB**, add the device and set it to **300 LEDs** (matching `--leds`). Map it on the canvas to cover your wall layout.

4. SignalRGB sends 300 pixels of color data. The bridge **downsamples** this to 10 zone colors by sampling the center pixel of each 30-pixel group. This gives the truest color match to what SignalRGB previews on screen.

### Tips for Hex Panel Users

- **Layout matters** — In SignalRGB's canvas editor, arrange the device strip to roughly match how your hex panels are physically mounted. This way the rainbow direction and effect flow match your wall.
- **Use wide effects** — Effects with broad color gradients (Rainbow Wave, Color Cycle, Gradient) look best. Fine-grained effects (Matrix rain, detailed patterns) will be simplified to 10 colors.
- **Lower FPS is fine** — With only 10 zones, `--fps 20` is plenty. The color transitions are smooth since each zone is a solid color anyway.

---

## Configuration

All options can be set via CLI flags, a `config.json` file, or both (CLI overrides JSON).

| CLI Flag | JSON Key | Default | Description |
|---|---|---|---|
| `--ip` | `magic_home_ip` | *(required)* | Magic Home controller IP address |
| `--port` | `magic_home_port` | `5577` | Magic Home TCP port |
| `--leds` | `num_leds` | `300` | Number of physical LEDs on your strip |
| `--fps` | `max_fps` | `30` | Max frames per second sent to controller |
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
    "max_fps": 30,
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

## Auto-Start on Windows

The bridge can run at logon as a system tray icon — no console window.

### Option A: Scheduled Task (recommended)

Run as **Administrator** in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File install-task.ps1 --ip 192.168.10.22 --leds 300
```

This registers a task that:
- Starts at logon using `pythonw.exe` (no console window)
- Shows a hexagon tray icon with status
- Auto-restarts up to 3 times on crash
- Right-click the tray icon → Quit to stop

To start immediately without rebooting:

```powershell
Start-ScheduledTask -TaskName "SignalRGB-MagicHome Bridge"
```

To uninstall:

```powershell
Unregister-ScheduledTask -TaskName "SignalRGB-MagicHome Bridge" -Confirm:$false
```

### Option B: Manual tray mode

```bash
signalrgb-bridge-tray --ip 192.168.10.22 --leds 300
```

### Option C: Console mode (for debugging)

```bash
signalrgb-bridge --ip 192.168.10.22 --leds 300 --log-level DEBUG
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **Device not found in SignalRGB** | Check Windows Firewall allows inbound UDP 4048 and TCP 80. Try `--http-port 8080` if port 80 is blocked. |
| **"Connection refused" to controller** | Verify the IP with `--discover`. Make sure the controller is powered on and on the same subnet. |
| **Port 80 requires admin** | Use `--http-port 8080` instead. SignalRGB can find the device via mDNS regardless of port. |
| **All LEDs show the same color** | This means the controller has fewer addressable zones than your LED count. The bridge auto-detects zones — check the startup log for "Controller config: N points". Each zone is one color. |
| **Flickering or stuttering** | Reduce `--fps` to 15-20. Check WiFi signal quality to the controller. |
| **High latency** | Magic Home uses TCP over WiFi — expect 30-100ms. Reduce `--fps` to reduce queuing. |
| **LEDs show wrong colors** | Verify `--leds` matches your actual LED count. Check LED wiring order in the Magic Home app. |
| **mDNS discovery fails** | Some networks block multicast. In SignalRGB, add the device manually by entering your PC's LAN IP. |
| **Bridge crashes when switching SignalRGB presets** | This was a known issue fixed in the current version via power command debounce and serialized TCP writes. Make sure you're running the latest code. |

---

## Architecture

| File | Purpose |
|---|---|
| `signalrgb_magichome_bridge/bridge.py` | Main entry point — wires all components together |
| `signalrgb_magichome_bridge/wled_emulator.py` | WLED HTTP JSON API + mDNS advertisement via zeroconf |
| `signalrgb_magichome_bridge/ddp_receiver.py` | UDP pixel receiver — DNRGB, DDP, DRGB, WARLS protocols |
| `signalrgb_magichome_bridge/magichome_client.py` | Persistent async TCP client with reconnect, throttling, zone mapping |
| `signalrgb_magichome_bridge/protocol.py` | Magic Home 0xA3 binary packet construction (pure functions, no I/O) |
| `signalrgb_magichome_bridge/discovery.py` | UDP broadcast controller discovery |
| `signalrgb_magichome_bridge/config.py` | Configuration management (JSON + CLI args) |
| `signalrgb_magichome_bridge/tray.py` | System tray wrapper using pystray |
| `install-task.ps1` | Windows Task Scheduler registration script |

---

## Running Tests

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

---

## Known Limitations

- **FPS** — Magic Home's TCP/WiFi protocol caps practical throughput at 15-30 FPS depending on LED count and WiFi conditions. This is a hardware limitation.
- **Latency** — Expect 30-100ms end-to-end (WiFi + TCP). Not suitable for rhythm games.
- **Addressable zones** — Some controllers only support a limited number of independently addressable zones (e.g., 10 zones for hex panel setups). The bridge auto-detects this and downsamples. Each zone displays one color.
- **Model support** — Only 0xA3 (Addressable v3) controllers. Legacy models use different protocols.
- **Single controller** — One bridge instance controls one controller. Run multiple instances on different `--http-port` values for multiple controllers.
- **Windows tray** — The system tray feature (`tray.py`) is Windows-specific. The core bridge (`bridge.py`) works on any platform.

---

## Protocol References

- [flux_led](https://github.com/lightinglibs/flux_led) — Magic Home protocol reference (packet formats verified against this library)
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
