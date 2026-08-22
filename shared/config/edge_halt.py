"""Edge degeneracy guard: are the predictions themselves broken today?

WHAT THIS IS — AND WHAT IT IS NOT (rewritten 2026-08-21)
-------------------------------------------------------
This module used to claim it was a market circuit breaker: "the market is too
compressed to publish picks." **It cannot be that, and it never was.** The
measurements behind that claim are in the next section. What it is now is a
narrow pathology detector: it fires when the model fleet stops disagreeing with
the line *at all* — the shape of a feature pipeline emitting the vegas line back
as its own prediction. That is a real failure mode and it is worth halting on.
A losing week is not one of them.

**Be precise about what this does NOT cover.** An earlier draft of this docstring
claimed a stale line feed and a constant-serving model as covered. Both are
wrong, and wrong in the dangerous direction: a frozen line feed with live
predictions makes edges *grow*, and a model emitting a constant produces large
edges too. This guard reads both as healthier. Neither is caught here, and the
guards that would catch them are thin — `EDGE_ABS_MAX = 20` in
`shared/validation/prediction_sanity.py` only rejects absurd single rows, the
>95% same-direction block in `ml/signals/aggregator.py` misses a constant near
the middle of the line distribution, the coordinator's recommendation-skew check
only alerts, and both pipeline canaries are currently PAUSED. **Large-edge
degeneracy was an open gap; it is now partly closable.** Measured across five
seasons: every per-model-day with median edge >= 5.0 belongs to exactly four
pathology episodes (a wrong-artifact model at 9.20 and 100% UNDER on its first
serving day; three panic-era `ensemble_v1` spike days; 17 stale `catboost_v8`
days; and `zone_matchup_v1`, chronically miscalibrated for five seasons), while
model families that were ever well-calibrated top out at **4.52**. So level
thresholds ARE defensible here — see the guards proposed in the 2026-08-21
handoff (per-model median-edge cap 5.5 and a prediction-spread floor, both in
`aggregator.py`, plus a symmetric fleet bound here at 4.5 against a five-season
max of 3.224). Note a self-baseline change-detector does NOT work: in this
system's history broken models were born broken or came back broken from the
off-season — none drifted mid-stream, so there is no baseline at the moment it
is needed.

The **frozen line feed specifically** remains unresolvable at this layer, and
that is measured, not assumed: line staleness accumulates only about **1 point
over 2-7 days**, which is squarely inside the normal range at any aggregation.
It belongs to feed-freshness monitoring, and to the pick-volume anomaly guard
shipping with the drawdown halt — inflated edges surface as a volume spike,
which is exactly what 2026-03-04..08 looked like.

Note also that the basis is the median ACROSS models, so a single broken model
among three cannot move it. This guard only ever fires on degeneracy shared
across the fleet, which makes the per-model guards above load-bearing.

Real collapse detection lives elsewhere, because the evidence says it has to:
realized drawdown and pick-volume anomaly are the only measured quantities that
tracked the one collapse this system has actually experienced.

WHY THE MARKET-BREAKER FRAMING WAS RETIRED
------------------------------------------
The 2026-08-19 rewrite calibrated `edge_med_7d < 1.4 AND pct_e3_7d < 10%` against
the 2026-02/04 episode and reported 0 false positives in five seasons. Re-examined
2026-08-21, every part of that calibration turned out to be measuring the fleet
rather than the market.

**1. On a fixed model set, February 2026 never collapsed.** Average daily median
edge for the models present in BOTH January and February:

    ensemble_v1             2.036 -> 2.695   (up)
    similarity_balanced_v1  2.189 -> 2.719   (up)
    moving_average          1.944 -> 2.750   (up)
    zone_matchup_v1         3.021 -> 2.592
    catboost_v9             1.222 -> 1.190   (flat)
    catboost_v8             2.290 -> 2.053   (see caveat)
    ensemble_v1_1           2.16  -> 1.39    (down 35%)

Two caveats an independent re-derivation raised, recorded so nobody later reads
this table as fitted. `catboost_v8`'s February figure does not reproduce under
several reasonable recipes (approximate vs exact percentile, dedup-per-player,
`is_active`, Feb capped at 02-21) — those read it flat to slightly UP.
`ensemble_v1_1` genuinely spans both months and genuinely fell 35%; it was
missing from the original table. With both corrections the tally is roughly
6 up, 3 down, 1 flat. The conclusion is unchanged, and the count was never the
argument — claim 2 below is.

Within-month detail the averages hide: `moving_average` and `zone_matchup_v1`
stopped predicting on 2026-02-12, so two of the "up" models only cover early
February, and over Feb 15-28 `catboost_v9` fell 1.62 -> 0.62 while `ensemble_v1`
rose 2.29 -> 4.37. Late February on the fixed set is mixed, not uniformly
healthy — but nothing that reads as a coherent collapse.

The fleet-wide reading fell 1.9 -> 1.5 (pooled daily median; 1.9 -> 1.3 on the
old 7d metric) because **42** new line-hugging `system_id`s appeared, 30 of them
alive five days or less, with a median-of-medians edge of 1.00. They are one-off
experiment runs writing into `player_prop_predictions`, and they moved the
circuit breaker.

**2. On a fixed procedure, no season collapses.** `walkforward_sim_predictions`
(`wf_sim_v12noveg`, leak-free, walk-forward retrained, five seasons) monthly
median edge:

    2021-22  0.738 - 0.874        2024-25  0.783 - 0.923
    2022-23  0.728 - 0.919        2025-26  0.799 - 0.880
    2023-24  0.823 - 0.999            Feb .799  Mar .839  Apr .880

Daily granularity around the damage window shows no dip either: 2026-03-04..08
read 1.08 / 0.89 / 0.84 / 0.93 / 0.82, at or above the series mean. The basis
starts 56 days into each season (walk-forward warm-up), so this is a Dec-Apr
claim; it says nothing about October or November.

March 2026 (0.839) reads ABOVE 2022-03 (0.738), 2023-01 (0.728) and 2025-01
(0.783). The quantity does not move. Note also that this basis would sit at
~0.85 every month of every season — permanently below the old 1.4 threshold.
There is no threshold on median edge that separates healthy from collapsed,
because on an invariant basis the metric is flat.

**3. The market never left its historical range.** Vegas MAE (closing line vs
actual points — model-free, so immune to the prediction-side leak contamination)
by month runs 4.64-5.38 across five seasons. Feb-2026 5.054, Mar-2026 5.044,
Apr-2026 5.391: normal to loose. The tightest recent month was Jan-2026 (4.719),
which was the system's best month (73.1% BB hit rate).

Stated honestly at daily resolution rather than monthly: the 7d trailing MAE did
touch five-season lows in this window — about 4.48 on 2026-02-20 and 4.68-4.79
around Mar 7-8 — so the Session-483 "March 8 was 4.40, TIGHT" reading was the
tight end of normal, not fiction. What it was not is a regime break, and the
tightest stretch (late February) *preceded* rather than caused the loss. Note
too that Dec-2025 was the loosest month in five seasons, so the within-season
move was loose -> normal, not normal -> tight.

**4. March 2026 was over-publishing, not a drought.** Picks per day ran ~3 in
January and ~2 in February, then 2026-03-04 through 03-08 produced 9, 13, 1, 10
and 16 — the highest volume of the season. 2026-03-08 went 2-11. The unit curve
at -110 peaked at 35.90 on 03-05 and fell to 22.63 on 03-08: **13.3 units lost in
two days**, against a season-long prior maximum drawdown of 3.64. Through all of
it the old metric was reading "median 0.97, halt". **The metric and the danger
were anti-correlated in the single episode it was calibrated on.**

WHAT THIS MODULE MEASURES NOW
-----------------------------
Per (day, model): the model's own median edge and its share of predictions at
edge >= 3. Per day: the MEDIAN ACROSS MODELS of each. Then the 7-calendar-day
trailing mean, strictly before the target date.

Two properties make this basis worth keeping even though the levels are still
fleet-dependent:

* **Warm-up quarantine.** A model contributes only after MIN_MODEL_HISTORY_DAYS
  distinct prediction-days for its FAMILY, and only on days where it produced at
  least MIN_MODEL_ROWS_PER_DAY rows.

  ⚠️ **Read this before re-tightening anything.** Keyed on `system_id` the
  quarantine did remove the transient experiment models (February 1.40 / 17.0%
  -> 1.63 / 22.5%, first old-threshold breach moving 2026-02-22 -> 03-04). Keyed
  on FAMILY — which it must be, see below — **45 system_ids become warm on their
  first prediction day by inheritance, re-admitting 29 February experiment
  model-days.** February reads 1.50 / 19.7%, and under the OLD 1.4 / 10%
  thresholds the first breach would regress to **2026-02-25, three days earlier
  than before the quarantine existed.**

  So the quarantine is no longer what protects against the February episode —
  **the loosened thresholds are, entirely.** That is a second, independent reason
  never to move 0.35 / 0.30% back toward the old values: doing so reinstates the
  false halt AND arrives at it sooner.

  Family keying is still correct, because the alternative is a guard that is
  structurally dead. `weekly_retrain` mints a new train-stamped `system_id` per
  generation, so under the intended weekly cadence each generation lives ~7 days
  and never clears a 7-day `system_id` quarantine: 80 of the 102 ids ever seen
  never reached warm, the basis fell to **1.7 warm models in March 2026 and 0.3
  in April**, and the entire currently-enabled fleet had `warm_days = 0`. Family
  keying restores 5.7 and 2.9.

  The obvious objection — that inheriting history hides a fresh line-hugging
  generation — was measured and is false. Differencing each model-day against
  its same-day family mates, a generation's day-1 delta is **-0.065 (median
  0.00)**; the systematic drift runs the other way, with models aged 14+ days
  sitting **+0.427** above their family. Stale models inflate; fresh ones do not
  hug. Inheritance is what makes a broken fresh artifact visible on day one
  instead of never.
* **Median across models, not a mean over rows.** The fleet has ranged from 2.3
  to 16.8 models per player-game; a row-mean tracks fleet size directly.

    HALT    when  edge_med_7d < 0.35  AND  pct_e3_7d < 0.30%
    RELEASE when  edge_med_7d >= 0.385  OR  pct_e3_7d >= 0.33%
                  for 2 consecutive evaluable days
    ...or unconditionally after MAX_HALT_DAYS (see below).

THRESHOLD CALIBRATION
---------------------
Both thresholds were LOOSENED from the previous 1.4 / 10.0. They sit below every
value observed on either basis in five seasons:

    basis                                    days   min edge_med_7d   min pct_e3_7d
    production, family-keyed (as shipped)    1663        0.800             4.47%
    production, system_id-keyed (historic)   1663        0.871             6.72%
    fixed procedure (wf_sim_v12noveg)         563        0.656             0.65%

The first row is the one that governs. The module's own rule — never change the
basis without re-measuring the floors — was very nearly violated when the keying
moved from `system_id` to family; the shipped floors are 0.800 / 4.47%, not the
0.871 / 6.72% originally quoted. The fixed-procedure floor stays binding either
way. 0.35 clears the tightest floor by 47%; 0.30% clears it by 54%. Zero days
breach either bar on any of the three bases. The fixed-procedure floor is the binding one
and it is the right one to respect: all three currently-enabled models are
v12_noveg-family, so a future fleet may well read like `wf_sim_v12noveg`. Note
`pct_e3_7d` dips below 1.0% on that basis in four of five seasons — which is why
the old 10% bar could not survive a fleet change, and why 0.30% is where a
pathology bar belongs.

The AND conjunction is retained. It is load-bearing for a narrower reason than
previously documented: `pct_e3_7d` is what keeps the system live when the median
dips, not what detects a collapse. Do not simplify to the median alone.

Do not tighten these back toward the old values. A threshold placed near live
healthy behavior on a metric that is a fleet property means enabling a model can
halt the season.

HONEST LIMITS
-------------
* Levels remain fleet-dependent. Warm-up stops transient experiments from moving
  the breaker; it does not make the metric invariant, and nothing does.
* Collapse detection here is N=0, not N=1. On an invariant basis the 2026
  episode does not appear at all. This guard has never been validated against a
  real degeneracy event because none has been observed.
* Early season the warm-up basis is empty for roughly the first 7 game-days, so
  the guard is dormant by construction. That is intended: do not run a circuit
  breaker you cannot calibrate.
* The basis can get thin exactly when it matters. Keyed on `system_id` it
  averaged **1.7 warm models in March 2026 and 0.3 in April** — the weekly
  retrainer mints a new train-stamped `system_id` per generation, so 80 of the
  102 `system_id`s ever seen never reached warm at all, and the guard finished
  the season measuring nobody. That is why the warm-up is keyed on model
  FAMILY (see the SQL). Family keying restores 5.7 warm models in March and 2.9
  in April, and February still reads 1.52 / 19.9% — nowhere near firing.
  `models_7d` is returned so a thin basis is visible rather than implicit.
* `MIN_MODEL_ROWS_PER_DAY` makes 1-2 game slates unevaluable, which is common in
  April. The guard carries state rather than judging on those days — the safe
  direction, but it means late-season coverage is patchier than mid-season.

Owner-approved 2026-08-21 (demote to degeneracy guard; bounded halt lifetime;
fail-closed with fallback; halt_state gates NBA picks).
"""

