"""MLB Signal Best Bets Exporter — port of NBA signal_best_bets_exporter.py.

Pipeline:
  1. Load predictions for game_date
  2. Apply direction filter (OVER-only until UNDER signals validated)
  3. Apply negative filters (bullpen_game, il_return, pitch_count_cap, insufficient_data)
  4. Apply edge floor (phase-aware: Phase 1 = 2.0, Phase 2 = 1.0) — with signal rescue
  5. Evaluate all active + shadow signals
  6. Gate: signal_count >= 2 (OVER) or >= 3 (UNDER, higher bar)
  7. Rank: OVER by edge, UNDER by signal quality
  8. Build pick angles (human-readable reasoning)
  9. Write to mlb_predictions.signal_best_bets_picks
 10. Write filter audit to mlb_predictions.best_bets_filter_audit

Season Phases (Session 433 — walk-forward validated):
  Phase 1 (season start → day 45): OVER-only, edge >= 2.0
    - April is historically 47-50% HR, conservative threshold protects bankroll
  Phase 2 (day 45+): OVER + qualified UNDER, edge >= 1.0
    - OVER at edge 1.0: 56% HR, +7.1% ROI (walk-forward 2025)
    - UNDER requires 3+ real signals (higher bar — raw UNDER is 47-49%)
  June tightening: edge >= 1.5 during ASB approach (June 15 - July 20)
    - June is consistently worst month (46-51%)
"""

import logging
import os
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Tuple
from ml.signals.mlb.registry import build_mlb_registry, MLBSignalRegistry
from ml.signals.mlb.base_signal import MLBSignalResult

logger = logging.getLogger(__name__)

# =============================================================================
# SEASON PHASE CONFIGURATION (walk-forward validated Session 433)
# =============================================================================

# Default edge floor (overridden by phase logic)
DEFAULT_EDGE_FLOOR = 1.0  # K

# Phase thresholds
PHASE_1_EDGE_FLOOR = 2.0   # Conservative early-season (OVER e2.0 = 58% HR)
PHASE_2_EDGE_FLOOR = 1.0   # Full production (OVER e1.0 = 56% HR)
JUNE_EDGE_FLOOR = 1.5      # Tightened during ASB approach

# How many days into season before Phase 2
PHASE_1_DURATION_DAYS = 45  # ~mid-May

# UNDER direction control
# UNDER is unprofitable without signal filtering (47-49% HR walk-forward)
# Only surface UNDER with strong signal backing
UNDER_ENABLED = os.environ.get('MLB_UNDER_ENABLED', 'false').lower() == 'true'
UNDER_MIN_SIGNALS = 3  # Higher bar than OVER (which uses 2)

# Minimum real signal count for best bets (OVER)
MIN_SIGNAL_COUNT = 2

# Base signals that inflate signal count with zero value
BASE_SIGNAL_TAGS = frozenset(['high_edge'])

# Signal rescue tags — picks can bypass edge floor if they have these signals
RESCUE_SIGNAL_TAGS = frozenset([
    'swstr_surge',
    'opponent_k_prone',
    'ballpark_k_boost',
])

# UNDER signal weights for quality-based ranking
UNDER_SIGNAL_WEIGHTS = {
    'velocity_drop_under': 2.0,
    'short_rest_under': 1.5,
    'high_variance_under': 1.5,
    'weather_cold_under': 1.0,
    'pitch_count_limit_under': 2.0,
}

# MLB season start dates (approximate — updated yearly)
MLB_SEASON_STARTS = {
    2025: date(2025, 3, 27),
    2026: date(2026, 3, 26),
    2027: date(2027, 4, 1),
}

# June tightening window (ASB approach — June 15 to July 20)
JUNE_TIGHTEN_START_MONTH_DAY = (6, 15)  # June 15
JUNE_TIGHTEN_END_MONTH_DAY = (7, 20)    # July 20


