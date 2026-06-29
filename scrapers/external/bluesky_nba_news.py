# File: scrapers/external/bluesky_nba_news.py
"""
Bluesky NBA News Jetstream Listener                             v1.0 - 2026-06-29
----------------------------------------------------------------------------------
Real-time WebSocket listener that subscribes to Bluesky posts from ~10 NBA beat
writers and captures injury/status updates via keyword filtering.

This is NOT a standard request/response scraper — it is a long-running WebSocket
listener designed to run as a Cloud Run Job on game days (noon–midnight ET).

Why this matters:
  Sharp books reprice player props within 10-30 seconds of major injury news.
  CASCADE REPRICING of TEAMMATE props takes 30-90 minutes.
  Beat writers post injury designations ~1-2 hours before tip, often before
  official NBA reports propagate to all books.

Tech stack:
  - atproto Python SDK (handle resolution + public API)
  - Bluesky Jetstream WebSocket API (no auth required for public posts)
  - websockets library for async WebSocket connection
  - google-cloud-bigquery + google-cloud-storage for persistence

Architecture:
  1. Resolve handles → DIDs via Bluesky public API (run once at startup)
  2. Open Jetstream WebSocket filtered to those DIDs + app.bsky.feed.post
  3. For each incoming post: filter for signal keywords
  4. Matching posts: buffer in memory, flush to GCS + BQ periodically
  5. On shutdown (SIGTERM or --duration elapsed): final flush + write summary

WebSocket URL format:
  wss://jetstream1.us-east.bsky.network/subscribe
    ?wantedCollections=app.bsky.feed.post
    &wantedDids=did:plc:xxx
    &wantedDids=did:plc:yyy
    ...

Jetstream message format (JSON, kind=commit, op=create):
  {
    "did": "did:plc:dw45eosoi7tiq3cjqyxx6tvn",
    "time_us": 1719676800000000,
    "kind": "commit",
    "commit": {
      "rev": "...",
      "operation": "create",
      "collection": "app.bsky.feed.post",
      "rkey": "3l7xyzabc",
      "cid": "bafyreid...",
      "record": {
        "$type": "app.bsky.feed.post",
        "text": "LeBron James listed as questionable tonight...",
        "createdAt": "2026-06-29T18:30:00.000Z",
        "langs": ["en"]
      }
    }
  }

Beat writers monitored:
  chrisbhaynes.bsky.social   Chris Haynes (ESPN)
  thesteinline.bsky.social   Marc Stein (Independent)
  zachlowenba.bsky.social    Zach Lowe (ESPN)
  samamick.bsky.social       Sam Amick (The Athletic)
  jakelfischer.bsky.social   Jake Fischer (Yahoo)
  anthonyvslater.bsky.social Anthony Slater (ESPN Warriors)
  danwoikesports.bsky.social Dan Woike (The Athletic Lakers)
  fredkatz.bsky.social       Fred Katz (The Athletic Knicks)
  jonkrawczynski.bsky.social Jon Krawczynski (The Athletic Wolves)
  bytimreynolds.bsky.social  Tim Reynolds (AP)

Signal keywords (case-insensitive):
  questionable, limited, scratch, GTD, game-time, won't play, out tonight,
  ruled out, reduced minutes, bounce back, called out, won't start,
  coming off bench

Usage:
  # Run for 6 hours (covers noon–6 PM ET pre-game window)
  python scrapers/external/bluesky_nba_news.py --date 2026-10-22 --duration 360

  # Run for 2 hours in dev mode (logs to stdout, no GCS/BQ writes)
  python scrapers/external/bluesky_nba_news.py --date 2026-10-22 --duration 120 --debug

  # Run and write to GCS + BQ (production)
  python scrapers/external/bluesky_nba_news.py --date 2026-10-22 --duration 360 --group prod

  # Override beat writer list (comma-separated handles)
  python scrapers/external/bluesky_nba_news.py --date 2026-10-22 \
      --handles "chrisbhaynes.bsky.social,thesteinline.bsky.social"

Notes:
  - Requires google-cloud-bigquery and google-cloud-storage in the environment.
  - BQ table: nba_raw.bluesky_nba_news (partitioned by game_date)
  - GCS path: external/bluesky/nba-news/{date}/{timestamp}.json
  - The script flushes to GCS/BQ every FLUSH_INTERVAL_SECS (default 300).
  - On SIGTERM (Cloud Run Job timeout), a final flush runs before exit.
  - atproto Client is used ONLY for handle resolution (unauthenticated public API).
    The Jetstream WebSocket does not require auth.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Optional dependencies — imported lazily so the file can be imported without
# crashing in environments that lack atproto or websockets.
# ---------------------------------------------------------------------------
try:
    import websockets
    import websockets.exceptions
    _WEBSOCKETS_AVAILABLE = True
except ImportError:
    _WEBSOCKETS_AVAILABLE = False

try:
    from atproto import Client as AtprotoClient
    _ATPROTO_AVAILABLE = True
except ImportError:
    _ATPROTO_AVAILABLE = False

try:
    from google.cloud import bigquery
    from google.cloud import storage as gcs
    _GCP_AVAILABLE = True
except ImportError:
    _GCP_AVAILABLE = False

# ---------------------------------------------------------------------------
# Project path setup (support both package import and direct script execution)
# ---------------------------------------------------------------------------
_SCRAPERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_SCRAPERS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from scrapers.utils.gcs_path_builder import GCSPathBuilder
    _GCS_PATH_BUILDER_AVAILABLE = True
except ImportError:
    _GCS_PATH_BUILDER_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Jetstream public WebSocket endpoints (us-east primary, us-west fallback)
JETSTREAM_ENDPOINTS = [
    "wss://jetstream1.us-east.bsky.network/subscribe",
    "wss://jetstream2.us-east.bsky.network/subscribe",
    "wss://jetstream1.us-west.bsky.network/subscribe",
]

# Handle resolution API (public, no auth)
BLUESKY_RESOLVE_HANDLE_URL = "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle"

# Bluesky public profile API to get display names
BLUESKY_GET_PROFILE_URL = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"

# Default duration to listen (minutes)
DEFAULT_DURATION_MINUTES = 360  # 6 hours — covers noon to 6 PM ET

# How often to flush buffered posts to GCS + BQ
FLUSH_INTERVAL_SECS = 300  # 5 minutes

# GCS bucket for scraped data
GCS_BUCKET = os.environ.get("GCS_BUCKET_RAW", "nba-scraped-data")

# BigQuery destination
BQ_PROJECT = os.environ.get("GCP_PROJECT", "nba-props-platform")
BQ_TABLE = f"{BQ_PROJECT}.nba_raw.bluesky_nba_news"

# GCS path key for the path builder
GCS_PATH_KEY = "bluesky_nba_news"

# ---------------------------------------------------------------------------
# Beat writers to monitor
# ---------------------------------------------------------------------------

BEAT_WRITERS: List[Dict[str, str]] = [
    {"handle": "chrisbhaynes.bsky.social",   "name": "Chris Haynes",     "outlet": "ESPN"},
    {"handle": "thesteinline.bsky.social",   "name": "Marc Stein",       "outlet": "Independent"},
    {"handle": "zachlowenba.bsky.social",    "name": "Zach Lowe",        "outlet": "ESPN"},
    {"handle": "samamick.bsky.social",       "name": "Sam Amick",        "outlet": "The Athletic"},
    {"handle": "jakelfischer.bsky.social",   "name": "Jake Fischer",     "outlet": "Yahoo"},
    {"handle": "anthonyvslater.bsky.social", "name": "Anthony Slater",   "outlet": "ESPN Warriors"},
    {"handle": "danwoikesports.bsky.social", "name": "Dan Woike",        "outlet": "The Athletic Lakers"},
    {"handle": "fredkatz.bsky.social",       "name": "Fred Katz",        "outlet": "The Athletic Knicks"},
    {"handle": "jonkrawczynski.bsky.social", "name": "Jon Krawczynski",  "outlet": "The Athletic Wolves"},
    {"handle": "bytimreynolds.bsky.social",  "name": "Tim Reynolds",     "outlet": "AP"},
]

# ---------------------------------------------------------------------------
# Signal keywords (case-insensitive)
# ---------------------------------------------------------------------------

SIGNAL_KEYWORDS: List[str] = [
    "questionable",
    "limited",
    "scratch",
    "GTD",
    "game-time",
    "won't play",
    "out tonight",
    "ruled out",
    "reduced minutes",
    "bounce back",
    "called out",
    "won't start",
    "coming off bench",
]

# Pre-lowercase for faster matching
_SIGNAL_KEYWORDS_LOWER = [k.lower() for k in SIGNAL_KEYWORDS]


# ---------------------------------------------------------------------------
# Handle → DID resolution
# ---------------------------------------------------------------------------

def resolve_handles(
    writers: List[Dict[str, str]],
    extra_handles: Optional[List[str]] = None,
) -> Dict[str, Dict[str, str]]:
    """
    Resolve Bluesky handles to DIDs using the public API.

    Returns a dict keyed by DID:
      {
        "did:plc:xyz": {
          "handle": "chrisbhaynes.bsky.social",
          "name": "Chris Haynes",
          "outlet": "ESPN",
        },
        ...
      }

    Falls back to the atproto Client if available; otherwise uses raw HTTP
    via urllib (no external deps required for resolution).
    """
    import urllib.request
    import urllib.error

    result: Dict[str, Dict[str, str]] = {}

    # Merge writers list with any extra handles provided via --handles CLI flag
    all_writers = list(writers)
    if extra_handles:
        for handle in extra_handles:
            handle = handle.strip()
            if handle and not any(w["handle"] == handle for w in all_writers):
                all_writers.append({"handle": handle, "name": handle, "outlet": "custom"})

    for writer in all_writers:
        handle = writer["handle"]
        url = f"{BLUESKY_RESOLVE_HANDLE_URL}?handle={handle}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            did = data.get("did")
            if did:
                result[did] = {
                    "handle": handle,
                    "name": writer.get("name", handle),
                    "outlet": writer.get("outlet", ""),
                }
                logger.info("Resolved %s → %s", handle, did)
            else:
                logger.warning("No DID in response for %s: %s", handle, data)
        except urllib.error.HTTPError as e:
            logger.warning("HTTP %d resolving handle %s: %s", e.code, handle, e.reason)
        except Exception as e:
            logger.warning("Failed to resolve handle %s: %s", handle, e)

    return result


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def find_keywords(text: str) -> List[str]:
    """Return list of signal keywords found in post text (case-insensitive)."""
    text_lower = text.lower()
    return [
        SIGNAL_KEYWORDS[i]
        for i, kw in enumerate(_SIGNAL_KEYWORDS_LOWER)
        if kw in text_lower
    ]


# ---------------------------------------------------------------------------
# GCS + BigQuery persistence
# ---------------------------------------------------------------------------

def _build_gcs_path(game_date: str) -> str:
    """Build the GCS object path for today's capture file."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if _GCS_PATH_BUILDER_AVAILABLE:
        template = GCSPathBuilder.get_path(GCS_PATH_KEY)
        try:
            return template % {"date": game_date, "timestamp": ts}
        except KeyError:
            pass
    # Fallback if path builder unavailable
    return f"external/bluesky/nba-news/{game_date}/{ts}.json"


