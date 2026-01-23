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


def get_proxy_urls():
    """
    Returns a list of proxy URLs to try in order.

    Order:
    1. ProxyFuel (datacenter) - cheaper, try first
    2. Decodo US (residential) - fallback for 403s
    """
    proxies = []

    # Primary: ProxyFuel
    proxyfuel_creds = os.getenv("PROXYFUEL_CREDENTIALS", "nchammas.gmail.com:bbuyfd")
    if proxyfuel_creds:
        proxies.append(f"http://{proxyfuel_creds}@gate2.proxyfuel.com:2000")

    # Fallback: Decodo US (residential)
    # TEMPORARILY DISABLED: Decodo returning 407 errors - credentials may need renewal
    # TODO: Re-enable once Decodo account is fixed
    # decodo_creds = os.getenv("DECODO_PROXY_CREDENTIALS")
    # if decodo_creds:
    #     # Use US gateway for US sports sites
    #     proxies.append(f"http://{decodo_creds}@us.decodo.com:10001")
    # else:
    #     logger.debug("DECODO_PROXY_CREDENTIALS not set - Decodo fallback unavailable")
    logger.debug("Decodo proxy temporarily disabled - using ProxyFuel only")

    if not proxies:
        logger.warning("No proxy credentials configured!")

    return proxies


def get_decodo_proxy_url():
    """
    Get Decodo proxy URL specifically (for cases where residential is required).
    """
    decodo_creds = os.getenv("DECODO_PROXY_CREDENTIALS")
    if decodo_creds:
        return f"http://{decodo_creds}@us.decodo.com:10001"
    return None


def get_proxyfuel_proxy_url():
    """
    Get ProxyFuel proxy URL specifically.
    """
    proxyfuel_creds = os.getenv("PROXYFUEL_CREDENTIALS", "nchammas.gmail.com:bbuyfd")
    if proxyfuel_creds:
        return f"http://{proxyfuel_creds}@gate2.proxyfuel.com:2000"
    return None
# Cache bust: 1769119791