import logging
import os
from datetime import date, timedelta
from typing import Any, Dict, Optional, Sequence

logger = logging.getLogger(__name__)

# --- Basis -------------------------------------------------------------------

#: A model FAMILY joins the halt basis only after this many distinct
#: prediction-days. Keeps 1-5 day experiment runs from moving the circuit
#: breaker (defect a) without going dormant every time the weekly retrainer
#: mints a new train-stamped system_id (see MODEL_FAMILY_PATTERN).
MIN_MODEL_HISTORY_DAYS = int(os.environ.get('NBA_HALT_MIN_MODEL_DAYS', '7'))

#: Strips the `_train{MMDD}_{MMDD}` suffix weekly_retrain appends, so
#: `catboost_v12_noveg_train0206_0402` inherits the history of every earlier
#: `catboost_v12_noveg_*` generation. Without this the quarantine never clears:
#: each generation is warm for 0-2 days of its life, and the freshest models —
#: the ones most likely to ship a broken artifact — are the ones never measured.
MODEL_FAMILY_PATTERN = r'_train[0-9]{4}[-_]?[0-9]{0,4}.*$'

#: ...and only on days where it produced at least this many predictions.
MIN_MODEL_ROWS_PER_DAY = int(os.environ.get('NBA_HALT_MIN_MODEL_ROWS', '20'))

