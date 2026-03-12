"""MLB Pitcher Strikeout Signals — 18 active + 22 shadow + 6 negative filters + 2 observation.

Active Signals (17):
  high_edge                       — Edge >= 1.0 K (base signal)
  velocity_drop_under             — FB velocity down 1.5+ mph
  opponent_k_prone                — Team K-rate top 25%
  short_rest_under                — < 4 days rest
  high_variance_under             — K std > 3.5 last 10
  ballpark_k_boost                — Park K-factor > 1.05
  umpire_k_friendly               — Umpire K-rate top 25%
  projection_agrees_over          — BettingPros proj > line + 0.5 (Session 433)
  k_trending_over                 — K avg last 3 > last 10 + 1.0 (Session 433)
  recent_k_above_line             — K avg last 5 > line (Session 433)
  regressor_projection_agrees_over — Projection value > line (regressor, Session 441)
  home_pitcher_over               — Pitcher is at home (Session 441)
  long_rest_over                  — Pitcher on 8+ days rest (Session 441)
  high_csw_over                   — CSW% >= 30% (Session 460, promoted)
  elite_peripherals_over          — FIP < 3.5 + K/9 >= 9.0 (Session 460, promoted)
  pitch_efficiency_depth_over     — IP avg >= 6.0 (Session 460, promoted)
  day_game_shadow_over            — Day game visibility (Session 464, promoted)
  pitcher_on_roll_over            — K avg L3 AND L5 > line (Session 464, promoted)

Shadow Signals (21):
  swstr_surge           — SwStr% last 3 > season avg + 2% (demoted S447, 55.2% HR)
  line_movement_over    — Line dropped 0.5+ from open
  weather_cold_under    — Temp < 50F
  platoon_advantage     — Pitcher hand vs lineup handedness
  ace_pitcher_over      — Top 20% K/9 pitcher
  catcher_framing_over  — Elite catcher framing
  pitch_count_limit_under — Documented pitch count cap
  cold_weather_k_over   — Temp < 60F not dome (Session 460)
  lineup_k_spike_over   — Lineup K% >= 26% vs hand (Session 460)
  short_starter_under   — IP avg < 5.0 (Session 460)
  game_total_low_over   — Game total <= 7.5 (Session 460)
  heavy_favorite_over   — ML <= -180 (Session 460)
  bottom_up_agrees_over — Bottom-up K > line (Session 460)
  catcher_framing_poor_under — Poor framing runs <= -3.0 (Session 460)
  rematch_familiarity_under — 3+ games vs opponent (Session 460)
  cumulative_arm_stress_under — High pitch count + heavy workload (Session 460)
  taxed_bullpen_over    — 10+ bullpen IP last 3 games (Session 460)
  k_rate_reversion_under — K avg last 3 >> season avg (Session 464)
  k_rate_bounce_over    — K avg last 3 << season avg (Session 464)
  umpire_csw_combo_over — K-friendly ump + high CSW (Session 464)
  rest_workload_stress_under — Short rest + high workload (Session 464)
  low_era_high_k_combo_over — ERA < 3.0 + K/9 >= 8.5 (Session 464)

Negative Filters (6):
  bullpen_game_skip     — Opener/bullpen game detected
  il_return_skip        — First start from IL
  pitch_count_cap_skip  — Under-only: documented pitch count cap
  insufficient_data_skip — < 3 career starts
  pitcher_blacklist     — Block pitchers with <45% HR (Session 447, expanded to 28)
  whole_line_over       — Block OVER on whole-number lines (Session 443, +9.6pp structural)

Observation Filters (2) — log but don't block, cross-season unstable:
  bad_opponent_over_obs — OVER vs low-K opponents (Session 443: r=-0.29 cross-season)
  bad_venue_over_obs    — OVER at K-unfriendly venues (Session 443: confounded with team)
"""

from typing import Dict, Optional
from ml.signals.mlb.base_signal import BaseMLBSignal, MLBSignalResult


# =============================================================================
# ACTIVE SIGNALS (8)
# =============================================================================

class HighEdgeSignal(BaseMLBSignal):
    """Edge >= 1.0 K — basic edge threshold signal."""
    tag = "high_edge"
    description = "Model edge >= 1.0 strikeouts vs line"
    direction = ""

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        edge = prediction.get('edge')
        recommendation = prediction.get('recommendation', '')
        if edge is None:
            return self._no_qualify()

        if recommendation == 'OVER' and edge >= 1.0:
            return self._qualify(confidence=min(1.0, edge / 3.0), edge=edge)
        elif recommendation == 'UNDER' and edge <= -1.0:
            return self._qualify(confidence=min(1.0, abs(edge) / 3.0), edge=edge)
        return self._no_qualify()


class SwStrSurgeSignal(BaseMLBSignal):
    """SwStr% last 3 starts > season avg + 2% — pitcher stuff is improving.

    Session 447: Demoted to shadow. 55.2% HR on 58 picks in season replay — inflates
    signal_count without adding value. Removed from rescue in Session 444.
    """
    tag = "swstr_surge"
    description = "SwStr% last 3 starts elevated vs season average"
    direction = "OVER"
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        swstr_last_3 = features.get('swstr_pct_last_3') or supplemental.get('swstr_pct_last_3') if supplemental else None
        swstr_season = features.get('season_swstr_pct')

        if swstr_last_3 is None or swstr_season is None:
            return self._no_qualify()

        surge = swstr_last_3 - swstr_season
        if surge >= 0.02:  # 2 percentage points above season avg
            conf = min(1.0, surge / 0.05)  # Max confidence at +5%
            return self._qualify(confidence=conf, surge_pct=round(surge, 4))
        return self._no_qualify()


class VelocityDropUnderSignal(BaseMLBSignal):
    """FB velocity down 1.5+ mph from season avg — fatigue/injury indicator."""
    tag = "velocity_drop_under"
    description = "Fastball velocity dropped 1.5+ mph from season average"
    direction = "UNDER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        sup = supplemental or {}
        velocity_change = sup.get('velocity_change') or (features or {}).get('velocity_change')
        if velocity_change is None:
            return self._no_qualify()

        # velocity_change = season - recent, positive = dropping
        if velocity_change >= 1.5:
            conf = min(1.0, velocity_change / 3.0)
            return self._qualify(confidence=conf, velocity_drop_mph=round(velocity_change, 1))
        return self._no_qualify()


class OpponentKProneSignal(BaseMLBSignal):
    """Opponent team K-rate in top 25% — team strikes out a lot."""
    tag = "opponent_k_prone"
    description = "Opponent team has high strikeout rate (top 25%)"
    direction = "OVER"

    # Top 25% K-rate threshold (approximately 24%+ team K-rate)
    K_RATE_THRESHOLD = 0.24

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        opp_k_rate = features.get('opponent_team_k_rate')
        if opp_k_rate is None:
            return self._no_qualify()

        if opp_k_rate >= self.K_RATE_THRESHOLD:
            conf = min(1.0, (opp_k_rate - 0.20) / 0.08)  # Scale 20-28%
            return self._qualify(confidence=conf, opponent_k_rate=round(opp_k_rate, 3))
        return self._no_qualify()


class ShortRestUnderSignal(BaseMLBSignal):
    """Pitcher on < 4 days rest — fatigue affects K rate."""
    tag = "short_rest_under"
    description = "Pitcher on short rest (< 4 days)"
    direction = "UNDER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        days_rest = features.get('days_rest')
        if days_rest is None:
            return self._no_qualify()

        if days_rest < 4:
            conf = 0.8 if days_rest <= 3 else 0.6
            return self._qualify(confidence=conf, days_rest=days_rest)
        return self._no_qualify()


class HighVarianceUnderSignal(BaseMLBSignal):
    """K standard deviation > 3.5 over last 10 starts — inconsistent pitcher."""
    tag = "high_variance_under"
    description = "Pitcher has high K variance (std > 3.5 last 10)"
    direction = "UNDER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        k_std = features.get('k_std_last_10')
        if k_std is None:
            return self._no_qualify()

        if k_std > 3.5:
            conf = min(1.0, (k_std - 3.0) / 3.0)
            return self._qualify(confidence=conf, k_std=round(k_std, 2))
        return self._no_qualify()


