#!/usr/bin/env python3
"""
File: data_processors/publishing/mlb/mlb_pitcher_exporter.py

MLB Pitcher Exporter

Exports two JSON products powering the pitcher UI:

  1. gs://nba-props-platform-api/v1/mlb/pitchers/leaderboard.json
     - Tonight's starters ranked by model edge
     - Curated leaderboards (Hot Hands, Strikeout Kings, Model Trusts Him, Line Beaters)

  2. gs://nba-props-platform-api/v1/mlb/pitchers/{pitcher_lookup}.json
     - Per-pitcher profile: tonight card, season stats, last-20 game log,
       our historical prediction track record with population rank

Data sources:
  - mlb_predictions.pitcher_strikeouts  (predictions + graded results)
  - mlb_predictions.signal_best_bets_picks  (curated best bets with signal tags)
  - mlb_analytics.pitcher_game_summary  (per-start pitcher stats)
  - mlb_analytics.pitcher_pitch_arsenal_latest  (pitch mix from Statcast)

Usage:
    exporter = MlbPitcherExporter()
    result = exporter.export(game_date='2026-04-13')  # writes leaderboard + all profiles
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from data_processors.publishing.base_exporter import BaseExporter
from data_processors.publishing.exporter_utils import (
    CACHE_MEDIUM,
    CACHE_LONG,
    safe_float,
    safe_int,
)

logger = logging.getLogger(__name__)

# Active season for track record aggregation. Covers 2025 (full) and 2026 (current).
TRACK_RECORD_START = '2025-01-01'

# Minimum graded picks for a pitcher to be ranked in the population
MIN_RANK_SAMPLE = 5

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

    def export(self, game_date: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        """Generate + upload leaderboard and all pitcher profiles.

        Args:
            game_date: Target date (YYYY-MM-DD). Defaults to today.
            dry_run: If True, return payloads without uploading.

        Returns:
            Dict with 'leaderboard_path' and 'profile_paths' (list of GCS paths).
        """
        game_date = game_date or date.today().isoformat()
        logger.info(f"Generating MLB pitcher exports for {game_date}")

        bundle = self._build_bundle(game_date)

        if dry_run:
            return {
                'game_date': game_date,
                'leaderboard': bundle['leaderboard'],
                'profile_count': len(bundle['profiles']),
                'sample_profile': next(iter(bundle['profiles'].values()), None),
            }

        leaderboard_path = self.upload_to_gcs(
            bundle['leaderboard'],
            'mlb/pitchers/leaderboard.json',
            cache_control=CACHE_MEDIUM,
        )

        profile_paths: List[str] = []
        for pitcher_lookup, profile in bundle['profiles'].items():
            path = self.upload_to_gcs(
                profile,
                f'mlb/pitchers/{pitcher_lookup}.json',
                cache_control=CACHE_MEDIUM,
            )
            profile_paths.append(path)

        logger.info(
            f"Exported leaderboard + {len(profile_paths)} pitcher profiles"
        )
        return {
            'leaderboard_path': leaderboard_path,
            'profile_paths': profile_paths,
        }

    # ------------------------------------------------------------------
    # Bundle assembly
    # ------------------------------------------------------------------

    def _build_bundle(self, game_date: str) -> Dict[str, Any]:
        """Fetch all data once and assemble both outputs."""
        tonight = self._fetch_tonight_predictions(game_date)
        best_bet_keys = self._fetch_best_bet_keys(game_date)
        track_records = self._fetch_track_records()
        ranked_track_records = self._rank_track_records(track_records)
        season_aggs = self._fetch_season_aggregates(season_year=self._infer_season_year(game_date))
        game_logs = self._fetch_game_logs()

        # Union of pitchers we care about: anyone pitching tonight, or who has
        # any prediction/game history in the current active window.
        all_pitcher_keys: Set[str] = set(ranked_track_records.keys())
        all_pitcher_keys.update(season_aggs.keys())
        all_pitcher_keys.update(p['pitcher_lookup'] for p in tonight)

        pitch_arsenals = self._fetch_pitch_arsenal(list(all_pitcher_keys))
        advanced_arsenals = self._fetch_advanced_arsenal(list(all_pitcher_keys))

        # Build display-name map (prefer tonight name, then track record, then season_agg)
        names = self._build_name_map(tonight, ranked_track_records, season_aggs)

        # Mark best bet flag on tonight entries
        for p in tonight:
            p['is_best_bet'] = (p['pitcher_lookup'], p['game_date']) in best_bet_keys

        leaderboard = self._build_leaderboard(
            game_date=game_date,
            tonight=tonight,
            track_records=ranked_track_records,
            season_aggs=season_aggs,
            game_logs=game_logs,
            names=names,
        )

        profiles: Dict[str, Dict] = {}
        for pitcher_lookup in all_pitcher_keys:
            if not pitcher_lookup:
                continue
            profile = self._build_profile(
                pitcher_lookup=pitcher_lookup,
                name=names.get(pitcher_lookup, pitcher_lookup.replace('_', ' ').title()),
                tonight=next((p for p in tonight if p['pitcher_lookup'] == pitcher_lookup), None),
                is_best_bet=(pitcher_lookup, game_date) in best_bet_keys,
                track_record=ranked_track_records.get(pitcher_lookup),
                season_agg=season_aggs.get(pitcher_lookup),
                game_log=game_logs.get(pitcher_lookup, []),
                pitch_arsenal=pitch_arsenals.get(pitcher_lookup, []),
                advanced_arsenal=advanced_arsenals.get(pitcher_lookup),
            )
            profiles[pitcher_lookup] = profile

        return {'leaderboard': leaderboard, 'profiles': profiles}

    def _infer_season_year(self, game_date: str) -> int:
        return int(game_date[:4])

    def _build_name_map(
        self,
        tonight: List[Dict],
        track_records: Dict[str, Dict],
        season_aggs: Dict[str, Dict],
    ) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for row in tonight:
            if row.get('pitcher_name'):
                out[row['pitcher_lookup']] = row['pitcher_name']
        for pl, rec in track_records.items():
            if pl not in out and rec.get('pitcher_name'):
                out[pl] = rec['pitcher_name']
        for pl, rec in season_aggs.items():
            if pl not in out and rec.get('pitcher_name'):
                out[pl] = rec['pitcher_name']
        return out

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _fetch_tonight_predictions(self, game_date: str) -> List[Dict[str, Any]]:
        """Predictions for the target date, deduped to one row per pitcher."""
        query = f"""
        SELECT
            pitcher_lookup,
            pitcher_name,
            team_abbr AS team,
            opponent_team_abbr AS opponent,
            is_home,
            strikeouts_line,
            predicted_strikeouts,
            edge,
            recommendation,
            confidence,
            system_id,
            CAST(game_date AS STRING) AS game_date
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{game_date}'
          AND recommendation IN ('OVER', 'UNDER', 'PASS')
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY pitcher_lookup
            ORDER BY ABS(IFNULL(edge, 0)) DESC, processed_at DESC
        ) = 1
        """
        return self.query_to_list(query)

    def _fetch_best_bet_keys(self, game_date: str) -> Set[Tuple[str, str]]:
        """Set of (pitcher_lookup, game_date) flagged as best bets."""
        query = f"""
        SELECT DISTINCT
            pitcher_lookup,
            CAST(game_date AS STRING) AS game_date
        FROM `{self.project_id}.mlb_predictions.signal_best_bets_picks`
        WHERE game_date = '{game_date}'
        """
        rows = self.query_to_list(query)
        return {(r['pitcher_lookup'], r['game_date']) for r in rows}

    def _fetch_track_records(self) -> Dict[str, Dict[str, Any]]:
        """Per-pitcher prediction track record over the active window."""
        query = f"""
        WITH graded AS (
          SELECT
            pitcher_lookup,
            pitcher_name,
            game_date,
            recommendation,
            edge,
            is_correct,
            actual_strikeouts,
            strikeouts_line
          FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
          WHERE game_date >= '{TRACK_RECORD_START}'
            AND game_date < CURRENT_DATE()
            AND recommendation IN ('OVER', 'UNDER')
            AND is_correct IS NOT NULL
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY pitcher_lookup, game_date
            ORDER BY ABS(IFNULL(edge, 0)) DESC, processed_at DESC
          ) = 1
        ),
        aggregated AS (
          SELECT
            pitcher_lookup,
            ANY_VALUE(pitcher_name) AS pitcher_name,
            COUNT(*) AS total_picks,
            COUNTIF(is_correct) AS correct,
            COUNTIF(recommendation = 'OVER') AS over_picks,
            COUNTIF(recommendation = 'OVER' AND is_correct) AS over_correct,
            COUNTIF(recommendation = 'UNDER') AS under_picks,
            COUNTIF(recommendation = 'UNDER' AND is_correct) AS under_correct,
            AVG(ABS(edge)) AS avg_edge,
            MAX(game_date) AS last_pick_date
          FROM graded
          GROUP BY pitcher_lookup
        )
        SELECT * FROM aggregated
        """
        rows = self.query_to_list(query)
        out: Dict[str, Dict] = {}
        for r in rows:
            total = int(r['total_picks'])
            correct = int(r['correct'])
            out[r['pitcher_lookup']] = {
                'pitcher_name': r.get('pitcher_name'),
                'total_picks': total,
                'correct': correct,
                'hit_rate_pct': round(100 * correct / total, 1) if total else 0.0,
                'over_picks': int(r['over_picks']),
                'over_correct': int(r['over_correct']),
                'under_picks': int(r['under_picks']),
                'under_correct': int(r['under_correct']),
                'avg_edge': safe_float(r.get('avg_edge'), default=0.0, precision=2),
                'last_pick_date': str(r['last_pick_date']) if r.get('last_pick_date') else None,
            }
        return out

    def _rank_track_records(self, records: Dict[str, Dict]) -> Dict[str, Dict]:
        """Add population rank by hit_rate_pct (min sample gated)."""
        eligible = [
            (pl, rec) for pl, rec in records.items()
            if rec['total_picks'] >= MIN_RANK_SAMPLE
        ]
        eligible.sort(key=lambda kv: (-kv[1]['hit_rate_pct'], -kv[1]['total_picks']))
        population = len(eligible)
        for idx, (pl, rec) in enumerate(eligible, start=1):
            rec['rank'] = idx
            rec['rank_of'] = population
        # Copy the ranked dicts back (they mutated in place) and also include sub-min entries without rank
        return records

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
        """Last N starts per pitcher joined with prediction + best-bet flags.

        over_under_result is computed inline from strikeouts vs line since the
        source column in pitcher_game_summary is unpopulated.
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
            strikeouts_line,
            predicted_strikeouts,
            recommendation,
            edge,
            is_correct
          FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
          WHERE game_date >= '{TRACK_RECORD_START}'
          QUALIFY ROW_NUMBER() OVER (
            PARTITION BY pitcher_lookup, game_date
            ORDER BY ABS(IFNULL(edge, 0)) DESC, processed_at DESC
          ) = 1
        ),
        bb_flags AS (
          SELECT DISTINCT pitcher_lookup, game_date
          FROM `{self.project_id}.mlb_predictions.signal_best_bets_picks`
          WHERE game_date >= '{TRACK_RECORD_START}'
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
          p.predicted_strikeouts,
          p.recommendation,
          p.edge,
          p.is_correct AS prediction_correct,
          (bb.pitcher_lookup IS NOT NULL) AS was_best_bet,
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
        LEFT JOIN bb_flags bb
          ON r.pitcher_lookup = bb.pitcher_lookup
          AND r.game_date = bb.game_date
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
                'predicted_strikeouts': safe_float(r.get('predicted_strikeouts'), precision=1),
                'recommendation': r.get('recommendation'),
                'edge': safe_float(r.get('edge'), precision=2),
                'prediction_correct': r.get('prediction_correct'),
                'was_best_bet': bool(r.get('was_best_bet')),
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

    # ------------------------------------------------------------------
    # Leaderboard assembly
    # ------------------------------------------------------------------

    def _build_leaderboard(
        self,
        game_date: str,
        tonight: List[Dict],
        track_records: Dict[str, Dict],
        season_aggs: Dict[str, Dict],
        game_logs: Dict[str, List[Dict]],
        names: Dict[str, str],
    ) -> Dict[str, Any]:
        # Tonight's slate: sorted by abs(edge) DESC, best bets float up on ties
        slate = []
        for p in tonight:
            pl = p['pitcher_lookup']
            tr = track_records.get(pl, {})
            slate.append({
                'pitcher_id': pl,
                'pitcher_name': p.get('pitcher_name') or names.get(pl),
                'team': p.get('team'),
                'opponent': p.get('opponent'),
                'is_home': bool(p.get('is_home')),
                'strikeouts_line': safe_float(p.get('strikeouts_line'), precision=1),
                'predicted_strikeouts': safe_float(p.get('predicted_strikeouts'), precision=1),
                'edge': safe_float(p.get('edge'), precision=2),
                'recommendation': p.get('recommendation'),
                'is_best_bet': p.get('is_best_bet', False),
                'track_record_picks': tr.get('total_picks', 0),
                'track_record_hr_pct': tr.get('hit_rate_pct'),
            })
        slate.sort(
            key=lambda x: (
                -1 if x['is_best_bet'] else 0,
                -abs(x['edge'] or 0),
            )
        )

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

        # Model Trusts Him — highest graded hit rate with meaningful sample
        model_trusts_him = sorted(
            (
                {
                    'pitcher_id': pl,
                    'pitcher_name': names.get(pl, rec.get('pitcher_name', pl)),
                    'total_picks': rec['total_picks'],
                    'correct': rec['correct'],
                    'hit_rate_pct': rec['hit_rate_pct'],
                    'avg_edge': rec['avg_edge'],
                    'rank': rec.get('rank'),
                    'rank_of': rec.get('rank_of'),
                }
                for pl, rec in track_records.items()
                if rec.get('rank') is not None
            ),
            key=lambda x: (-x['hit_rate_pct'], -x['total_picks']),
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
                'model_trusts_him': model_trusts_him,
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
        is_best_bet: bool,
        track_record: Optional[Dict],
        season_agg: Optional[Dict],
        game_log: List[Dict],
        pitch_arsenal: Optional[List[Dict]] = None,
        advanced_arsenal: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile = {
            'generated_at': self.get_generated_at(),
            'pitcher_id': pitcher_lookup,
            'pitcher_name': name,
            'team': (season_agg or {}).get('team'),
        }

        if tonight:
            profile['tonight'] = {
                'has_start': True,
                'game_date': tonight.get('game_date'),
                'opponent': tonight.get('opponent'),
                'is_home': bool(tonight.get('is_home')),
                'strikeouts_line': safe_float(tonight.get('strikeouts_line'), precision=1),
                'predicted_strikeouts': safe_float(tonight.get('predicted_strikeouts'), precision=1),
                'edge': safe_float(tonight.get('edge'), precision=2),
                'recommendation': tonight.get('recommendation'),
                'is_best_bet': is_best_bet,
                'confidence': safe_float(tonight.get('confidence'), precision=3),
            }
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

        if track_record:
            profile['track_record'] = {
                'total_picks': track_record.get('total_picks', 0),
                'correct': track_record.get('correct', 0),
                'hit_rate_pct': track_record.get('hit_rate_pct'),
                'over_picks': track_record.get('over_picks', 0),
                'over_correct': track_record.get('over_correct', 0),
                'over_hr_pct': (
                    round(100 * track_record['over_correct'] / track_record['over_picks'], 1)
                    if track_record.get('over_picks') else None
                ),
                'under_picks': track_record.get('under_picks', 0),
                'under_correct': track_record.get('under_correct', 0),
                'under_hr_pct': (
                    round(100 * track_record['under_correct'] / track_record['under_picks'], 1)
                    if track_record.get('under_picks') else None
                ),
                'avg_edge': track_record.get('avg_edge'),
                'rank': track_record.get('rank'),
                'rank_of': track_record.get('rank_of'),
                'last_pick_date': track_record.get('last_pick_date'),
            }

        profile['game_log'] = game_log

        # Pitch arsenal from Statcast (last 5 starts). Empty list when data
        # isn't available yet (early season, off-season, pre-2025 pitchers).
        profile['pitch_arsenal'] = pitch_arsenal or []

        # Advanced per-pitch metrics (putaway, velo fade, concentration).
        # None when no per-pitch data for this pitcher yet.
        profile['advanced_arsenal'] = advanced_arsenal

        return profile


def main():
    """CLI entry point."""
    import argparse
    import json as json_mod

    parser = argparse.ArgumentParser(description='MLB Pitcher Exporter')
    parser.add_argument('--date', type=str, default=date.today().isoformat(),
                        help='Target date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Build payloads but do not upload to GCS')
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

    result = exporter.export(args.date)
    print(f"Leaderboard → {result['leaderboard_path']}")
    print(f"Profiles:     {len(result['profile_paths'])} files uploaded")


if __name__ == '__main__':
    main()
