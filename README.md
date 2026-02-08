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

```bash
git clone https://github.com/YourUsername/signalrgb-magichome-bridge.git
cd signalrgb-magichome-bridge
pip install -r requirements.txt
```

---

## Quick Start

### 1. Find your controller

```bash
python bridge.py --discover
```

```
Searching for Magic Home controllers on the network...

Found 1 device(s):

  IP Address           MAC Address          Model
  ------------------   -----------------    --------------------
  192.168.10.22        AABBCCDDEEFF         HF-LPB100-ZJ200

Use: python bridge.py --ip <IP> --leds <COUNT>
```

### 2. Start the bridge

```bash
python bridge.py --ip 192.168.10.22 --leds 300
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
python bridge.py
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
pythonw tray.py --ip 192.168.10.22 --leds 300
```

### Option C: Console mode (for debugging)

```bash
python bridge.py --ip 192.168.10.22 --leds 300 --log-level DEBUG
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
| `bridge.py` | Main entry point — wires all components together |
| `wled_emulator.py` | WLED HTTP JSON API + mDNS advertisement via zeroconf |
| `ddp_receiver.py` | UDP pixel receiver — DNRGB, DDP, DRGB, WARLS protocols |
| `magichome_client.py` | Persistent async TCP client with reconnect, throttling, zone mapping |
| `protocol.py` | Magic Home 0xA3 binary packet construction (pure functions, no I/O) |
| `discovery.py` | UDP broadcast controller discovery |
| `config.py` | Configuration management (JSON + CLI args) |
| `tray.py` | System tray wrapper using pystray |
| `install-task.ps1` | Windows Task Scheduler registration script |

---

## Running Tests

```bash
pip install pytest pytest-aiohttp
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
