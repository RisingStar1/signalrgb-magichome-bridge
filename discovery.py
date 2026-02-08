"""Magic Home controller discovery via UDP broadcast.

Sends the Magic Home discovery message to the LAN broadcast address
and collects responses containing IP, MAC, and model information.
"""

import asyncio
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

DISCOVERY_PORT = 48899
DISCOVERY_MSG = b"HF-A11ASSISTHREAD"
DISCOVERY_TIMEOUT = 3.0


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    """Collects UDP discovery responses."""

    def __init__(self):
        self.responses: List[Tuple[str, str, str]] = []
        self._seen_ips: set = set()
        self.transport = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        try:
            text = data.decode("utf-8").strip()
        except UnicodeDecodeError:
            return

        parts = text.split(",")
        if len(parts) != 3:
            return

        ip, mac, model = parts[0].strip(), parts[1].strip(), parts[2].strip()

        # Deduplicate by IP
        if ip in self._seen_ips:
            return
        self._seen_ips.add(ip)

        self.responses.append((ip, mac, model))
        logger.debug("Discovered: %s  MAC=%s  Model=%s", ip, mac, model)


async def discover_devices(
    timeout: float = DISCOVERY_TIMEOUT,
) -> List[Tuple[str, str, str]]:
    """Broadcast discovery message and collect Magic Home controller responses.

    Returns list of (ip, mac, model) tuples.
    """
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _DiscoveryProtocol,
        local_addr=("0.0.0.0", 0),
        allow_broadcast=True,
    )

    logger.info("Broadcasting Magic Home discovery on port %d...", DISCOVERY_PORT)
    transport.sendto(DISCOVERY_MSG, ("255.255.255.255", DISCOVERY_PORT))

    # Send a second broadcast after 1 second for reliability
    await asyncio.sleep(1.0)
    transport.sendto(DISCOVERY_MSG, ("255.255.255.255", DISCOVERY_PORT))

    # Wait remaining time
    await asyncio.sleep(max(0, timeout - 1.0))

    transport.close()
    return protocol.responses
