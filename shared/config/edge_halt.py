"""Edge-collapse auto-halt: when is the market too compressed to publish picks?

The halt exists to stop the system betting through a collapse like 2026-02/04,
where the model kept emitting confident picks into a market it could no longer
beat. It is a circuit breaker, not a selectivity knob.

WHY THIS WAS REWRITTEN (2026-08-19)
-----------------------------------
The Session 515 implementation halted on **865 of 865 prediction-days across all
five seasons** — every day it was ever able to evaluate. Replayed against
``player_prop_predictions``, the 2025-26 season (415-235, 63.8%) would have
published zero picks, and so would the four seasons before it.

Two independent bugs:

1. **Scale mismatch.** The thresholds (7d avg edge < 5.0, edge-5+ rate < 50%)
   were calibrated on *best-bets-level* edges, which are >= 3 by construction.
   The query applied them to *every model's every prediction*, where the typical
   edge is ~2.5 and the edge-5+ rate is ~1-20%. Both conditions were therefore
   true essentially always. Measured all-season maxima: 4.41 avg edge, 19.5%
   edge-5+ rate — neither bar was cleared once in five seasons.

2. **Unreachable release.** Un-halting required the same 5.0 / 50% to be
   *exceeded*. Since the all-time maxima sit below both, a halt once fired could
   never release: a permanent zero-pick trap.

The replacement measures the same thing at the right scale and is
**fleet-size invariant**, which the old mean was not — the fleet grew from 2.3 to
16.8 models per player-game over these seasons, which moves a mean over raw
prediction rows for reasons that have nothing to do with the market.

THE METRIC
----------
Per player-game, take the **median edge across models** (one number per
opportunity, not per model). Then per day, the median of those, and the share at
edge >= 3. The halt reads the 7-calendar-day trailing window, strictly before the
target date.

    HALT    when  edge_med_7d < 1.4  AND  pct_e3_7d < 10%
    RELEASE when  edge_med_7d >= 1.6  for 3 consecutive days   (hysteresis)

Validated by replaying this exact query + state machine over every prediction-day
in ``player_prop_predictions``, 2021-11-05 → 2026-04-19 (988 evaluable days):

    healthy days (pre 2026-02-21)     false positives      0 / 931
    anomaly window (2026-02-21 on)    days halted         57 /  57
    state transitions, five seasons   exactly 1 (HALT on 2026-02-22) — no flapping

**The conjunction is what makes this safe — do not simplify it to the median
alone.** The median condition on its own fires in perfectly healthy seasons:

    season     edge_med_7d min   vs 1.4      pct_e3_7d min   vs 10%
    2021-22        1.587         +13.3%          13.56       +35.6%
    2022-23        1.637         +16.9%          12.43       +24.3%
    2023-24        1.367          -2.4%   <--    17.35       +73.5%
    2024-25        1.300          -7.1%   <--    15.14       +51.4%
    2025-26        0.757         -45.9%           1.37       -86.3%

In 2023-24 and 2024-25 the trailing median dipped below the halt threshold, and
what kept the system live was ``pct_e3_7d`` sitting 51-74% clear. A collapse
depresses both together; ordinary quiet stretches depress only the median.

Across the four pre-anomaly seasons, **0 of 843 days come within 25% of both
thresholds at once**, and the closest day (2023-05-13) is 28.8% clear on its
binding condition. The rejected mean-based variant had 26 such days and only
9.9% margin on its closest — which is why the median variant was chosen.

HONEST LIMITS — read before trusting the margin above
-----------------------------------------------------
Two caveats materially weaken the comfortable-looking numbers.

**1. The four prior seasons are backfills, and they look too good.** Their rows
in ``player_prop_predictions`` carry the same leak contamination already
documented for ``prediction_accuracy``: graded on that table, UNDER at edge >= 5
shows 72-86% hit rates against a clean walk-forward figure of 50-66%. Whatever
inflates hit rate plausibly also inflates edge, and their edge floors do run
25-40% above the live season's. So "0 of 843 prior-season days within 25% of both
thresholds" should be read as an upper bound on comfort, not a measurement.

**2. On the one clean season, the margin is 2.4%, not 28.8%.** Restricted to
2025-26 before the anomaly window — live predictions, no backfill — the halt
condition still fires on 0 of 88 days, but the closest day (2026-02-15) clears
its binding condition by only 2.4%, with the median falling 1.360 -> 1.300 ->
1.233 over the three days before the halt engages on 02-22. Those days are
arguably already the collapse onset rather than healthy days, and firing a week
earlier would have been no disaster. But the thresholds sit closer to live
healthy behavior than the five-season view implies.

**3. Collapse detection is a single episode (N=1).** Thresholds were placed off
healthy-day floors with margin, not fitted to the collapse.

Consequences: do not tighten these thresholds further on the strength of the
prior-season margin — it is the least trustworthy number here. Treat this as a
coarse circuit breaker, not a calibrated instrument, and do not tune it
mid-season on a bad week; that is the exact panic-deploy failure mode this
system has already paid for.

Owner-approved 2026-08-19 (median variant + hysteresis).
"""

