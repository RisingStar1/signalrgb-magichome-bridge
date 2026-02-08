"""Register SignalRGB-MagicHome Bridge as a Windows auto-start scheduled task.

Usage:
    signalrgb-bridge-install --ip 192.168.10.22 --leds 300
    signalrgb-bridge-install --uninstall
"""

import shutil
import subprocess
import sys

TASK_NAME = "SignalRGB-MagicHome Bridge"


def _find_pythonw() -> str:
    """Find pythonw.exe (Python without console window)."""
    pythonw = shutil.which("pythonw")
    if pythonw:
        return pythonw
    # Fallback: derive from python.exe path
    return sys.executable.replace("python.exe", "pythonw.exe")


def _run_powershell(script: str) -> bool:
    """Run a PowerShell script. Returns True on success."""
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr.strip()}")
        return False
    if result.stdout.strip():
        print(result.stdout.strip())
    return True


def install(bridge_args: list[str]) -> None:
    pythonw = _find_pythonw()
    arg_string = f"-m signalrgb_magichome_bridge.tray {' '.join(bridge_args)}"

    print(f"Using: {pythonw}")
    print(f"Arguments: {arg_string}")
    print()

    script = f"""
$action = New-ScheduledTaskAction `
    -Execute '{pythonw}' `
    -Argument '{arg_string}'

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -RunLevel Highest `
    -LogonType Interactive

Register-ScheduledTask `
    -TaskName '{TASK_NAME}' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force
"""

    if not _run_powershell(script):
        print("Failed to register scheduled task.")
        print("Try running as Administrator.")
        sys.exit(1)

    print()
    print(f"Task '{TASK_NAME}' registered!")
    print("It runs as a system tray icon at logon (no CMD window).")
    print()
    print(f"To start now:  signalrgb-bridge-install --start")
    print(f"To remove:     signalrgb-bridge-install --uninstall")


def start() -> None:
    print(f"Starting '{TASK_NAME}'...")
    _run_powershell(f"Start-ScheduledTask -TaskName '{TASK_NAME}'")


def uninstall() -> None:
    print(f"Removing '{TASK_NAME}'...")
    if _run_powershell(
        f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false"
    ):
        print("Task removed.")


def main() -> None:
    if sys.platform != "win32":
        print("Error: Auto-start installation is only supported on Windows.")
        sys.exit(1)

    args = sys.argv[1:]

    if "--uninstall" in args:
        uninstall()
    elif "--start" in args:
        start()
    elif not args:
        print("Usage: signalrgb-bridge-install --ip <IP> --leds <COUNT>")
        print()
        print("Options:")
        print("  --ip, --leds, etc.  Bridge arguments (passed to signalrgb-bridge-tray)")
        print("  --start             Start the scheduled task now")
        print("  --uninstall         Remove the scheduled task")
        sys.exit(1)
    else:
        install(args)


if __name__ == "__main__":
    main()