class MLBBestBetsExporter:
    """Generate MLB best bets from predictions + signals."""

    def __init__(self, bq_client=None, project_id: str = "nba-props-platform"):
        self.project_id = project_id
        self.bq_client = bq_client
        self.registry = build_mlb_registry()
        self.filter_audit: List[Dict] = []

    def _get_bq_client(self):
        if self.bq_client is None:
            from shared.clients.bigquery_pool import get_bigquery_client
            self.bq_client = get_bigquery_client(project_id=self.project_id)
        return self.bq_client

    def _get_season_phase(self, game_date_str: str) -> dict:
        """Determine season phase and applicable thresholds.

        Returns dict with:
          phase: 1 or 2
          edge_floor: float
          under_enabled: bool
          under_min_signals: int
          reason: str
        """
        gd = date.fromisoformat(game_date_str)
        year = gd.year
        season_start = MLB_SEASON_STARTS.get(year, date(year, 3, 28))
        days_into_season = (gd - season_start).days

        # June tightening check (overrides phase)
        tighten_start = date(year, *JUNE_TIGHTEN_START_MONTH_DAY)
        tighten_end = date(year, *JUNE_TIGHTEN_END_MONTH_DAY)
        in_june_window = tighten_start <= gd <= tighten_end

        if days_into_season < PHASE_1_DURATION_DAYS:
            return {
                'phase': 1,
                'edge_floor': PHASE_1_EDGE_FLOOR,
                'under_enabled': False,
                'under_min_signals': UNDER_MIN_SIGNALS,
                'reason': f'Phase 1 (day {days_into_season}/{PHASE_1_DURATION_DAYS}): '
                          f'OVER-only, edge >= {PHASE_1_EDGE_FLOOR}',
            }
        elif in_june_window:
            return {
                'phase': 2,
                'edge_floor': JUNE_EDGE_FLOOR,
                'under_enabled': UNDER_ENABLED,
                'under_min_signals': UNDER_MIN_SIGNALS,
                'reason': f'Phase 2 + June tightening: edge >= {JUNE_EDGE_FLOOR}',
            }
        else:
            return {
                'phase': 2,
                'edge_floor': PHASE_2_EDGE_FLOOR,
                'under_enabled': UNDER_ENABLED,
                'under_min_signals': UNDER_MIN_SIGNALS,
                'reason': f'Phase 2 (day {days_into_season}): '
                          f'edge >= {PHASE_2_EDGE_FLOOR}, UNDER={UNDER_ENABLED}',
            }

    def export(
        self,
        predictions: List[Dict],
        game_date: str,
        features_by_pitcher: Optional[Dict[str, Dict]] = None,
        supplemental_by_pitcher: Optional[Dict[str, Dict]] = None,
        edge_floor: Optional[float] = None,
        min_signals: int = MIN_SIGNAL_COUNT,
        dry_run: bool = False,
    ) -> List[Dict]:
        """Run the full best bets pipeline.

        Args:
            predictions: List of prediction dicts from prediction systems
            game_date: Target game date (YYYY-MM-DD)
            features_by_pitcher: {pitcher_lookup: {feature_dict}}
            supplemental_by_pitcher: {pitcher_lookup: {supplemental_dict}}
            edge_floor: Override edge floor (None = use phase-aware default)
            min_signals: Minimum real signal count for OVER (default 2)
            dry_run: If True, don't write to BQ

        Returns:
            List of best bet picks
        """
        features_by_pitcher = features_by_pitcher or {}
        supplemental_by_pitcher = supplemental_by_pitcher or {}
        self.filter_audit = []

        # Determine season phase
        phase = self._get_season_phase(game_date)
        effective_edge_floor = edge_floor if edge_floor is not None else phase['edge_floor']

        logger.info(f"[MLB BB] Processing {len(predictions)} predictions for {game_date}")
        logger.info(f"[MLB BB] {phase['reason']}")

        # 1. Filter to actionable predictions (OVER/UNDER with line)
        allowed_directions = ['OVER']
        if phase['under_enabled']:
            allowed_directions.append('UNDER')

        actionable = []
        for p in predictions:
            rec = p.get('recommendation')
            if (rec in allowed_directions
                    and p.get('strikeouts_line') is not None
                    and p.get('predicted_strikeouts') is not None):
                actionable.append(p)
            elif rec == 'UNDER' and not phase['under_enabled']:
                # Record UNDER blocks in audit for tracking
                self.filter_audit.append({
                    'game_date': game_date,
                    'pitcher_lookup': p.get('pitcher_lookup', ''),
                    'system_id': p.get('system_id', 'unknown'),
                    'filter_name': 'direction_filter',
                    'filter_result': 'BLOCKED',
                    'filter_reason': 'UNDER disabled (walk-forward: 47-49% HR without signals)',
                    'recommendation': rec,
                    'edge': p.get('edge'),
                    'line_value': p.get('strikeouts_line'),
                })

        logger.info(f"[MLB BB] {len(actionable)} actionable predictions "
                    f"(directions: {allowed_directions})")

        # 2. Apply negative filters
        passed_filters = []
        for pred in actionable:
            pitcher = pred.get('pitcher_lookup', '')
            features = features_by_pitcher.get(pitcher, {})
            supplemental = supplemental_by_pitcher.get(pitcher, {})

            blocked = False
            for filt in self.registry.negative_filters():
                result = filt.evaluate(pred, features, supplemental)
                audit_entry = {
                    'game_date': game_date,
                    'pitcher_lookup': pitcher,
                    'system_id': pred.get('system_id', 'unknown'),
                    'filter_name': filt.tag,
                    'filter_result': 'BLOCKED' if result.qualifies else 'PASSED',
                    'filter_reason': result.metadata.get('reason') if result.qualifies else None,
                    'recommendation': pred.get('recommendation'),
                    'edge': pred.get('edge'),
                    'line_value': pred.get('strikeouts_line'),
                }
                self.filter_audit.append(audit_entry)

                if result.qualifies:
                    blocked = True
                    logger.debug(f"[MLB BB] {pitcher} BLOCKED by {filt.tag}: {result.metadata}")
                    break

            if not blocked:
                passed_filters.append(pred)

        logger.info(f"[MLB BB] {len(passed_filters)} passed negative filters "
                    f"({len(actionable) - len(passed_filters)} blocked)")

        # 3. Edge floor + signal rescue
        edge_eligible = []
        for pred in passed_filters:
            edge = abs(pred.get('edge', 0))
            pitcher = pred.get('pitcher_lookup', '')

            if edge >= effective_edge_floor:
                edge_eligible.append((pred, False))  # (pred, rescued)
                continue

            # Signal rescue: check if any rescue signals fire
            features = features_by_pitcher.get(pitcher, {})
            supplemental = supplemental_by_pitcher.get(pitcher, {})
            rescued = False
            rescue_signal = None
            for tag in RESCUE_SIGNAL_TAGS:
                signal = self.registry.get(tag)
                result = signal.evaluate(pred, features, supplemental)
                if result.qualifies:
                    rescued = True
                    rescue_signal = tag
                    break

            if rescued:
                edge_eligible.append((pred, True))
                logger.debug(f"[MLB BB] {pitcher} RESCUED by {rescue_signal} (edge={edge:.1f})")
            else:
                self.filter_audit.append({
                    'game_date': game_date,
                    'pitcher_lookup': pitcher,
                    'system_id': pred.get('system_id', 'unknown'),
                    'filter_name': 'edge_floor',
                    'filter_result': 'BLOCKED',
                    'filter_reason': f'Edge {edge:.1f} < {effective_edge_floor} (phase {phase["phase"]})',
                    'recommendation': pred.get('recommendation'),
                    'edge': pred.get('edge'),
                    'line_value': pred.get('strikeouts_line'),
                })

        logger.info(f"[MLB BB] {len(edge_eligible)} passed edge floor")

        # 4. Evaluate all signals for eligible picks
        annotated_picks = []
        for pred, was_rescued in edge_eligible:
            pitcher = pred.get('pitcher_lookup', '')
            features = features_by_pitcher.get(pitcher, {})
            supplemental = supplemental_by_pitcher.get(pitcher, {})

            signal_tags = []
            signal_count = 0
            real_signal_count = 0
            signal_results = {}

            for signal in self.registry.all():
                if signal.is_negative_filter:
                    continue
                result = signal.evaluate(pred, features, supplemental)
                if result.qualifies:
                    signal_tags.append(signal.tag)
                    signal_count += 1
                    signal_results[signal.tag] = result
                    if signal.tag not in BASE_SIGNAL_TAGS:
                        real_signal_count += 1

            annotated_picks.append({
                **pred,
                'signal_tags': signal_tags,
                'signal_count': signal_count,
                'real_signal_count': real_signal_count,
                'signal_results': signal_results,
                'signal_rescued': was_rescued,
                'rescue_signal': None,  # TODO: track which signal
            })

        # 5. Signal count gate (UNDER has higher bar)
        gated_picks = []
        for p in annotated_picks:
            if p['recommendation'] == 'UNDER':
                required = phase['under_min_signals']
            else:
                required = min_signals
            if p['real_signal_count'] >= required:
                gated_picks.append(p)

        over_gated = sum(1 for p in gated_picks if p['recommendation'] == 'OVER')
        under_gated = sum(1 for p in gated_picks if p['recommendation'] == 'UNDER')
        logger.info(f"[MLB BB] {len(gated_picks)} passed signal count gate "
                    f"(OVER: {over_gated} >= {min_signals} signals, "
                    f"UNDER: {under_gated} >= {phase['under_min_signals']} signals)")

        # 6. Rank picks
        over_picks = [p for p in gated_picks if p['recommendation'] == 'OVER']
        under_picks = [p for p in gated_picks if p['recommendation'] == 'UNDER']

        # OVER: rank by edge (higher = better)
        over_picks.sort(key=lambda p: abs(p.get('edge', 0)), reverse=True)

        # UNDER: rank by weighted signal quality (same lesson as NBA)
        for pick in under_picks:
            quality = 0.0
            for tag, result in pick.get('signal_results', {}).items():
                weight = UNDER_SIGNAL_WEIGHTS.get(tag, 1.0)
                quality += result.confidence * weight
            pick['under_signal_quality'] = round(quality, 4)
        under_picks.sort(key=lambda p: p.get('under_signal_quality', 0), reverse=True)

        # Combine and assign ranks
        ranked_picks = over_picks + under_picks
        for i, pick in enumerate(ranked_picks, 1):
            pick['rank'] = i

        # 7. Build pick angles
        for pick in ranked_picks:
            pick['pick_angles'] = self._build_pick_angles(pick)

        # 8. Write to BigQuery
        if not dry_run and ranked_picks:
            self._write_best_bets(ranked_picks, game_date)
            self._write_filter_audit(game_date)

        logger.info(f"[MLB BB] Final best bets: {len(ranked_picks)} "
                    f"(OVER: {len(over_picks)}, UNDER: {len(under_picks)})")

        return ranked_picks

    def _build_pick_angles(self, pick: Dict) -> List[str]:
        """Build human-readable pick angles from signal results."""
        angles = []
        rec = pick.get('recommendation', '')
        pitcher = pick.get('pitcher_lookup', '').replace('_', ' ').title()
        edge = pick.get('edge', 0)
        line = pick.get('strikeouts_line')

        if rec == 'OVER':
            angles.append(f"Model projects {pick.get('predicted_strikeouts', '?')} K "
                         f"vs line {line} ({edge:+.1f} edge)")
        else:
            angles.append(f"Model projects {pick.get('predicted_strikeouts', '?')} K "
                         f"vs line {line} ({edge:+.1f} edge)")

        signal_results = pick.get('signal_results', {})

        if 'swstr_surge' in signal_results:
            meta = signal_results['swstr_surge'].metadata
            angles.append(f"SwStr% surge: +{meta.get('surge_pct', 0):.1%} above season avg")

        if 'velocity_drop_under' in signal_results:
            meta = signal_results['velocity_drop_under'].metadata
            angles.append(f"Velocity down {meta.get('velocity_drop_mph', 0):.1f} mph from season avg")

        if 'opponent_k_prone' in signal_results:
            meta = signal_results['opponent_k_prone'].metadata
            angles.append(f"Opponent K-rate {meta.get('opponent_k_rate', 0):.1%} (top 25%)")

        if 'short_rest_under' in signal_results:
            meta = signal_results['short_rest_under'].metadata
            angles.append(f"Short rest: {meta.get('days_rest', '?')} days")

        if 'high_variance_under' in signal_results:
            meta = signal_results['high_variance_under'].metadata
            angles.append(f"High K variance: {meta.get('k_std', 0):.1f} std dev last 10")

        if 'ballpark_k_boost' in signal_results:
            meta = signal_results['ballpark_k_boost'].metadata
            angles.append(f"K-friendly ballpark: {meta.get('ballpark_k_factor', 0):.3f} factor")

        if 'umpire_k_friendly' in signal_results:
            meta = signal_results['umpire_k_friendly'].metadata
            angles.append(f"K-friendly umpire: {meta.get('umpire_k_rate', 0):.1%} K rate")

        if 'ace_pitcher_over' in signal_results:
            meta = signal_results['ace_pitcher_over'].metadata
            angles.append(f"Elite K rate: {meta.get('k_per_9', 0):.1f} K/9")

        if 'projection_agrees_over' in signal_results:
            meta = signal_results['projection_agrees_over'].metadata
            angles.append(f"Projection confirms: +{meta.get('projection_diff', 0):.1f} K above line")

        if 'k_trending_over' in signal_results:
            meta = signal_results['k_trending_over'].metadata
            angles.append(f"K trending up: {meta.get('k_last_3', 0):.1f} avg last 3 "
                         f"vs {meta.get('k_last_10', 0):.1f} last 10 (+{meta.get('trend', 0):.1f})")

        if 'recent_k_above_line' in signal_results:
            meta = signal_results['recent_k_above_line'].metadata
            angles.append(f"Recent K avg exceeds line by {meta.get('k_avg_vs_line', 0):.1f} K")

        return angles

    def _write_best_bets(self, picks: List[Dict], game_date: str):
        """Write best bets to signal_best_bets_picks table."""
        client = self._get_bq_client()
        table_id = f"{self.project_id}.mlb_predictions.signal_best_bets_picks"

        # Scoped delete: only delete for pitchers we're refreshing
        pitcher_lookups = [p['pitcher_lookup'] for p in picks]
        if pitcher_lookups:
            placeholders = ", ".join(f"'{pl}'" for pl in pitcher_lookups)
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE game_date = '{game_date}'
              AND pitcher_lookup IN ({placeholders})
            """
            try:
                client.query(delete_query).result()
            except Exception as e:
                logger.warning(f"Delete before insert failed: {e}")

        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for pick in picks:
            rows.append({
                'pitcher_lookup': pick['pitcher_lookup'],
                'game_pk': pick.get('game_pk'),
                'game_date': game_date,
                'system_id': pick.get('system_id', 'unknown'),
                'pitcher_name': pick.get('pitcher_name'),
                'team_abbr': pick.get('team_abbr'),
                'opponent_team_abbr': pick.get('opponent_team_abbr'),
                'predicted_strikeouts': pick.get('predicted_strikeouts'),
                'line_value': pick.get('strikeouts_line'),
                'recommendation': pick.get('recommendation'),
                'edge': pick.get('edge'),
                'confidence_score': pick.get('confidence'),
                'signal_tags': pick.get('signal_tags', []),
                'signal_count': pick.get('signal_count', 0),
                'real_signal_count': pick.get('real_signal_count', 0),
                'rank': pick.get('rank'),
                'pick_angles': pick.get('pick_angles', []),
                'algorithm_version': f'mlb_v2_phase{phase["phase"]}',
                'signal_rescued': pick.get('signal_rescued', False),
                'rescue_signal': pick.get('rescue_signal'),
                'under_signal_quality': pick.get('under_signal_quality'),
                'created_at': now,
            })

        if rows:
            try:
                errors = client.insert_rows_json(table_id, rows)
                if errors:
                    logger.error(f"Insert errors: {errors[:3]}")
                else:
                    logger.info(f"Wrote {len(rows)} best bets to {table_id}")
            except Exception as e:
                logger.error(f"Failed to write best bets: {e}")

    def _write_filter_audit(self, game_date: str):
        """Write filter audit records to best_bets_filter_audit table."""
        if not self.filter_audit:
            return

        client = self._get_bq_client()
        table_id = f"{self.project_id}.mlb_predictions.best_bets_filter_audit"

        now = datetime.now(timezone.utc).isoformat()
        rows = [{**entry, 'created_at': now} for entry in self.filter_audit]

        try:
            errors = client.insert_rows_json(table_id, rows)
            if errors:
                logger.error(f"Filter audit insert errors: {errors[:3]}")
            else:
                logger.info(f"Wrote {len(rows)} filter audit records")
        except Exception as e:
            logger.error(f"Failed to write filter audit: {e}")
