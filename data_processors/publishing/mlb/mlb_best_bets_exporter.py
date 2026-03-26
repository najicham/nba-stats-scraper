#!/usr/bin/env python3
"""
File: data_processors/publishing/mlb/mlb_best_bets_exporter.py

MLB Best Bets Exporter

Exports high-confidence MLB pitcher strikeout picks.

Criteria:
- Confidence >= 70%
- Edge >= 1.0
- OVER or UNDER recommendation (no PASS)

Output: gs://mlb-props-platform-api/v1/mlb/best-bets/{date}.json

Usage:
    exporter = MlbBestBetsExporter()
    result = exporter.export(game_date='2025-08-15')
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple

from data_processors.publishing.base_exporter import BaseExporter
from data_processors.publishing.exporter_utils import safe_float, safe_int

logger = logging.getLogger(__name__)

# Best bets thresholds
MIN_CONFIDENCE = 70
MIN_EDGE = 1.0


class MlbBestBetsExporter(BaseExporter):
    """
    Exports high-confidence MLB picks.

    Schema:
    {
        "generated_at": "2025-08-15T10:00:00Z",
        "game_date": "2025-08-15",
        "criteria": {...},
        "best_bets": [...],
        "summary": {...}
    }
    """

    def __init__(
        self,
        project_id: str = 'nba-props-platform',
        bucket_name: str = 'nba-props-platform-api',
        min_confidence: int = MIN_CONFIDENCE,
        min_edge: float = MIN_EDGE
    ):
        super().__init__(project_id=project_id, bucket_name=bucket_name)
        self.min_confidence = min_confidence
        self.min_edge = min_edge
        logger.info(f"MlbBestBetsExporter initialized (conf>={min_confidence}, edge>={min_edge})")

    def generate_json(self, game_date: str, **kwargs) -> Dict[str, Any]:
        """
        Generate best bets JSON for a date.

        Args:
            game_date: Date to export (YYYY-MM-DD)

        Returns:
            Dictionary ready for JSON export
        """
        logger.info(f"Generating MLB best bets export for {game_date}")

        # Query best bets
        best_bets = self._get_best_bets(game_date)

        # Build summary
        summary = self._build_summary(best_bets)

        return {
            'generated_at': self.get_generated_at(),
            'game_date': game_date,
            'criteria': {
                'min_confidence': self.min_confidence,
                'min_edge': self.min_edge,
                'recommendations': ['OVER', 'UNDER']
            },
            'best_bets': best_bets,
            'summary': summary
        }

    def _get_best_bets(self, game_date: str) -> List[Dict]:
        """Get high-confidence picks for a date."""
        query = f"""
        SELECT
            pitcher_lookup,
            pitcher_name,
            team_abbr,
            opponent_team_abbr,
            is_home,
            strikeouts_line,
            predicted_strikeouts,
            recommendation,
            confidence,
            edge,
            model_version,
            is_correct,
            actual_strikeouts
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{game_date}'
          AND confidence >= {self.min_confidence}
          AND ABS(edge) >= {self.min_edge}
          AND recommendation IN ('OVER', 'UNDER')
        ORDER BY confidence DESC, ABS(edge) DESC
        """

        rows = self.query_to_list(query)

        best_bets = []
        for row in rows:
            bet = {
                'pitcher_id': row.get('pitcher_lookup'),
                'pitcher_name': row.get('pitcher_name'),
                'team': row.get('team_abbr'),
                'opponent': row.get('opponent_team_abbr'),
                'is_home': bool(row.get('is_home')),
                'strikeouts_line': safe_float(row.get('strikeouts_line'), default=0.0),
                'predicted_strikeouts': safe_float(row.get('predicted_strikeouts'), default=0.0, precision=1),
                'recommendation': row.get('recommendation'),
                'confidence': safe_int(row.get('confidence'), default=0),
                'edge': safe_float(row.get('edge'), default=0.0),
                'model_version': row.get('model_version'),
                'rank': len(best_bets) + 1
            }

            # Add grading if available
            if row.get('is_correct') is not None:
                bet['is_correct'] = row.get('is_correct')
                bet['actual_strikeouts'] = row.get('actual_strikeouts')

            best_bets.append(bet)

        return best_bets

    def _build_summary(self, best_bets: List[Dict]) -> Dict[str, Any]:
        """Build summary statistics."""
        total = len(best_bets)
        over_picks = sum(1 for b in best_bets if b.get('recommendation') == 'OVER')
        under_picks = sum(1 for b in best_bets if b.get('recommendation') == 'UNDER')

        # Average metrics
        avg_confidence = sum(b.get('confidence', 0) for b in best_bets) / total if total else 0
        avg_edge = sum(abs(b.get('edge', 0)) for b in best_bets) / total if total else 0

        # Grading if available
        graded = [b for b in best_bets if b.get('is_correct') is not None]
        grading_summary = None
        if graded:
            correct = sum(1 for b in graded if b.get('is_correct') == True)
            grading_summary = {
                'graded': len(graded),
                'correct': correct,
                'accuracy': round(100 * correct / len(graded), 1) if graded else 0
            }

        return {
            'total_best_bets': total,
            'over_picks': over_picks,
            'under_picks': under_picks,
            'avg_confidence': round(avg_confidence, 1),
            'avg_edge': round(avg_edge, 2),
            'grading': grading_summary
        }

    def export(self, game_date: str, **kwargs) -> str:
        """
        Generate and upload best bets to GCS.

        Args:
            game_date: Date to export

        Returns:
            GCS path of uploaded file
        """
        json_data = self.generate_json(game_date, **kwargs)
        path = f"mlb/best-bets/{game_date}.json"

        return self.upload_to_gcs(
            json_data,
            path,
            cache_control='public, max-age=60'
        )

    # -----------------------------------------------------------------------
    # all.json support (frontend BestBetsAllResponse shape)
    # -----------------------------------------------------------------------

    def _map_to_frontend_pick(self, row: Dict, rank: int) -> Dict:
        """Map a BQ pitcher_strikeouts row to the frontend BestBetsPick shape."""
        is_correct = row.get('is_correct')
        actual = row.get('actual_strikeouts')

        if is_correct is True:
            result = 'WIN'
        elif is_correct is False:
            result = 'LOSS'
        else:
            result = None

        game_time = row.get('game_time')
        if game_time and hasattr(game_time, 'isoformat'):
            game_time = game_time.isoformat()

        return {
            'rank': rank,
            'player': row.get('pitcher_name'),
            'player_lookup': row.get('pitcher_lookup'),
            'team': row.get('team_abbr'),
            'opponent': row.get('opponent_team_abbr'),
            'home': bool(row.get('is_home')),
            'direction': row.get('recommendation'),
            'stat': 'K',
            'line': safe_float(row.get('strikeouts_line'), default=0.0),
            'edge': safe_float(row.get('edge'), default=0.0),
            'angles': [],
            'game_time': game_time,
            'is_ultra': False,
            'actual': safe_int(actual) if actual is not None else None,
            'result': result,
            'sport': 'mlb',
        }

    def _compute_record(self, graded_rows: List[Dict]) -> Dict:
        """Compute wins/losses/pct from a list of rows with is_correct field."""
        wins = sum(1 for r in graded_rows if r.get('is_correct') is True)
        losses = sum(1 for r in graded_rows if r.get('is_correct') is False)
        total = wins + losses
        pct = round(wins / total, 3) if total > 0 else 0.0
        return {'wins': wins, 'losses': losses, 'pct': pct}

    def _compute_streak(self, graded_rows: List[Dict]) -> Tuple[Dict, Dict]:
        """
        Compute current streak and best streak.

        Args:
            graded_rows: Rows sorted oldest-first with game_date and is_correct.

        Returns:
            (current_streak, best_streak) — each is {'type': 'W'|'L', 'count': N}
        """
        if not graded_rows:
            return {'type': 'W', 'count': 0}, {'type': 'W', 'count': 0}

        # Sort oldest → newest
        sorted_rows = sorted(graded_rows, key=lambda r: str(r.get('game_date', '')))

        # Best streak (walk forward)
        best_count = 0
        best_type = 'W'
        run_count = 0
        run_type: Optional[str] = None
        for row in sorted_rows:
            t = 'W' if row.get('is_correct') is True else 'L'
            if t == run_type:
                run_count += 1
            else:
                run_type = t
                run_count = 1
            if run_count > best_count:
                best_count = run_count
                best_type = t

        # Current streak (walk backward from most recent)
        last_type = 'W' if sorted_rows[-1].get('is_correct') is True else 'L'
        current_count = 0
        for row in reversed(sorted_rows):
            t = 'W' if row.get('is_correct') is True else 'L'
            if t == last_type:
                current_count += 1
            else:
                break

        return (
            {'type': last_type, 'count': current_count},
            {'type': best_type, 'count': best_count},
        )

    def _build_weekly_history(self, graded_rows: List[Dict]) -> List[Dict]:
        """
        Build weekly history (last 8 weeks) from graded picks.

        Returns list of BestBetsWeek dicts, most recent week first.
        """
        if not graded_rows:
            return []

        # Group by date string
        picks_by_date: Dict[str, List[Dict]] = defaultdict(list)
        for row in graded_rows:
            game_date_str = str(row.get('game_date', ''))
            picks_by_date[game_date_str].append(row)

        # Group dates by ISO week (Monday = week start)
        picks_by_week: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
        for game_date_str, rows in picks_by_date.items():
            try:
                d = date.fromisoformat(game_date_str)
                week_start = (d - timedelta(days=d.weekday())).isoformat()
                picks_by_week[week_start][game_date_str].extend(rows)
            except ValueError:
                continue

        weeks = []
        for week_start_str in sorted(picks_by_week.keys(), reverse=True)[:8]:
            dates_in_week = picks_by_week[week_start_str]

            days = []
            for game_date_str in sorted(dates_in_week.keys(), reverse=True):
                day_rows = dates_in_week[game_date_str]
                graded = [r for r in day_rows if r.get('is_correct') is not None]
                wins = sum(1 for r in graded if r.get('is_correct') is True)
                losses = len(graded) - wins

                if not graded:
                    status = 'pending'
                elif wins == len(graded):
                    status = 'sweep'
                elif losses == len(graded):
                    status = 'miss'
                else:
                    status = 'split'

                sorted_rows = sorted(day_rows, key=lambda r: abs(r.get('edge') or 0), reverse=True)
                day_picks = [self._map_to_frontend_pick(r, i + 1) for i, r in enumerate(sorted_rows)]

                days.append({
                    'date': game_date_str,
                    'status': status,
                    'record': self._compute_record(graded),
                    'picks': day_picks,
                })

            # Week record across all graded picks in week
            all_week_graded = [r for rows in dates_in_week.values() for r in rows if r.get('is_correct') is not None]

            weeks.append({
                'week_start': week_start_str,
                'record': self._compute_record(all_week_graded),
                'days': days,
            })

        return weeks

    def export_all(self, today: Optional[str] = None) -> str:
        """
        Generate and upload mlb/best-bets/all.json (frontend BestBetsAllResponse).

        Args:
            today: Date string YYYY-MM-DD (defaults to today)

        Returns:
            GCS path of uploaded file
        """
        if today is None:
            today = date.today().isoformat()

        logger.info(f"Generating MLB all.json for {today}")

        SEASON_START = '2026-03-27'  # MLB Opening Day 2026

        query = f"""
        SELECT
            CAST(game_date AS STRING) AS game_date,
            pitcher_lookup,
            pitcher_name,
            team_abbr,
            opponent_team_abbr,
            is_home,
            strikeouts_line,
            predicted_strikeouts,
            recommendation,
            confidence,
            edge,
            model_version,
            is_correct,
            actual_strikeouts,
            game_time
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date >= '{SEASON_START}'
          AND game_date <= '{today}'
          AND confidence >= {self.min_confidence}
          AND ABS(edge) >= {self.min_edge}
          AND recommendation IN ('OVER', 'UNDER')
        ORDER BY game_date ASC, edge DESC
        """

        all_rows = self.query_to_list(query)

        # Split today's picks from history
        today_rows = [r for r in all_rows if r.get('game_date') == today]
        graded_rows = [r for r in all_rows if r.get('is_correct') is not None]

        # Today's picks ranked by edge
        today_sorted = sorted(today_rows, key=lambda r: abs(r.get('edge') or 0), reverse=True)
        today_picks = [self._map_to_frontend_pick(r, i + 1) for i, r in enumerate(today_sorted)]

        # Record windows
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1).strftime('%Y-%m-%d')
        week_start = (now.date() - timedelta(days=7)).isoformat()

        record = {
            'season': self._compute_record([r for r in graded_rows if r.get('game_date', '') >= SEASON_START]),
            'month': self._compute_record([r for r in graded_rows if r.get('game_date', '') >= month_start]),
            'week': self._compute_record([r for r in graded_rows if r.get('game_date', '') >= week_start]),
            'last_10': self._compute_record(
                sorted(graded_rows, key=lambda r: r.get('game_date', ''), reverse=True)[:10]
            ),
        }

        streak, best_streak = self._compute_streak(graded_rows)
        weeks = self._build_weekly_history(graded_rows)

        json_data = {
            'date': today,
            'season': today[:4],
            'generated_at': self.get_generated_at(),
            'record': record,
            'streak': streak,
            'best_streak': best_streak,
            'today': today_picks,
            'weeks': weeks,
            'total_picks': len(graded_rows) + len(today_rows),
            'graded': len(graded_rows),
        }

        return self.upload_to_gcs(
            json_data,
            'mlb/best-bets/all.json',
            cache_control='public, max-age=60'
        )


def main():
    """Main entry point."""
    import argparse
    from datetime import date

    parser = argparse.ArgumentParser(
        description='MLB Best Bets Exporter'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=date.today().isoformat(),
        help='Date to export (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--min-confidence',
        type=int,
        default=MIN_CONFIDENCE,
        help='Minimum confidence threshold'
    )
    parser.add_argument(
        '--min-edge',
        type=float,
        default=MIN_EDGE,
        help='Minimum edge threshold'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Generate JSON but do not upload'
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    exporter = MlbBestBetsExporter(
        min_confidence=args.min_confidence,
        min_edge=args.min_edge
    )

    if args.dry_run:
        import json
        result = exporter.generate_json(args.date)
        print(json.dumps(result, indent=2))
    else:
        gcs_path = exporter.export(args.date)
        print(f"Exported to: {gcs_path}")


if __name__ == '__main__':
    main()
