#!/usr/bin/env python3
"""Find Pub/Sub topics that in-repo code publishes to but nothing subscribes to.

Why
---
Publishing to a topic with no subscription SUCCEEDS. `publisher.publish()`
returns a message id, the caller logs "triggered", and the message is discarded.
Every symptom points downstream, so the diagnosis costs days.

This has now happened three times on this project:

  * 2026-09-02 — a 31-day Pub/Sub TTL deleted the Phase 5 dispatch subscription
    off-season. Predictions "dispatched" into nothing.
  * 2026-09-07 — `prediction-ready-prod` had ZERO subscribers, so batch
    completion never fired, `BatchConsolidator` never ran, and
    `player_prop_predictions` gained no rows at all. The worst defect of the
    off-season; found by a two-line `comm`.
  * 2026-09-08 — `nba-phase3-trigger` (orphaned by the Phase 2 -> 3 migration)
    was still the target of three BDB operator tools and the auto-backfill
    orchestrator, all of which reported success.

Usage
-----
    PYTHONPATH=. python bin/validation/validate_pubsub_topology.py
    PYTHONPATH=. python bin/validation/validate_pubsub_topology.py --json

Exit codes: 0 = every published topic has a subscriber (or is explicitly
allow-listed); 1 = at least one dead publish target; 2 = could not query GCP.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that describe history or scratch work rather than running code.
SKIP_DIRS = {
    '.git', '.claude', 'docs', 'node_modules', '__pycache__', '.venv', 'venv',
    'ops',  # scheduler/catalog snapshots, not executable
}
CODE_SUFFIXES = {'.py', '.sh', '.yaml', '.yml'}

# Topics that are legitimately subscriber-less. Add with a reason, never bare.
ALLOWED_WITHOUT_SUBSCRIBER: Dict[str, str] = {
    # Dead-letter topics are written by Pub/Sub itself. They still deserve a
    # consumer or an alert, but a missing subscription is not a broken publish.
    'nba-phase1-scrapers-complete-dlq': 'dead-letter sink',
    'nba-phase2-raw-complete-dlq': 'dead-letter sink',
    'nba-phase3-analytics-complete-dlq': 'dead-letter sink',
    'nba-phase4-precompute-complete-dlq': 'dead-letter sink',
    'nba-backfill-trigger-dlq': 'dead-letter sink',
    'mlb-phase1-scrapers-complete-dlq': 'dead-letter sink',
    'mlb-phase2-raw-complete-dlq': 'dead-letter sink',
}

# `publisher.publish(topic_path, ...)` hides the topic name behind a variable,
# so rather than trying to parse the call, look for each LIVE topic name as a
# literal anywhere in the file. Exact names from GCP means no guessing at naming
# conventions and no false positives from invented patterns; the trailing
# boundary check stops `nba-phase2-raw-complete` matching inside
# `nba-phase2-raw-complete-dlq`.
# A topic name only counts when it appears as (part of) a string literal —
# `'nba-phase3-trigger'` or `.../topics/nba-phase3-trigger'` — not when it is
# named in prose or a comment. Without this, every docstring explaining a dead
# topic re-reports it and the exit code stops meaning anything.
QUOTE_CHARS = "'\"/`"
NAME_BOUNDARY = re.compile(r'[A-Za-z0-9_-]')


def _mentions_topic(text: str, name: str) -> bool:
    start = 0
    while True:
        i = text.find(name, start)
        if i == -1:
            return False
        end = i + len(name)
        before = text[i - 1] if i > 0 else ''
        after = text[end] if end < len(text) else ''
        delimited = (
            not NAME_BOUNDARY.match(before or ' ')
            and not NAME_BOUNDARY.match(after or ' ')
        )
        quoted = before in "'\"/" and after in "'\""
        if delimited and quoted:
            return True
        start = end


def gcloud(args: List[str]) -> List[str]:
    out = subprocess.run(
        ['gcloud'] + args + ['--project', PROJECT_ID, '--format', 'value(name)'],
        capture_output=True, text=True, timeout=180,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or 'gcloud failed')
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def live_topics_and_subscribed() -> (Set[str], Set[str]):
    topics = {t.rsplit('/', 1)[-1] for t in gcloud(['pubsub', 'topics', 'list'])}
    subbed = set()
    out = subprocess.run(
        ['gcloud', 'pubsub', 'subscriptions', 'list', '--project', PROJECT_ID,
         '--format', 'value(topic)'],
        capture_output=True, text=True, timeout=180,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or 'gcloud failed')
    for line in out.stdout.splitlines():
        line = line.strip()
        if line:
            subbed.add(line.rsplit('/', 1)[-1])
    return topics, subbed


# A file that merely *names* a topic (a create-topics script, a docstring, this
# validator) is not a bug. Only a file that actually publishes is.
PY_PUBLISH = re.compile(r'\.publish\s*\(|publish_message|PublisherClient')
SH_PUBLISH = re.compile(r'pubsub\s+topics\s+publish')


def _is_publisher(path: Path, text: str) -> bool:
    if path.suffix == '.py':
        return bool(PY_PUBLISH.search(text))
    if path.suffix == '.sh':
        return bool(SH_PUBLISH.search(text))
    return False


def repo_publish_targets(topics: Set[str]):
    """Return (publishers, mentions), each mapping topic name -> repo files.

    `publishers` is the part that matters: code that would hand a message to a
    topic nothing reads. `mentions` is context — topic-creation scripts, model
    docstrings, this file.
    """
    publishers: Dict[str, List[str]] = {}
    mentions: Dict[str, List[str]] = {}
    self_rel = str(Path(__file__).resolve().relative_to(REPO_ROOT))

    for path in REPO_ROOT.rglob('*'):
        if not path.is_file() or path.suffix not in CODE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = str(path.relative_to(REPO_ROOT))
        if rel == self_rel:
            continue
        # Cloud Functions vendor a copy of shared/ at deploy time; the original
        # under shared/ is the one to report.
        if '/shared/' in rel and rel.startswith('orchestration/cloud_functions/'):
            continue
        try:
            text = path.read_text(errors='ignore')
        except OSError:
            continue

        bucket = publishers if _is_publisher(path, text) else mentions
        for name in topics:
            if _mentions_topic(text, name):
                bucket.setdefault(name, [])
                if rel not in bucket[name]:
                    bucket[name].append(rel)
    return publishers, mentions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='machine-readable output')
    args = parser.parse_args()

    try:
        topics, subscribed = live_topics_and_subscribed()
    except Exception as e:
        print(f"ERROR: could not query Pub/Sub in {PROJECT_ID}: {e}", file=sys.stderr)
        return 2

    publishers, mentions = repo_publish_targets(topics)
    referenced = {**mentions, **publishers}

    dead = {
        name: files
        for name, files in sorted(publishers.items())
        if name not in subscribed and name not in ALLOWED_WITHOUT_SUBSCRIBER
    }
    allowed_dead = sorted(
        name for name in topics
        if name not in subscribed and name in ALLOWED_WITHOUT_SUBSCRIBER
    )
    orphan_topics = sorted(
        name for name in topics
        if name not in subscribed
        and name not in referenced
        and name not in ALLOWED_WITHOUT_SUBSCRIBER
    )

    if args.json:
        print(json.dumps({
            'project': PROJECT_ID,
            'topics': len(topics),
            'dead_publish_targets': dead,
            'allowed_without_subscriber': allowed_dead,
            'unreferenced_subscriberless_topics': orphan_topics,
        }, indent=2))
        return 1 if dead else 0

    print(f"Pub/Sub topology — {PROJECT_ID}")
    print(f"  {len(topics)} topics, {len(subscribed)} with at least one subscription")
    print()

    if dead:
        print(f"DEAD PUBLISH TARGETS ({len(dead)}) — code publishes here, nothing reads:")
        for name, files in dead.items():
            print(f"  {name}")
            for f in files:
                print(f"      {f}")
        print()
    else:
        print("No dead publish targets. Every topic referenced by repo code has a subscriber.")
        print()

    if orphan_topics:
        print(f"Subscriber-less topics with no in-repo reference ({len(orphan_topics)}) —")
        print("  candidates for deletion, not necessarily bugs:")
        for name in orphan_topics:
            print(f"  {name}")
        print()

    if allowed_dead:
        print("Allow-listed without a subscriber:")
        for name in allowed_dead:
            print(f"  {name}  ({ALLOWED_WITHOUT_SUBSCRIBER[name]})")

    return 1 if dead else 0


if __name__ == '__main__':
    sys.exit(main())