# --- Thresholds --------------------------------------------------------------

#: Halt when the 7d median-across-models edge falls below this.
HALT_EDGE_MEDIAN = float(os.environ.get('NBA_HALT_EDGE_MEDIAN', '0.35'))

#: ...AND the 7d median-across-models share at edge >= 3 falls below this (percent).
HALT_PCT_EDGE_3PLUS = float(os.environ.get('NBA_HALT_PCT_E3', '0.30'))

#: Release band. Release mirrors the halt test rather than using an independent,
#: much higher bar — the old asymmetry (halt < 1.4, release >= 1.6) meant a false
#: halt on 2026-02-15 would not have cleared for 63 days, through season end.
RELEASE_BAND = float(os.environ.get('NBA_HALT_RELEASE_BAND', '1.10'))
if RELEASE_BAND < 1.0:
    # A band below 1.0 makes the halt and release tests overlap, so a single day
    # can be both. The clear-then-halt ordering in the state machine is only
    # safe while they are disjoint.
    logger.warning("NBA_HALT_RELEASE_BAND=%s < 1.0 would overlap the halt and "
                   "release bands; clamping to 1.0.", RELEASE_BAND)
    RELEASE_BAND = 1.0
RELEASE_EDGE_MEDIAN = HALT_EDGE_MEDIAN * RELEASE_BAND
RELEASE_PCT_EDGE_3PLUS = HALT_PCT_EDGE_3PLUS * RELEASE_BAND