def flush_to_gcs(posts: List[Dict], game_date: str, dry_run: bool = False) -> Optional[str]:
    """
    Write the current buffer of matching posts to a GCS JSON file.

    Returns the GCS path written, or None if dry_run / no GCS available.
    The file format mirrors other external news scrapers:
      {
        "source": "bluesky",
        "date": "2026-10-22",
        "timestamp": "...",
        "post_count": N,
        "posts": [...]
      }
    """
    if dry_run or not _GCP_AVAILABLE:
        logger.info("[DRY RUN] Would write %d posts to GCS", len(posts))
        return None

    if not posts:
        logger.debug("No posts to flush to GCS")
        return None

    ts_now = datetime.now(timezone.utc).isoformat()
    payload = {
        "source": "bluesky",
        "date": game_date,
        "timestamp": ts_now,
        "post_count": len(posts),
        "posts": posts,
    }

    gcs_path = _build_gcs_path(game_date)
    json_bytes = json.dumps(payload, indent=2).encode("utf-8")

    try:
        client = gcs.Client(project=BQ_PROJECT)
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(json_bytes, content_type="application/json")
        full_path = f"gs://{GCS_BUCKET}/{gcs_path}"
        logger.info("Flushed %d posts to GCS: %s", len(posts), full_path)
        return full_path
    except Exception as e:
        logger.error("GCS flush failed: %s", e)
        return None


