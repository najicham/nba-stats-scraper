"""Drawdown circuit breaker: stop betting when we are actually losing money.

WHY THIS IS THE REAL BREAKER (2026-08-21)
-----------------------------------------
`shared/config/edge_halt.py` used to claim this job. It cannot do it. On an
invariant basis its metric does not move at all — across five seasons of a
fixed walk-forward procedure the median edge sits at 0.73-1.00 with no season
standing out, and March 2026 reads ABOVE 2022-03, 2023-01 and 2025-01. Worse,
during the only collapse this system has experienced the metric was
**anti-correlated with the danger**: it read "halt" throughout 2026-03-04..08,
the highest-pick-volume days of the season, which produced the loss. It has
been demoted to a degeneracy guard.

Realized profit and loss is the only measured quantity that tracked the
collapse. That makes this module the circuit breaker and that one a smoke
alarm. Owner decision 4, 2026-08-21.

WHAT THE DATA SAYS
------------------
Production unit curve, 2025-26 (175 graded best bets, 105-70, flat 1u at -110):

    cumulative peak            35.90 on 2026-03-05
    trough                     21.63 on 2026-03-09
    max drawdown               14.27u
    max drawdown before 03-04   3.64u

Cross-season, replaying BB-shaped pick rules over `walkforward_sim_predictions`
(the leak-free basis; prior-season rows in `player_prop_predictions` are
contaminated), season-scoped max drawdown separates cleanly:

    2021-22   7.2   flat season
    2022-23  11.6   no-edge season
    2023-24   7.6   healthy
    2024-25  14.8   no-edge season
    2025-26   5.1   healthy

Healthy seasons top out at 5.1-7.6; no-edge seasons reach 11.6-14.8; the live
collapse hit 14.3. Thresholds are placed in that gap.

**State plainly what this cannot do.** 9.2 of March's 14.3 units died on a
SINGLE slate (03-08 went 2-11). Both guards here evaluate at 5 AM on data
through yesterday, so any threshold above 4.09u misses that event entirely.
A daily-cadence drawdown halt cannot prevent a one-slate catastrophe — it can
only truncate a bleed. Chasing that slate by dropping the threshold to 4u is
the wrong trade: on a 53-59% curve it fires 2-5x a season and costs up to 11u.
The slate belongs to the volume guard below, which catches it without touching
this threshold.

Honest limits: the collapse is N=1; the cross-season drawdowns come from a
49-59% raw walk-forward curve rather than the ~60% BB pipeline, so healthy-season
false-positive rates are an UPPER bound; and the healthy production baseline
(3.64u) covers eight weeks, not a season — `signal_best_bets_picks` starts
2026-01-09.

THE VOLUME GUARD IS THE HALF THAT PAYS
--------------------------------------
Published picks per day ran a season median of 2, then 2026-03-04..08 produced
**9, 13, 1, 10, 16** — the highest volume of the season, and 16 exceeds even the
15/day merger cap. Replayed at 5 AM cadence the volume guard fires on one
non-March day and on 03-05 and 03-08, netting about +8u for the season against a
single false-positive episode in 58 pick-days.

It has no grading dependency — counts exist at export time, D-1 — so it keeps
working when grading is late and the drawdown guard is blind. That is a
load-bearing reason to run both.

It cannot fire on 2026-03-04 itself at 5 AM cadence: that day's count does not
exist yet. Catching day one requires an export-time cap in `pipeline_merger`,
which degrades gracefully (trim to top-N) instead of zeroing. Recommended
follow-up, deliberately out of scope here.

MEASURED RESULT OF BOTH GUARDS TOGETHER
---------------------------------------
Replayed over 2025-26 at true 5 AM cadence (each day judged only on data that
existed that morning), against a season that actually returned +25.45u:

    halt days                 6, in a single episode
    losses avoided       +14.27u
    winnings forgone      -2.45u
    net                  +11.82u
    season with guards    +37.27u, max drawdown capped near 4u instead of 14.27u

The drawdown guard alone contributes almost nothing here — the volume guard
removes the slates before the curve ever falls far enough to trip it. That is
the intended division of labour: volume is fast, cheap and needs no grading;
drawdown is the slow backstop for the different failure of normal volume and
sustained losing, which is what 2022-23 and 2024-25 look like in the
walk-forward replay.
"""

import logging
import os
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# --- Payout ------------------------------------------------------------------

#: Win return at -110. Note the project's own measurement: reporting ROI at a
#: flat -110 overstates reality by 3.1-4.5pp because of execution leakage. The
#: thresholds below were calibrated on this same convention, so both sides carry
#: the bias; change one and you must re-measure the other.
WIN_UNITS = float(os.environ.get('NBA_DD_WIN_UNITS', '0.909'))

# --- Drawdown tiers ----------------------------------------------------------