#: Consecutive evaluable days above the release band before the halt lifts.
RELEASE_CONSECUTIVE_DAYS = int(os.environ.get('NBA_HALT_RELEASE_DAYS', '2'))

#: Bounded automatic lifetime. An auto-halt self-releases after this many
#: calendar days no matter what the metric says, and says so loudly. Keeping the
#: system down past this point requires a human writing a `halt_overrides` row —
#: overrides can only ADD a halt, so permanence-by-human is the safe direction.
#: A false positive then costs two weeks, not a season.
MAX_HALT_DAYS = int(os.environ.get('NBA_HALT_MAX_DAYS', '14'))

#: Symmetric UPPER bound. The conditions above catch edges collapsing toward
#: zero; this catches the correlated large-edge failure no per-model guard can —
#: a fleet-wide feature-store regression, a mass wrong-artifact load, a unit
#: mismatch. Five-season maximum on this basis is 3.224 (2023-04-12), so 4.5
#: clears it by 40%, mirroring the convention used for the floors. Unlike the
#: floors this fires on ONE condition: there is no second quantity that
#: independently confirms "edges are impossibly large", and requiring one would
#: make the bound unreachable.
#:
#: Per-model large-edge pathology is NOT this guard's job — the basis is a
#: median across models, so one broken model cannot move it. That lives in
#: ml/signals/aggregator.py (median-edge cap 5.5, prediction-spread floor 2.0).
HALT_EDGE_MEDIAN_MAX = float(os.environ.get('NBA_HALT_EDGE_MEDIAN_MAX', '4.5'))

#: Edge level whose prevalence forms the second halt condition.
EDGE_3PLUS = 3.0

#: Don't judge on a window this thin — see the warmup guard in regime_context.
MIN_DAYS_SAMPLED = 3

#: How far back to replay the state machine, clamped to the current season (see
#: `series_start_for`). The old 120 was shorter than the Apr->Oct off-season, so
#: an end-of-season halt was always silently forgotten by the next opener —
#: contradicting the invariant the constant was documented to protect.
LOOKBACK_DAYS = int(os.environ.get('NBA_HALT_LOOKBACK_DAYS', '240'))

#: Trailing window the metrics are computed over.
WINDOW_DAYS = 7

#: NBA season boundary used for replay clamping.
SEASON_START_MONTH = 10
SEASON_START_DAY = 1

#: How stale the last `halt_state` row may be and still serve as the fallback
#: answer when the live query fails.
FALLBACK_MAX_AGE_DAYS = 3


def season_start_for(target_date: date) -> date:
    """First day of the NBA season containing `target_date` (Oct 1 boundary)."""
    year = target_date.year
    if (target_date.month, target_date.day) < (SEASON_START_MONTH, SEASON_START_DAY):
        year -= 1
    return date(year, SEASON_START_MONTH, SEASON_START_DAY)


def series_start_for(target_date: date, lookback_days: int = LOOKBACK_DAYS) -> date:
    """Where to begin replaying the state machine.

    The later of (target - lookback) and the current season's start. Replay is
    season-scoped on purpose: an edge halt live on the last day of April should
    not silently govern opening night in October, six months and one full fleet
    later. Carrying a halt across an off-season is an operator decision, and the
    `halt_overrides` table is how an operator makes it.
    """
    return max(target_date - timedelta(days=lookback_days), season_start_for(target_date))