class BallparkKBoostSignal(BaseMLBSignal):
    """Park K-factor > 1.05 — ballpark inflates strikeouts."""
    tag = "ballpark_k_boost"
    description = "Ballpark has elevated K factor (> 1.05)"
    direction = "OVER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        k_factor = features.get('ballpark_k_factor')
        if k_factor is None:
            return self._no_qualify()

        if k_factor > 1.05:
            conf = min(1.0, (k_factor - 1.0) / 0.15)
            return self._qualify(confidence=conf, ballpark_k_factor=round(k_factor, 3))
        return self._no_qualify()


class UmpireKFriendlySignal(BaseMLBSignal):
    """Umpire K-rate in top 25% — umpire has wide zone."""
    tag = "umpire_k_friendly"
    description = "Umpire has elevated K rate (top 25%)"
    direction = "OVER"

    # Top 25% umpire K-rate threshold
    UMPIRE_K_THRESHOLD = 0.22

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sup = supplemental or {}
        umpire_k_rate = sup.get('umpire_k_rate')
        if umpire_k_rate is None:
            return self._no_qualify()

        if umpire_k_rate >= self.UMPIRE_K_THRESHOLD:
            conf = min(1.0, (umpire_k_rate - 0.18) / 0.08)
            return self._qualify(confidence=conf, umpire_k_rate=round(umpire_k_rate, 3))
        return self._no_qualify()


# =============================================================================
# SHADOW SIGNALS (6) — accumulate data, don't affect picks yet
# =============================================================================

class LineMovementOverSignal(BaseMLBSignal):
    """Line dropped 0.5+ from open — sharp money on OVER."""
    tag = "line_movement_over"
    description = "Strikeout line dropped 0.5+ from opening"
    direction = "OVER"
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sup = supplemental or {}
        opening_line = sup.get('opening_line')
        current_line = prediction.get('line_value')

        if opening_line is None or current_line is None:
            return self._no_qualify()

        line_drop = opening_line - current_line
        if line_drop >= 0.5:
            conf = min(1.0, line_drop / 1.5)
            return self._qualify(confidence=conf, line_drop=round(line_drop, 1))
        return self._no_qualify()


class WeatherColdUnderSignal(BaseMLBSignal):
    """Temperature < 50F — cold weather reduces pitch movement and Ks."""
    tag = "weather_cold_under"
    description = "Game temperature below 50F"
    direction = "UNDER"
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        sup = supplemental or {}
        temp = sup.get('temperature')
        if temp is None:
            return self._no_qualify()

        if temp < 50:
            conf = min(1.0, (55 - temp) / 20.0)
            return self._qualify(confidence=conf, temperature=temp)
        return self._no_qualify()


class PlatoonAdvantageSignal(BaseMLBSignal):
    """Pitcher has platoon advantage vs majority of lineup."""
    tag = "platoon_advantage"
    description = "Pitcher hand matches poorly against opposing lineup"
    direction = ""  # Can be either direction
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        sup = supplemental or {}
        platoon_k_rate = sup.get('lineup_k_vs_hand')
        if platoon_k_rate is None:
            return self._no_qualify()

        # High K rate vs hand = advantage for pitcher OVER
        if prediction.get('recommendation') == 'OVER' and platoon_k_rate >= 0.26:
            return self._qualify(confidence=0.7, platoon_k_rate=round(platoon_k_rate, 3))
        # Low K rate vs hand = bad matchup for UNDER
        elif prediction.get('recommendation') == 'UNDER' and platoon_k_rate <= 0.18:
            return self._qualify(confidence=0.7, platoon_k_rate=round(platoon_k_rate, 3))
        return self._no_qualify()


class AcePitcherOverSignal(BaseMLBSignal):
    """Top 20% K/9 pitcher — aces consistently produce Ks."""
    tag = "ace_pitcher_over"
    description = "Pitcher has elite K/9 rate (top 20%)"
    direction = "OVER"
    is_shadow = True

    # Top 20% K/9 threshold
    ACE_K9_THRESHOLD = 10.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        k_per_9 = features.get('season_k_per_9')
        if k_per_9 is None:
            return self._no_qualify()

        if k_per_9 >= self.ACE_K9_THRESHOLD:
            conf = min(1.0, (k_per_9 - 8.0) / 4.0)
            return self._qualify(confidence=conf, k_per_9=round(k_per_9, 2))
        return self._no_qualify()


class CatcherFramingOverSignal(BaseMLBSignal):
    """Elite catcher framing adds 1-2 called strikes per game."""
    tag = "catcher_framing_over"
    description = "Elite catcher framing (top 25% framing runs)"
    direction = "OVER"
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sup = supplemental or {}
        framing_runs = sup.get('catcher_framing_runs')
        if framing_runs is None:
            return self._no_qualify()

        if framing_runs >= 5.0:  # Season framing runs above average
            conf = min(1.0, framing_runs / 15.0)
            return self._qualify(confidence=conf, catcher_framing_runs=round(framing_runs, 1))
        return self._no_qualify()


class ProjectionAgreesOverSignal(BaseMLBSignal):
    """BettingPros projection > line + 0.5 — projection confirms OVER.

    Walk-forward: projection_diff is top feature by importance (6.9%).
    When projection agrees with model direction, HR improves.
    """
    tag = "projection_agrees_over"
    description = "BettingPros projection exceeds line by 0.5+ K"
    direction = "OVER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        # projection_diff = bp_projection - bp_over_line (already computed)
        proj_diff = features.get('projection_diff')
        if proj_diff is None:
            # Try raw values
            proj = features.get('bp_projection')
            line = prediction.get('strikeouts_line')
            if proj is not None and line is not None:
                proj_diff = proj - line
            else:
                return self._no_qualify()

        if proj_diff >= 0.5:
            conf = min(1.0, proj_diff / 2.0)
            return self._qualify(confidence=conf, projection_diff=round(proj_diff, 2))
        return self._no_qualify()


class KTrendingOverSignal(BaseMLBSignal):
    """Recent K avg trending up — K avg last 3 > K avg last 10 + 1.0.

    Captures pitchers on a hot streak whose model prediction is confirmed
    by recent performance momentum.
    """
    tag = "k_trending_over"
    description = "K average last 3 starts exceeds last 10 by 1.0+"
    direction = "OVER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        k_last_3 = features.get('k_avg_last_3')
        k_last_10 = features.get('k_avg_last_10')
        if k_last_3 is None or k_last_10 is None:
            return self._no_qualify()

        trend = k_last_3 - k_last_10
        if trend >= 1.0:
            conf = min(1.0, trend / 3.0)
            return self._qualify(confidence=conf,
                                k_last_3=round(k_last_3, 1),
                                k_last_10=round(k_last_10, 1),
                                trend=round(trend, 1))
        return self._no_qualify()


class RecentKAboveLineSignal(BaseMLBSignal):
    """K avg last 5 > strikeouts line — direct empirical evidence for OVER.

    Walk-forward validated: k_avg_vs_line (f30) is a core feature.
    When the pitcher's recent avg exceeds the line, OVER has higher HR.
    """
    tag = "recent_k_above_line"
    description = "K average last 5 starts exceeds current line"
    direction = "OVER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        # k_avg_vs_line = k_avg_last_5 - line (already computed as f30)
        k_vs_line = features.get('k_avg_vs_line')
        if k_vs_line is None:
            k_last_5 = features.get('k_avg_last_5')
            line = prediction.get('strikeouts_line')
            if k_last_5 is not None and line is not None:
                k_vs_line = k_last_5 - line
            else:
                return self._no_qualify()

        if k_vs_line > 0:
            conf = min(1.0, k_vs_line / 2.0)
            return self._qualify(confidence=conf, k_avg_vs_line=round(k_vs_line, 2))
        return self._no_qualify()


