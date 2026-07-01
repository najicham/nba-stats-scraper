#!/usr/bin/env python3
"""Cascade repricing — teammate props when stars are ruled out.

Surfaces teammate prop opportunities when a star player is ruled out for
tonight's game. When a star is out, their teammates often get extra
usage/minutes — the market may not fully reprice all teammate props
within 2h of tip.

Run: PYTHONPATH=. .venv/bin/python3 bin/analysis/cascade_repricing.py [--date YYYY-MM-DD]
"""

import argparse
import os
from datetime import date, datetime, timezone

from google.cloud import bigquery

PROJECT_ID = os.environ.get("BQ_PROJECT", "nba-props-platform")

# Star threshold: avg PPG in last 90 non-DNP games
STAR_PPG_THRESHOLD = 15.0
# How many recent Bluesky posts to show per star
BLUESKY_POSTS_LIMIT = 3
# Roster snapshot window (days) — find latest roster within this many days
ROSTER_WINDOW_DAYS = 90


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

INJURED_STARS_QUERY = f"""
WITH latest_report AS (
    SELECT
        player_lookup,
        team,
        injury_status,
        report_hour,
        ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY report_hour DESC
        ) AS rn
    FROM `{PROJECT_ID}.nba_raw.nbac_injury_report`
    WHERE game_date = @target_date
      AND injury_status IN ('Out', 'Doubtful', 'OUT', 'DOUBTFUL')
),
recent_avg AS (
    SELECT
        player_lookup,
        AVG(points) AS pts_avg
    FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(@target_date, INTERVAL 90 DAY)
      AND game_date < @target_date
      AND (is_dnp IS NULL OR is_dnp = FALSE)
      AND points IS NOT NULL
    GROUP BY player_lookup
)
SELECT
    r.player_lookup,
    r.team,
    r.injury_status,
    r.report_hour,
    COALESCE(a.pts_avg, 0.0) AS pts_avg
FROM latest_report r
LEFT JOIN recent_avg a USING (player_lookup)
WHERE r.rn = 1
  AND COALESCE(a.pts_avg, 0.0) >= {STAR_PPG_THRESHOLD}
ORDER BY pts_avg DESC
"""

TEAMMATE_PREDICTIONS_QUERY = f"""
WITH latest_roster AS (
    -- Get the most recent roster snapshot per player within the window
    SELECT
        player_lookup,
        team_abbr,
        roster_date,
        ROW_NUMBER() OVER (
            PARTITION BY player_lookup
            ORDER BY roster_date DESC
        ) AS rn
    FROM `{PROJECT_ID}.nba_raw.espn_team_rosters`
    WHERE roster_date >= DATE_SUB(@target_date, INTERVAL {ROSTER_WINDOW_DAYS} DAY)
      AND roster_date <= @target_date
),
roster AS (
    SELECT player_lookup, team_abbr
    FROM latest_roster
    WHERE rn = 1
),
ranked_systems AS (
    -- Pick the catboost system with the most predictions today
    SELECT
        system_id,
        COUNT(*) AS pred_count,
        ROW_NUMBER() OVER (ORDER BY COUNT(*) DESC) AS sys_rank
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = @target_date
      AND system_id LIKE 'catboost_%'
    GROUP BY system_id
),
main_system AS (
    SELECT system_id FROM ranked_systems WHERE sys_rank = 1
),
predictions AS (
    SELECT
        p.player_lookup,
        p.player_name,
        p.current_points_line AS line,
        p.recommendation,
        p.confidence_score,
        p.predicted_points,
        p.system_id,
        ABS(p.predicted_points - p.current_points_line) AS edge
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` p
    CROSS JOIN main_system ms
    WHERE p.game_date = @target_date
      AND p.system_id = ms.system_id
      AND p.current_points_line IS NOT NULL
)
SELECT
    pred.player_lookup,
    pred.player_name,
    roster.team_abbr,
    pred.line,
    pred.recommendation,
    pred.confidence_score,
    pred.predicted_points,
    pred.edge,
    pred.system_id
FROM predictions pred
JOIN roster ON roster.player_lookup = pred.player_lookup
WHERE roster.team_abbr = @team_abbr
  AND pred.player_lookup != @injured_player
ORDER BY pred.edge DESC
"""

