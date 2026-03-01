"""
Consolidated Best Bets Exporter for Phase 6 Publishing

Single-file export for the playerprops.io frontend. Merges:
  - Season/month/week record + streak
  - Today's picks (ungraded, with angles)
  - Full graded history grouped by week/day

Output: v1/best-bets/all.json (~50-200 KB for a full season)

Design: Frontend team chose single-file architecture over three separate
files. One fetch, everything available, <200KB. See Session 319.

Pick Locking (Session 340):
  Today's picks are merged from three sources:
    signal_best_bets_picks (volatile algo output)
    + best_bets_published_picks (locked picks from prior exports)
    + best_bets_manual_picks (manual overrides via CLI)
  Once a pick is published, it persists in exports even if the signal
  pipeline later drops it. This prevents picks from disappearing mid-day.

Created: 2026-02-21 (Session 319)
Updated: 2026-02-28 (Session 340) — Pick locking + audit trail
"""

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery

from data_processors.publishing.base_exporter import BaseExporter
from data_processors.publishing.exporter_utils import safe_float, safe_int
from ml.signals.aggregator import ALGORITHM_VERSION

logger = logging.getLogger(__name__)


def _is_home(game_id: str, team_abbr: str) -> bool:
    """Derive whether team is the home team from game_id format YYYYMMDD_AWAY_HOME."""
    parts = game_id.split('_')
    if len(parts) == 3:
        return team_abbr == parts[2]
    return False

PROJECT_ID = 'nba-props-platform'


def _compute_season_label(d: date) -> str:
    """Compute NBA season label from a date (e.g. Feb 2026 -> '2025-26')."""
    if d.month >= 10:
        return f"{d.year}-{str(d.year + 1)[-2:]}"
    return f"{d.year - 1}-{str(d.year)[-2:]}"