class PitchCountLimitUnderSignal(BaseMLBSignal):
    """Pitcher has documented pitch count limit — caps K upside."""
    tag = "pitch_count_limit_under"
    description = "Pitcher has documented pitch count cap (80-85)"
    direction = "UNDER"
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        sup = supplemental or {}
        pitch_limit = sup.get('pitch_count_limit')
        if pitch_limit is None:
            return self._no_qualify()

        if pitch_limit <= 85:
            conf = 0.9 if pitch_limit <= 75 else 0.7
            return self._qualify(confidence=conf, pitch_count_limit=pitch_limit)
        return self._no_qualify()


# =============================================================================
# NEGATIVE FILTERS (4) — block picks, don't count toward signal count
# =============================================================================

class BullpenGameFilter(BaseMLBSignal):
    """Block picks for bullpen/opener games — K props are voided or meaningless."""
    tag = "bullpen_game_skip"
    description = "Opener or bullpen game detected"
    is_negative_filter = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if not features:
            return self._no_qualify()

        ip_avg = features.get('ip_avg_last_5')
        if ip_avg is not None and ip_avg < 4.0:
            return self._qualify(confidence=1.0, ip_avg=round(ip_avg, 1),
                                reason="Avg IP < 4.0 — likely opener/bullpen")

        sup = supplemental or {}
        if sup.get('is_opener') or sup.get('is_bullpen_game'):
            return self._qualify(confidence=1.0, reason="Flagged as opener/bullpen")

        return self._no_qualify()


class ILReturnFilter(BaseMLBSignal):
    """Block picks for first start back from IL — unpredictable pitch count."""
    tag = "il_return_skip"
    description = "First start returning from injured list"
    is_negative_filter = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        sup = supplemental or {}
        if sup.get('is_il_return') or sup.get('first_start_from_il'):
            return self._qualify(confidence=1.0, reason="First start from IL")
        return self._no_qualify()


class PitchCountCapFilter(BaseMLBSignal):
    """Block OVER picks for pitchers with documented pitch count cap."""
    tag = "pitch_count_cap_skip"
    description = "Block OVER when pitcher has documented pitch count cap"
    is_negative_filter = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sup = supplemental or {}
        pitch_limit = sup.get('pitch_count_limit')
        if pitch_limit is not None and pitch_limit <= 85:
            return self._qualify(
                confidence=1.0,
                pitch_count_limit=pitch_limit,
                reason=f"Pitch count cap at {pitch_limit} — blocks OVER",
            )
        return self._no_qualify()


class InsufficientDataFilter(BaseMLBSignal):
    """Block picks for pitchers with < 3 starts — not enough data."""
    tag = "insufficient_data_skip"
    description = "Pitcher has fewer than 3 starts this season"
    is_negative_filter = True

    MIN_STARTS = 3

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if not features:
            return self._no_qualify()

        season_games = features.get('season_games_started', 0) or 0
        rolling_games = features.get('rolling_stats_games', 0) or 0

        starts = max(season_games, rolling_games)
        if starts < self.MIN_STARTS:
            return self._qualify(
                confidence=1.0, starts=starts,
                reason=f"Only {starts} starts — need {self.MIN_STARTS}+",
            )
        return self._no_qualify()


class PitcherBlacklistFilter(BaseMLBSignal):
    """Block pitchers with historically poor OVER performance.
    Walk-forward regressor: blocked picks at 37.5% HR -> +3.1pp lift.

    Session 443 deep dive: Expanded from 10 to 18 pitchers.
    Removed: freddy_peralta (54.5%), tyler_glasnow (66.7%),
             hunter_greene (46.2%), yusei_kikuchi (51.9%), jose_soriano (no data).
    Added: 12 new pitchers with <45% HR at N >= 10 in regressor walk-forward.
    Session 447: +5 from season replay (40% combined HR on 35 picks, +4u P&L lift).
    """
    tag = "pitcher_blacklist"
    description = "Pitcher on blacklist (walk-forward <45% HR at edge >= 0.75)"
    direction = "OVER"
    is_negative_filter = True

    # Session 443-444-447: Walk-forward + season replay validated, <45% HR
    # Session 469: Removed 5 pitchers (new team or tiny sample + elite 2025):
    #   mackenzie_gore (WSH→TEX), luis_severino (NYM→OAK), ranger_suárez (PHI→BOS),
    #   paul_skenes (Cy Young, N=9), cade_horton (2.67 ERA, N=8)
    # Monitor early 2026: adrian_houser (TB→SF), tyler_mahle (TEX→SF),
    #   stephen_kolek (SD→KC), casey_mize (breakout 2025)
    BLACKLIST = frozenset([
        # Kept from original (confirmed bad in regressor data)
        'tanner_bibee', 'mitchell_parker', 'casey_mize', 'mitch_keller',
        # Session 443 additions (walk-forward <45% HR at N >= 10)
        'logan_webb',          # 37.5% HR, N=24
        'jose_berrios',        # 38.1% HR, N=21
        'logan_gilbert',       # 38.5% HR, N=26
        'logan_allen',         # 36.2% HR, N=47
        'jake_irvin',          # 33.3% HR, N=15
        'george_kirby',        # 40.0% HR, N=25
        'bailey_ober',         # 40.0% HR, N=20
        'zach_eflin',          # 30.0% HR, N=10
        'ryne_nelson',         # 30.8% HR, N=13
        'jameson_taillon',     # 33.3% HR, N=12
        'ryan_feltner',        # 33.3% HR, N=12
        'randy_vasquez',       # 27.8% HR, N=18
        # Session 444 additions (season replay 0% or <40% HR at N >= 3)
        'adrian_houser',       # 0-4 (0% HR) — monitor: signed SF Giants
        'stephen_kolek',       # 0-3 (0% HR) — monitor: traded to KC Royals
        'dean_kremer',         # 1-3 (25% HR)
        'michael_mcgreevy',    # 1-3 (25% HR)
        'tyler_mahle',         # 1-3 (25% HR) — monitor: signed SF Giants
        # Session 447 additions (season replay <45% HR at N >= 5)
        'blake_snell',         # 40.0% HR, N=5
        'luis_castillo',       # 42.9% HR, N=7
    ])

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        pitcher = prediction.get('pitcher_lookup', '')
        if pitcher in self.BLACKLIST:
            return self._qualify(confidence=0.8,
                                 reason=f'{pitcher} on blacklist (walk-forward <45% HR)')
        return self._no_qualify()


class WholeLineOverFilter(BaseMLBSignal):
    """Block OVER on whole-number strikeout lines (X.0).

    Session 443: Whole-number lines have 17.3% push rate (actual == line = OVER loss).
    Half-lines: 58.6% OVER HR vs Whole-lines: 49.0% (-9.6pp). p < 0.001.
    Effect is structural (integer K counts), consistent across both seasons,
    independent of pitcher/opponent/venue. 75% of blocks are unique (not caught
    by other filters). Incremental +1.6pp after existing filters.
    """
    tag = "whole_line_over"
    description = "Whole-number K line has high push rate (49% OVER HR, p<0.001)"
    direction = "OVER"
    is_negative_filter = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        line = prediction.get('strikeouts_line')
        if line is None:
            return self._no_qualify()
        # Check if line is a whole number (X.0)
        if line == int(line):
            push_rates = {3.0: 26.2, 4.0: 20.4, 5.0: 10.1, 6.0: 14.6, 7.0: 25.9}
            push_pct = push_rates.get(float(line), 17.3)
            return self._qualify(
                confidence=0.9,
                reason=f'Whole-number line {line:.0f}.0 — {push_pct:.0f}% push rate (structural)',
            )
        return self._no_qualify()


class BadOpponentObservationFilter(BaseMLBSignal):
    """OBSERVATION: OVER vs low-K opponents. Logs but does not block.

    Session 443: Cross-season opponent HR is ANTI-CORRELATED (r=-0.29).
    Static opponent lists go stale within a season. KC improved from 40%
    to 51% between 2024 and 2025. Demoted from active filter to observation.
    """
    tag = "bad_opponent_over_obs"
    description = "OBSERVATION: Opponent low K rate (cross-season r=-0.29, unstable)"
    direction = "OVER"
    is_shadow = True  # Shadow = observation, logs but doesn't block

    BAD_OPPONENTS = frozenset(['KC', 'MIA'])

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        opp = prediction.get('opponent_team_abbr', '')
        if opp in self.BAD_OPPONENTS:
            return self._qualify(confidence=0.5,
                                 reason=f'OBS: vs {opp} (cross-season unstable, r=-0.29)')
        return self._no_qualify()