def build_daily_edge_query(project_id: str = 'nba-props-platform') -> str:
    """SQL for the daily edge series plus its 7d trailing aggregates.

    One row per calendar day from @series_start to @target_date, including days
    with no games (so the window arithmetic stays calendar-correct). For the row
    at date D the aggregates cover [D-7, D-1] — strictly before D, matching how
    the halt is evaluated for a target date.

    Params: @target_date (DATE), @series_start (DATE).
    """
    return f"""
        WITH base AS (
          -- One row per prediction as written. Note ~20% of rows in a season
          -- window are repeat (game_date, system_id, player_lookup) tuples from
          -- intraday re-prediction runs, so a model that refreshes often
          -- over-weights its refreshed players here. Left as-is deliberately:
          -- the calibration floors in the module header were measured on this
          -- same basis, so metric and thresholds are self-consistent. Deduping
          -- to the latest row per player REQUIRES re-measuring those floors --
          -- never do one without the other.
          SELECT
            game_date,
            system_id,
            REGEXP_REPLACE(system_id, r'{MODEL_FAMILY_PATTERN}', '') AS family,
            ABS(predicted_points - current_points_line) AS edge
          FROM `{project_id}.nba_predictions.player_prop_predictions`
          -- Scan back past @series_start so warm-up history is established for
          -- models that were already running when the replay window opens.
          WHERE game_date >= DATE_SUB(@series_start, INTERVAL 60 DAY)
            -- Strictly BEFORE the target date. The window frame below already
            -- excludes each row's own date, but the halt for day D must not be
            -- able to depend on D's own predictions, which are generated the
            -- same morning the halt is evaluated.
            AND game_date < @target_date
            AND has_prop_line = TRUE
            AND current_points_line IS NOT NULL
            AND predicted_points IS NOT NULL
        ),
        family_days AS (
          SELECT family, game_date FROM base GROUP BY family, game_date
        ),
        history AS (
          -- Distinct prediction-days each FAMILY has accumulated strictly
          -- before this date. The warm-up quarantine (defect a): a family that
          -- has only existed for a few days is an experiment run, not the
          -- fleet. `family_days` is one row per (family, game_date), so the
          -- ordinal IS the count of strictly-earlier days.
          SELECT
            family,
            game_date,
            ROW_NUMBER() OVER (PARTITION BY family ORDER BY game_date) - 1 AS prior_days
          FROM family_days
        ),
        per_model_day AS (
          -- Still one row per SERVING model per day: family only decides
          -- eligibility, it does not pool distinct models into one number.
          SELECT
            game_date,
            system_id,
            ANY_VALUE(family) AS family,
            APPROX_QUANTILES(edge, 100)[OFFSET(50)] AS model_edge_med,
            100.0 * COUNTIF(edge >= {EDGE_3PLUS}) / NULLIF(COUNT(*), 0) AS model_pct_e3,
            COUNT(*) AS n_rows
          FROM base
          GROUP BY game_date, system_id
        ),
        warm AS (
          SELECT p.*
          FROM per_model_day p
          JOIN history h ON h.family = p.family AND h.game_date = p.game_date
          WHERE h.prior_days >= {MIN_MODEL_HISTORY_DAYS}
            AND p.n_rows >= {MIN_MODEL_ROWS_PER_DAY}
        ),
        daily AS (
          -- Median ACROSS MODELS, one number per model per day. A mean over raw
          -- prediction rows tracks fleet size (2.3 -> 16.8 models/player-game
          -- over these seasons) rather than anything about the predictions.
          --
          -- APPROX_QUANTILES(...)[OFFSET(50)] returns the LOWER-middle element
          -- for even n and never interpolates -- measured: [1.0, 10.0] -> 1.0.
          -- With a two-model warm fleet this is literally MIN across models.
          -- The bias is downward, i.e. toward halting, which is the safe
          -- direction for a guard, and the calibration floors in the module
          -- header were measured with this same estimator, so both sides of the
          -- comparison carry it. Switch to PERCENTILE_CONT only together with a
          -- re-measurement of those floors.
          SELECT
            game_date,
            APPROX_QUANTILES(model_edge_med, 100)[OFFSET(50)] AS daily_edge_med,
            APPROX_QUANTILES(model_pct_e3, 100)[OFFSET(50)] AS daily_pct_e3,
            COUNT(*) AS n_models
          FROM warm
          GROUP BY game_date
        ),
        spine AS (
          SELECT d AS game_date
          FROM UNNEST(GENERATE_DATE_ARRAY(@series_start, @target_date)) AS d
        ),
        joined AS (
          SELECT s.game_date, dl.daily_edge_med, dl.daily_pct_e3, dl.n_models
          FROM spine s
          LEFT JOIN daily dl USING (game_date)
        )
        SELECT
          game_date,
          n_models,
          ROUND(AVG(daily_edge_med) OVER w, 4) AS edge_med_7d,
          ROUND(AVG(daily_pct_e3) OVER w, 4) AS pct_e3_7d,
          ROUND(AVG(n_models) OVER w, 2) AS models_7d,
          COUNT(daily_edge_med) OVER w AS days_sampled
        FROM joined
        WINDOW w AS (
          ORDER BY UNIX_DATE(game_date)
          RANGE BETWEEN {WINDOW_DAYS} PRECEDING AND 1 PRECEDING
        )
        ORDER BY game_date
    """


def _is_collapse(edge_med: float, pct_e3: float) -> bool:
    """Edges have collapsed toward zero — both conditions, the AND is required."""
    return edge_med < HALT_EDGE_MEDIAN and pct_e3 < HALT_PCT_EDGE_3PLUS


def _is_inflated(edge_med: float) -> bool:
    """Edges are impossibly large — the correlated-degeneracy direction."""
    return edge_med > HALT_EDGE_MEDIAN_MAX


def _is_release(edge_med: float, pct_e3: float) -> bool:
    """Release test — the mirror of the halt test, widened by RELEASE_BAND.

    The collapse halt requires BOTH conditions, so releasing it requires only
    ONE to recover; anything else reintroduces the asymmetry that turned a false
    halt into a lost season. The inflation halt is one-sided, so it releases when
    the median comes back under the bound with the same band applied.
    """
    if edge_med > HALT_EDGE_MEDIAN_MAX / RELEASE_BAND:
        return False
    return edge_med >= RELEASE_EDGE_MEDIAN or pct_e3 >= RELEASE_PCT_EDGE_3PLUS


