@echo off
where signalrgb-bridge >nul 2>&1 && (
    signalrgb-bridge %*
) || (
    python -m signalrgb_magichome_bridge %*
)