#: Soft halt. 65% above the observed healthy production maximum (3.64) and at or
#: above every healthy proxy season (5.1-7.6) except one 6.37 touch.
DD_SOFT_THRESHOLD = float(os.environ.get('NBA_DD_SOFT', '6.0'))

#: Hard halt. Outside every healthy observation on every basis.
DD_HARD_THRESHOLD = float(os.environ.get('NBA_DD_HARD', '10.0'))

#: Calendar days a soft halt holds before releasing with a peak reset.
#: (Calendar, not game days, matching MAX_HALT_DAYS in edge_halt — a halt must
#: keep aging through an all-star break or a data gap.)
DD_SOFT_COOLDOWN_DAYS = int(os.environ.get('NBA_DD_SOFT_COOLDOWN', '3'))

#: Calendar days a hard halt holds. Longer, because reaching it means the
#: season's thesis is in question, not just a bad week.
DD_HARD_COOLDOWN_DAYS = int(os.environ.get('NBA_DD_HARD_COOLDOWN', '7'))

#: Absolute lifetime. A drawdown halt FREEZES the curve — no picks, no results,
#: so the metric can never recover on its own. Without this the guard is the
#: permanent trap the edge-halt rewrite exists to remove. Permanence requires an
#: operator `halt_overrides` row.
DD_MAX_HALT_DAYS = int(os.environ.get('NBA_DD_MAX_HALT_DAYS', '21'))

#: Escalate for operator review after this many soft halts in one season.
DD_MAX_EPISODES_SEASON = int(os.environ.get('NBA_DD_MAX_EPISODES', '3'))

#: Below this many graded picks the curve is too short to judge.
DD_MIN_GRADED = int(os.environ.get('NBA_DD_MIN_GRADED', '20'))

# --- Volume anomaly ----------------------------------------------------------

# Halt when a day published >= max(VOL_ABSOLUTE_MIN, VOL_MULTIPLE x trailing
# median), looking back VOL_COOLDOWN_DAYS.
#
# Chosen from a 36-cell grid replayed over 2025-26 (net units = losses avoided
# minus winnings forgone). The point is the PLATEAU, not the maximum:
#
#   MIN  MULT  WINDOW | halt days  episodes  avoided  forgone     net
#     8   3.0       1 |         4         3     2.09     4.27   -2.18
#     8   3.0       2 |         7         3     7.18     4.91   +2.27
#    10   2.5       3 |         6         1    14.27     2.45  +11.82
#    10   3.0       3 |         6         1    14.27     2.45  +11.82   <- taken
#    10   4.0       3 |         3         1    13.27     0.00  +13.27
#    12   3.0       3 |         6         1    14.27     2.45  +11.82
#    14   4.0       3 |         0         0     0.00     0.00    0.00
#
# Everything at MIN >= 10 with a 3-day window returns +11.8 to +13.3 with ONE
# episode and 0-2.45u forgone, and is insensitive to the multiple — that
# insensitivity is the evidence the setting is not fitted. The grid maximum
# (+13.64 at MIN=10/2.5/2) was deliberately NOT taken; this repo has a
# documented history of tuning on tiny samples and reverting.
#
# MIN=8 is the one clearly wrong choice: it fires on the 9-pick day of
# 2026-03-04 and forgoes 03-05's +4.27.
#
# The 3-day window is load-bearing. Volume spikes and the slates they poison
# are a day or two apart: 03-06 published 13 picks, 03-07 published 1, and the
# 03-08 slate lost 9.18u. A 1-day window sees the quiet day and lets it through.
#
# ⚠️ Calibrated on ONE episode across 58 pick-days of a single season. No
# cross-season basis exists — production pick volume is pipeline-determined and
# only 2025-26 has it. Treat as a coarse guard; do not tune it on a bad week.
VOL_MULTIPLE = float(os.environ.get('NBA_VOL_MULT', '3.0'))
VOL_ABSOLUTE_MIN = int(os.environ.get('NBA_VOL_MIN', '10'))
VOL_LOOKBACK_PICK_DAYS = int(os.environ.get('NBA_VOL_LOOKBACK', '10'))
VOL_MIN_PRIOR_PICK_DAYS = int(os.environ.get('NBA_VOL_MIN_PRIOR_DAYS', '5'))
VOL_COOLDOWN_DAYS = int(os.environ.get('NBA_VOL_COOLDOWN', '3'))

SEASON_START_MONTH = 10
SEASON_START_DAY = 1

HALT_REASON_DRAWDOWN = 'unit_drawdown'
HALT_REASON_VOLUME = 'volume_anomaly'


def season_start_for(target_date: date) -> date:
    """First day of the season containing `target_date`.

    The peak is season-scoped on purpose: an April drawdown must not govern
    October, six months and one fleet later. Same reasoning as `edge_halt`'s
    replay clamp.
    """
    year = target_date.year
    if (target_date.month, target_date.day) < (SEASON_START_MONTH, SEASON_START_DAY):
        year -= 1
    return date(year, SEASON_START_MONTH, SEASON_START_DAY)