def evaluate_halt_state(rows: Sequence[Any]) -> Dict[str, Any]:
    """Walk the halt state machine forward over the daily series.

    Stateless by construction: the halt is re-derived from scratch each run by
    replaying the season-to-date series, so there is no stored flag to drift, to
    be lost on redeploy, or to disagree between the exporter and the halt_state
    writer. Both callers replay the same series and reach the same answer.

    ``rows`` must be ordered by ``game_date`` ascending and expose
    ``game_date``, ``edge_med_7d``, ``pct_e3_7d``, ``days_sampled`` and
    (optionally) ``models_7d``.

    Returns the state as of the LAST row (i.e. the target date).
    """
    halted = False
    release_streak = 0
    halt_started: Optional[date] = None
    lifetime_expired = False
    #: Latch set when a halt spends its automatic lifetime. Without it the state
    #: machine re-halts on the very next day of the same degenerate stretch and
    #: the lifetime cap accomplishes nothing. Cleared only by a genuine recovery
    #: day, so the guard re-arms for the NEXT episode, not this one.
    lifetime_spent = False
    halt_direction: Optional[str] = None
    #: Consecutive release-band days observed while NOT halted. Re-arming after a
    #: spent lifetime requires the same streak a normal release does — with a
    #: single day, a degenerate stretch oscillating around the band would re-arm
    #: on one noisy day and start a fresh 14-day halt, repeatedly, which spends
    #: far more than the advertised two weeks.
    rearm_streak = 0
    evaluated = 0
    #: The target-date row, whether or not it was thick enough to evaluate.
    #: Reporting the last EVALUATED row here was defect (e): a thin target day
    #: inherited an older day's `days_sampled`, so halt_state_writer's
    #: MIN_DAYS_SAMPLED guard could never reject it.
    target_row: Optional[Any] = None

    def _lifetime_lapsed(row_date: Optional[date]) -> bool:
        return (
            halt_started is not None
            and row_date is not None
            and (row_date - halt_started).days >= MAX_HALT_DAYS
        )

    for row in rows:
        target_row = row
        days = int(getattr(row, 'days_sampled', 0) or 0)
        edge_med = getattr(row, 'edge_med_7d', None)
        pct_e3 = getattr(row, 'pct_e3_7d', None)
        row_date = getattr(row, 'game_date', None)

        if days < MIN_DAYS_SAMPLED or edge_med is None:
            # Too thin to judge the metric. Carry the existing state and do not
            # credit either streak for a day that provided no evidence — but DO
            # keep aging the halt. The lifetime is a calendar-day promise, and a
            # halt that lapses during an all-star break or a pipeline gap must
            # not stay live until games and data both come back.
            if halted and _lifetime_lapsed(row_date):
                halted = False
                release_streak = 0
                halt_started = None
                lifetime_expired = True
                lifetime_spent = True
                logger.warning(
                    "Edge degeneracy halt hit its %s-day automatic lifetime during a "
                    "no-data stretch and released.", MAX_HALT_DAYS,
                )
            continue

        evaluated += 1
        edge_med = float(edge_med)
        pct_e3 = float(pct_e3) if pct_e3 is not None else 0.0

        if not halted:
            # A spent lifetime latches against the SAME pathology. A stretch that
            # flips to the OPPOSITE direction is a different failure — an artifact
            # swap during an outage looks exactly like this — and must re-arm the
            # guard immediately. Without this, a collapse halt that spent its
            # 14-day lifetime leaves the inflation bound disarmed for as long as
            # the inflation lasts, because inflated readings never satisfy
            # `_is_release` and so never accrue the re-arm streak. That would
            # disable HALT_EDGE_MEDIAN_MAX exactly when it is needed.
            if lifetime_spent and halt_direction is not None:
                now_inflated = _is_inflated(edge_med)
                if (halt_direction == 'collapsed' and now_inflated) or \
                        (halt_direction == 'inflated' and _is_collapse(edge_med, pct_e3)):
                    logger.warning(
                        "Degeneracy flipped direction (%s -> %s) after a spent "
                        "lifetime; re-arming immediately — this is a new pathology, "
                        "not a continuation.",
                        halt_direction, 'inflated' if now_inflated else 'collapsed',
                    )
                    lifetime_spent = False
                    lifetime_expired = False
                    rearm_streak = 0
            if _is_release(edge_med, pct_e3):
                rearm_streak += 1
                if rearm_streak >= RELEASE_CONSECUTIVE_DAYS:
                    # A sustained recovery re-arms the guard for the NEXT
                    # episode and clears the stale expiry flag, which otherwise
                    # keeps alerting on a months-old event.
                    lifetime_spent = False
                    lifetime_expired = False
            else:
                rearm_streak = 0
            if not lifetime_spent and (
                _is_collapse(edge_med, pct_e3) or _is_inflated(edge_med)
            ):
                halted = True
                halt_direction = 'inflated' if _is_inflated(edge_med) else 'collapsed'
                release_streak = 0
                rearm_streak = 0
                # A row with no game_date leaves halt_started None, which would
                # silently disable the lifetime cap. Not reachable from
                # build_daily_edge_query (the calendar spine always emits one).
                halt_started = row_date
                lifetime_expired = False
        else:
            # Bounded lifetime wins over the metric. An automatic halt that has
            # run MAX_HALT_DAYS without a human confirming it releases itself.
            if _lifetime_lapsed(row_date):
                halted = False
                release_streak = 0
                halt_started = None
                lifetime_expired = True
                lifetime_spent = True
                logger.warning(
                    "Edge degeneracy halt hit its %s-day automatic lifetime and released. "
                    "If the halt is real, an operator must write a halt_overrides row.",
                    MAX_HALT_DAYS,
                )
            elif _is_release(edge_med, pct_e3):
                release_streak += 1
                if release_streak >= RELEASE_CONSECUTIVE_DAYS:
                    halted = False
                    release_streak = 0
                    halt_started = None
            else:
                release_streak = 0

    def _f(attr: str) -> Optional[float]:
        if target_row is None:
            return None
        v = getattr(target_row, attr, None)
        return float(v) if v is not None else None

    result: Dict[str, Any] = {
        'error': False,
        'halt_active': halted,
        'halt_source': 'computed',
        'edge_med_7d': _f('edge_med_7d'),
        'pct_e3_7d': _f('pct_e3_7d'),
        'models_7d': _f('models_7d'),
        'days_sampled': int(getattr(target_row, 'days_sampled', 0) or 0) if target_row is not None else 0,
        'days_evaluated': evaluated,
        'halt_started': halt_started,
        'carried_forward_from': None,
        'release_streak': release_streak,
        'lifetime_expired': lifetime_expired,
        'lifetime_spent': lifetime_spent,
        'halt_direction': halt_direction if halted else None,
        'reason': '',
    }

    if halted:
        def _fmt(value: Optional[float], spec: str) -> str:
            # A halt can end on a target day with no metrics at all (7+ dataless
            # days before it). Formatting None crashed here, and the crash
            # escaped query_halt_state's try/except, breaking the module's
            # "always returns a dict" guarantee exactly when halted.
            return format(value, spec) if value is not None else 'n/a'

        held = (
            (getattr(target_row, 'game_date', None) - halt_started).days
            if halt_started is not None and getattr(target_row, 'game_date', None) is not None
            else 0
        )
        if halt_direction == 'inflated':
            result['reason'] = (
                f"Edge inflation halt: 7d median-across-models edge "
                f"{_fmt(result['edge_med_7d'], '.3f')} > {HALT_EDGE_MEDIAN_MAX} "
                f"(five-season maximum on this basis is 3.224). This is the "
                f"correlated large-edge signature — a feature-store regression, a "
                f"mass wrong-artifact load or a unit mismatch. Halted since "
                f"{halt_started}, day {held} of {MAX_HALT_DAYS}."
            )
            return result

        result['reason'] = (
            f"Edge degeneracy halt: 7d median-across-models edge "
            f"{_fmt(result['edge_med_7d'], '.3f')} < {HALT_EDGE_MEDIAN} AND "
            f"{_fmt(result['pct_e3_7d'], '.2f')}% of predictions at edge >= {EDGE_3PLUS:.0f} "
            f"< {HALT_PCT_EDGE_3PLUS}% (halted since {halt_started}, day {held} of "
            f"{MAX_HALT_DAYS}; releases on {RELEASE_CONSECUTIVE_DAYS} consecutive days "
            f"at median >= {RELEASE_EDGE_MEDIAN:.3f} OR pct_e3 >= {RELEASE_PCT_EDGE_3PLUS:.2f}%)"
        )
    return result