BLUESKY_QUERY = f"""
SELECT
    handle,
    post_text,
    created_at
FROM `{PROJECT_ID}.nba_raw.bluesky_nba_news`
WHERE game_date = @target_date
  AND (
      LOWER(post_text) LIKE @name_pattern_first
      OR LOWER(post_text) LIKE @name_pattern_last
      OR LOWER(post_text) LIKE @name_pattern_full
  )
ORDER BY created_at DESC
LIMIT {BLUESKY_POSTS_LIMIT}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _player_lookup_to_tokens(player_lookup: str) -> tuple[str, str, str]:
    """Split a player_lookup into name search tokens.

    Returns (first_token, last_token, full_no_separator) — all lowercase.
    Handles both underscore-separated ('lebron_james') and
    flat ('lebronjames') formats.
    """
    parts = player_lookup.lower().replace("-", "_").split("_")
    if len(parts) >= 2:
        first = parts[0]
        last = "_".join(parts[1:])
    else:
        # Flat string — use first 4 chars as a rough first-name proxy
        s = player_lookup.lower()
        first = s[:4] if len(s) > 4 else s
        last = s[4:] if len(s) > 4 else s
    full = player_lookup.lower().replace("_", "")
    return first, last, full


def _format_time_ago(dt: datetime) -> str:
    """Return human-readable 'Xh ago' / 'Xm ago' relative to UTC now."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "just now"
    if total_seconds < 60:
        return f"{total_seconds}s ago"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m ago"
    if total_seconds < 86400:
        return f"{total_seconds // 3600}h ago"
    return f"{total_seconds // 86400}d ago"


def _display_name(player_lookup: str) -> str:
    """Convert player_lookup to a readable display name."""
    if "_" in player_lookup:
        return " ".join(p.capitalize() for p in player_lookup.split("_"))
    return player_lookup.title()


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def find_injured_stars(client: bigquery.Client, target_date: str) -> list[dict]:
    """Return star players ruled out for target_date, sorted by pts_avg desc."""
    query = INJURED_STARS_QUERY.format(
        project=PROJECT_ID,
        star_threshold=STAR_PPG_THRESHOLD,
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
        ]
    )
    rows = list(client.query(query, job_config=job_config).result())
    return [dict(r) for r in rows]


def find_teammate_predictions(
    client: bigquery.Client,
    target_date: str,
    team_abbr: str,
    injured_player: str,
) -> list[dict]:
    """Return today's predictions for active teammates of the injured player."""
    query = TEAMMATE_PREDICTIONS_QUERY.format(
        project=PROJECT_ID,
        roster_window=ROSTER_WINDOW_DAYS,
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
            bigquery.ScalarQueryParameter("team_abbr", "STRING", team_abbr),
            bigquery.ScalarQueryParameter("injured_player", "STRING", injured_player),
        ]
    )
    rows = list(client.query(query, job_config=job_config).result())
    return [dict(r) for r in rows]


def find_bluesky_posts(
    client: bigquery.Client,
    target_date: str,
    player_lookup: str,
) -> list[dict]:
    """Return recent Bluesky posts mentioning the injured player (today)."""
    first, last, full = _player_lookup_to_tokens(player_lookup)
    query = BLUESKY_QUERY.format(
        project=PROJECT_ID,
        limit=BLUESKY_POSTS_LIMIT,
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
            bigquery.ScalarQueryParameter("name_pattern_first", "STRING", f"%{first}%"),
            bigquery.ScalarQueryParameter("name_pattern_last", "STRING", f"%{last}%"),
            bigquery.ScalarQueryParameter("name_pattern_full", "STRING", f"%{full}%"),
        ]
    )
    try:
        rows = list(client.query(query, job_config=job_config).result())
        return [dict(r) for r in rows]
    except Exception as exc:
        # Table may not exist off-season — degrade gracefully
        if "Not found" in str(exc) or "does not exist" in str(exc):
            return []
        raise


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------