class BadVenueObservationFilter(BaseMLBSignal):
    """OBSERVATION: OVER at K-unfriendly venues. Logs but does not block.

    Session 443: Venue effects are confounded with home team quality.
    Variance attribution: eta-squared ~0.006 (not significant, p=0.13).
    Demoted from active filter to observation.
    """
    tag = "bad_venue_over_obs"
    description = "OBSERVATION: K-unfriendly venue (confounded with team, p=0.13)"
    direction = "OVER"
    is_shadow = True  # Shadow = observation, logs but doesn't block

    BAD_VENUES = frozenset([
        'loanDepot park', 'Guaranteed Rate Field', 'Progressive Field', 'Nationals Park',
    ])

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        venue = prediction.get('venue', '') or (features or {}).get('venue', '')
        if venue in self.BAD_VENUES:
            return self._qualify(confidence=0.4,
                                 reason=f'OBS: {venue} (confounded with team, eta²=0.006)')
        return self._no_qualify()


# =============================================================================
# NEW SHADOW SIGNALS — Session 460
# Research-backed signals for cross-season validation.
# All start as shadow (accumulate data) before promotion.
# =============================================================================

class ColdWeatherKOverSignal(BaseMLBSignal):
    """Cold weather (<60°F) increases strikeouts — harder to barrel the ball.

    Session 460: Research shows cold weather = more swing-and-miss = more Ks.
    This is OPPOSITE to the existing weather_cold_under signal (which assumed
    cold = fewer Ks). The barrel-difficulty mechanism is well-documented.
    Threshold 60°F is conservative; strongest effect at <50°F.
    """
    tag = "cold_weather_k_over"
    description = "Cold weather (<60°F) — harder to barrel, more strikeouts"
    direction = "OVER"
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sup = supplemental or {}
        temp = sup.get('temperature')
        is_dome = sup.get('is_dome', False)
        if temp is None or is_dome:
            return self._no_qualify()

        if temp < 60:
            conf = min(1.0, (65 - temp) / 25.0)  # Max confidence at 40°F
            return self._qualify(confidence=conf, temperature=temp,
                                 reason=f'Cold weather {temp:.0f}°F — barrel difficulty')
        return self._no_qualify()


class LineupKSpikeOverSignal(BaseMLBSignal):
    """Today's lineup K% vs pitcher hand is elevated above team average.

    Session 460: Team-level K rate (opponent_k_prone) uses season averages.
    But the actual lineup today may be much more K-prone if stars are resting
    and bench bats (higher K%) are in. lineup_k_vs_hand captures this.
    Threshold 0.26 = top ~20% of lineups.
    """
    tag = "lineup_k_spike_over"
    description = "Today's lineup K% vs pitcher hand in top 20% (>=26%)"
    direction = "OVER"
    is_shadow = True

    LINEUP_K_THRESHOLD = 0.26

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        lineup_k = features.get('lineup_k_vs_hand')
        team_k = features.get('opponent_team_k_rate')
        if lineup_k is None:
            return self._no_qualify()

        if lineup_k >= self.LINEUP_K_THRESHOLD:
            spike = lineup_k - (team_k or 0.22)
            conf = min(1.0, (lineup_k - 0.22) / 0.08)
            return self._qualify(
                confidence=conf,
                lineup_k_vs_hand=round(lineup_k, 3),
                team_k_rate=round(team_k, 3) if team_k else None,
                spike=round(spike, 3) if team_k else None,
            )
        return self._no_qualify()


class PitchEfficiencyDepthOverSignal(BaseMLBSignal):
    """Efficient pitcher (high IP, low pitch count) goes deeper = more K time.

    Session 460: Average MLB starter goes 5.25 IP. Pitchers averaging 6+ IP
    on <95 pitches have ~33% more batter-faced than short starters. This is
    arguably the most underpriced factor in K props — books set lines based
    on K/IP rate but don't fully price innings depth.

    Cross-season validated: 65.4% HR, N=651, 3/4 seasons positive.
    PROMOTED from shadow → active (Session 460).
    """
    tag = "pitch_efficiency_depth_over"
    description = "Efficient pitcher (6+ IP avg, <95 pitches) — deeper outings"
    direction = "OVER"
    is_shadow = False

    IP_THRESHOLD = 6.0
    PITCH_COUNT_THRESHOLD = 95

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        ip_avg = features.get('ip_avg_last_5')
        pitch_avg = features.get('pitch_count_avg_last_5') or features.get('pitch_count_avg')
        if ip_avg is None:
            return self._no_qualify()

        # Primary check: high IP average
        if ip_avg >= self.IP_THRESHOLD:
            # Bonus confidence if also pitch-efficient
            is_efficient = (pitch_avg is not None and pitch_avg < self.PITCH_COUNT_THRESHOLD)
            conf = 0.8 if is_efficient else 0.6
            return self._qualify(
                confidence=conf,
                ip_avg_last_5=round(ip_avg, 1),
                pitch_count_avg=round(pitch_avg, 1) if pitch_avg else None,
                reason=f'Deep starter: {ip_avg:.1f} IP avg'
                       + (f', {pitch_avg:.0f} P/G' if pitch_avg else ''),
            )
        return self._no_qualify()


class ShortStarterUnderSignal(BaseMLBSignal):
    """Short starter (IP avg < 5.0) caps K upside — pulled early.

    Session 460: If a pitcher averages fewer than 5 IP, they face fewer
    batters and have less time to accumulate Ks. This is a structural
    UNDER signal independent of K/IP rate.
    Different from bullpen_game_skip (which blocks at IP < 4.0).
    """
    tag = "short_starter_under"
    description = "Short starter (IP avg < 5.0) — pulled early, caps K upside"
    direction = "UNDER"
    is_shadow = True

    IP_THRESHOLD = 5.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        ip_avg = features.get('ip_avg_last_5')
        if ip_avg is None:
            return self._no_qualify()

        if ip_avg < self.IP_THRESHOLD:
            conf = min(1.0, (self.IP_THRESHOLD - ip_avg) / 2.0)
            return self._qualify(
                confidence=conf,
                ip_avg_last_5=round(ip_avg, 1),
                reason=f'Short starter: {ip_avg:.1f} IP avg — limited K time',
            )
        return self._no_qualify()


class HighCSWOverSignal(BaseMLBSignal):
    """CSW% (Called Strikes + Whiffs) >= 30% — elite pitch quality.

    Session 460: CSW% has R² ~0.59 against K% — the single strongest
    predictor of strikeout rate. Pitchers above 30% are consistently
    elite K generators. Stabilizes faster than K/9 in small samples.
    Different from swstr_surge (which tracks recent change vs season avg).

    Cross-season validated: 65.0% HR, N=406, 4/4 seasons positive.
    PROMOTED from shadow → active (Session 460).
    """
    tag = "high_csw_over"
    description = "Elite CSW% (>=30%) — top strikeout pitch quality"
    direction = "OVER"
    is_shadow = False

    CSW_THRESHOLD = 0.30

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        csw = features.get('season_csw_pct')
        if csw is None:
            return self._no_qualify()

        if csw >= self.CSW_THRESHOLD:
            conf = min(1.0, (csw - 0.25) / 0.10)
            return self._qualify(
                confidence=conf,
                season_csw_pct=round(csw, 3),
                reason=f'Elite CSW%: {csw:.1%}',
            )
        return self._no_qualify()