class BestBetsAllExporter(BaseExporter):
    """Export consolidated best bets (record + today + history) to one file."""

    def generate_json(self, target_date: str, **kwargs) -> Dict[str, Any]:
        """Generate all.json with record, today's picks, and history.

        kwargs:
            trigger_source: str — 'scheduled', 'manual', or 'post_grading'
        """
        trigger_source = kwargs.get('trigger_source', 'scheduled')
        target = (
            date.fromisoformat(target_date) if isinstance(target_date, str)
            else target_date
        )
        season_start_year = target.year if target.month >= 11 else target.year - 1
        season_start = date(season_start_year, 11, 1)

        # One query gets all picks for the season (including today's ungraded)
        all_picks = self._query_all_picks(target_date, season_start.isoformat())

        # Split into today vs history
        today_signal_picks = []
        history_picks = []
        for p in all_picks:
            gd = p['game_date']
            if hasattr(gd, 'isoformat'):
                gd_str = gd.isoformat()
            else:
                gd_str = str(gd)

            if gd_str == target_date:
                today_signal_picks.append(p)
            else:
                history_picks.append(p)

        # ── Pick Locking (Session 340) ──────────────────────────────────
        # Merge today's signal picks with locked published picks and manual picks.
        # This ensures picks never disappear once published.
        published_picks = self._query_published_picks(target_date)
        manual_picks = self._query_manual_picks(target_date)
        started_game_ids = self._query_started_games(target_date)
        today_picks, merge_stats = self._merge_and_lock_picks(
            today_signal_picks, published_picks, manual_picks,
            started_game_ids=started_game_ids,
        )

        # Persist newly published picks + audit trail
        self._write_published_picks(target_date, today_picks)
        self._write_export_audit(
            target_date, today_picks, merge_stats,
            trigger_source=trigger_source,
        )

        # Replace today's signal picks with merged set in all_picks for
        # record/streak/weeks computation
        all_picks = history_picks + today_picks

        # Build record from graded picks only
        record = self._build_record(all_picks, target, season_start)
        ultra_record = self._build_ultra_record(all_picks)

        # Build streaks
        streak, best_streak = self._compute_streaks(all_picks)

        # Look up game times for today's picks (Session 328)
        game_times = self._query_game_times(target_date, today_picks)

        # Format today's picks (with angles, rank)
        today_formatted = self._format_today(today_picks, game_times)

        # Build weeks array (history + today merged in)
        weeks = self._build_weeks(all_picks)

        voided = sum(1 for p in all_picks if p.get('is_voided'))
        total_picks = len(all_picks) - voided
        graded = sum(1 for p in all_picks if p.get('prediction_correct') is not None)

        result = {
            'date': target_date,
            'season': _compute_season_label(target),
            'generated_at': self.get_generated_at(),
            'algorithm_version': ALGORITHM_VERSION,
            'record': record,
            'ultra_record': ultra_record,
            'streak': streak,
            'best_streak': best_streak,
            'today': today_formatted,
            'total_today': len(today_formatted),
            'weeks': weeks,
            'total_picks': total_picks,
            'graded': graded,
        }
        if voided > 0:
            result['voided'] = voided
        return result

    def export(self, target_date: str, trigger_source: str = 'scheduled') -> str:
        """Generate and upload all.json.

        Args:
            target_date: Date string in YYYY-MM-DD format.
            trigger_source: What triggered this export — 'scheduled', 'manual',
                or 'post_grading'. Recorded in the audit table.

        Returns:
            GCS path where file was uploaded.
        """
        json_data = self.generate_json(target_date, trigger_source=trigger_source)

        gcs_path = self.upload_to_gcs(
            json_data=json_data,
            path='best-bets/all.json',
            cache_control='public, max-age=300',
        )

        logger.info(
            f"Exported best-bets/all.json: {json_data['total_today']} today, "
            f"{json_data['total_picks']} total, {json_data['graded']} graded"
        )
        return gcs_path

    # ── Private helpers ──────────────────────────────────────────────────

    def _query_all_picks(self, target_date: str, season_start: str) -> List[Dict]:
        """Query all signal best bets for the season with grading and angles."""
        query = """
        SELECT
          b.game_date,
          b.game_id,
          b.player_name,
          b.player_lookup,
          b.team_abbr,
          b.opponent_team_abbr,
          b.recommendation,
          b.line_value,
          b.edge,
          b.predicted_points,
          b.rank,
          b.pick_angles,
          b.ultra_tier,
          pa.prediction_correct,
          pa.actual_points,
          pa.is_voided,
          pa.void_reason
        FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` b
        LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
          ON b.player_lookup = pa.player_lookup
          AND b.game_date = pa.game_date
          AND b.system_id = pa.system_id
        WHERE b.game_date >= @season_start
          AND b.game_date <= @target_date
        ORDER BY b.game_date DESC, b.rank ASC, b.edge DESC
        """

        params = [
            bigquery.ScalarQueryParameter('season_start', 'DATE', season_start),
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            return self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query all picks: {e}")
            return []

    def _format_today(
        self,
        picks: List[Dict],
        game_times: Dict[str, str],
    ) -> List[Dict]:
        """Format today's picks with angles for the hero section."""
        formatted = []
        for p in sorted(picks, key=lambda x: x.get('rank') or 999):
            angles = p.get('pick_angles') or []
            game_id = p.get('game_id', '')

            pick_dict = {
                'rank': safe_int(p.get('rank')),
                'player': p.get('player_name') or '',
                'player_lookup': p.get('player_lookup') or '',
                'team': p.get('team_abbr') or '',
                'opponent': p.get('opponent_team_abbr') or '',
                'home': _is_home(game_id, p.get('team_abbr') or ''),
                'direction': p.get('recommendation') or '',
                'stat': 'PTS',
                'line': safe_float(p.get('line_value'), precision=1),
                'edge': safe_float(p.get('edge'), precision=1),
                'game_time': game_times.get(game_id),
                'angles': list(angles)[:3],
                'actual': safe_int(p.get('actual_points')),
                'result': (
                    'VOID' if p.get('is_voided')
                    else 'WIN' if p.get('prediction_correct') is True
                    else 'LOSS' if p.get('prediction_correct') is False
                    else None
                ),
                'is_ultra': self._is_ultra(p.get('ultra_tier')),
            }

            source = p.get('_source')
            if source and source != 'algorithm':
                pick_dict['source'] = source

            if p.get('is_voided'):
                pick_dict['void_reason'] = 'DNP'

            formatted.append(pick_dict)
        return formatted

    def _query_game_times(
        self, target_date: str, picks: List[Dict]
    ) -> Dict[str, str]:
        """Look up game start times from schedule for today's picks.

        Returns:
            Dict mapping prediction game_id → ISO 8601 datetime string.
        """
        if not picks:
            return {}

        query = f"""
        SELECT away_team_tricode, home_team_tricode, game_date_est
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_date = @target_date
        """

        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]

        try:
            rows = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(query_parameters=params),
            ).result(timeout=30)

            schedule_times = {}
            for row in rows:
                if row.game_date_est and hasattr(row.game_date_est, 'isoformat'):
                    schedule_times[f"{row.away_team_tricode}_{row.home_team_tricode}"] = (
                        row.game_date_est.isoformat()
                    )

            result = {}
            for pick in picks:
                gid = pick.get('game_id', '')
                parts = gid.split('_', 1)
                if len(parts) == 2 and parts[1] in schedule_times:
                    result[gid] = schedule_times[parts[1]]

            return result
        except Exception as e:
            logger.warning(f"Game times lookup failed (non-fatal): {e}")
            return {}

    def _query_started_games(self, target_date: str) -> set:
        """Return set of game_ids (YYYYMMDD_AWAY_HOME) for started/finished games."""
        query = f"""
        SELECT
          CONCAT(FORMAT_DATE('%Y%m%d', game_date), '_',
                 away_team_tricode, '_', home_team_tricode) AS game_id,
          game_status
        FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
        WHERE game_date = @target_date
          AND game_status >= 2
        """
        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
        try:
            rows = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(query_parameters=params),
            ).result(timeout=30)
            return {row.game_id for row in rows}
        except Exception as e:
            logger.warning(f"Started games lookup failed (non-fatal): {e}")
            return set()

    def _build_weeks(self, all_picks: List[Dict]) -> List[Dict]:
        """Group all picks into weeks → days (most recent first)."""
        weeks_map: Dict[str, Dict[str, List]] = {}

        for row in all_picks:
            game_date = row['game_date']
            if hasattr(game_date, 'isoformat'):
                game_date_str = game_date.isoformat()
                gd = game_date
            else:
                game_date_str = str(game_date)
                gd = date.fromisoformat(game_date_str)

            week_start = gd - timedelta(days=gd.weekday())
            week_key = week_start.isoformat()

            if week_key not in weeks_map:
                weeks_map[week_key] = {}
            if game_date_str not in weeks_map[week_key]:
                weeks_map[week_key][game_date_str] = []

            if row.get('is_voided'):
                result = 'VOID'
            elif row.get('prediction_correct') is not None:
                result = 'WIN' if row['prediction_correct'] else 'LOSS'
            else:
                result = None

            angles = row.get('pick_angles') or []

            game_id = row.get('game_id') or ''
            pick_dict = {
                'player': row.get('player_name') or '',
                'player_lookup': row.get('player_lookup') or '',
                'team': row.get('team_abbr') or '',
                'opponent': row.get('opponent_team_abbr') or '',
                'home': _is_home(game_id, row.get('team_abbr') or ''),
                'direction': row.get('recommendation') or '',
                'stat': 'PTS',
                'line': safe_float(row.get('line_value'), precision=1),
                'edge': safe_float(row.get('edge'), precision=1),
                'actual': safe_int(row.get('actual_points')),
                'result': result,
                'angles': list(angles)[:3],
                'is_ultra': self._is_ultra(row.get('ultra_tier')),
            }

            if row.get('is_voided'):
                pick_dict['void_reason'] = 'DNP'

            weeks_map[week_key][game_date_str].append(pick_dict)

        weeks = []
        for week_key in sorted(weeks_map.keys(), reverse=True):
            days_map = weeks_map[week_key]
            week_wins = 0
            week_losses = 0
            week_pending = 0
            days = []

            for day_key in sorted(days_map.keys(), reverse=True):
                picks = days_map[day_key]
                day_wins = sum(1 for p in picks if p['result'] == 'WIN')
                day_losses = sum(1 for p in picks if p['result'] == 'LOSS')
                day_voided = sum(1 for p in picks if p['result'] == 'VOID')
                day_pending = sum(1 for p in picks if p['result'] is None)
                week_wins += day_wins
                week_losses += day_losses
                week_pending += day_pending

                # Day-level result color hint for frontend
                # Voided picks don't count — a day with only voided picks is complete
                actionable = len(picks) - day_voided
                if actionable == 0:
                    day_status = 'void'
                elif day_pending == actionable:
                    day_status = 'pending'
                elif day_wins > 0 and day_losses == 0 and day_pending == 0:
                    day_status = 'sweep'
                elif day_losses > 0 and day_wins == 0 and day_pending == 0:
                    day_status = 'miss'
                else:
                    day_status = 'split'

                day_record = {
                    'wins': day_wins,
                    'losses': day_losses,
                    'pending': day_pending,
                }
                if day_voided > 0:
                    day_record['voided'] = day_voided

                days.append({
                    'date': day_key,
                    'status': day_status,
                    'record': day_record,
                    'picks': picks,
                })

            week_graded = week_wins + week_losses
            weeks.append({
                'week_start': week_key,
                'record': {
                    'wins': week_wins,
                    'losses': week_losses,
                    'pending': week_pending,
                    'pct': round(
                        100.0 * week_wins / max(week_graded, 1), 1
                    ) if week_graded > 0 else None,
                },
                'days': days,
            })

        return weeks

    def _build_record(
        self, all_picks: List[Dict], target: date, season_start: date
    ) -> Dict[str, Any]:
        """Compute W-L record from graded picks across season/month/week."""
        month_start = target.replace(day=1)
        week_start = target - timedelta(days=target.weekday())

        season = {'wins': 0, 'losses': 0, 'total': 0}
        month = {'wins': 0, 'losses': 0, 'total': 0}
        week = {'wins': 0, 'losses': 0, 'total': 0}

        # Collect last 10 graded results (most recent first — picks are sorted desc)
        last_10_results = []

        for p in all_picks:
            correct = p.get('prediction_correct')
            if correct is None:
                continue

            gd = p['game_date']
            if hasattr(gd, 'isoformat'):
                gd = gd if isinstance(gd, date) else date.fromisoformat(gd.isoformat())
            else:
                gd = date.fromisoformat(str(gd))

            is_win = bool(correct)

            # Season
            season['total'] += 1
            if is_win:
                season['wins'] += 1
            else:
                season['losses'] += 1

            # Month
            if gd >= month_start:
                month['total'] += 1
                if is_win:
                    month['wins'] += 1
                else:
                    month['losses'] += 1

            # Week
            if gd >= week_start:
                week['total'] += 1
                if is_win:
                    week['wins'] += 1
                else:
                    week['losses'] += 1

            # Last 10
            if len(last_10_results) < 10:
                last_10_results.append(is_win)

        def pct(w, t):
            return round(100.0 * w / t, 1) if t > 0 else 0.0

        last10_wins = sum(last_10_results)
        last10_total = len(last_10_results)

        return {
            'season': {
                'wins': season['wins'],
                'losses': season['losses'],
                'total': season['total'],
                'pct': pct(season['wins'], season['total']),
            },
            'month': {
                'wins': month['wins'],
                'losses': month['losses'],
                'total': month['total'],
                'pct': pct(month['wins'], month['total']),
            },
            'week': {
                'wins': week['wins'],
                'losses': week['losses'],
                'total': week['total'],
                'pct': pct(week['wins'], week['total']),
            },
            'last_10': {
                'wins': last10_wins,
                'losses': last10_total - last10_wins,
                'pct': pct(last10_wins, last10_total),
            },
        }

    def _build_ultra_record(self, all_picks: List[Dict]) -> Dict[str, Any]:
        """Compute W-L record for ultra-tier picks (overall + OVER/UNDER splits)."""
        totals = {'wins': 0, 'losses': 0}
        over = {'wins': 0, 'losses': 0}
        under = {'wins': 0, 'losses': 0}

        for p in all_picks:
            ultra = self._is_ultra(p.get('ultra_tier'))
            if not ultra or p.get('prediction_correct') is None:
                continue

            is_win = bool(p['prediction_correct'])
            direction = p.get('recommendation', '')

            if is_win:
                totals['wins'] += 1
            else:
                totals['losses'] += 1

            if direction == 'OVER':
                if is_win:
                    over['wins'] += 1
                else:
                    over['losses'] += 1
            elif direction == 'UNDER':
                if is_win:
                    under['wins'] += 1
                else:
                    under['losses'] += 1

        def pct(w, t):
            return round(100.0 * w / t, 1) if t > 0 else None

        total = totals['wins'] + totals['losses']
        over_total = over['wins'] + over['losses']
        under_total = under['wins'] + under['losses']

        return {
            'wins': totals['wins'],
            'losses': totals['losses'],
            'total': total,
            'pct': pct(totals['wins'], total),
            'over': {
                'wins': over['wins'],
                'losses': over['losses'],
                'total': over_total,
                'pct': pct(over['wins'], over_total),
            },
            'under': {
                'wins': under['wins'],
                'losses': under['losses'],
                'total': under_total,
                'pct': pct(under['wins'], under_total),
            },
        }

    def _compute_streaks(self, all_picks: List[Dict]) -> tuple:
        """Compute current streak and best W streak from graded picks.

        all_picks is sorted game_date DESC, so iterate directly for current streak.
        """
        graded = [
            p for p in all_picks if p.get('prediction_correct') is not None
        ]

        empty_current = {'type': 'N/A', 'count': 0}
        empty_best = {'type': 'N/A', 'count': 0, 'start': None, 'end': None}

        if not graded:
            return empty_current, empty_best

        # Current streak (newest first)
        current_type = 'W' if graded[0]['prediction_correct'] else 'L'
        current_count = 0
        for p in graded:
            is_win = bool(p['prediction_correct'])
            if (is_win and current_type == 'W') or (not is_win and current_type == 'L'):
                current_count += 1
            else:
                break

        # Best W streak (oldest first)
        best_w_count = 0
        best_w_start = None
        best_w_end = None
        curr_w_count = 0
        curr_w_start = None

        for p in reversed(graded):
            gd = p['game_date']
            if p['prediction_correct']:
                if curr_w_count == 0:
                    curr_w_start = gd
                curr_w_count += 1
                if curr_w_count > best_w_count:
                    best_w_count = curr_w_count
                    best_w_start = curr_w_start
                    best_w_end = gd
            else:
                curr_w_count = 0

        def fmt_date(d):
            if d is None:
                return None
            return d.isoformat() if hasattr(d, 'isoformat') else str(d)

        return (
            {'type': current_type, 'count': current_count},
            {
                'type': 'W',
                'count': best_w_count,
                'start': fmt_date(best_w_start),
                'end': fmt_date(best_w_end),
            },
        )

    # ── Pick Locking Methods (Session 340) ──────────────────────────────

    def _query_published_picks(self, target_date: str) -> List[Dict]:
        """Read locked picks from best_bets_published_picks for this date."""
        query = """
        SELECT
          player_lookup, game_id, game_date,
          player_name, team_abbr, opponent_team_abbr,
          recommendation, line_value, edge, rank,
          pick_angles, ultra_tier, source,
          first_published_at, last_seen_in_signal
        FROM `nba-props-platform.nba_predictions.best_bets_published_picks`
        WHERE game_date = @target_date
        """
        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
        try:
            return self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query published picks (non-fatal): {e}")
            return []

    def _query_manual_picks(self, target_date: str) -> List[Dict]:
        """Read active manual picks for this date."""
        query = """
        SELECT
          player_lookup, game_id, game_date,
          player_name, team_abbr, opponent_team_abbr,
          recommendation, line_value, edge, rank,
          pick_angles, stat, notes
        FROM `nba-props-platform.nba_predictions.best_bets_manual_picks`
        WHERE game_date = @target_date
          AND is_active = TRUE
        """
        params = [
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
        try:
            return self.query_to_list(query, params)
        except Exception as e:
            logger.warning(f"Failed to query manual picks (non-fatal): {e}")
            return []

    @staticmethod
    def _is_ultra(val) -> bool:
        """Normalize ultra_tier from BOOLEAN or STRING to Python bool."""
        return val is True or val == 'true'

    def _merge_and_lock_picks(
        self,
        signal_picks: List[Dict],
        published_picks: List[Dict],
        manual_picks: List[Dict],
        started_game_ids: Optional[set] = None,
    ) -> Tuple[List[Dict], Dict[str, int]]:
        """Merge signal, published (locked), and manual picks for today.

        Merge logic:
        1. Start with published (locked) picks as baseline
        2. If a pick is both locked AND in signal, update edge/rank/angles
        3. Add signal picks not yet published (new picks)
        4. Add manual picks not already present
        5. Re-rank: active signal picks first, then locked-but-dropped, then manual

        Ultra gate: ultra_tier cannot be added to a pick whose game has
        already started (game_status >= 2). Blocked changes are logged.

        Returns:
            (merged_picks, merge_stats) where merge_stats has counts for audit.
        """
        now = datetime.now(timezone.utc)
        started = started_game_ids or set()

        # Index signal picks by player_lookup for fast lookup
        signal_by_key = {}
        for p in signal_picks:
            key = p.get('player_lookup', '')
            if key:
                signal_by_key[key] = p

        # Index published picks by player_lookup
        published_by_key = {}
        for p in published_picks:
            key = p.get('player_lookup', '')
            if key:
                published_by_key[key] = p

        # Index manual picks by player_lookup for source attribution
        manual_by_key = {
            mp.get('player_lookup', ''): mp
            for mp in manual_picks
            if mp.get('player_lookup')
        }

        merged = {}
        stats = {
            'algorithm_picks': 0,
            'manual_picks': 0,
            'locked_picks': 0,
            'new_picks': 0,
            'dropped_from_signal': 0,
        }

        # Step 1+2: Start with published picks, overlay signal data if available
        for key, pub in published_by_key.items():
            pick = dict(pub)
            if key in signal_by_key:
                # Pick still in signal — update volatile fields from fresh data
                sig = signal_by_key[key]
                pick['edge'] = sig.get('edge', pick.get('edge'))
                pick['rank'] = sig.get('rank', pick.get('rank'))
                pick['pick_angles'] = sig.get('pick_angles', pick.get('pick_angles'))
                pick['predicted_points'] = sig.get('predicted_points')
                pick['prediction_correct'] = sig.get('prediction_correct')
                pick['actual_points'] = sig.get('actual_points')
                pick['is_voided'] = sig.get('is_voided')
                pick['void_reason'] = sig.get('void_reason')
                # Ultra gate: only update ultra_tier if game hasn't started
                game_id = pick.get('game_id') or sig.get('game_id', '')
                sig_ultra = self._is_ultra(sig.get('ultra_tier'))
                pub_ultra = self._is_ultra(pub.get('ultra_tier'))
                if game_id in started:
                    # Game started — freeze ultra at published value
                    pick['ultra_tier'] = pub_ultra
                    if sig_ultra and not pub_ultra:
                        logger.warning(
                            f"Ultra blocked (game started): {key} game={game_id} "
                            f"— signal says ultra but game already in progress"
                        )
                else:
                    # Game not started — update ultra from signal
                    pick['ultra_tier'] = sig_ultra
                pick['_last_seen_in_signal'] = now
                pick['_in_signal'] = True
                stats['locked_picks'] += 1
            else:
                # Pick dropped from signal — keep it locked
                pick['_in_signal'] = False
                pick['_last_seen_in_signal'] = pub.get('last_seen_in_signal')
                stats['locked_picks'] += 1
                stats['dropped_from_signal'] += 1
            # Manual picks in manual_by_key always get 'manual' source,
            # even if a prior export stored them as 'algorithm'
            pick['_source'] = 'manual' if key in manual_by_key else pub.get('source', 'algorithm')
            merged[key] = pick

        # Step 3: Add signal picks not yet published (new picks)
        for key, sig in signal_by_key.items():
            if key not in merged:
                pick = dict(sig)
                # Ultra gate: strip ultra from new picks if game has started
                game_id = pick.get('game_id', '')
                if game_id in started and self._is_ultra(pick.get('ultra_tier')):
                    logger.warning(
                        f"Ultra blocked (game started): {key} game={game_id} "
                        f"— new pick, stripping ultra_tier"
                    )
                    pick['ultra_tier'] = False
                # A manual pick written to signal_best_bets_picks (system_id=
                # manual_override) should retain 'manual' source attribution
                is_manual = key in manual_by_key
                pick['_source'] = 'manual' if is_manual else 'algorithm'
                pick['_in_signal'] = True
                pick['_first_published_at'] = now
                pick['_last_seen_in_signal'] = now
                merged[key] = pick
                stats['new_picks'] += 1
                if is_manual:
                    stats['manual_picks'] += 1
                else:
                    stats['algorithm_picks'] += 1

        # Step 4: Add manual picks — override algorithm picks if same player
        for mp in manual_picks:
            key = mp.get('player_lookup', '')
            if not key:
                continue
            existing = merged.get(key)
            if existing and existing.get('_source') == 'manual':
                # Already a manual pick (from published table) — skip
                continue
            pick = dict(mp)
            pick['_source'] = 'manual'
            pick['_in_signal'] = False
            pick['_first_published_at'] = now
            if existing:
                # Manual override of algorithm pick — preserve grading fields
                pick['prediction_correct'] = existing.get('prediction_correct')
                pick['actual_points'] = existing.get('actual_points')
                pick['is_voided'] = existing.get('is_voided')
                pick['void_reason'] = existing.get('void_reason')
                pick['_first_published_at'] = existing.get('_first_published_at', now)
                logger.info(
                    f"Manual override: {key} — replacing algorithm "
                    f"{existing.get('recommendation')} {existing.get('line_value')} "
                    f"with manual {pick.get('recommendation')} {pick.get('line_value')}"
                )
            merged[key] = pick
            stats['manual_picks'] += 1

        # Step 5: Re-rank
        # Active signal picks first (by original rank), then locked-but-dropped,
        # then manual. Within each group, sort by rank then edge.
        def sort_key(p):
            if p.get('_in_signal'):
                group = 0
            elif p.get('_source') == 'manual':
                group = 2
            else:
                group = 1
            return (group, p.get('rank') or 999, -(p.get('edge') or 0))

        sorted_picks = sorted(merged.values(), key=sort_key)
        for i, pick in enumerate(sorted_picks, 1):
            pick['rank'] = i

        # Recount by source (covers all three merge paths)
        stats['algorithm_picks'] = sum(
            1 for p in sorted_picks if p.get('_source') != 'manual'
        )
        stats['manual_picks'] = sum(
            1 for p in sorted_picks if p.get('_source') == 'manual'
        )

        logger.info(
            f"Pick merge: {len(sorted_picks)} total "
            f"({stats['algorithm_picks']} algo, {stats['manual_picks']} manual, "
            f"{stats['dropped_from_signal']} locked-but-dropped, "
            f"{stats['new_picks']} new)"
        )

        return sorted_picks, stats

    @staticmethod
    def _to_iso(val) -> Optional[str]:
        """Convert a datetime, date, or string to ISO format string. Returns None for None."""
        if val is None:
            return None
        if hasattr(val, 'isoformat'):
            return val.isoformat()
        return str(val)

    def _write_published_picks(
        self, target_date: str, merged_picks: List[Dict]
    ) -> None:
        """Persist merged picks to best_bets_published_picks (upsert via MERGE)."""
        if not merged_picks:
            return

        now = datetime.now(timezone.utc)
        rows = []
        for p in merged_picks:
            rows.append({
                'player_lookup': p.get('player_lookup') or '',
                'game_id': p.get('game_id') or '',
                'game_date': target_date,
                'player_name': p.get('player_name') or '',
                'team_abbr': p.get('team_abbr') or '',
                'opponent_team_abbr': p.get('opponent_team_abbr') or '',
                'recommendation': p.get('recommendation') or '',
                'line_value': float(p['line_value']) if p.get('line_value') is not None else None,
                'edge': float(p['edge']) if p.get('edge') is not None else None,
                'rank': p.get('rank'),
                'pick_angles': list(p.get('pick_angles') or []),
                'ultra_tier': p.get('ultra_tier'),
                'source': p.get('_source', 'algorithm'),
                'first_published_at': self._to_iso(
                    p.get('_first_published_at')
                    or p.get('first_published_at')
                    or now
                ),
                'last_seen_in_signal': self._to_iso(
                    p.get('_last_seen_in_signal')
                    or p.get('last_seen_in_signal')
                ),
                'updated_at': now.isoformat(),
            })

        # Atomic partition-level write — WRITE_TRUNCATE on a partition
        # decorator replaces the entire partition in one load job.
        # No race condition: concurrent exports both truncate+write atomically,
        # last one wins with correct data.
        table_id = f'{PROJECT_ID}.nba_predictions.best_bets_published_picks'
        partition_date = target_date.replace('-', '')
        partition_table_id = f'{table_id}${partition_date}'

        try:
            job_config = bigquery.LoadJobConfig(
                schema=[
                    bigquery.SchemaField('player_lookup', 'STRING', mode='REQUIRED'),
                    bigquery.SchemaField('game_id', 'STRING', mode='REQUIRED'),
                    bigquery.SchemaField('game_date', 'DATE', mode='REQUIRED'),
                    bigquery.SchemaField('player_name', 'STRING'),
                    bigquery.SchemaField('team_abbr', 'STRING'),
                    bigquery.SchemaField('opponent_team_abbr', 'STRING'),
                    bigquery.SchemaField('recommendation', 'STRING'),
                    bigquery.SchemaField('line_value', 'NUMERIC'),
                    bigquery.SchemaField('edge', 'NUMERIC'),
                    bigquery.SchemaField('rank', 'INTEGER'),
                    bigquery.SchemaField('pick_angles', 'STRING', mode='REPEATED'),
                    bigquery.SchemaField('ultra_tier', 'STRING'),
                    bigquery.SchemaField('source', 'STRING', mode='REQUIRED'),
                    bigquery.SchemaField('first_published_at', 'TIMESTAMP', mode='REQUIRED'),
                    bigquery.SchemaField('last_seen_in_signal', 'TIMESTAMP'),
                    bigquery.SchemaField('updated_at', 'TIMESTAMP'),
                ],
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            )

            self.bq_client.load_table_from_json(
                rows, partition_table_id, job_config=job_config
            ).result(timeout=30)

            logger.info(f"Wrote {len(rows)} picks to best_bets_published_picks")
        except Exception as e:
            logger.warning(f"Failed to write published picks (non-fatal): {e}")

    def _write_export_audit(
        self,
        target_date: str,
        merged_picks: List[Dict],
        merge_stats: Dict[str, int],
        trigger_source: str = 'scheduled',
    ) -> None:
        """Write an audit snapshot row for this export."""
        export_id = f"exp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        # Build a compact snapshot of the pick list
        snapshot = []
        for p in merged_picks:
            snapshot.append({
                'player_lookup': p.get('player_lookup'),
                'player_name': p.get('player_name'),
                'team': p.get('team_abbr'),
                'opponent': p.get('opponent_team_abbr'),
                'direction': p.get('recommendation'),
                'line': float(p['line_value']) if p.get('line_value') is not None else None,
                'edge': float(p['edge']) if p.get('edge') is not None else None,
                'rank': p.get('rank'),
                'source': p.get('_source', 'algorithm'),
                'in_signal': p.get('_in_signal', True),
            })

        row = {
            'export_id': export_id,
            'game_date': target_date,
            'total_picks': len(merged_picks),
            'algorithm_picks': merge_stats.get('algorithm_picks', 0),
            'manual_picks': merge_stats.get('manual_picks', 0),
            'locked_picks': merge_stats.get('locked_picks', 0),
            'new_picks': merge_stats.get('new_picks', 0),
            'dropped_from_signal': merge_stats.get('dropped_from_signal', 0),
            'picks_snapshot': json.dumps(snapshot, default=str),
            'algorithm_version': ALGORITHM_VERSION,
            'trigger_source': trigger_source,
        }

        table_id = f'{PROJECT_ID}.nba_predictions.best_bets_export_audit'
        try:
            job_config = bigquery.LoadJobConfig(
                schema=[
                    bigquery.SchemaField('export_id', 'STRING', mode='REQUIRED'),
                    bigquery.SchemaField('game_date', 'DATE', mode='REQUIRED'),
                    bigquery.SchemaField('total_picks', 'INTEGER'),
                    bigquery.SchemaField('algorithm_picks', 'INTEGER'),
                    bigquery.SchemaField('manual_picks', 'INTEGER'),
                    bigquery.SchemaField('locked_picks', 'INTEGER'),
                    bigquery.SchemaField('new_picks', 'INTEGER'),
                    bigquery.SchemaField('dropped_from_signal', 'INTEGER'),
                    bigquery.SchemaField('picks_snapshot', 'STRING'),
                    bigquery.SchemaField('algorithm_version', 'STRING'),
                    bigquery.SchemaField('trigger_source', 'STRING'),
                ],
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            )
            self.bq_client.load_table_from_json(
                [row], table_id, job_config=job_config
            ).result(timeout=30)
            logger.info(f"Wrote export audit: {export_id}")
        except Exception as e:
            logger.warning(f"Failed to write export audit (non-fatal): {e}")