import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# --- Thresholds ---------------------------------------------------------------

#: Halt when the 7d median-per-player-game edge falls below this.
HALT_EDGE_MEDIAN = float(os.environ.get('NBA_HALT_EDGE_MEDIAN', '1.4'))

#: ...AND the 7d share of player-games at edge >= 3 falls below this (percent).
HALT_PCT_EDGE_3PLUS = float(os.environ.get('NBA_HALT_PCT_E3', '10.0'))

#: Release when the 7d median edge recovers to at least this...
RELEASE_EDGE_MEDIAN = float(os.environ.get('NBA_HALT_RELEASE_EDGE_MEDIAN', '1.6'))

#: ...for this many consecutive days (hysteresis; prevents flapping).
RELEASE_CONSECUTIVE_DAYS = int(os.environ.get('NBA_HALT_RELEASE_DAYS', '3'))

#: Edge level whose prevalence forms the second halt condition.
EDGE_3PLUS = 3.0

#: Don't judge on a window this thin — see the warmup guard in regime_context.
MIN_DAYS_SAMPLED = 3

#: How far back to replay the state machine. Must exceed the longest plausible
#: uninterrupted halt, or a collapse older than the window would be forgotten and
#: silently released. The 2026 collapse ran 56 days.
LOOKBACK_DAYS = 120

#: Trailing window the metrics are computed over.
WINDOW_DAYS = 7


def build_daily_edge_query(project_id: str = 'nba-props-platform') -> str:
    """SQL for the daily edge series plus its 7d trailing aggregates.

    One row per calendar day in the lookback, including days with no games (so
    the window arithmetic stays calendar-correct). For the row at date D, the
    aggregates cover [D-7, D-1] — strictly before D, matching how the halt is
    evaluated for a target date.

    Params: @target_date (DATE), @lookback (INT64).
    """
    return f"""
        WITH player_games AS (
          -- One row per opportunity. MEDIAN across models, not mean across rows:
          -- the fleet grew 2.3 -> 16.8 models/player-game and a row-mean tracks
          -- that growth rather than the market.
          SELECT
            game_date,
            player_lookup,
            game_id,
            APPROX_QUANTILES(ABS(predicted_points - current_points_line), 100)[OFFSET(50)] AS edge_pg
          FROM `{project_id}.nba_predictions.player_prop_predictions`
          WHERE game_date >= DATE_SUB(@target_date, INTERVAL @lookback + {WINDOW_DAYS} DAY)
            -- Strictly BEFORE the target date. The window frame below already
            -- excludes each row's own date, but the halt for day D must not be
            -- able to depend on D's own predictions, which are generated the
            -- same morning the halt is evaluated.
            AND game_date < @target_date
            AND has_prop_line = TRUE
            AND current_points_line IS NOT NULL
            AND predicted_points IS NOT NULL
          GROUP BY game_date, player_lookup, game_id
        ),
        daily AS (
          SELECT
            game_date,
            APPROX_QUANTILES(edge_pg, 100)[OFFSET(50)] AS daily_edge_med,
            100.0 * COUNTIF(edge_pg >= {EDGE_3PLUS}) / NULLIF(COUNT(*), 0) AS daily_pct_e3,
            COUNT(*) AS n_player_games
          FROM player_games
          GROUP BY game_date
        ),
        spine AS (
          SELECT d AS game_date
          FROM UNNEST(GENERATE_DATE_ARRAY(
                 DATE_SUB(@target_date, INTERVAL @lookback DAY), @target_date)) AS d
        ),
        joined AS (
          SELECT s.game_date, dl.daily_edge_med, dl.daily_pct_e3, dl.n_player_games
          FROM spine s
          LEFT JOIN daily dl USING (game_date)
        )
        SELECT
          game_date,
          n_player_games,
          ROUND(AVG(daily_edge_med) OVER w, 4) AS edge_med_7d,
          ROUND(AVG(daily_pct_e3) OVER w, 4) AS pct_e3_7d,
          COUNT(daily_edge_med) OVER w AS days_sampled
        FROM joined
        WINDOW w AS (
          ORDER BY UNIX_DATE(game_date)
          RANGE BETWEEN {WINDOW_DAYS} PRECEDING AND 1 PRECEDING
        )
        ORDER BY game_date
    """