def _error_state(detail: str) -> Dict[str, Any]:
    """Sentinel for "could not determine".

    Deliberately NOT ``None`` and deliberately ``halt_active=None``. Both live
    callers used to read a bare ``None`` as "not halted" (defect c), so a
    transient BigQuery failure during a real halt published picks. A dict whose
    ``halt_active`` is neither True nor False cannot be misread that way.
    """
    return {
        'error': True,
        'error_detail': detail,
        'halt_active': None,
        'halt_source': 'error',
        'edge_med_7d': None,
        'pct_e3_7d': None,
        'models_7d': None,
        'days_sampled': 0,
        'days_evaluated': 0,
        'halt_started': None,
        'carried_forward_from': None,
        'release_streak': 0,
        'lifetime_expired': False,
        'lifetime_spent': False,
        'halt_direction': None,
        'reason': '',
    }


def query_halt_state(bq_client, target_date: date,
                     project_id: str = 'nba-props-platform',
                     timeout: Optional[float] = None) -> Dict[str, Any]:
    """Run the daily-edge query and evaluate the halt.

    Always returns a dict. On failure the dict has ``error=True`` and
    ``halt_active=None`` — callers must NOT read that as "not halted". Prefer
    `resolve_halt_state`, which applies the documented fallback chain.
    """
    from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter

    job_config = QueryJobConfig(query_parameters=[
        ScalarQueryParameter('target_date', 'DATE', target_date),
        ScalarQueryParameter('series_start', 'DATE', series_start_for(target_date)),
    ])
    try:
        job = bq_client.query(build_daily_edge_query(project_id), job_config=job_config)
        rows = list(job.result(timeout=timeout) if timeout else job.result())
        # Evaluation is inside the try on purpose. A crash in the state machine
        # must degrade to the fail-closed path like any other failure, not
        # propagate out of a function documented to always return a dict.
        return evaluate_halt_state(rows)
    except Exception as e:
        logger.warning(f"Edge-halt state could not be determined: {e}")
        return _error_state(str(e))