class ElitePeripheralsOverSignal(BaseMLBSignal):
    """FIP < 3.5 + K/9 >= 9.0 — ace with elite underlying peripherals.

    Session 460: FIP strips out defense and luck. Combined with high K/9,
    identifies pitchers whose strikeout ability is genuine (not lucky BABIP).
    FIP is the #2 feature by importance (10.9%) in the model.

    Cross-season validated: 65.8% HR, N=549, 4/4 seasons positive.
    PROMOTED from shadow → active (Session 460).
    """
    tag = "elite_peripherals_over"
    description = "Ace peripherals (FIP < 3.5 + K/9 >= 9.0)"
    direction = "OVER"
    is_shadow = False

    FIP_THRESHOLD = 3.5
    K9_THRESHOLD = 9.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        fip = features.get('fip')
        k_per_9 = features.get('season_k_per_9')
        if fip is None or k_per_9 is None:
            return self._no_qualify()

        if fip < self.FIP_THRESHOLD and k_per_9 >= self.K9_THRESHOLD:
            # Higher confidence for more extreme values
            fip_score = max(0, (self.FIP_THRESHOLD - fip) / 1.5)
            k9_score = max(0, (k_per_9 - 8.0) / 4.0)
            conf = min(1.0, (fip_score + k9_score) / 2.0)
            return self._qualify(
                confidence=conf,
                fip=round(fip, 2),
                k_per_9=round(k_per_9, 1),
                reason=f'Elite peripherals: {fip:.2f} FIP, {k_per_9:.1f} K/9',
            )
        return self._no_qualify()


class GameTotalLowOverSignal(BaseMLBSignal):
    """Low game total (<=7.5) implies starters pitch deeper = more K time.

    Session 460: When Vegas prices a low-scoring game, it implies good
    pitching matchup. Starters in low-total games average 0.3-0.5 more IP
    than high-total games. More IP = more K opportunities.
    """
    tag = "game_total_low_over"
    description = "Low game total (<=7.5) — starters pitch deeper"
    direction = "OVER"
    is_shadow = True

    TOTAL_THRESHOLD = 7.5

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sup = supplemental or {}
        game_total = sup.get('game_total_line')
        if game_total is None:
            # Try features dict (pitcher_game_summary has game_total_line)
            game_total = (features or {}).get('game_total_line')
        if game_total is None:
            return self._no_qualify()

        if game_total <= self.TOTAL_THRESHOLD:
            conf = min(1.0, (9.0 - game_total) / 3.0)
            return self._qualify(
                confidence=conf,
                game_total_line=round(game_total, 1),
                reason=f'Low game total {game_total:.1f} — deeper outings expected',
            )
        return self._no_qualify()


class HeavyFavoriteOverSignal(BaseMLBSignal):
    """Pitcher's team is heavy favorite (moneyline < -180) — starter goes deep.

    Session 460: Heavy favorites protect leads by keeping their starter in.
    When a team is -180+, the starter averages 0.5+ more IP than normal.
    Combined with K ability, this is a structural depth signal.
    """
    tag = "heavy_favorite_over"
    description = "Heavy favorite (ML < -180) — starter pitches deeper"
    direction = "OVER"
    is_shadow = True

    ML_THRESHOLD = -180

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sup = supplemental or {}
        moneyline = sup.get('team_moneyline')
        if moneyline is None:
            return self._no_qualify()

        if moneyline <= self.ML_THRESHOLD:
            conf = min(1.0, abs(moneyline - (-150)) / 100.0)
            return self._qualify(
                confidence=conf,
                team_moneyline=moneyline,
                reason=f'Heavy favorite ML {moneyline} — starter pitches deep',
            )
        return self._no_qualify()


class BottomUpAgreesOverSignal(BaseMLBSignal):
    """Bottom-up K estimate from lineup analysis exceeds line.

    Session 460: The model uses team-level features. A bottom-up approach
    that sums individual batter K rates for the actual lineup provides
    independent confirmation. When bottom-up projection > line, it means
    THIS SPECIFIC LINEUP is K-prone, not just the team on average.
    """
    tag = "bottom_up_agrees_over"
    description = "Bottom-up lineup K estimate exceeds line"
    direction = "OVER"
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        bottom_up = features.get('bottom_up_k_expected')
        line = prediction.get('strikeouts_line')
        if bottom_up is None or line is None:
            return self._no_qualify()

        diff = bottom_up - line
        if diff > 0:
            conf = min(1.0, diff / 2.0)
            return self._qualify(
                confidence=conf,
                bottom_up_k_expected=round(bottom_up, 1),
                line=line,
                diff=round(diff, 1),
                reason=f'Bottom-up {bottom_up:.1f} K > line {line} (+{diff:.1f})',
            )
        return self._no_qualify()


class DayGameShadowOverSignal(BaseMLBSignal):
    """Day games create shadow/visibility issues for hitters = more Ks.

    Session 460: Research confirms pitchers have higher K rates in day games
    since 2014. Shadow effects where mound is in sunlight and batter's box
    is in shade make pitch pickup harder. Effect is especially strong at
    certain stadiums (Wrigley, Fenway) during afternoon starts.

    Session 464 PROMOTED: 61.6% HR, N=895, 4/4 seasons >= 59%.
    2022: 59.5% (210), 2023: 61.9% (134), 2024: 61.6% (268), 2025: 63.6% (283).
    """
    tag = "day_game_shadow_over"
    description = "Day game shadow effect — hitters struggle with visibility"
    direction = "OVER"
    is_shadow = False

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        is_day = features.get('is_day_game')
        if is_day is None:
            return self._no_qualify()

        if is_day:
            return self._qualify(confidence=0.5,
                                 reason='Day game — shadow/visibility disadvantage for hitters')
        return self._no_qualify()


class RematchFamiliarityUnderSignal(BaseMLBSignal):
    """Pitcher facing same team again within recent games = lower K rate.

    Session 460: FanGraphs research confirms K% drops when a pitcher faces
    the same lineup within ~10 days. Hitter familiarity advantage is real
    and measurable. Division rivals especially affected.
    Uses vs_opponent_games feature — high count = frequent matchup.
    """
    tag = "rematch_familiarity_under"
    description = "Pitcher facing familiar opponent (division rival) — K% drops"
    direction = "UNDER"
    is_shadow = True

    # Threshold: 3+ games vs this opponent this season = familiarity penalty
    MIN_VS_GAMES = 3

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        vs_games = features.get('vs_opponent_games') or features.get('games_vs_opponent')
        if vs_games is None:
            return self._no_qualify()

        if vs_games >= self.MIN_VS_GAMES:
            conf = min(1.0, vs_games / 6.0)
            return self._qualify(
                confidence=conf,
                vs_opponent_games=int(vs_games),
                reason=f'{int(vs_games)} games vs this opponent — familiarity penalty',
            )
        return self._no_qualify()


class CumulativeArmStressUnderSignal(BaseMLBSignal):
    """Pitcher accumulated high pitch counts across recent starts.

    Session 460: Research shows cumulative fatigue across multiple starts
    is more predictive of K rate decline than single-game pitch count.
    High recent workload (pitch count avg + games in last 30 days) signals
    arm stress before velocity drops manifest.
    """
    tag = "cumulative_arm_stress_under"
    description = "High cumulative arm stress — K rate likely to decline"
    direction = "UNDER"
    is_shadow = True

    # Thresholds: high pitch count avg + high recent game density
    PITCH_COUNT_THRESHOLD = 100
    GAMES_30D_THRESHOLD = 6

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        pitch_avg = features.get('pitch_count_avg_last_5') or features.get('pitch_count_avg')
        games_30d = features.get('games_last_30_days')
        if pitch_avg is None or games_30d is None:
            return self._no_qualify()

        if pitch_avg >= self.PITCH_COUNT_THRESHOLD and games_30d >= self.GAMES_30D_THRESHOLD:
            stress_score = (pitch_avg / 100.0) * (games_30d / 6.0)
            conf = min(1.0, (stress_score - 1.0) / 1.0)
            return self._qualify(
                confidence=conf,
                pitch_count_avg=round(pitch_avg, 0),
                games_last_30d=int(games_30d),
                reason=f'Arm stress: {pitch_avg:.0f} P/G avg + {int(games_30d)} games in 30d',
            )
        return self._no_qualify()