def evaluate_halt_state(rows: Sequence[Any]) -> Dict[str, Any]:
    """Walk the halt state machine forward over the daily series.

    Stateless by construction: the halt is re-derived from scratch each run by
    replaying ``LOOKBACK_DAYS`` of history, so there is no stored flag to drift,
    to be lost on redeploy, or to disagree between the exporter and the
    halt_state writer. Both callers replay the same series and reach the same
    answer.

    ``rows`` must be ordered by ``game_date`` ascending and expose
    ``game_date``, ``edge_med_7d``, ``pct_e3_7d``, ``days_sampled``.

    Returns the state as of the LAST row (i.e. the target date).
    """
    halted = False
    release_streak = 0
    halt_started: Optional[date] = None
    last: Optional[Any] = None
    evaluated = 0

    for row in rows:
        days = int(getattr(row, 'days_sampled', 0) or 0)
        edge_med = getattr(row, 'edge_med_7d', None)
        pct_e3 = getattr(row, 'pct_e3_7d', None)
        if days < MIN_DAYS_SAMPLED or edge_med is None:
            # Too thin to judge. Carry the existing state; do not credit the
            # release streak for a day that provided no evidence.
            continue

        evaluated += 1
        last = row
        edge_med = float(edge_med)
        pct_e3 = float(pct_e3) if pct_e3 is not None else 0.0

        if not halted:
            if edge_med < HALT_EDGE_MEDIAN and pct_e3 < HALT_PCT_EDGE_3PLUS:
                halted = True
                release_streak = 0
                halt_started = getattr(row, 'game_date', None)
        else:
            if edge_med >= RELEASE_EDGE_MEDIAN:
                release_streak += 1
                if release_streak >= RELEASE_CONSECUTIVE_DAYS:
                    halted = False
                    release_streak = 0
                    halt_started = None
            else:
                release_streak = 0

    result: Dict[str, Any] = {
        'halt_active': halted,
        'edge_med_7d': float(last.edge_med_7d) if last is not None else None,
        'pct_e3_7d': float(last.pct_e3_7d) if last is not None and last.pct_e3_7d is not None else None,
        'days_sampled': int(last.days_sampled) if last is not None else 0,
        'days_evaluated': evaluated,
        'halt_started': halt_started,
        'release_streak': release_streak,
        'reason': '',
    }

    if halted:
        result['reason'] = (
            f"Edge-collapse auto-halt: 7d median edge {result['edge_med_7d']:.2f} "
            f"< {HALT_EDGE_MEDIAN} AND {result['pct_e3_7d']:.1f}% of player-games at "
            f"edge >= {EDGE_3PLUS:.0f} < {HALT_PCT_EDGE_3PLUS}% "
            f"(halted since {halt_started}; releases after "
            f"{RELEASE_CONSECUTIVE_DAYS} consecutive days at median >= {RELEASE_EDGE_MEDIAN})"
        )
    return result


def query_halt_state(bq_client, target_date: date,
                     project_id: str = 'nba-props-platform',
                     timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Run the daily-edge query and evaluate the halt. None if the query fails.

    Returning None means "could not determine" — callers must NOT read that as
    "not halted". The 2026-07-03 fail-open bug in regime_context was exactly
    this confusion: a transient query failure lifted an active halt.
    """
    from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter

    job_config = QueryJobConfig(query_parameters=[
        ScalarQueryParameter('target_date', 'DATE', target_date),
        ScalarQueryParameter('lookback', 'INT64', LOOKBACK_DAYS),
    ])
    try:
        job = bq_client.query(build_daily_edge_query(project_id), job_config=job_config)
        rows = list(job.result(timeout=timeout) if timeout else job.result())
    except Exception as e:
        logger.warning(f"Edge-halt query failed (non-fatal): {e}")
        return None
    return evaluate_halt_state(rows)
