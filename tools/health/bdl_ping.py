#!/usr/bin/env python3
"""
bdl_ping.py - lightweight Ball-Dont-Lie liveness + API-key check
----------------------------------------------------------------
Exit codes
from dotenv import load_dotenv
load_dotenv()
----------
0  OK           - HTTP 200
1  Service down - 5xx (infrastructure)
2  Auth error   - 401 / 403 (missing or bad key)
3  Client error - other 4xx
4  Network error / timeout

Usage
-----
# simplest (key picked up from env)
python tools/health/bdl_ping.py

# override key on CLI
python tools/health/bdl_ping.py --api_key=abc123
"""

from __future__ import annotations
import argparse
import os
import sys
import json
import requests

PING_URL = "https://api.balldontlie.io/v1/players?per_page=1"

def build_headers(api_key: str | None) -> dict[str, str]:
    headers = {
        "User-Agent": "bdl-ping/1.0 (+https://github.com/your-org)",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def extract_detail(resp: requests.Response) -> str:
    """Return a concise error message from a failed response."""
    try:
        if "application/json" in resp.headers.get("content-type", ""):
            return resp.json().get("message", "")
    except (ValueError, json.JSONDecodeError):
        pass

    text = (resp.text or "").strip()
    if text:
        return text.splitlines()[0][:120]
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--api_key", help="Override BDL_API_KEY env var")
    args = parser.parse_args()

    api_key = args.api_key or os.getenv("BDL_API_KEY")
    try:
        resp = requests.get(PING_URL, headers=build_headers(api_key), timeout=8)
    except requests.RequestException as exc:
        print(f"BDL ping: network error - {exc}", file=sys.stderr)
        sys.exit(4)

    code = resp.status_code
    if code == 200:
        sys.exit(0)

    detail = extract_detail(resp)
    print(f"BDL ping: {code} - {detail}", file=sys.stderr)

    if code in (401, 403):
        sys.exit(2)
    if 500 <= code < 600:
        sys.exit(1)
    sys.exit(3)


if __name__ == "__main__":
    main()