class TaxedBullpenOverSignal(BaseMLBSignal):
    """Team bullpen is taxed from recent heavy usage — starter goes deeper.

    Session 460: Multiple betting analysts describe bullpen state as "the
    single most underpriced variable" in pitcher prop markets. When the
    bullpen has been heavily used in prior 2-3 games, the manager gives
    the starter a longer leash. More innings = more K opportunities.
    Requires supplemental data from recent bullpen usage.
    """
    tag = "taxed_bullpen_over"
    description = "Bullpen taxed from recent use — starter pitches deeper"
    direction = "OVER"
    is_shadow = True

    # Threshold: 10+ bullpen IP in last 3 games = taxed
    BULLPEN_IP_THRESHOLD = 10.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sup = supplemental or {}
        bullpen_ip_3d = sup.get('bullpen_ip_last_3_games')
        if bullpen_ip_3d is None:
            return self._no_qualify()

        if bullpen_ip_3d >= self.BULLPEN_IP_THRESHOLD:
            conf = min(1.0, (bullpen_ip_3d - 8.0) / 6.0)
            return self._qualify(
                confidence=conf,
                bullpen_ip_last_3d=round(bullpen_ip_3d, 1),
                reason=f'Bullpen taxed: {bullpen_ip_3d:.1f} IP last 3 games — starter stays in',
            )
        return self._no_qualify()


class CatcherFramingPoorUnderSignal(BaseMLBSignal):
    """Poor catcher framing reduces called strikes = fewer Ks.

    Session 460: Each framing run per game adds ~3.9% to K rate.
    When a poor framer (negative framing runs) catches, the pitcher
    loses called strikes. Complement to catcher_framing_over.
    Threshold: framing_runs <= -3.0 (bottom ~25% of catchers).
    """
    tag = "catcher_framing_poor_under"
    description = "Poor catcher framing (bottom 25%) — fewer called strikes"
    direction = "UNDER"
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()

        sup = supplemental or {}
        framing_runs = sup.get('catcher_framing_runs')
        if framing_runs is None:
            return self._no_qualify()

        if framing_runs <= -3.0:
            conf = min(1.0, abs(framing_runs) / 10.0)
            return self._qualify(
                confidence=conf,
                catcher_framing_runs=round(framing_runs, 1),
                reason=f'Poor framing: {framing_runs:.1f} runs — fewer called strikes',
            )
        return self._no_qualify()


# =============================================================================
# ACTIVE SIGNALS — Session 441 additions (regressor transition)
# =============================================================================

class RegressorProjectionAgreesSignal(BaseMLBSignal):
    """Projection source agrees with OVER direction.
    Walk-forward: +3.8pp lift when projection > line."""
    tag = "regressor_projection_agrees_over"
    description = "Projection value exceeds strikeouts line"
    direction = "OVER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        proj = prediction.get('projection_value') or (features or {}).get('projection_value')
        line = prediction.get('strikeouts_line')
        if proj is not None and line is not None and proj > line:
            diff = proj - line
            return self._qualify(confidence=min(1.0, diff / 2.0),
                                 reason=f'Projection {proj:.1f} > line {line:.1f} (+{diff:.1f})',
                                 projection_diff=round(diff, 2))
        return self._no_qualify()


class HomePitcherSignal(BaseMLBSignal):
    """Home pitcher advantage for strikeout OVER.
    Walk-forward: HOME 64.9% vs AWAY 59.7% (+5.2pp)."""
    tag = "home_pitcher_over"
    description = "Home pitcher K advantage"
    direction = "OVER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        is_home = prediction.get('is_home') or (features or {}).get('is_home')
        if is_home:
            return self._qualify(confidence=0.6, reason='Home pitcher K advantage')
        return self._no_qualify()


class LongRestSignal(BaseMLBSignal):
    """Pitcher on extended rest (8+ days). Walk-forward: 69.4% HR."""
    tag = "long_rest_over"
    description = "Pitcher on extended rest (8+ days)"
    direction = "OVER"

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        days_rest = (features or {}).get('days_rest') or prediction.get('days_rest')
        if days_rest is not None and days_rest >= 8:
            return self._qualify(confidence=0.7,
                                 reason=f'{days_rest:.0f} days rest (extended)',
                                 days_rest=days_rest)
        return self._no_qualify()


# =============================================================================
# SESSION 464 — New Shadow Signals (research-backed, features already available)
# =============================================================================

class KRateReversionUnderSignal(BaseMLBSignal):
    """K avg last 3 significantly above season avg — mean reversion to UNDER.

    Session 464: Mirrors NBA 3PT reversion finding. When a pitcher has been
    on a K hot streak (last 3 >> season avg), the market anchors to the streak
    but regression is likely. K/9 has ~0.40 correlation game-to-game.

    Threshold: K avg last 3 >= season K/9 * innings_coefficient + 2.0 Ks
    Simplified: k_avg_last_3 - (season_k_per_9 * ip_avg_last_5 / 9) >= 2.0
    """
    tag = "k_rate_reversion_under"
    description = "K hot streak above season norm — reversion expected"
    direction = "UNDER"
    is_shadow = True

    K_EXCESS_THRESHOLD = 2.0  # Ks above expected season rate

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        k_avg_3 = features.get('k_avg_last_3')
        k_per_9 = features.get('season_k_per_9')
        ip_avg = features.get('ip_avg_last_5')
        if k_avg_3 is None or k_per_9 is None or ip_avg is None:
            return self._no_qualify()

        # Expected Ks per game based on season rate and IP depth
        expected_k = k_per_9 * ip_avg / 9.0
        excess = k_avg_3 - expected_k

        if excess >= self.K_EXCESS_THRESHOLD:
            conf = min(1.0, excess / 4.0)
            return self._qualify(
                confidence=conf,
                k_avg_last_3=round(k_avg_3, 1),
                expected_k=round(expected_k, 1),
                k_excess=round(excess, 1),
                reason=f'K hot streak: {k_avg_3:.1f} avg vs {expected_k:.1f} expected (+{excess:.1f})',
            )
        return self._no_qualify()


class KRateBounceOverSignal(BaseMLBSignal):
    """K avg last 3 significantly below season avg — bounce-back to OVER.

    Session 464: Inverse of reversion. When a pitcher has been cold on Ks
    (bad matchups, bad luck, short outings), the market overweights the
    recent cold streak. Season-long K ability reasserts.

    Threshold: expected_k - k_avg_last_3 >= 2.0 Ks
    """
    tag = "k_rate_bounce_over"
    description = "K cold streak below season norm — bounce-back expected"
    direction = "OVER"
    is_shadow = True

    K_DEFICIT_THRESHOLD = 2.0  # Ks below expected season rate

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        k_avg_3 = features.get('k_avg_last_3')
        k_per_9 = features.get('season_k_per_9')
        ip_avg = features.get('ip_avg_last_5')
        if k_avg_3 is None or k_per_9 is None or ip_avg is None:
            return self._no_qualify()

        expected_k = k_per_9 * ip_avg / 9.0
        deficit = expected_k - k_avg_3

        if deficit >= self.K_DEFICIT_THRESHOLD:
            conf = min(1.0, deficit / 4.0)
            return self._qualify(
                confidence=conf,
                k_avg_last_3=round(k_avg_3, 1),
                expected_k=round(expected_k, 1),
                k_deficit=round(deficit, 1),
                reason=f'K cold streak: {k_avg_3:.1f} avg vs {expected_k:.1f} expected (-{deficit:.1f})',
            )
        return self._no_qualify()


class UmpireCSWComboOverSignal(BaseMLBSignal):
    """K-friendly umpire + high CSW pitcher — amplified K environment.

    Session 464: When a pitcher with elite CSW% (>= 28%) gets a K-friendly
    umpire (K-rate >= 22%), the called strike zone expands and whiff-prone
    pitches get more borderline calls. The combination should be more
    predictive than either signal alone.
    """
    tag = "umpire_csw_combo_over"
    description = "K-friendly umpire + high CSW pitcher — amplified Ks"
    direction = "OVER"
    is_shadow = True

    CSW_THRESHOLD = 0.28
    UMPIRE_K_THRESHOLD = 0.22

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        csw = features.get('season_csw_pct')
        sup = supplemental or {}
        umpire_k = sup.get('umpire_k_rate')

        if csw is None or umpire_k is None:
            return self._no_qualify()

        if csw >= self.CSW_THRESHOLD and umpire_k >= self.UMPIRE_K_THRESHOLD:
            # Both contribute to confidence
            csw_score = min(1.0, (csw - 0.25) / 0.10)
            ump_score = min(1.0, (umpire_k - 0.18) / 0.08)
            conf = min(1.0, (csw_score + ump_score) / 2.0)
            return self._qualify(
                confidence=conf,
                season_csw_pct=round(csw, 3),
                umpire_k_rate=round(umpire_k, 3),
                reason=f'K-friendly ump ({umpire_k:.1%}) + high CSW ({csw:.1%})',
            )
        return self._no_qualify()


