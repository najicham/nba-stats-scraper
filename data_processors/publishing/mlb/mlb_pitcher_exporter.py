#!/usr/bin/env python3
"""
File: data_processors/publishing/mlb/mlb_pitcher_exporter.py

MLB Pitcher Exporter

Exports two JSON products powering the pitcher UI. Both surfaces are
intentionally prediction-free — they show only factual information (matchups,
betting lines, season stats, recent results). No model predictions are emitted.

  1. gs://nba-props-platform-api/v1/mlb/pitchers/leaderboard.json
     - Tonight's starters sorted chronologically by game time
     - Curated leaderboards (Hot Hands, Strikeout Kings, Line Beaters)

  2. gs://nba-props-platform-api/v1/mlb/pitchers/{pitcher_lookup}.json
     - Per-pitcher profile: tonight card, season stats, last-20 game log

Data sources:
  - mlb_predictions.pitcher_strikeouts  (factual K line + matchup info only)
  - mlb_analytics.pitcher_game_summary  (per-start pitcher stats)
  - mlb_analytics.pitcher_pitch_arsenal_latest  (pitch mix, last 5 starts)
  - mlb_analytics.pitcher_pitch_arsenal_season  (pitch mix, full season)
  - mlb_analytics.pitcher_advanced_arsenal_latest  (putaway / velo fade / concentration)
  - mlb_analytics.pitcher_expected_arsenal_latest  (expected vs actual whiff by arsenal)

Usage:
    exporter = MlbPitcherExporter()
    result = exporter.export(game_date='2026-04-13')  # writes leaderboard + all profiles
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set

from data_processors.publishing.base_exporter import BaseExporter
from data_processors.publishing.exporter_utils import (
    CACHE_MEDIUM,
    CACHE_LONG,
    safe_float,
    safe_int,
    resolve_player_name as _resolve_pitcher_name,
)

logger = logging.getLogger(__name__)

# Active-window start for game-log / season aggregation. Covers 2025 (full)
# and 2026 (current).
TRACK_RECORD_START = '2025-01-01'

# How many rows to include in each curated leaderboard
LEADERBOARD_SIZE = 20

# Game log depth on profile pages
GAME_LOG_DEPTH = 20


class MlbPitcherExporter(BaseExporter):
    """Exports pitcher leaderboard + per-pitcher profile JSONs to GCS."""

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def generate_json(self, **kwargs) -> Dict[str, Any]:
        """Satisfy BaseExporter abstract method. Returns leaderboard payload.

        Per-pitcher profiles are written as side effects of export() since
        they aren't a single JSON doc.
        """
        game_date = kwargs.get('game_date') or date.today().isoformat()
        bundle = self._build_bundle(game_date)
        return bundle['leaderboard']

    def export(
        self,
        game_date: Optional[str] = None,
        dry_run: bool = False,
        history_only: bool = False,
    ) -> Dict[str, Any]:
        """Generate + upload leaderboard and all pitcher profiles.

        Args:
            game_date: Target date (YYYY-MM-DD). Defaults to today.
            dry_run: If True, return payloads without uploading.
            history_only: If True, only write the frozen history/{game_date}.json
                sidecar. Skip the live leaderboard.json and per-pitcher profile
                uploads. Used by the history backfill job to fill past dates
                without clobbering live content.

        Returns:
            Dict with 'leaderboard_path' (or None when history_only),
            'history_path', and 'profile_paths' (empty list when history_only).
        """
        game_date = game_date or date.today().isoformat()
        logger.info(
            f"Generating MLB pitcher exports for {game_date}"
            + (" (history-only)" if history_only else "")
        )

        bundle = self._build_bundle(game_date, history_only=history_only)

        if dry_run:
            return {
                'game_date': game_date,
                'leaderboard': bundle['leaderboard'],
                'profile_count': len(bundle['profiles']),
                'sample_profile': next(iter(bundle['profiles'].values()), None),
            }

        leaderboard_path: Optional[str] = None
        starters_count = bundle['leaderboard'].get('tonight', {}).get('count', 0)
        if not history_only:
            # Don't overwrite a populated leaderboard.json with an empty one. The
            # morning exporter run (3:45 AM PDT) fires before mlb-predictions-generate
            # (10 AM PDT) — without this guard, the page goes empty for ~7 hours
            # daily while yesterday's data is destroyed. Frontend keeps last good
            # leaderboard until fresh predictions land.
            if starters_count == 0:
                logger.info(
                    f"Skipping live leaderboard.json upload for {game_date} — "
                    "0 tonight starters (preserving prior payload)"
                )
            else:
                leaderboard_path = self.upload_to_gcs(
                    bundle['leaderboard'],
                    'mlb/pitchers/leaderboard.json',
                    cache_control=CACHE_MEDIUM,
                )

        # Date-keyed history copy so the date selector can show past days.
        # Frozen once written — past dates never change.
        history_path = self.upload_to_gcs(
            bundle['leaderboard'],
            f'mlb/pitchers/history/{game_date}.json',
            cache_control=CACHE_LONG,
        )

        profile_paths: List[str] = []
        if not history_only:
            for pitcher_lookup, profile in bundle['profiles'].items():
                path = self.upload_to_gcs(
                    profile,
                    f'mlb/pitchers/{pitcher_lookup}.json',
                    cache_control=CACHE_MEDIUM,
                )
                profile_paths.append(path)

        if history_only:
            logger.info(f"Exported history sidecar for {game_date}")
        else:
            logger.info(
                f"Exported leaderboard + {len(profile_paths)} pitcher profiles"
            )
        return {
            'leaderboard_path': leaderboard_path,
            'history_path': history_path,
            'profile_paths': profile_paths,
        }

    # ------------------------------------------------------------------
    # Bundle assembly
    # ------------------------------------------------------------------

    def _build_bundle(self, game_date: str, history_only: bool = False) -> Dict[str, Any]:
        """Fetch all data once and assemble both outputs.

        When `history_only=True`, skip the four `_latest` arsenal queries and
        the per-pitcher profile assembly — only the leaderboard is needed for
        the history sidecar. This avoids a multi-minute scan against
        `mlb_game_feed_pitches` (`_fetch_strikeout_zones`) which has no
        partition pruning on the 45-day rolling window filter.
        """
        tonight = self._fetch_tonight_predictions(game_date)
        opponent_k_defense = self._fetch_opponent_k_defense(game_date)
        season_aggs = self._fetch_season_aggregates(season_year=self._infer_season_year(game_date))
        game_logs = self._fetch_game_logs()

        # Union of pitchers we care about: anyone pitching tonight, or who has
        # any game history in the current active window.
        all_pitcher_keys: Set[str] = set(season_aggs.keys())
        all_pitcher_keys.update(game_logs.keys())
        all_pitcher_keys.update(p['pitcher_lookup'] for p in tonight)

        if history_only:
            pitch_arsenals: Dict[str, List[Dict[str, Any]]] = {}
            pitch_arsenals_season: Dict[str, List[Dict[str, Any]]] = {}
            advanced_arsenals: Dict[str, Dict[str, Any]] = {}
            expected_arsenals: Dict[str, Dict[str, Any]] = {}
            strikeout_zones: Dict[str, Dict[str, Any]] = {}
        else:
            pitch_arsenals = self._fetch_pitch_arsenal(list(all_pitcher_keys))
            pitch_arsenals_season = self._fetch_pitch_arsenal_season(
                list(all_pitcher_keys), self._infer_season_year(game_date)
            )
            advanced_arsenals = self._fetch_advanced_arsenal(list(all_pitcher_keys))
            expected_arsenals = self._fetch_expected_arsenal(list(all_pitcher_keys))
            strikeout_zones = self._fetch_strikeout_zones(list(all_pitcher_keys))

        # Build display-name map (prefer tonight name, then season_agg)
        names = self._build_name_map(tonight, season_aggs)

        leaderboard = self._build_leaderboard(
            game_date=game_date,
            tonight=tonight,
            season_aggs=season_aggs,
            game_logs=game_logs,
            names=names,
        )

        profiles: Dict[str, Dict] = {}
        if not history_only:
            for pitcher_lookup in all_pitcher_keys:
                if not pitcher_lookup:
                    continue
                profile = self._build_profile(
                    pitcher_lookup=pitcher_lookup,
                    name=names.get(pitcher_lookup, pitcher_lookup.replace('_', ' ').title()),
                    tonight=next((p for p in tonight if p['pitcher_lookup'] == pitcher_lookup), None),
                    season_agg=season_aggs.get(pitcher_lookup),
                    game_log=game_logs.get(pitcher_lookup, []),
                    pitch_arsenal=pitch_arsenals.get(pitcher_lookup, []),
                    pitch_arsenal_season=pitch_arsenals_season.get(pitcher_lookup, []),
                    advanced_arsenal=advanced_arsenals.get(pitcher_lookup),
                    expected_arsenal=expected_arsenals.get(pitcher_lookup),
                    opponent_k_defense=opponent_k_defense.get(pitcher_lookup),
                    strikeout_zones=strikeout_zones.get(pitcher_lookup),
                )
                profiles[pitcher_lookup] = profile

        return {'leaderboard': leaderboard, 'profiles': profiles}

    def _infer_season_year(self, game_date: str) -> int:
        return int(game_date[:4])

    def _build_name_map(
        self,
        tonight: List[Dict],
        season_aggs: Dict[str, Dict],
    ) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for row in tonight:
            if row.get('pitcher_name'):
                out[row['pitcher_lookup']] = row['pitcher_name']
        for pl, rec in season_aggs.items():
            if pl not in out and rec.get('pitcher_name'):
                out[pl] = rec['pitcher_name']
        return out

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _fetch_tonight_predictions(self, game_date: str) -> List[Dict[str, Any]]:
        """Factual slate info for the target date, deduped to one row per pitcher.

        The Tonight page is intentionally prediction-free: this returns only
        factual fields (matchup, line, game time). JOINs `mlb_schedule` for
        `game_time_utc` so the leaderboard can be sorted chronologically.
        """
        query = f"""
        WITH preds AS (
            SELECT
                pitcher_lookup,
                pitcher_name,
                team_abbr AS team,
                opponent_team_abbr AS opponent,
                is_home,
                strikeouts_line,
                CAST(game_date AS STRING) AS game_date,
                game_date AS _gd
            FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
            WHERE game_date = '{game_date}'
              AND recommendation IN ('OVER', 'UNDER', 'PASS')
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY pitcher_lookup
                ORDER BY ABS(IFNULL(edge, 0)) DESC, processed_at DESC
            ) = 1
        )
        SELECT
            p.pitcher_lookup, p.pitcher_name, p.team, p.opponent, p.is_home,
            p.strikeouts_line, p.game_date,
            CAST(s.game_time_utc AS STRING) AS game_time_utc
        FROM preds p
        LEFT JOIN `{self.project_id}.mlb_raw.mlb_schedule` s
          ON s.game_date = p._gd
         AND (
              s.home_probable_pitcher_name = p.pitcher_name
           OR s.away_probable_pitcher_name = p.pitcher_name
         )
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY p.pitcher_lookup ORDER BY s.game_time_utc
        ) = 1
        """
        return self.query_to_list(query)

    def _fetch_strikeout_zones(
        self, pitcher_lookups: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Aggregate K-pitch zone distribution per pitcher over last 5 starts.

        Source table uses MLB zone codes (1-14):
          - 1-9: in-zone 3x3 grid (1=top-left ... 9=bottom-right)
          - 11-14: out-of-zone corners (11=up-left, 12=up-right, 13=low-left, 14=low-right)

        Returns per-pitcher:
          {
            starts_sampled: int,
            total_ks: int,
            zones: [{zone: int, count: int, top_pitch: str, top_pitch_count: int}, ...],
            last_seen_date: str,
          }

        Only pitches that end a strikeout at-bat are counted.
        """
        if not pitcher_lookups:
            return {}

        # mlb_game_feed_pitches uses no-underscore lookups (e.g. 'landenroupp')
        # while callers pass underscore lookups (e.g. 'landen_roupp'). Normalize
        # the query side and translate results back — same pattern as
        # _fetch_pitch_arsenal / _fetch_advanced_arsenal.
        lookup_map = {pl.replace('_', ''): pl for pl in pitcher_lookups if pl}
        cleaned = list(lookup_map.keys())
        if not cleaned:
            return {}

        quoted = ', '.join(f"'{pl}'" for pl in cleaned)

        query = f"""
        WITH recent_starts AS (
          -- Last 5 start dates per pitcher
          SELECT
            pitcher_lookup,
            game_date
          FROM `{self.project_id}.mlb_raw.mlb_game_feed_pitches`
          WHERE pitcher_lookup IN ({quoted})
            AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 45 DAY)
          GROUP BY pitcher_lookup, game_date
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY pitcher_lookup ORDER BY game_date DESC
          ) <= 5
        ),
        k_pitches AS (
          SELECT
            p.pitcher_lookup,
            p.game_date,
            p.zone,
            p.pitch_type_code
          FROM `{self.project_id}.mlb_raw.mlb_game_feed_pitches` p
          INNER JOIN recent_starts r
            ON p.pitcher_lookup = r.pitcher_lookup
           AND p.game_date = r.game_date
          WHERE p.at_bat_event = 'Strikeout'
            AND p.is_at_bat_end = TRUE
            AND p.zone IS NOT NULL
        ),
        zone_agg AS (
          SELECT
            pitcher_lookup,
            zone,
            pitch_type_code,
            COUNT(*) AS pitches
          FROM k_pitches
          GROUP BY pitcher_lookup, zone, pitch_type_code
        ),
        zone_totals AS (
          SELECT
            pitcher_lookup,
            zone,
            SUM(pitches) AS count,
            ARRAY_AGG(
              STRUCT(pitch_type_code, pitches AS count)
              ORDER BY pitches DESC LIMIT 1
            )[OFFSET(0)] AS top_pitch_row
          FROM zone_agg
          GROUP BY pitcher_lookup, zone
        )
        SELECT
          zt.pitcher_lookup,
          zt.zone,
          zt.count,
          zt.top_pitch_row.pitch_type_code AS top_pitch,
          zt.top_pitch_row.count AS top_pitch_count,
          (SELECT COUNT(DISTINCT game_date)
             FROM recent_starts rs
            WHERE rs.pitcher_lookup = zt.pitcher_lookup) AS starts_sampled,
          (SELECT MAX(game_date)
             FROM recent_starts rs
            WHERE rs.pitcher_lookup = zt.pitcher_lookup) AS last_seen_date
        FROM zone_totals zt
        """
        rows = self.query_to_list(query)
        out: Dict[str, Dict] = {}
        for r in rows:
            # Translate the no-underscore feed lookup back to the caller's key.
            pl = lookup_map.get(r['pitcher_lookup'], r['pitcher_lookup'])
            if pl not in out:
                out[pl] = {
                    'starts_sampled': safe_int(r.get('starts_sampled'), default=0),
                    'last_seen_date': str(r['last_seen_date']) if r.get('last_seen_date') else None,
                    'zones': [],
                }
            out[pl]['zones'].append({
                'zone': safe_int(r.get('zone')),
                'count': safe_int(r.get('count'), default=0),
                'top_pitch': r.get('top_pitch'),
                'top_pitch_count': safe_int(r.get('top_pitch_count'), default=0),
            })
        # Compute total_ks per pitcher
        for pl, data in out.items():
            data['total_ks'] = sum(z['count'] or 0 for z in data['zones'])
        return out

    def _fetch_opponent_k_defense(self, game_date: str) -> Dict[str, Dict[str, Any]]:
        """Opponent team K-rate and season rank for tonight's pitchers.

        Returns:
            Dict[pitcher_lookup -> {k_rate: 0.243, rank: 8, rank_of: 30}]

        Rank is computed across all MLB teams for the current season. Higher
        K rate = higher rank (rank 1 = strikes out the most).

        The pitcher -> opponent mapping for the target date is sourced from
        `pitcher_strikeouts` (the predictions table), NOT `pitcher_game_summary`:
        the summary table only holds COMPLETED games, so for a same-day export
        it has no rows for tonight and the join would yield nothing.
        """
        season_year = self._infer_season_year(game_date)
        query = f"""
        WITH tonight_pitchers AS (
          -- pitcher_strikeouts carries one row per (pitcher, model) for the
          -- date; DISTINCT collapses to one opponent per pitcher.
          SELECT DISTINCT
            pitcher_lookup,
            opponent_team_abbr
          FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
          WHERE game_date = '{game_date}'
            AND opponent_team_abbr IS NOT NULL
        ),
        season_team_k AS (
          -- Aggregate season-level K rate per team from batter game summaries
          SELECT
            team_abbr,
            SAFE_DIVIDE(SUM(strikeouts), SUM(at_bats)) AS season_k_rate
          FROM `{self.project_id}.mlb_analytics.batter_game_summary`
          WHERE season_year = {season_year}
            AND at_bats > 0
          GROUP BY team_abbr
          HAVING SUM(at_bats) >= 100  -- filter noise from early-season / call-ups
        ),
        ranked AS (
          SELECT
            team_abbr,
            season_k_rate,
            RANK() OVER (ORDER BY season_k_rate DESC) AS k_rank,
            COUNT(*) OVER () AS k_rank_of
          FROM season_team_k
        )
        SELECT
          t.pitcher_lookup,
          t.opponent_team_abbr,
          r.season_k_rate AS k_rate,
          r.k_rank,
          r.k_rank_of
        FROM tonight_pitchers t
        LEFT JOIN ranked r ON r.team_abbr = t.opponent_team_abbr
        """
        rows = self.query_to_list(query)
        out: Dict[str, Dict] = {}
        for r in rows:
            if not r.get('pitcher_lookup'):
                continue
            out[r['pitcher_lookup']] = {
                'opponent': r.get('opponent_team_abbr'),
                'k_rate': safe_float(r.get('k_rate'), precision=3),
                'k_rank': safe_int(r.get('k_rank')),
                'k_rank_of': safe_int(r.get('k_rank_of')),
            }
        return out

    def _fetch_season_aggregates(self, season_year: int) -> Dict[str, Dict[str, Any]]:
        """Current-season pitcher aggregates from pitcher_game_summary."""
        query = f"""
        SELECT
            player_lookup AS pitcher_lookup,
            ANY_VALUE(player_full_name) AS pitcher_name,
            ANY_VALUE(team_abbr) AS team,
            COUNT(*) AS games_started,
            SUM(strikeouts) AS season_k,
            SUM(innings_pitched) AS season_ip,
            SAFE_DIVIDE(SUM(strikeouts) * 9.0, SUM(innings_pitched)) AS k_per_9,
            SAFE_DIVIDE(SUM(earned_runs) * 9.0, SUM(innings_pitched)) AS era,
            SAFE_DIVIDE(SUM(walks_allowed) + SUM(hits_allowed), SUM(innings_pitched)) AS whip,
            COUNTIF(quality_start) AS quality_starts,
            ANY_VALUE(season_k_per_9) AS latest_season_k_per_9,
            ANY_VALUE(season_era) AS latest_season_era,
            ANY_VALUE(season_whip) AS latest_season_whip
        FROM `{self.project_id}.mlb_analytics.pitcher_game_summary`
        WHERE game_date >= DATE('{season_year}-01-01')
          AND game_date <= DATE('{season_year}-12-31')
          AND season_year = {season_year}
          AND game_status IN ('Final', 'F')
        GROUP BY player_lookup
        """
        rows = self.query_to_list(query)
        out: Dict[str, Dict] = {}
        for r in rows:
            out[r['pitcher_lookup']] = {
                'pitcher_name': r.get('pitcher_name'),
                'team': r.get('team'),
                'games_started': safe_int(r.get('games_started'), default=0),
                'season_k': safe_int(r.get('season_k'), default=0),
                'season_ip': safe_float(r.get('season_ip'), default=0.0, precision=1),
                'k_per_9': safe_float(r.get('k_per_9') or r.get('latest_season_k_per_9'), precision=2),
                'era': safe_float(r.get('era') or r.get('latest_season_era'), precision=2),
                'whip': safe_float(r.get('whip') or r.get('latest_season_whip'), precision=2),
                'quality_starts': safe_int(r.get('quality_starts'), default=0),
            }
        return out

    def _fetch_game_logs(self) -> Dict[str, List[Dict[str, Any]]]:
        """Last N starts per pitcher with factual stats and the K line.

        over_under_result is computed inline from strikeouts vs line since the
        source column in pitcher_game_summary is unpopulated. The Tonight and
        Trends surfaces are prediction-free — no model fields are emitted.
        """
        query = f"""
        WITH recent AS (
          SELECT
            pgs.player_lookup AS pitcher_lookup,
            pgs.game_date,
            pgs.opponent_team_abbr AS opponent,
            pgs.is_home,
            pgs.strikeouts,
            pgs.innings_pitched,
            pgs.walks_allowed,
            pgs.earned_runs,
            pgs.pitch_count,
            ROW_NUMBER() OVER (
              PARTITION BY pgs.player_lookup
              ORDER BY pgs.game_date DESC
            ) AS rn
          FROM `{self.project_id}.mlb_analytics.pitcher_game_summary` pgs
          WHERE pgs.game_date >= '{TRACK_RECORD_START}'
            AND pgs.game_status IN ('Final', 'F')
        ),
        preds AS (
          SELECT
            pitcher_lookup,
            game_date,
            strikeouts_line
          FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
          WHERE game_date >= '{TRACK_RECORD_START}'
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY pitcher_lookup, game_date
            ORDER BY ABS(IFNULL(edge, 0)) DESC, processed_at DESC
          ) = 1
        )
        SELECT
          r.pitcher_lookup,
          r.game_date,
          r.opponent,
          r.is_home,
          r.strikeouts,
          r.innings_pitched,
          r.walks_allowed,
          r.earned_runs,
          r.pitch_count,
          p.strikeouts_line,
          CASE
            WHEN p.strikeouts_line IS NULL OR r.strikeouts IS NULL THEN NULL
            WHEN r.strikeouts > p.strikeouts_line THEN 'OVER'
            WHEN r.strikeouts < p.strikeouts_line THEN 'UNDER'
            ELSE 'PUSH'
          END AS over_under_result
        FROM recent r
        LEFT JOIN preds p
          ON r.pitcher_lookup = p.pitcher_lookup
          AND r.game_date = p.game_date
        WHERE r.rn <= {GAME_LOG_DEPTH}
        ORDER BY r.pitcher_lookup, r.game_date DESC
        """
        rows = self.query_to_list(query)
        out: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            entry = {
                'game_date': str(r['game_date']),
                'opponent': r.get('opponent'),
                'is_home': bool(r.get('is_home')) if r.get('is_home') is not None else None,
                'strikeouts': safe_int(r.get('strikeouts')),
                'innings_pitched': safe_float(r.get('innings_pitched'), precision=1),
                'walks_allowed': safe_int(r.get('walks_allowed')),
                'earned_runs': safe_int(r.get('earned_runs')),
                'pitch_count': safe_int(r.get('pitch_count')),
                'strikeouts_line': safe_float(r.get('strikeouts_line'), precision=1),
                'over_under_result': r.get('over_under_result'),
            }
            out[r['pitcher_lookup']].append(entry)
        return dict(out)

    def _fetch_pitch_arsenal(self, pitcher_lookups: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Pitch type breakdown for a set of pitchers from Statcast data (last 5 starts).

        Returns Dict[pitcher_lookup -> list of pitch type rows, sorted by usage_pct DESC].

        Note: statcast_pitcher_daily uses no-underscore lookups (e.g. 'seanmanaea')
        while pitcher_game_summary uses underscore lookups (e.g. 'sean_manaea').
        We normalize both sides to match them correctly.
        """
        if not pitcher_lookups:
            return {}

        # Build a map from no-underscore → original-with-underscores
        # so we can translate query results back to the caller's key format
        lookup_map = {pl.replace('_', ''): pl for pl in pitcher_lookups if pl}
        cleaned = list(lookup_map.keys())

        quoted = ', '.join(f"'{pl}'" for pl in cleaned)
        query = f"""
        SELECT
            player_lookup AS pitcher_lookup_statcast,
            pitch_type_code,
            pitch_type_desc,
            usage_pct,
            whiff_rate,
            avg_velocity,
            starts_sampled,
            CAST(last_seen_date AS STRING) AS last_seen_date
        FROM `{self.project_id}.mlb_analytics.pitcher_pitch_arsenal_latest`
        WHERE player_lookup IN ({quoted})
        ORDER BY player_lookup, usage_pct DESC
        """
        rows = self.query_to_list(query)
        out: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            # Translate statcast lookup back to the original key format
            statcast_key = r['pitcher_lookup_statcast']
            original_key = lookup_map.get(statcast_key, statcast_key)
            out[original_key].append({
                'pitch_type': r['pitch_type_code'],
                'pitch_type_desc': r.get('pitch_type_desc') or r['pitch_type_code'],
                'usage_pct': safe_float(r.get('usage_pct'), precision=1),
                'whiff_rate': safe_float(r.get('whiff_rate'), precision=1),
                'avg_velocity': safe_float(r.get('avg_velocity'), precision=1),
                'starts_sampled': safe_int(r.get('starts_sampled'), default=0),
                'last_seen_date': r.get('last_seen_date'),
            })
        return dict(out)

    def _fetch_pitch_arsenal_season(
        self, pitcher_lookups: List[str], season_year: int
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Full-season pitch type breakdown per pitcher from per-pitch feed data.

        Identical row shape to `_fetch_pitch_arsenal()`, but aggregated over the
        entire `season_year` instead of the last 5 starts. Backed by the
        `pitcher_pitch_arsenal_season` view (feed-path only).

        Returns Dict[pitcher_lookup -> list of pitch type rows, sorted by
        usage_pct DESC]. Pitchers with no per-pitch feed data for the season are
        absent from the dict (caller defaults them to []).

        Same underscore vs no-underscore lookup mismatch as `_fetch_pitch_arsenal`:
        the feed view uses no-underscore lookups while the caller's keys use
        underscore lookups — normalize both sides to match.
        """
        if not pitcher_lookups:
            return {}

        # Build a map from no-underscore → original-with-underscores so we can
        # translate query results back to the caller's key format.
        lookup_map = {pl.replace('_', ''): pl for pl in pitcher_lookups if pl}
        cleaned = list(lookup_map.keys())
        if not cleaned:
            return {}

        quoted = ', '.join(f"'{pl}'" for pl in cleaned)
        query = f"""
        SELECT
            player_lookup AS pitcher_lookup_feed,
            pitch_type_code,
            pitch_type_desc,
            usage_pct,
            whiff_rate,
            avg_velocity,
            starts_sampled,
            CAST(last_seen_date AS STRING) AS last_seen_date
        FROM `{self.project_id}.mlb_analytics.pitcher_pitch_arsenal_season`
        WHERE player_lookup IN ({quoted})
          AND season_year = {season_year}
        ORDER BY player_lookup, usage_pct DESC
        """
        rows = self.query_to_list(query)
        out: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            # Translate feed lookup back to the original key format
            feed_key = r['pitcher_lookup_feed']
            original_key = lookup_map.get(feed_key, feed_key)
            out[original_key].append({
                'pitch_type': r['pitch_type_code'],
                'pitch_type_desc': r.get('pitch_type_desc') or r['pitch_type_code'],
                'usage_pct': safe_float(r.get('usage_pct'), precision=1),
                'whiff_rate': safe_float(r.get('whiff_rate'), precision=1),
                'avg_velocity': safe_float(r.get('avg_velocity'), precision=1),
                'starts_sampled': safe_int(r.get('starts_sampled'), default=0),
                'last_seen_date': r.get('last_seen_date'),
            })
        return dict(out)

    def _fetch_advanced_arsenal(self, pitcher_lookups: List[str]) -> Dict[str, Dict[str, Any]]:
        """Advanced per-pitcher arsenal metrics from mlb_game_feed_pitches:
        putaway pitch + whiff, inning velocity fade, arsenal concentration.

        Returns Dict[pitcher_lookup -> nested dict]. Returns {} when the pitcher
        has no per-pitch data yet (early season / old seasons).

        Same underscore vs no-underscore lookup mismatch as pitch_arsenal.
        """
        if not pitcher_lookups:
            return {}

        lookup_map = {pl.replace('_', ''): pl for pl in pitcher_lookups if pl}
        cleaned = list(lookup_map.keys())
        quoted = ', '.join(f"'{pl}'" for pl in cleaned)

        query = f"""
        SELECT
            player_lookup AS feed_lookup,
            starts_l3, starts_l5,
            putaway_pitch_code, putaway_pitch_desc,
            putaway_whiff_rate, putaway_usage_pct_on_2k, putaway_2k_pitches,
            velo_inning_1, velo_inning_5_plus, velo_fade_mph,
            fb_n_inning_1, fb_n_inning_5_plus,
            arsenal_concentration, effective_pitch_count,
            CAST(last_seen_date AS STRING) AS last_seen_date
        FROM `{self.project_id}.mlb_analytics.pitcher_advanced_arsenal_latest`
        WHERE player_lookup IN ({quoted})
        """
        rows = self.query_to_list(query)
        out: Dict[str, Dict] = {}
        for r in rows:
            original = lookup_map.get(r['feed_lookup'], r['feed_lookup'])

            putaway = None
            if r.get('putaway_pitch_code'):
                putaway = {
                    'pitch_code': r['putaway_pitch_code'],
                    'pitch_desc': r.get('putaway_pitch_desc') or r['putaway_pitch_code'],
                    'whiff_rate': safe_float(r.get('putaway_whiff_rate'), precision=1),
                    'usage_pct_on_2k': safe_float(r.get('putaway_usage_pct_on_2k'), precision=1),
                    'sample_size': safe_int(r.get('putaway_2k_pitches'), default=0),
                }

            velo_fade = None
            if r.get('velo_fade_mph') is not None:
                velo_fade = {
                    'inning_1_mph': safe_float(r.get('velo_inning_1'), precision=1),
                    'inning_5_plus_mph': safe_float(r.get('velo_inning_5_plus'), precision=1),
                    'fade_mph': safe_float(r.get('velo_fade_mph'), precision=1),
                    'n_inning_1': safe_int(r.get('fb_n_inning_1'), default=0),
                    'n_inning_5_plus': safe_int(r.get('fb_n_inning_5_plus'), default=0),
                }

            concentration = None
            if r.get('arsenal_concentration') is not None:
                concentration = {
                    'herfindahl': safe_float(r.get('arsenal_concentration'), precision=3),
                    'effective_pitch_count': safe_float(r.get('effective_pitch_count'), precision=2),
                }

            out[original] = {
                'starts_l3': safe_int(r.get('starts_l3'), default=0),
                'starts_l5': safe_int(r.get('starts_l5'), default=0),
                'last_seen_date': r.get('last_seen_date'),
                'putaway': putaway,
                'velo_fade': velo_fade,
                'concentration': concentration,
            }
        return out

    def _fetch_expected_arsenal(self, pitcher_lookups: List[str]) -> Dict[str, Dict[str, Any]]:
        """Arsenal-weighted league expectations vs actuals.

        Source: `mlb_analytics.pitcher_expected_arsenal_latest` (joins arsenal
        usage to `league_pitch_type_stats`). Returns `None` entry when the
        pitcher's row fails the `is_reliable` gate (≥300 feed-sourced pitches,
        ≥70% arsenal coverage).
        """
        if not pitcher_lookups:
            return {}

        lookup_map = {pl.replace('_', ''): pl for pl in pitcher_lookups if pl}
        cleaned = list(lookup_map.keys())
        quoted = ', '.join(f"'{pl}'" for pl in cleaned)

        query = f"""
        SELECT
            player_lookup AS feed_lookup,
            total_pitches_sampled,
            starts_sampled,
            pitch_types_sampled,
            arsenal_coverage_pct,
            expected_whiff_pct,
            actual_whiff_pct,
            whiff_vs_expected_pp,
            expected_csw_pct,
            stuff_velocity_premium,
            is_reliable,
            CAST(last_seen_date AS STRING) AS last_seen_date
        FROM `{self.project_id}.mlb_analytics.pitcher_expected_arsenal_latest`
        WHERE player_lookup IN ({quoted})
          AND is_reliable = TRUE
        """
        rows = self.query_to_list(query)
        out: Dict[str, Dict] = {}
        for r in rows:
            original = lookup_map.get(r['feed_lookup'], r['feed_lookup'])
            out[original] = {
                'expected_whiff_pct': safe_float(r.get('expected_whiff_pct'), precision=1),
                'actual_whiff_pct': safe_float(r.get('actual_whiff_pct'), precision=1),
                'whiff_vs_expected_pp': safe_float(r.get('whiff_vs_expected_pp'), precision=1),
                'expected_csw_pct': safe_float(r.get('expected_csw_pct'), precision=1),
                'stuff_velocity_premium': safe_float(r.get('stuff_velocity_premium'), precision=1),
                'total_pitches_sampled': safe_int(r.get('total_pitches_sampled'), default=0),
                'starts_sampled': safe_int(r.get('starts_sampled'), default=0),
                'arsenal_coverage_pct': safe_float(r.get('arsenal_coverage_pct'), precision=1),
                'last_seen_date': r.get('last_seen_date'),
            }
        return out

    # ------------------------------------------------------------------
    # Leaderboard assembly
    # ------------------------------------------------------------------

    def _build_leaderboard(
        self,
        game_date: str,
        tonight: List[Dict],
        season_aggs: Dict[str, Dict],
        game_logs: Dict[str, List[Dict]],
        names: Dict[str, str],
    ) -> Dict[str, Any]:
        # Tonight's slate: sorted by game time ASC. Tonight page is intentionally
        # prediction-free — no model fields are emitted.
        slate = []
        for p in tonight:
            pl = p['pitcher_lookup']
            # Last 5 starts — mirrors the NBA Last10Grid shape: per-game
            # O/U/NL results + K totals + lines. game_logs is pre-sorted DESC.
            log = game_logs.get(pl, [])[:5]
            last_5_results = []
            last_5_k = []
            last_5_lines = []
            for g in log:
                ou = g.get('over_under_result')
                if ou == 'OVER':
                    last_5_results.append('O')
                elif ou == 'UNDER':
                    last_5_results.append('U')
                else:
                    last_5_results.append('NL')  # no line / push
                last_5_k.append(g.get('strikeouts'))
                last_5_lines.append(g.get('strikeouts_line'))

            slate.append({
                'pitcher_id': pl,
                'pitcher_name': _resolve_pitcher_name({'pitcher_name': p.get('pitcher_name') or names.get(pl), 'pitcher_lookup': pl}),
                'team': p.get('team'),
                'opponent': p.get('opponent'),
                'is_home': bool(p.get('is_home')),
                'game_time_utc': p.get('game_time_utc'),
                'strikeouts_line': safe_float(p.get('strikeouts_line'), precision=1),
                'last_5_results': last_5_results,
                'last_5_k': last_5_k,
                'last_5_lines': last_5_lines,
            })
        # Chronological sort (earliest first). NULL game_time_utc sorts last
        # via the '~' high-ASCII fallback in the tuple key, then by pitcher_name
        # to give stable ordering for same-time games.
        slate.sort(key=lambda x: (
            x.get('game_time_utc') or '~',
            x.get('pitcher_name') or '',
        ))

        # Hot Hands — pitchers with longest current OVER streak from game log
        hot_hands = self._leaderboard_hot_hands(game_logs, names, season_aggs)

        # Strikeout Kings — season Ks leader
        strikeout_kings = sorted(
            (
                {
                    'pitcher_id': pl,
                    'pitcher_name': names.get(pl, pl.replace('_', ' ').title()),
                    'team': agg.get('team'),
                    'season_k': agg.get('season_k'),
                    'games_started': agg.get('games_started'),
                    'k_per_9': agg.get('k_per_9'),
                }
                for pl, agg in season_aggs.items() if agg.get('season_k')
            ),
            key=lambda x: -(x['season_k'] or 0),
        )[:LEADERBOARD_SIZE]

        # Line Beaters — biggest avg (strikeouts - strikeouts_line) over last 10 starts
        line_beaters = self._leaderboard_line_beaters(game_logs, names, season_aggs)

        return {
            'generated_at': self.get_generated_at(),
            'game_date': game_date,
            'tonight': {
                'count': len(slate),
                'starters': slate,
            },
            'leaderboards': {
                'hot_hands': hot_hands,
                'strikeout_kings': strikeout_kings,
                'line_beaters': line_beaters,
            },
        }

    def _leaderboard_hot_hands(
        self,
        game_logs: Dict[str, List[Dict]],
        names: Dict[str, str],
        season_aggs: Dict[str, Dict],
    ) -> List[Dict]:
        """Longest current OVER streaks (consecutive starts hitting OVER)."""
        entries = []
        for pl, log in game_logs.items():
            # log is newest-first; a "current" streak ends at the most recent start
            streak = 0
            for entry in log:
                if entry.get('over_under_result') == 'OVER':
                    streak += 1
                else:
                    break
            if streak >= 2:
                entries.append({
                    'pitcher_id': pl,
                    'pitcher_name': names.get(pl, pl.replace('_', ' ').title()),
                    'team': (season_aggs.get(pl) or {}).get('team'),
                    'over_streak': streak,
                    'last_game_date': log[0]['game_date'] if log else None,
                })
        entries.sort(key=lambda x: -x['over_streak'])
        return entries[:LEADERBOARD_SIZE]

    def _leaderboard_line_beaters(
        self,
        game_logs: Dict[str, List[Dict]],
        names: Dict[str, str],
        season_aggs: Dict[str, Dict],
    ) -> List[Dict]:
        """Biggest avg margin above K line, last 10 starts, min 5 starts."""
        entries = []
        for pl, log in game_logs.items():
            margins = []
            for entry in log[:10]:
                k = entry.get('strikeouts')
                line = entry.get('strikeouts_line')
                if k is not None and line is not None:
                    margins.append(k - line)
            if len(margins) >= 5:
                avg = sum(margins) / len(margins)
                entries.append({
                    'pitcher_id': pl,
                    'pitcher_name': names.get(pl, pl.replace('_', ' ').title()),
                    'team': (season_aggs.get(pl) or {}).get('team'),
                    'avg_margin_vs_line': round(avg, 2),
                    'sample_size': len(margins),
                })
        entries.sort(key=lambda x: -x['avg_margin_vs_line'])
        return entries[:LEADERBOARD_SIZE]

    # ------------------------------------------------------------------
    # Profile assembly
    # ------------------------------------------------------------------

    def _build_profile(
        self,
        pitcher_lookup: str,
        name: str,
        tonight: Optional[Dict],
        season_agg: Optional[Dict],
        game_log: List[Dict],
        pitch_arsenal: Optional[List[Dict]] = None,
        pitch_arsenal_season: Optional[List[Dict]] = None,
        advanced_arsenal: Optional[Dict[str, Any]] = None,
        expected_arsenal: Optional[Dict[str, Any]] = None,
        opponent_k_defense: Optional[Dict[str, Any]] = None,
        strikeout_zones: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile = {
            'generated_at': self.get_generated_at(),
            'pitcher_id': pitcher_lookup,
            'pitcher_name': name,
            'team': (season_agg or {}).get('team'),
        }

        if tonight:
            tonight_block = {
                'has_start': True,
                'game_date': tonight.get('game_date'),
                'opponent': tonight.get('opponent'),
                'is_home': bool(tonight.get('is_home')),
                'strikeouts_line': safe_float(tonight.get('strikeouts_line'), precision=1),
            }
            if opponent_k_defense and opponent_k_defense.get('k_rate') is not None:
                tonight_block['opponent_k_rate'] = opponent_k_defense.get('k_rate')
                tonight_block['opponent_k_rank'] = opponent_k_defense.get('k_rank')
                tonight_block['opponent_k_rank_of'] = opponent_k_defense.get('k_rank_of')
            profile['tonight'] = tonight_block
        else:
            profile['tonight'] = {'has_start': False}

        if season_agg:
            profile['season_stats'] = {
                'games_started': season_agg.get('games_started'),
                'innings_pitched': season_agg.get('season_ip'),
                'strikeouts': season_agg.get('season_k'),
                'k_per_9': season_agg.get('k_per_9'),
                'era': season_agg.get('era'),
                'whip': season_agg.get('whip'),
                'quality_starts': season_agg.get('quality_starts'),
            }

        profile['game_log'] = game_log

        # Pitch arsenal from Statcast (last 5 starts). Empty list when data
        # isn't available yet (early season, off-season, pre-2025 pitchers).
        profile['pitch_arsenal'] = pitch_arsenal or []

        # Full-season pitch arsenal (feed-path only). Empty list when the
        # pitcher has no per-pitch feed data this season; the frontend falls
        # back to the L5 pitch_arsenal above. Kept alongside pitch_arsenal —
        # pitch_arsenal is still used for a pitch code→name lookup.
        profile['pitch_arsenal_season'] = pitch_arsenal_season or []

        # Advanced per-pitch metrics (putaway, velo fade, concentration).
        # None when no per-pitch data for this pitcher yet.
        profile['advanced_arsenal'] = advanced_arsenal

        # Expected vs actual whiff, arsenal-weighted against league baselines.
        # None for pitchers failing reliability gate (<300 pitches sampled, etc.).
        profile['expected_arsenal'] = expected_arsenal

        # Strikeout zone distribution from last 5 starts (Strike Zone Heartbeat).
        # None when no per-pitch K data in mlb_game_feed_pitches.
        profile['strikeout_zones'] = strikeout_zones

        # Server-computed Key Angles for tonight's start — magnitude-ranked
        # reasoning factors. [] when the pitcher has no start tonight or no
        # factor has enough data. Mirrors NBA `tonights_factors`.
        profile['tonights_factors'] = self._build_pitcher_factors(
            tonight=profile['tonight'] if profile['tonight'].get('has_start') else None,
            expected_arsenal=expected_arsenal,
            advanced_arsenal=advanced_arsenal,
            game_log=game_log,
            pitcher_lookup=pitcher_lookup,
        )

        return profile

    # ------------------------------------------------------------------
    # Tonight's factors (Key Angles)
    # ------------------------------------------------------------------

    @staticmethod
    def _ordinal(n: Optional[int]) -> str:
        """Format an integer as an English ordinal (1 -> '1st', 22 -> '22nd')."""
        if n is None:
            return ''
        if 10 <= (n % 100) <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"

    def _build_pitcher_factors(
        self,
        tonight: Optional[Dict[str, Any]],
        expected_arsenal: Optional[Dict[str, Any]],
        advanced_arsenal: Optional[Dict[str, Any]],
        game_log: List[Dict[str, Any]],
        pitcher_lookup: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build magnitude-ranked Key Angles for tonight's start.

        Mirrors the NBA `tonight_player_exporter._build_candidate_angles`
        pattern: scores each candidate factor by a 0-1 magnitude, sorts, and
        returns the top ~5.

        Each factor is a purely factual observation (opponent K-rate, whiff
        trends, recent form, K floor, velocity). No OVER/UNDER lean is emitted
        — the Tonight and Trends surfaces are prediction-free.

        Runs entirely off data the exporter already fetched. Returns [] when
        the pitcher has no start tonight, or when no factor has enough data.
        Never raises — Key Angles must never block a profile export.
        """
        if not tonight:
            return []

        try:
            return self._compute_pitcher_factors(
                tonight, expected_arsenal, advanced_arsenal, game_log
            )
        except Exception:  # pragma: no cover - defensive: Key Angles never block
            logger.warning(
                "Failed to build pitcher factors for %s; emitting []",
                pitcher_lookup or '?',
                exc_info=True,
            )
            return []

    def _compute_pitcher_factors(
        self,
        tonight: Dict[str, Any],
        expected_arsenal: Optional[Dict[str, Any]],
        advanced_arsenal: Optional[Dict[str, Any]],
        game_log: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Inner factor computation. See `_build_pitcher_factors` for contract."""
        factors: List[Dict[str, Any]] = []
        opponent = tonight.get('opponent') or 'the opposing'
        line = tonight.get('strikeouts_line')

        # game_log is newest-first, completed starts only.
        recent_ks = [
            g.get('strikeouts') for g in game_log[:10]
            if g.get('strikeouts') is not None
        ]
        ou_results = [
            g.get('over_under_result') for g in game_log[:10]
            if g.get('over_under_result') in ('OVER', 'UNDER')
        ]

        # 1. Opponent strikeout-proneness. Driven by the opponent's season
        #    K-rate RANK (1 = strikes out most), not a deviation from a fixed
        #    baseline: opponent_k_rate is K/AB (see _fetch_opponent_k_defense),
        #    whose league mean (~0.243) differs from the familiar K/PA ~0.22 —
        #    rank is distribution-free and sidesteps that ambiguity. Skipped
        #    when the opponent has no season rank yet (early season, <100 AB).
        opp_k_rate = tonight.get('opponent_k_rate')
        opp_k_rank = tonight.get('opponent_k_rank')
        opp_k_rank_of = tonight.get('opponent_k_rank_of')
        if (
            opp_k_rate is not None
            and opp_k_rank and opp_k_rank_of and opp_k_rank_of > 1
        ):
            # pct 0.0 = most strikeout-prone lineup, 1.0 = most contact-oriented.
            pct = (opp_k_rank - 1) / (opp_k_rank_of - 1)
            mag = min(abs(0.5 - pct) * 2, 1.0)
            rate_pct = opp_k_rate * 100
            if pct <= 0.40:
                desc = (
                    f"Faces a strikeout-prone {opponent} lineup "
                    f"({rate_pct:.1f}% K rate, {self._ordinal(opp_k_rank)}-highest "
                    f"of {opp_k_rank_of})."
                )
            elif pct >= 0.60:
                fewest = opp_k_rank_of - opp_k_rank + 1
                desc = (
                    f"Faces a contact-oriented {opponent} lineup "
                    f"({rate_pct:.1f}% K rate, {self._ordinal(fewest)}-lowest "
                    f"of {opp_k_rank_of})."
                )
            else:
                desc = (
                    f"Faces a middle-of-the-pack {opponent} lineup for strikeouts "
                    f"({rate_pct:.1f}% K rate, ranked {opp_k_rank} of {opp_k_rank_of})."
                )
            factors.append({
                'id': 'opp_k_prone',
                'factor': 'opp_k_prone',
                'magnitude': round(mag, 2),
                'description': desc,
            })

        # 2. Deception — whiff rate vs arsenal-weighted league expectation.
        if expected_arsenal:
            wae = expected_arsenal.get('whiff_vs_expected_pp')
            if wae is not None and abs(wae) >= 1.0:
                # Divisor 7.0 ~ the production p90 of |whiff_vs_expected_pp|.
                mag = min(abs(wae) / 7.0, 1.0)
                if wae > 0:
                    desc = (
                        f"Misses more bats than his pitch mix predicts "
                        f"({wae:+.1f} pp whiff vs league baseline)."
                    )
                else:
                    desc = (
                        f"Misses fewer bats than his pitch mix predicts "
                        f"({wae:+.1f} pp whiff vs league baseline)."
                    )
                factors.append({
                    'id': 'deception',
                    'factor': 'deception',
                    'magnitude': round(mag, 2),
                    'description': desc,
                })

        # 3. Recent form — OVER/UNDER results across the last starts.
        if len(ou_results) >= 4:
            over_n = sum(1 for r in ou_results if r == 'OVER')
            total = len(ou_results)
            over_rate = over_n / total
            mag = min(abs(over_rate - 0.5) / 0.4, 1.0)
            if over_rate > 0.5:
                desc = (
                    f"Has gone OVER his strikeout line in {over_n} of his "
                    f"last {total} starts."
                )
            elif over_rate < 0.5:
                desc = (
                    f"Has gone UNDER his strikeout line in {total - over_n} of "
                    f"his last {total} starts."
                )
            else:
                desc = (
                    f"Split his strikeout line {over_n}-{total - over_n} O/U "
                    f"over his last {total} starts."
                )
            factors.append({
                'id': 'recent_form',
                'factor': 'recent_form',
                'magnitude': round(mag, 2),
                'description': desc,
            })

        # 4. K floor — a ROBUST floor: the 2nd-lowest strikeout total over the
        #    last 8 starts, so a single disaster start (early hook, rain delay)
        #    does not poison the signal the way a raw min() would. Floor at or
        #    above tonight's line means he reliably clears it.
        if line is not None and len(recent_ks) >= 6:
            window = recent_ks[:8]
            n = len(window)
            robust_floor = sorted(window)[1]  # 2nd-lowest — drop the worst start
            diff = robust_floor - line
            mag = min(abs(diff) / 3.0, 1.0)
            if robust_floor >= line:
                desc = (
                    f"Struck out {robust_floor}+ in {n - 1} of his last {n} "
                    f"starts — reliable floor at or above tonight's "
                    f"{self._fmt_line(line)} line."
                )
            else:
                desc = (
                    f"Reliable floor of {robust_floor} K over his last {n} "
                    f"starts sits below tonight's {self._fmt_line(line)} line."
                )
            factors.append({
                'id': 'k_floor',
                'factor': 'k_floor',
                'magnitude': round(mag, 2),
                'description': desc,
            })

        # 5. Velocity fade — drop in fastball velocity from the 1st inning to
        #    the 5th+. A large late fade signals tiring → fewer late strikeouts.
        if advanced_arsenal:
            velo_fade = advanced_arsenal.get('velo_fade') or {}
            fade = velo_fade.get('fade_mph')
            if fade is not None and fade >= 0.8:
                mag = min(fade / 3.0, 1.0)
                desc = (
                    f"Velocity fades {fade:.1f} mph from the 1st inning to the "
                    f"5th+ — late-game strikeout risk."
                )
                factors.append({
                    'id': 'velo_fade',
                    'factor': 'velo_fade',
                    'magnitude': round(mag, 2),
                    'description': desc,
                })

        # 6. Velocity premium — average velocity vs league for this arsenal.
        if expected_arsenal:
            svp = expected_arsenal.get('stuff_velocity_premium')
            if svp is not None and abs(svp) >= 0.5:
                mag = min(abs(svp) / 3.0, 1.0)
                if svp > 0:
                    desc = (
                        f"Throws {svp:.1f} mph harder than the league average "
                        f"for his pitch mix."
                    )
                else:
                    desc = (
                        f"Throws {abs(svp):.1f} mph softer than the league "
                        f"average for his pitch mix."
                    )
                factors.append({
                    'id': 'velo_premium',
                    'factor': 'velo_premium',
                    'magnitude': round(mag, 2),
                    'description': desc,
                })

        # 7. Putaway — whiff rate on his go-to 2-strike pitch (league ~14%).
        if advanced_arsenal:
            putaway = advanced_arsenal.get('putaway') or {}
            pa_whiff = putaway.get('whiff_rate')
            pa_n = putaway.get('sample_size') or 0
            if pa_whiff is not None and pa_n >= 15:
                deviation = pa_whiff - 14.0
                mag = min(abs(deviation) / 18.0, 1.0)
                pitch = putaway.get('pitch_desc') or putaway.get('pitch_code') or 'putaway pitch'
                if deviation > 0:
                    desc = (
                        f"Puts hitters away with the {pitch} — {pa_whiff:.0f}% "
                        f"whiff rate on 2-strike counts."
                    )
                elif deviation < 0:
                    desc = (
                        f"Soft 2-strike putaway — only {pa_whiff:.0f}% whiff "
                        f"rate on the {pitch}."
                    )
                else:
                    desc = (
                        f"League-average 2-strike putaway ({pa_whiff:.0f}% "
                        f"whiff on the {pitch})."
                    )
                factors.append({
                    'id': 'putaway',
                    'factor': 'putaway',
                    'magnitude': round(mag, 2),
                    'description': desc,
                })

        # 8. Line vs recent average — tonight's line against his recent K avg.
        if line is not None and len(recent_ks) >= 4:
            avg_k = sum(recent_ks) / len(recent_ks)
            diff = round(avg_k - line, 1)
            if abs(diff) >= 0.5:
                mag = min(abs(diff) / 2.5, 1.0)
                if diff > 0:
                    desc = (
                        f"Tonight's {self._fmt_line(line)} K line sits "
                        f"{abs(diff)} below his {avg_k:.1f} average over the "
                        f"last {len(recent_ks)} starts."
                    )
                else:
                    desc = (
                        f"Tonight's {self._fmt_line(line)} K line sits "
                        f"{abs(diff)} above his {avg_k:.1f} average over the "
                        f"last {len(recent_ks)} starts."
                    )
                factors.append({
                    'id': 'line_vs_recent',
                    'factor': 'line_vs_recent',
                    'magnitude': round(mag, 2),
                    'description': desc,
                })

        # Rank by magnitude and drop pure-noise (zero-magnitude) factors.
        factors = [f for f in factors if f['magnitude'] > 0.0]
        factors.sort(key=lambda f: f['magnitude'], reverse=True)

        # Select the top 5, but cap the recent-game-log family at 2 so a single
        # data source (recent_form / k_floor / line_vs_recent) cannot crowd out
        # the more independent angles (opponent, arsenal, velocity).
        recent_log_family = {'recent_form', 'k_floor', 'line_vs_recent'}
        selected: List[Dict[str, Any]] = []
        family_count = 0
        for f in factors:
            if f['id'] in recent_log_family:
                if family_count >= 2:
                    continue
                family_count += 1
            selected.append(f)
            if len(selected) >= 5:
                break
        return selected

    @staticmethod
    def _fmt_line(line: Optional[float]) -> str:
        """Render a strikeout line without a trailing '.0' for whole numbers."""
        if line is None:
            return '?'
        return f"{line:g}"


def main():
    """CLI entry point."""
    import argparse
    import json as json_mod

    parser = argparse.ArgumentParser(description='MLB Pitcher Exporter')
    parser.add_argument('--date', type=str, default=date.today().isoformat(),
                        help='Target date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Build payloads but do not upload to GCS')
    parser.add_argument('--history-only', action='store_true',
                        help='Only write history/{date}.json; skip live leaderboard + profiles')
    parser.add_argument('--sample-slug', type=str, default=None,
                        help='With --dry-run, print profile JSON for this pitcher_lookup')

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )

    exporter = MlbPitcherExporter()

    if args.dry_run:
        bundle = exporter._build_bundle(args.date)
        print(f"Leaderboard: {len(bundle['leaderboard']['tonight']['starters'])} tonight starters")
        for name, entries in bundle['leaderboard']['leaderboards'].items():
            print(f"  {name}: {len(entries)} entries")
        print(f"Profiles: {len(bundle['profiles'])}")
        if args.sample_slug and args.sample_slug in bundle['profiles']:
            print(json_mod.dumps(bundle['profiles'][args.sample_slug], indent=2, default=str))
        return

    result = exporter.export(args.date, history_only=args.history_only)
    if args.history_only:
        print(f"History    → {result['history_path']}")
    else:
        print(f"Leaderboard → {result['leaderboard_path']}")
        print(f"History     → {result['history_path']}")
        print(f"Profiles:     {len(result['profile_paths'])} files uploaded")


if __name__ == '__main__':
    main()