def print_report(
    target_date: str,
    stars: list[dict],
    teammate_map: dict[str, list[dict]],
    bluesky_map: dict[str, list[dict]],
) -> None:
    """Print the full cascade repricing report to stdout."""
    print()
    print("=" * 60)
    print(f"  CASCADE REPRICING REPORT — {target_date}")
    print("=" * 60)

    if not stars:
        print(f"\n  No star outs found for {target_date}.")
        print(f"  (Threshold: {STAR_PPG_THRESHOLD}+ PPG avg, status Out/Doubtful)\n")
        return

    print(f"  Stars ruled out: {len(stars)}  |  Threshold: {STAR_PPG_THRESHOLD}+ PPG\n")

    for star in stars:
        player_lookup = star["player_lookup"]
        team = star["team"]
        injury_status = star["injury_status"]
        report_hour = star.get("report_hour")
        pts_avg = star.get("pts_avg", 0.0)

        report_str = f"{report_hour}h before tip" if report_hour is not None else "unknown"

        print("━" * 60)
        print(
            f"  STAR OUT: {_display_name(player_lookup)} ({team})"
            f" — {injury_status.upper()}"
        )
        print(f"    Avg PPG (last 90d): {pts_avg:.1f}    Latest report: {report_str}")
        print()

        # Teammate predictions
        teammates = teammate_map.get(player_lookup, [])
        print("  TEAMMATE PROPS TO WATCH:")
        if teammates:
            for rank, tm in enumerate(teammates, start=1):
                name = tm.get("player_name") or _display_name(tm["player_lookup"])
                line = tm.get("line")
                rec = tm.get("recommendation", "N/A")
                edge = tm.get("edge")
                conf = tm.get("confidence_score")
                pred = tm.get("predicted_points")

                line_str = f"{line:.1f}" if line is not None else "N/A"
                edge_str = f"{edge:.2f}" if edge is not None else "N/A"
                conf_str = f"{conf:.3f}" if conf is not None else "N/A"
                pred_str = f"{pred:.1f}" if pred is not None else "N/A"

                print(
                    f"  {rank:>2}. {name:<28}  Line: {line_str:<6}  "
                    f"{rec:<6}  Edge: {edge_str:<6}  Conf: {conf_str}  "
                    f"(pred {pred_str})"
                )
        else:
            print("       (none found for today)")

        # Bluesky context
        print()
        posts = bluesky_map.get(player_lookup, [])
        print("  BLUESKY CONTEXT:")
        if posts:
            for post in posts:
                handle = post.get("handle", "unknown")
                created_at = post.get("created_at")
                post_text = post.get("post_text", "")
                truncated = (
                    post_text[:120] + "..." if len(post_text) > 120 else post_text
                )
                time_str = _format_time_ago(created_at) if created_at else ""
                print(f"  @{handle} [{time_str}]: {truncated}")
        else:
            print(
                "       (no posts found — Bluesky listener may be off-season"
                " or no mentions today)"
            )

        print()

    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Cascade repricing — surface teammate props when stars are ruled out."
        )
    )
    parser.add_argument(
        "--date",
        default=str(date.today()),
        help="Target game date (YYYY-MM-DD). Defaults to today.",
    )
    args = parser.parse_args()
    target_date = args.date

    client = bigquery.Client(project=PROJECT_ID)

    # Step 1 — Find today's injured stars
    print(f"[1/3] Querying injury report for {target_date}...")
    stars = find_injured_stars(client, target_date)
    print(f"      Found {len(stars)} star(s) ruled out (>= {STAR_PPG_THRESHOLD} PPG).")

    if not stars:
        print_report(target_date, stars, {}, {})
        return

    # Step 2 — Find teammate predictions for each star's team
    print("[2/3] Querying teammate predictions...")
    teammate_map: dict[str, list[dict]] = {}
    for star in stars:
        player_lookup = star["player_lookup"]
        team = star["team"]
        preds = find_teammate_predictions(client, target_date, team, player_lookup)
        teammate_map[player_lookup] = preds
        print(
            f"      {_display_name(player_lookup)} ({team}): "
            f"{len(preds)} teammate prediction(s)."
        )

    # Step 3 — Bluesky context for each star
    print("[3/3] Querying Bluesky posts...")
    bluesky_map: dict[str, list[dict]] = {}
    for star in stars:
        player_lookup = star["player_lookup"]
        posts = find_bluesky_posts(client, target_date, player_lookup)
        bluesky_map[player_lookup] = posts
        print(f"      {_display_name(player_lookup)}: {len(posts)} post(s).")

    # Step 4 — Print report
    print_report(target_date, stars, teammate_map, bluesky_map)


if __name__ == "__main__":
    main()
