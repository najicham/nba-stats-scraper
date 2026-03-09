"""MLB Pitcher Strikeout Signals — 14 active + 6 shadow + 6 negative filters + 2 observation.

Active Signals (14):
  high_edge                       — Edge >= 1.0 K (base signal)
  swstr_surge                     — SwStr% last 3 > season avg + 2% (demoted from rescue, Session 444)
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

Shadow Signals (6):
  line_movement_over    — Line dropped 0.5+ from open
  weather_cold_under    — Temp < 50F
  platoon_advantage     — Pitcher hand vs lineup handedness
  ace_pitcher_over      — Top 20% K/9 pitcher
  catcher_framing_over  — Elite catcher framing
  pitch_count_limit_under — Documented pitch count cap

Negative Filters (6):
  bullpen_game_skip     — Opener/bullpen game detected
  il_return_skip        — First start from IL
  pitch_count_cap_skip  — Under-only: documented pitch count cap
  insufficient_data_skip — < 3 career starts
  pitcher_blacklist     — Block pitchers with <45% HR (Session 444, expanded to 23)
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
    """SwStr% last 3 starts > season avg + 2% — pitcher stuff is improving."""
    tag = "swstr_surge"
    description = "SwStr% last 3 starts elevated vs season average"
    direction = "OVER"

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
    Removed: freddy_peralta (54.5%), tyler_glasnow (66.7%), paul_skenes (61.9%),
             hunter_greene (46.2%), yusei_kikuchi (51.9%), jose_soriano (no data).
    Added: 12 new pitchers with <45% HR at N >= 10 in regressor walk-forward.
    """
    tag = "pitcher_blacklist"
    description = "Pitcher on blacklist (walk-forward <45% HR at edge >= 0.75)"
    direction = "OVER"
    is_negative_filter = True

    # Session 443-444: Walk-forward + season replay validated, <45% HR
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
        'mackenzie_gore',      # 40.9% HR, N=22
        'bailey_ober',         # 40.0% HR, N=20
        'zach_eflin',          # 30.0% HR, N=10
        'ryne_nelson',         # 30.8% HR, N=13
        'jameson_taillon',     # 33.3% HR, N=12
        'ryan_feltner',        # 33.3% HR, N=12
        'luis_severino',       # 42.1% HR, N=19
        'randy_vasquez',       # 27.8% HR, N=18
        # Session 444 additions (season replay 0% or <40% HR at N >= 3)
        'adrian_houser',       # 0-4 (0% HR)
        'stephen_kolek',       # 0-3 (0% HR)
        'dean_kremer',         # 1-3 (25% HR)
        'michael_mcgreevy',    # 1-3 (25% HR)
        'tyler_mahle',         # 1-3 (25% HR)
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