def build_daily_pnl_query(project_id: str = 'nba-props-platform') -> str:
    """Daily graded best-bets results, season to date.

    The five-key join is not optional. `prediction_accuracy` holds one row per
    (player, date, system, recommendation, line); joining on fewer keys
    multiplies rows and inflates both wins and losses. Params: @season_start,
    @target_date.
    """
    return f"""
        WITH picks AS (
          SELECT DISTINCT
            game_date, player_lookup, system_id, recommendation, line_value
          FROM `{project_id}.nba_predictions.signal_best_bets_picks`
          WHERE game_date >= @season_start AND game_date < @target_date
            AND IFNULL(is_voided, FALSE) = FALSE
        )
        SELECT
          p.game_date,
          COUNTIF(pa.prediction_correct) AS wins,
          COUNTIF(NOT pa.prediction_correct) AS losses
        FROM picks p
        JOIN `{project_id}.nba_predictions.prediction_accuracy` pa
          ON  pa.game_date      = p.game_date
          AND pa.player_lookup  = p.player_lookup
          AND pa.system_id      = p.system_id
          AND pa.recommendation = p.recommendation
          AND pa.line_value     = p.line_value
        WHERE pa.game_date >= @season_start AND pa.game_date < @target_date
          AND pa.has_prop_line = TRUE
          AND pa.recommendation IN ('OVER', 'UNDER')
          AND pa.prediction_correct IS NOT NULL
        GROUP BY p.game_date
        ORDER BY p.game_date
    """


def build_daily_volume_query(project_id: str = 'nba-props-platform') -> str:
    """Published pick counts per day, season to date. No grading dependency.

    Params: @season_start, @target_date.
    """
    return f"""
        SELECT
          game_date,
          COUNT(DISTINCT CONCAT(
            player_lookup, '|', recommendation, '|', CAST(line_value AS STRING)
          )) AS picks
        FROM `{project_id}.nba_predictions.signal_best_bets_picks`
        WHERE game_date >= @season_start AND game_date < @target_date
        GROUP BY game_date
        HAVING picks > 0
        ORDER BY game_date
    """


def evaluate_drawdown(rows: Sequence[Any], target_date: date) -> Dict[str, Any]:
    """Replay the unit curve and return the drawdown halt state for `target_date`.

    Faithful simulation rather than a plain running maximum: once the guard
    halts, subsequent days are SKIPPED (a halt means no picks, so no results),
    and on release the peak is reset to the cumulative at that moment.

    **The peak reset is what makes this releasable at all.** A halt freezes the
    curve, so drawdown-from-the-old-peak stays above the threshold forever and
    the halt re-fires every morning — the same latch failure the edge-halt
    rewrite had to fix with `lifetime_spent`.
    """
    cum = 0.0
    peak = 0.0
    graded = 0
    halted = False
    tier: Optional[str] = None
    halt_started: Optional[date] = None
    episodes = 0
    lifetime_expired = False
    last_date: Optional[date] = None

    def _cooldown_for(t: Optional[str]) -> int:
        return DD_HARD_COOLDOWN_DAYS if t == 'hard' else DD_SOFT_COOLDOWN_DAYS

    for row in rows:
        day = getattr(row, 'game_date', None)
        wins = int(getattr(row, 'wins', 0) or 0)
        losses = int(getattr(row, 'losses', 0) or 0)
        if day is None or (wins + losses) == 0:
            continue
        last_date = day

        if halted:
            elapsed = (day - halt_started).days if halt_started else 0
            if elapsed >= DD_MAX_HALT_DAYS:
                halted, tier, halt_started = False, None, None
                lifetime_expired = True
                peak = cum
                logger.warning(
                    "Drawdown halt hit its %s-day lifetime and released. If the "
                    "drawdown is real, an operator must write a halt_overrides row.",
                    DD_MAX_HALT_DAYS,
                )
            elif elapsed >= _cooldown_for(tier):
                halted, tier, halt_started = False, None, None
                # Reset the baseline, or the frozen curve re-halts immediately.
                peak = cum
            else:
                # Halted: these results would not have existed. Skip them.
                continue

        cum += wins * WIN_UNITS - losses
        graded += wins + losses
        peak = max(peak, cum)
        drawdown = peak - cum

        if graded >= DD_MIN_GRADED and not halted:
            if drawdown >= DD_HARD_THRESHOLD:
                halted, tier, halt_started = True, 'hard', day
                episodes += 1
            elif drawdown >= DD_SOFT_THRESHOLD:
                halted, tier, halt_started = True, 'soft', day
                episodes += 1

    # Age an open halt forward to the target date, which may be well past the
    # last graded day (a halt stops picks, so grading stops too).
    if halted and halt_started is not None:
        elapsed = (target_date - halt_started).days
        if elapsed >= DD_MAX_HALT_DAYS:
            halted, tier, lifetime_expired = False, None, True
            peak = cum
        elif elapsed >= _cooldown_for(tier):
            halted, tier = False, None
            peak = cum

    result: Dict[str, Any] = {
        'halt_active': halted,
        'dd_tier': tier,
        'dd_units': round(peak - cum, 3),
        'dd_cum_units': round(cum, 3),
        'dd_peak_units': round(peak, 3),
        'dd_graded_picks': graded,
        'dd_graded_through': last_date.isoformat() if last_date else None,
        'dd_grading_lag_days': (target_date - last_date).days if last_date else None,
        'dd_season_start': season_start_for(target_date).isoformat(),
        'dd_started': halt_started.isoformat() if (halted and halt_started) else None,
        'dd_threshold': DD_HARD_THRESHOLD if tier == 'hard' else DD_SOFT_THRESHOLD,
        'dd_episode_count_season': episodes,
        'dd_escalated': episodes >= DD_MAX_EPISODES_SEASON,
        'dd_lifetime_expired': lifetime_expired,
        'reason': '',
    }
    if halted:
        result['reason'] = (
            f"Unit-drawdown halt ({tier}): {result['dd_units']:.2f}u below the "
            f"season peak of {result['dd_peak_units']:.2f}u "
            f"(threshold {result['dd_threshold']}u, {graded} graded picks, "
            f"halted since {result['dd_started']}, releases after "
            f"{_cooldown_for(tier)} days with a peak reset; hard cap "
            f"{DD_MAX_HALT_DAYS} days)"
        )
    return result