def flush_to_bq(posts: List[Dict], gcs_source_path: Optional[str], dry_run: bool = False) -> int:
    """
    Stream-insert matching posts into BigQuery.

    Returns the number of rows successfully inserted.
    Uses insert_rows_json (streaming inserts) for low-latency writes.
    Posts already contain all schema fields; we just add source_file_path.
    """
    if dry_run or not _GCP_AVAILABLE:
        logger.info("[DRY RUN] Would insert %d rows into %s", len(posts), BQ_TABLE)
        return 0

    if not posts:
        return 0

    rows = []
    for post in posts:
        row = dict(post)
        row["source_file_path"] = gcs_source_path or ""
        # Ensure game_date is a string (BQ DATE expects "YYYY-MM-DD")
        if isinstance(row.get("game_date"), str):
            pass  # already correct
        rows.append(row)

    try:
        client = bigquery.Client(project=BQ_PROJECT)
        table_ref = client.get_table(BQ_TABLE)
        errors = client.insert_rows_json(table_ref, rows)
        if errors:
            logger.error("BQ insert errors: %s", errors)
            return 0
        logger.info("Inserted %d rows into %s", len(rows), BQ_TABLE)
        return len(rows)
    except Exception as e:
        logger.error("BQ insert failed: %s", e)
        return 0