def _last_known_halt_row(bq_client, target_date: date, sport: str,
                         project_id: str, timeout: Optional[float]) -> Optional[Dict[str, Any]]:
    """Most recent GENUINELY COMPUTED `halt_state` row within FALLBACK_MAX_AGE_DAYS.

    The `edge_halt_source` filter is load-bearing. `halt_state_writer` re-writes
    this table daily *from this function's own output*, so without it every row
    is at most one day old even when the last real computation was weeks ago —
    the writer would launder stale into fresh and FALLBACK_MAX_AGE_DAYS would
    never engage during a sustained edge-query outage. Rows written before this
    key existed have a NULL source and are still eligible.
    """
    from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter

    query = f"""
        SELECT effective_date, halt_active, halt_reason, halt_since
        FROM `{project_id}.nba_orchestration.halt_state`
        WHERE sport = @sport
          AND effective_date <= @target_date
          AND effective_date >= DATE_SUB(@target_date, INTERVAL @max_age DAY)
          AND IFNULL(JSON_VALUE(halt_metrics, '$.edge_halt_source'), 'computed')
              NOT IN ('halt_state_fallback', 'fail_closed', 'error')
        ORDER BY effective_date DESC
        LIMIT 1
    """
    job_config = QueryJobConfig(query_parameters=[
        ScalarQueryParameter('sport', 'STRING', sport),
        ScalarQueryParameter('target_date', 'DATE', target_date),
        ScalarQueryParameter('max_age', 'INT64', FALLBACK_MAX_AGE_DAYS),
    ])
    try:
        job = bq_client.query(query, job_config=job_config)
        rows = list(job.result(timeout=timeout) if timeout else job.result())
    except Exception as e:
        logger.warning(f"halt_state fallback lookup failed: {e}")
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        'effective_date': r.effective_date,
        'halt_active': bool(r.halt_active),
        'halt_reason': r.halt_reason,
        'halt_since': r.halt_since,
    }


def resolve_halt_state(bq_client, target_date: date, sport: str = 'nba',
                       project_id: str = 'nba-props-platform',
                       timeout: Optional[float] = None) -> Dict[str, Any]:
    """The answer every caller should use. Never fails open.

    Precedence:
      1. Fresh computation from the daily edge series.
      2. The most recent `halt_state` row within FALLBACK_MAX_AGE_DAYS. A
         one-day-old answer is far better than a coin flip, and it is what the
         rest of the pipeline is already reading.
      3. Fail CLOSED — halt with reason `halt_state_unavailable`.

    Step 2 is what makes step 3 rare enough to be safe: a partial BigQuery
    failure no longer costs a slate of picks unless the halt_state table is
    unreachable too, and in that case the exporter has bigger problems.
    """
    state = query_halt_state(bq_client, target_date, project_id=project_id, timeout=timeout)
    if not state.get('error'):
        return state

    fallback = _last_known_halt_row(bq_client, target_date, sport, project_id, timeout)
    if fallback is not None:
        state = dict(state)
        state['halt_active'] = fallback['halt_active']
        state['halt_source'] = 'halt_state_fallback'
        state['halt_started'] = fallback.get('halt_since')
        state['carried_forward_from'] = fallback['effective_date']

        # The MAX_HALT_DAYS lifetime lives in evaluate_halt_state, which this
        # path never reaches. Enforce it here too, or a carried-forward halt is
        # a halt with no expiry — the permanent trap this rewrite exists to
        # remove, reintroduced through the back door.
        started = fallback.get('halt_since')
        if (
            state['halt_active']
            and started is not None
            and (target_date - started).days >= MAX_HALT_DAYS
        ):
            state['halt_active'] = False
            state['lifetime_expired'] = True
            state['lifetime_spent'] = True
            state['reason'] = ''
            logger.warning(
                "Carried-forward halt began %s, past its %s-day lifetime — releasing. "
                "If the halt is real, an operator must write a halt_overrides row.",
                started, MAX_HALT_DAYS,
            )
            return state

        state['reason'] = (
            f"Edge query unavailable; carrying forward halt_state from "
            f"{fallback['effective_date']} (halt_active={fallback['halt_active']}, "
            f"reason={fallback['halt_reason']})"
        ) if fallback['halt_active'] else ''
        logger.warning(
            "Edge-halt query failed; using halt_state row from %s (halt_active=%s)",
            fallback['effective_date'], fallback['halt_active'],
        )
        return state

    state = dict(state)
    state['halt_active'] = True
    state['halt_source'] = 'fail_closed'
    state['reason'] = (
        'Edge state unavailable and no halt_state row within '
        f'{FALLBACK_MAX_AGE_DAYS} days — failing CLOSED (halt_state_unavailable)'
    )
    logger.error(state['reason'])
    return state