def evaluate_volume_anomaly(rows: Sequence[Any], target_date: date) -> Dict[str, Any]:
    """Did yesterday publish an anomalous number of picks?

    Measures the pipeline's own output, so it needs no grading and keeps working
    when the drawdown guard is blind. Days with zero picks are excluded from the
    trailing median so a halt cannot deflate its own baseline.
    """
    series: List[Any] = [r for r in rows if int(getattr(r, 'picks', 0) or 0) > 0]
    result: Dict[str, Any] = {
        'halt_active': False,
        'vol_yesterday_date': None,
        'vol_yesterday_picks': None,
        'vol_trailing_median': None,
        'vol_threshold_picks': None,
        'vol_prior_pick_days': 0,
        'vol_trigger_date': None,
        'vol_trigger_picks': None,
        'reason': '',
    }
    if not series:
        return result

    # Anything within the cooldown counts as "yesterday" — the anomaly and the
    # slate it poisons are often a day apart.
    recent = [r for r in series
              if 0 < (target_date - r.game_date).days <= VOL_COOLDOWN_DAYS]
    if not recent:
        return result

    # Check EVERY day in the cooldown window, not just the most recent one.
    # The anomaly and the slate it poisons are frequently a day or two apart —
    # 2026-03-06 published 13 picks and 03-07 published 1, so looking only at
    # "yesterday" on 03-08 sees the quiet day and lets the 03-08 slate through.
    # That slate lost 9.2u, which is most of the episode this guard exists for.
    for row in sorted(recent, key=lambda r: r.game_date, reverse=True):
        prior = [int(r.picks) for r in series if r.game_date < row.game_date]
        prior = prior[-VOL_LOOKBACK_PICK_DAYS:]
        if len(prior) < VOL_MIN_PRIOR_PICK_DAYS:
            continue
        ordered = sorted(prior)
        median = ordered[len(ordered) // 2]
        threshold = max(VOL_ABSOLUTE_MIN, VOL_MULTIPLE * median)
        picks = int(row.picks)

        # Always report the most recent evaluable day; only overwrite with an
        # older day when that older day is what triggers the halt.
        if result['vol_yesterday_date'] is None:
            result.update({
                'vol_yesterday_date': row.game_date.isoformat(),
                'vol_yesterday_picks': picks,
                'vol_trailing_median': median,
                'vol_threshold_picks': round(threshold, 1),
                'vol_prior_pick_days': len(prior),
            })

        if picks >= threshold:
            result.update({
                'halt_active': True,
                'vol_trigger_date': row.game_date.isoformat(),
                'vol_trigger_picks': picks,
                'vol_trailing_median': median,
                'vol_threshold_picks': round(threshold, 1),
                'vol_prior_pick_days': len(prior),
                'reason': (
                    f"Pick-volume anomaly: {row.game_date} published {picks} picks "
                    f"against a trailing median of {median} over {len(prior)} "
                    f"pick-days (threshold {threshold:.1f}). A volume spike of this "
                    f"shape preceded the 2026-03-08 slate that lost 9.2u."
                ),
            })
            return result
    return result