class RestWorkloadStressUnderSignal(BaseMLBSignal):
    """Short rest combined with high recent workload — compounding fatigue.

    Session 464: Short rest alone (< 4 days) is already an active UNDER signal.
    But short rest + high games in 30 days (>= 6) compounds the fatigue effect.
    This captures the interaction term that the individual signals miss.

    The model has these features (f20, f21) but may not capture the interaction.
    """
    tag = "rest_workload_stress_under"
    description = "Short rest + high workload — compounding fatigue"
    direction = "UNDER"
    is_shadow = True

    MAX_REST_DAYS = 5
    MIN_GAMES_30D = 6

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        days_rest = features.get('days_rest')
        games_30d = features.get('games_last_30_days')
        if days_rest is None or games_30d is None:
            return self._no_qualify()

        if days_rest <= self.MAX_REST_DAYS and games_30d >= self.MIN_GAMES_30D:
            # Higher confidence when both are extreme
            rest_score = max(0, (self.MAX_REST_DAYS - days_rest) / 2.0)
            workload_score = max(0, (games_30d - 5) / 3.0)
            conf = min(1.0, (rest_score + workload_score) / 2.0)
            return self._qualify(
                confidence=conf,
                days_rest=days_rest,
                games_last_30_days=games_30d,
                reason=f'{days_rest:.0f}d rest + {games_30d:.0f} games/30d — fatigue compound',
            )
        return self._no_qualify()


class LowEraHighKComboOverSignal(BaseMLBSignal):
    """ERA < 3.0 + K/9 >= 8.5 — dominant ace firing on all cylinders.

    Session 464: Elite peripherals (FIP + K/9) is already active, but this
    captures a different angle: results-based dominance (ERA) combined with
    K ability. A pitcher with low ERA AND high K/9 is one who is both
    performing well AND generating strikeouts — not just peripherals.

    Wider than elite_peripherals (FIP < 3.5 + K/9 >= 9.0) to capture
    borderline aces who are pitching well by results.
    """
    tag = "low_era_high_k_combo_over"
    description = "Low ERA (< 3.0) + high K/9 (>= 8.5) — dominant ace"
    direction = "OVER"
    is_shadow = True

    ERA_THRESHOLD = 3.0
    K9_THRESHOLD = 8.5

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        era = features.get('season_era')
        k_per_9 = features.get('season_k_per_9')
        if era is None or k_per_9 is None:
            return self._no_qualify()

        if era < self.ERA_THRESHOLD and k_per_9 >= self.K9_THRESHOLD:
            era_score = max(0, (self.ERA_THRESHOLD - era) / 1.5)
            k9_score = max(0, (k_per_9 - 7.5) / 4.0)
            conf = min(1.0, (era_score + k9_score) / 2.0)
            return self._qualify(
                confidence=conf,
                season_era=round(era, 2),
                k_per_9=round(k_per_9, 1),
                reason=f'Dominant ace: {era:.2f} ERA, {k_per_9:.1f} K/9',
            )
        return self._no_qualify()


class PitcherOnRollOverSignal(BaseMLBSignal):
    """K average last 3 AND last 5 both above the line — sustained K production.

    Session 464: When a pitcher's recent K output (last 3 and last 5) both
    exceed the current line, it's a sustained pattern not just a spike. This
    differs from recent_k_above_line (last 5 only) by requiring BOTH windows
    to agree — reducing false positives from a single hot game.

    Session 464 PROMOTED: 63.2% HR, N=1473, 4/4 seasons >= 58%.
    2022: 59.4% (350), 2023: 60.2% (216), 2024: 58.2% (400), 2025: 71.4% (507).
    Highest-volume shadow signal. Sustained production stronger than single-window.
    """
    tag = "pitcher_on_roll_over"
    description = "K avg last 3 AND last 5 both above line — sustained K production"
    direction = "OVER"
    is_shadow = False

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        k_avg_3 = features.get('k_avg_last_3')
        k_avg_5 = features.get('k_avg_last_5')
        line = prediction.get('strikeouts_line')
        if k_avg_3 is None or k_avg_5 is None or line is None:
            return self._no_qualify()

        if k_avg_3 > line and k_avg_5 > line:
            margin_3 = k_avg_3 - line
            margin_5 = k_avg_5 - line
            avg_margin = (margin_3 + margin_5) / 2.0
            conf = min(1.0, avg_margin / 2.0)
            return self._qualify(
                confidence=conf,
                k_avg_last_3=round(k_avg_3, 1),
                k_avg_last_5=round(k_avg_5, 1),
                line=round(line, 1),
                reason=f'On a roll: L3={k_avg_3:.1f}, L5={k_avg_5:.1f} > {line:.1f} line',
            )
        return self._no_qualify()


# =============================================================================
# SESSION 464 — Round 2: Research-Backed Shadow Signals (FanGraphs + Weather)
# =============================================================================

class ChaseRateOverSignal(BaseMLBSignal):
    """Opponent chase rate (O-Swing%) extremely high — batters swing at junk.

    Session 464: O-Swing% measures the rate batters swing at pitches outside
    the strike zone. When >= 35%, batters are undisciplined chasers — they
    swing at breaking balls out of the zone, generating whiffs. Feature f70
    (o_swing_pct) is the #4 most important feature (4.14% importance).

    Combined with a pitcher who has elite K stuff, this amplifies the K rate.
    """
    tag = "chase_rate_over"
    description = "High opponent chase rate (O-Swing >= 35%)"
    direction = "OVER"
    is_shadow = True

    O_SWING_THRESHOLD = 0.35

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        o_swing = features.get('o_swing_pct')
        if o_swing is None:
            return self._no_qualify()

        if o_swing >= self.O_SWING_THRESHOLD:
            conf = min(1.0, (o_swing - 0.30) / 0.10)
            return self._qualify(
                confidence=conf,
                o_swing_pct=round(o_swing, 3),
                reason=f'High chase rate: {o_swing:.1%} O-Swing%',
            )
        return self._no_qualify()


class ContactSpecialistUnderSignal(BaseMLBSignal):
    """Pitcher facing high-contact batters — Z-Contact% >= 85%.

    Session 464: Z-Contact% measures the rate batters make contact on pitches
    in the strike zone. When >= 85%, batters rarely whiff on strikes. Feature
    f71 (z_contact_pct) is the #6 most important feature (3.39% importance).

    High Z-Contact means fewer swinging strikes in the zone, which is where
    most strikeouts come from. Combined with a pitcher who lacks elite stuff,
    this suppresses K rate.
    """
    tag = "contact_specialist_under"
    description = "High opponent contact rate (Z-Contact >= 85%)"
    direction = "UNDER"
    is_shadow = True

    Z_CONTACT_THRESHOLD = 0.85

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        z_contact = features.get('z_contact_pct')
        if z_contact is None:
            return self._no_qualify()

        if z_contact >= self.Z_CONTACT_THRESHOLD:
            conf = min(1.0, (z_contact - 0.80) / 0.10)
            return self._qualify(
                confidence=conf,
                z_contact_pct=round(z_contact, 3),
                reason=f'Contact-heavy lineup: {z_contact:.1%} Z-Contact%',
            )
        return self._no_qualify()


