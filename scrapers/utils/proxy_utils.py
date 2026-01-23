# scrapers/utils/proxy_utils.py
"""
Proxy configuration for web scrapers.

Supports multiple proxy providers with automatic fallback:
1. ProxyFuel (datacenter rotating) - Primary, already paid
2. Decodo/Smartproxy (residential) - Fallback for blocked sites

Environment Variables:
- DECODO_PROXY_CREDENTIALS: "username:password" for Decodo (from Secret Manager)
- PROXYFUEL_CREDENTIALS: "username:password" for ProxyFuel (optional override)

Usage:
    The scraper_base.py will try each proxy in order until one succeeds.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Decodo ports - different ports may use different IP pools
DECODO_PORTS = [10001, 10002, 10003]


def get_proxy_urls():
    """
    Returns a list of proxy URLs to try in order.

    Order:
    1. ProxyFuel (datacenter) - cheaper, try first
    2. Decodo (residential) - multiple ports for different IP pools
    """
    proxies = []

    # Primary: ProxyFuel
    proxyfuel_creds = os.getenv("PROXYFUEL_CREDENTIALS", "nchammas.gmail.com:bbuyfd")
    if proxyfuel_creds:
        proxies.append(f"http://{proxyfuel_creds}@gate2.proxyfuel.com:2000")

    # Fallback: Decodo (residential) - try multiple ports for different IP pools
    decodo_creds = os.getenv("DECODO_PROXY_CREDENTIALS")
    if decodo_creds:
        # Use global gateway with multiple ports (each port may route to different IPs)
        for port in DECODO_PORTS:
            proxies.append(f"http://{decodo_creds}@gate.decodo.com:{port}")
    else:
        logger.debug("DECODO_PROXY_CREDENTIALS not set - Decodo fallback unavailable")

    if not proxies:
        logger.warning("No proxy credentials configured!")

    return proxies


def get_decodo_proxy_url(port: int = 10001):
    """
    Get Decodo proxy URL specifically (for cases where residential is required).

    Args:
        port: Decodo port (10001-10010), different ports may use different IP pools
    """
    decodo_creds = os.getenv("DECODO_PROXY_CREDENTIALS")
    if decodo_creds:
        return f"http://{decodo_creds}@gate.decodo.com:{port}"
    return None


def get_proxyfuel_proxy_url():
    """
    Get ProxyFuel proxy URL specifically.
    """
    proxyfuel_creds = os.getenv("PROXYFUEL_CREDENTIALS", "nchammas.gmail.com:bbuyfd")
    if proxyfuel_creds:
        return f"http://{proxyfuel_creds}@gate2.proxyfuel.com:2000"
    return None