# ---------------------------------------------------------------------------
# Core listener
# ---------------------------------------------------------------------------

class BlueSkyNBAListener:
    """
    Async Jetstream WebSocket listener for NBA beat writer posts.

    Lifecycle:
      1. resolve_handles() — one-time HTTP calls at startup
      2. listen() — open WebSocket, process messages until done
      3. Periodic flush every FLUSH_INTERVAL_SECS
      4. Final flush on shutdown

    Thread-safety: This class is single-threaded (asyncio). SIGTERM is caught
    in the main function and sets the shutdown event.
    """

    def __init__(
        self,
        game_date: str,
        duration_minutes: int = DEFAULT_DURATION_MINUTES,
        dry_run: bool = False,
        extra_handles: Optional[List[str]] = None,
    ):
        self.game_date = game_date
        self.duration_secs = duration_minutes * 60
        self.dry_run = dry_run
        self.extra_handles = extra_handles or []

        # DID → writer metadata (populated by resolve_handles)
        self.did_map: Dict[str, Dict[str, str]] = {}

        # Buffer of matching posts not yet flushed
        self._buffer: List[Dict] = []

        # Shutdown event — set by SIGTERM handler or duration expiry
        self._shutdown = asyncio.Event()

        # Stats
        self.stats = {
            "posts_seen": 0,
            "posts_matched": 0,
            "flushes": 0,
            "bq_rows_inserted": 0,
            "errors": 0,
            "start_time": None,
            "end_time": None,
        }

    def prepare(self) -> bool:
        """
        Resolve handles and validate dependencies.

        Returns True if we have at least one DID to subscribe to.
        """
        if not _WEBSOCKETS_AVAILABLE:
            logger.error(
                "websockets library not available. Install with: pip install websockets"
            )
            return False

        logger.info("Resolving %d beat writer handles...", len(BEAT_WRITERS))
        self.did_map = resolve_handles(BEAT_WRITERS, self.extra_handles)

        if not self.did_map:
            logger.error("No DIDs resolved — cannot subscribe. Check network connectivity.")
            return False

        logger.info(
            "Resolved %d/%d handles → DIDs: %s",
            len(self.did_map),
            len(BEAT_WRITERS) + len(self.extra_handles),
            list(self.did_map.keys()),
        )
        return True

    def _build_ws_url(self, endpoint: str) -> str:
        """
        Build the Jetstream WebSocket URL with DID and collection filters.

        Example:
          wss://jetstream1.us-east.bsky.network/subscribe
            ?wantedCollections=app.bsky.feed.post
            &wantedDids=did:plc:aaa
            &wantedDids=did:plc:bbb
        """
        params = [("wantedCollections", "app.bsky.feed.post")]
        for did in sorted(self.did_map.keys()):
            params.append(("wantedDids", did))
        return f"{endpoint}?{urlencode(params)}"

    def _parse_event(self, raw_message: str) -> Optional[Dict]:
        """
        Parse a Jetstream JSON event message.

        Returns a normalized post record if:
          - kind == "commit"
          - commit.operation == "create"
          - commit.collection == "app.bsky.feed.post"
          - post text matches at least one signal keyword

        Returns None for non-matching events.
        """
        try:
            event = json.loads(raw_message)
        except json.JSONDecodeError as e:
            logger.debug("JSON parse error: %s", e)
            return None

        # Only care about commit events
        if event.get("kind") != "commit":
            return None

        commit = event.get("commit", {})
        if commit.get("operation") != "create":
            return None
        if commit.get("collection") != "app.bsky.feed.post":
            return None

        record = commit.get("record", {})
        text = record.get("text", "")
        if not text:
            return None

        keywords = find_keywords(text)
        if not keywords:
            return None

        did = event.get("did", "")
        writer = self.did_map.get(did, {})
        rkey = commit.get("rkey", "")
        post_uri = f"at://{did}/app.bsky.feed.post/{rkey}" if did and rkey else ""

        # Parse createdAt from the post record
        created_at_raw = record.get("createdAt", "")
        created_at: Optional[str] = None
        if created_at_raw:
            try:
                # Normalise to UTC ISO (strip trailing Z, add +00:00)
                if created_at_raw.endswith("Z"):
                    created_at_raw = created_at_raw[:-1] + "+00:00"
                dt = datetime.fromisoformat(created_at_raw)
                created_at = dt.astimezone(timezone.utc).isoformat()
            except ValueError:
                created_at = created_at_raw  # store raw if parse fails

        return {
            "post_uri": post_uri,
            "game_date": self.game_date,
            "did": did,
            "handle": writer.get("handle", ""),
            "author_name": writer.get("name", ""),
            "post_text": text,
            "created_at": created_at,
            "keywords_matched": ",".join(keywords),
            "keyword_count": len(keywords),
            "rkey": rkey,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _flush(self) -> None:
        """Flush the current buffer to GCS and BQ, then clear the buffer."""
        if not self._buffer:
            return

        posts_to_flush = list(self._buffer)
        self._buffer.clear()

        logger.info("Flushing %d matched posts...", len(posts_to_flush))
        gcs_path = flush_to_gcs(posts_to_flush, self.game_date, dry_run=self.dry_run)
        rows = flush_to_bq(posts_to_flush, gcs_path, dry_run=self.dry_run)

        self.stats["flushes"] += 1
        self.stats["bq_rows_inserted"] += rows

    async def _periodic_flush(self) -> None:
        """Coroutine that flushes every FLUSH_INTERVAL_SECS until shutdown."""
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(), timeout=FLUSH_INTERVAL_SECS
                )
            except asyncio.TimeoutError:
                pass
            if self._buffer:
                await self._flush()

    async def _duration_watchdog(self) -> None:
        """Set the shutdown event after the configured duration expires."""
        await asyncio.sleep(self.duration_secs)
        logger.info(
            "Duration limit (%d minutes) reached — initiating shutdown",
            self.duration_secs // 60,
        )
        self._shutdown.set()

    async def _connect_and_listen(self, endpoint: str) -> None:
        """
        Connect to a Jetstream endpoint and stream events until shutdown.

        Handles connection drops and retries with exponential backoff.
        """
        ws_url = self._build_ws_url(endpoint)
        logger.info("Connecting to Jetstream: %s", ws_url)

        retry_delay = 5  # seconds
        max_retry_delay = 120

        while not self._shutdown.is_set():
            try:
                # websockets ≥ 12: use websockets.connect as async context manager
                async with websockets.connect(
                    ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    logger.info("WebSocket connected to %s", endpoint)
                    retry_delay = 5  # reset on successful connect

                    async for message in ws:
                        if self._shutdown.is_set():
                            break

                        self.stats["posts_seen"] += 1

                        post = self._parse_event(message)
                        if post:
                            self.stats["posts_matched"] += 1
                            self._buffer.append(post)
                            logger.info(
                                "MATCH [%s] @%s: %r (keywords: %s)",
                                post["created_at"],
                                post["handle"],
                                post["post_text"][:120],
                                post["keywords_matched"],
                            )

            except websockets.exceptions.ConnectionClosedError as e:
                if self._shutdown.is_set():
                    break
                logger.warning("WebSocket connection closed: %s — retrying in %ds", e, retry_delay)
                self.stats["errors"] += 1
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

            except websockets.exceptions.WebSocketException as e:
                if self._shutdown.is_set():
                    break
                logger.warning("WebSocket error: %s — retrying in %ds", e, retry_delay)
                self.stats["errors"] += 1
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

            except OSError as e:
                if self._shutdown.is_set():
                    break
                logger.warning("Network error: %s — retrying in %ds", e, retry_delay)
                self.stats["errors"] += 1
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def listen(self) -> Dict:
        """
        Main entry point: start the listener and run until shutdown.

        Returns the stats dict after completion.
        """
        self.stats["start_time"] = datetime.now(timezone.utc).isoformat()

        # Try endpoints in order; fall back to the next if the first fails
        endpoint = JETSTREAM_ENDPOINTS[0]
        for ep in JETSTREAM_ENDPOINTS:
            # Quick connectivity check: resolve hostname
            try:
                import socket
                host = ep.replace("wss://", "").split("/")[0]
                socket.getaddrinfo(host, 443, socket.AF_INET)
                endpoint = ep
                logger.info("Using Jetstream endpoint: %s", ep)
                break
            except socket.gaierror:
                logger.warning("Cannot resolve %s — trying next endpoint", ep)

        # Launch background tasks
        tasks = [
            asyncio.create_task(self._connect_and_listen(endpoint)),
            asyncio.create_task(self._periodic_flush()),
            asyncio.create_task(self._duration_watchdog()),
        ]

        # Wait until shutdown is signaled
        await self._shutdown.wait()
        logger.info("Shutdown signaled — cancelling WebSocket tasks...")

        for task in tasks:
            task.cancel()
        # Allow tasks to finish cleanly
        await asyncio.gather(*tasks, return_exceptions=True)

        # Final flush
        logger.info("Running final flush...")
        await self._flush()

        self.stats["end_time"] = datetime.now(timezone.utc).isoformat()
        return self.stats


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bluesky NBA News Jetstream Listener — captures beat writer injury/status posts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run for 6 hours (game-day noon-6PM window)
  python scrapers/external/bluesky_nba_news.py --date 2026-10-22 --duration 360 --group prod

  # Dev/debug run for 10 minutes (no GCS/BQ writes)
  python scrapers/external/bluesky_nba_news.py --date 2026-10-22 --duration 10 --debug

  # Custom beat writer handles (overrides built-in list)
  python scrapers/external/bluesky_nba_news.py --date 2026-10-22 \\
      --handles "chrisbhaynes.bsky.social,thesteinline.bsky.social" --duration 60
        """,
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Game date (YYYY-MM-DD, default: today)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=DEFAULT_DURATION_MINUTES,
        help=f"How long to listen (minutes, default: {DEFAULT_DURATION_MINUTES})",
    )
    parser.add_argument(
        "--group",
        default="dev",
        choices=["dev", "prod"],
        help="Export group: dev (dry run, no GCS/BQ) or prod (write to GCS + BQ)",
    )
    parser.add_argument(
        "--handles",
        default="",
        help="Comma-separated extra Bluesky handles to monitor (added to default list)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG logging",
    )

    args = parser.parse_args()

    # Logging setup
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    game_date = args.date or datetime.now(timezone.utc).strftime('%Y-%m-%d')

    dry_run = args.group != "prod"
    if dry_run:
        logger.info(
            "Running in DRY RUN mode (--group dev). "
            "Matched posts will be logged but NOT written to GCS or BQ. "
            "Use --group prod to persist data."
        )

    extra_handles = [h.strip() for h in args.handles.split(",") if h.strip()]

    listener = BlueSkyNBAListener(
        game_date=game_date,
        duration_minutes=args.duration,
        dry_run=dry_run,
        extra_handles=extra_handles,
    )

    # Setup: resolve handles
    if not listener.prepare():
        logger.error("Preparation failed — exiting")
        sys.exit(1)

    logger.info(
        "Starting Bluesky NBA News listener for %s (duration: %d min, group: %s)",
        game_date,
        args.duration,
        args.group,
    )

    # SIGTERM handler — sets shutdown event for graceful drain + final flush
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_sigterm(signum, frame):
        logger.info("SIGTERM received — initiating graceful shutdown")
        loop.call_soon_threadsafe(listener._shutdown.set)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    try:
        stats = loop.run_until_complete(listener.listen())
    finally:
        loop.close()

    # Print summary
    elapsed_secs = 0
    if stats.get("start_time") and stats.get("end_time"):
        start = datetime.fromisoformat(stats["start_time"])
        end = datetime.fromisoformat(stats["end_time"])
        elapsed_secs = int((end - start).total_seconds())

    print("\n" + "=" * 60, flush=True)
    print("Bluesky NBA News Listener — Run Summary", flush=True)
    print("=" * 60, flush=True)
    print(f"  Date:             {game_date}", flush=True)
    print(f"  Duration:         {elapsed_secs // 60}m {elapsed_secs % 60}s", flush=True)
    print(f"  Posts seen:       {stats['posts_seen']:,}", flush=True)
    print(f"  Posts matched:    {stats['posts_matched']:,}", flush=True)
    print(f"  Flushes:          {stats['flushes']}", flush=True)
    print(f"  BQ rows inserted: {stats['bq_rows_inserted']:,}", flush=True)
    print(f"  Errors:           {stats['errors']}", flush=True)
    print(f"  Dry run:          {dry_run}", flush=True)
    print("=" * 60, flush=True)

    # Exit 0 even if no matches (expected off-season / no games)
    sys.exit(0)


if __name__ == "__main__":
    main()