class HumidityOverSignal(BaseMLBSignal):
    """High humidity (>= 75%) in non-dome outdoor game.

    Session 464: High humidity increases air density and reduces ball carry.
    Batters can't drive the ball, leading to more marginal contact and foul
    balls. This increases pitch count and K opportunities. Effect is strongest
    at humid outdoor parks (Houston pre-roof, Miami, Tampa Bay excluded as dome).
    """
    tag = "humidity_over"
    description = "High humidity (>= 75%) — reduced ball carry, more whiffs"
    direction = "OVER"
    is_shadow = True

    HUMIDITY_THRESHOLD = 75

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()

        sup = supplemental or {}
        humidity = sup.get('humidity_pct')
        is_dome = sup.get('is_dome')

        if humidity is None or is_dome:
            return self._no_qualify()

        if humidity >= self.HUMIDITY_THRESHOLD:
            conf = min(1.0, (humidity - 65) / 25.0)
            return self._qualify(
                confidence=conf,
                humidity_pct=round(humidity, 1),
                reason=f'High humidity {humidity:.0f}% — reduced ball carry',
            )
        return self._no_qualify()


class FreshOpponentOverSignal(BaseMLBSignal):
    """First matchup of season vs opponent — unknown tendencies advantage.

    Session 464: When a pitcher faces an opponent for the first time this
    season (vs_opponent_games == 0 or 1), the hitters have no recent data
    on the pitcher's current pitch mix and tendencies. This information
    asymmetry favors the pitcher.
    """
    tag = "fresh_opponent_over"
    description = "First matchup vs opponent this season — info advantage"
    direction = "OVER"
    is_shadow = True

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        vs_games = features.get('vs_opponent_games')
        if vs_games is None:
            return self._no_qualify()

        if vs_games <= 1:
            conf = 0.7 if vs_games == 0 else 0.5
            return self._qualify(
                confidence=conf,
                vs_opponent_games=vs_games,
                reason=f'Fresh opponent matchup ({vs_games} prior games)',
            )
        return self._no_qualify()


# =============================================================================
# Session 465 — Combo signals (4-season replay validated pairs)
# =============================================================================


class DayGameHighCSWComboOverSignal(BaseMLBSignal):
    """Day game + high CSW pitcher — visibility stress + elite pitch quality.

    Session 465: 4-season cross-validated: 73.0% HR (N=122).
    2022: 68.4%, 2023: 65.0%, 2024: 75.0%, 2025: 82.1%.
    Day game visibility stress + pitcher CSW% >= 30% = compounding K advantage.
    PROMOTED Session 465 — consistent all 4 seasons.
    """
    tag = "day_game_high_csw_combo_over"
    description = "Day game + high CSW (>= 30%) — visibility + pitch quality"
    direction = "OVER"
    is_shadow = False  # PROMOTED Session 465

    CSW_THRESHOLD = 0.30

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        is_day = features.get('is_day_game')
        csw = features.get('season_csw_pct')
        if is_day is None or csw is None:
            return self._no_qualify()

        if is_day and csw >= self.CSW_THRESHOLD:
            csw_score = min(1.0, (csw - 0.25) / 0.10)
            conf = min(1.0, 0.25 + csw_score * 0.5)
            return self._qualify(
                confidence=conf,
                is_day_game=is_day,
                season_csw_pct=round(csw, 3),
                reason=f'Day game + elite CSW ({csw:.1%}) — visibility stress + pitch quality',
            )
        return self._no_qualify()


class DayGameElitePeripheralsComboOverSignal(BaseMLBSignal):
    """Day game + elite peripherals (FIP < 3.5, K/9 >= 9.0) — ace in visibility stress.

    Session 465: 4-season replay: 72.6% HR (N=190). Elite pitchers compound
    the visibility disadvantage from day games. Hitters facing elite stuff
    in difficult visibility conditions = elevated K rate.
    """
    tag = "day_game_elite_peripherals_combo_over"
    description = "Day game + elite peripherals (FIP < 3.5, K/9 >= 9.0)"
    direction = "OVER"
    is_shadow = True

    FIP_THRESHOLD = 3.5
    K9_THRESHOLD = 9.0

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        is_day = features.get('is_day_game')
        fip = features.get('fip')
        k_per_9 = features.get('season_k_per_9')
        if is_day is None or fip is None or k_per_9 is None:
            return self._no_qualify()

        if is_day and fip < self.FIP_THRESHOLD and k_per_9 >= self.K9_THRESHOLD:
            fip_score = max(0, (self.FIP_THRESHOLD - fip) / 1.5)
            k9_score = max(0, (k_per_9 - 8.0) / 4.0)
            conf = min(1.0, 0.15 + (fip_score + k9_score) / 2.0 * 0.7)
            return self._qualify(
                confidence=conf,
                is_day_game=is_day,
                fip=round(fip, 2),
                k_per_9=round(k_per_9, 1),
                reason=f'Day game + elite ace: {fip:.2f} FIP, {k_per_9:.1f} K/9',
            )
        return self._no_qualify()


class HighCSWLowEraHighKComboOverSignal(BaseMLBSignal):
    """High CSW + low ERA + high K/9 — elite pitcher across all dimensions.

    Session 465: 4-season replay: 71.0% HR (N=169). Three independent markers
    of elite pitch quality: called strike dominance (CSW >= 30%), results-based
    dominance (ERA < 3.0), and strikeout ability (K/9 >= 8.5). Pitcher excelling
    in all three = peak K environment.
    """
    tag = "high_csw_low_era_high_k_combo_over"
    description = "High CSW (>= 30%) + low ERA (< 3.0) + K/9 (>= 8.5)"
    direction = "OVER"
    is_shadow = True

    CSW_THRESHOLD = 0.30
    ERA_THRESHOLD = 3.0
    K9_THRESHOLD = 8.5

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        csw = features.get('season_csw_pct')
        era = features.get('season_era')
        k_per_9 = features.get('season_k_per_9')
        if csw is None or era is None or k_per_9 is None:
            return self._no_qualify()

        if csw >= self.CSW_THRESHOLD and era < self.ERA_THRESHOLD and k_per_9 >= self.K9_THRESHOLD:
            csw_score = min(1.0, (csw - 0.25) / 0.10)
            era_score = max(0, (self.ERA_THRESHOLD - era) / 1.5)
            k9_score = max(0, (k_per_9 - 7.5) / 4.0)
            conf = min(1.0, (csw_score + era_score + k9_score) / 3.0)
            return self._qualify(
                confidence=conf,
                season_csw_pct=round(csw, 3),
                season_era=round(era, 2),
                k_per_9=round(k_per_9, 1),
                reason=f'Elite on all fronts: {csw:.1%} CSW, {era:.2f} ERA, {k_per_9:.1f} K/9',
            )
        return self._no_qualify()


class XfipEliteOverSignal(BaseMLBSignal):
    """xFIP < 3.5 — elite underlying pitching skill regardless of ERA.

    Session 465: 4-season cross-validated: 67.5% HR (N=704).
    2022: 63.2%, 2023: 68.0%, 2024: 67.5%, 2025: 71.9%.
    xFIP normalizes HR/FB rate to league average — identifies elite stuff
    even when ERA is inflated by bad luck. Wider than elite_peripherals.
    PROMOTED Session 465 — consistent all 4 seasons, large N.
    """
    tag = "xfip_elite_over"
    description = "xFIP < 3.5 — elite underlying stuff"
    direction = "OVER"
    is_shadow = False  # PROMOTED Session 465

    XFIP_THRESHOLD = 3.5

    def evaluate(self, prediction: Dict,
                 features: Optional[Dict] = None,
                 supplemental: Optional[Dict] = None) -> MLBSignalResult:
        if prediction.get('recommendation') != 'OVER':
            return self._no_qualify()
        if not features:
            return self._no_qualify()

        xfip = features.get('xfip')
        if xfip is None:
            return self._no_qualify()

        if xfip < self.XFIP_THRESHOLD:
            conf = min(1.0, (self.XFIP_THRESHOLD - xfip) / 1.5)
            return self._qualify(
                confidence=conf,
                xfip=round(xfip, 2),
                reason=f'Elite xFIP ({xfip:.2f}) — top-tier underlying stuff',
            )
        return self._no_qualify()
