"""CLV validation — do our picks beat the closing line? (2026-06-24, Phase 1 first cut)

Phase 0 (feasibility, DONE) verdict: CONDITIONAL GO on 3 seasons.
  - Closing lines reconstructed from nba_raw.odds_api_player_points_props via player_lookup
    (direct join) + minutes_before_tipoff (closing = smallest positive value).
  - Coverage (graded pick -> pre-tip snapshot): 2023-24 77%, 2024-25 77%, 2025-26 88%.
    2021-22 absent; 2022-23 only 2.9% pre-tip -> EXCLUDED. 5-season CLV is NOT possible.
  - CAVEAT: pre-2025-26 has ~1 snapshot/game at ~T-2.2hr (a near-close proxy, misses the final
    ~2hr of movement); only 2025-26 has to-the-tip granularity. So pre-2025-26 CLV is conservative.
  - Mechanically measurable: 47-61% of picks have a line that moved vs close (mean 0.4-0.7 pts).

CLV sign (points; positive = we beat the close):
  UNDER: line_value - close_line  (line dropped after we bet -> easier under -> +CLV)
  OVER : close_line - line_value  (line rose -> +CLV)

The validation question: do edge3+ UNDER picks show POSITIVE average CLV in the NON-anomaly
seasons (2023-24, 2024-25), not just 2025-26? Positive CLV cross-season = the UNDER edge is real
(independent, lower-variance confirmation). Also: does +CLV correlate with winning (sanity)?

Run: PYTHONPATH=. .venv/bin/python3 scripts/nba/training/discovery/clv_validation.py
"""

import logging
from google.cloud import bigquery

logging.basicConfig(level=logging.WARNING, format='%(message)s')
PROJECT = 'nba-props-platform'

QUERY = f"""
WITH closing AS (
  SELECT game_date, player_lookup,
         APPROX_QUANTILES(points_line, 2)[OFFSET(1)] AS close_line   -- median near-close line
  FROM `{PROJECT}.nba_raw.odds_api_player_points_props`
  WHERE game_date >= '2023-10-01' AND minutes_before_tipoff BETWEEN 0 AND 180
  GROUP BY game_date, player_lookup
),
picks AS (
  SELECT
    CASE WHEN game_date BETWEEN '2023-10-01' AND '2024-08-01' THEN '2023-24'
         WHEN game_date BETWEEN '2024-10-01' AND '2025-08-01' THEN '2024-25'
         WHEN game_date BETWEEN '2025-10-01' AND '2026-08-01' THEN '2025-26' END AS season,
    game_date, player_lookup, recommendation, line_value, prediction_correct,
    ABS(predicted_points - line_value) AS edge
  FROM `{PROJECT}.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2023-10-01' AND has_prop_line = TRUE
    AND recommendation IN ('OVER','UNDER') AND prediction_correct IS NOT NULL
),
joined AS (
  SELECT p.*, c.close_line,
    CASE WHEN p.recommendation = 'UNDER' THEN p.line_value - c.close_line
         ELSE c.close_line - p.line_value END AS clv
  FROM picks p JOIN closing c USING (game_date, player_lookup)
  WHERE p.edge >= 3.0 AND c.close_line IS NOT NULL
)
SELECT season, recommendation AS dir, COUNT(*) AS n,
  ROUND(AVG(clv), 3) AS mean_clv,
  ROUND(100*COUNTIF(clv > 0)/COUNT(*), 1) AS pct_pos_clv,
  ROUND(100*COUNTIF(clv = 0)/COUNT(*), 1) AS pct_zero_clv,
  ROUND(100*AVG(CAST(prediction_correct AS INT64)), 1) AS hr,
  ROUND(100*SAFE_DIVIDE(COUNTIF(clv > 0 AND prediction_correct), COUNTIF(clv > 0)), 1) AS hr_pos_clv,
  ROUND(100*SAFE_DIVIDE(COUNTIF(clv < 0 AND prediction_correct), COUNTIF(clv < 0)), 1) AS hr_neg_clv
FROM joined
GROUP BY season, dir ORDER BY dir, season
"""


def main():
    c = bigquery.Client(project=PROJECT)
    print("=" * 96)
    print("CLV VALIDATION (edge3+ graded picks, 3 seasons) — do our picks beat the close?")
    print("  +CLV = we got a better number than the close. Pre-2025-26 close = ~T-2.2hr proxy.")
    print("=" * 96)
    print(f"\n  {'dir':<6} {'season':<9} {'N':>5} {'mean_CLV':>9} {'%+CLV':>7} {'%0CLV':>7} "
          f"{'HR':>6} {'HR|+CLV':>8} {'HR|-CLV':>8}")
    print("  " + "-" * 78)
    rows = list(c.query(QUERY).result())
    for r in rows:
        print(f"  {r.dir:<6} {r.season:<9} {r.n:>5} {r.mean_clv:>+9.3f} {r.pct_pos_clv:>6.1f}% "
              f"{r.pct_zero_clv:>6.1f}% {r.hr:>5.1f}% {str(r.hr_pos_clv):>7}% {str(r.hr_neg_clv):>7}%")

    print("\n" + "=" * 96)
    print("READ")
    print("=" * 96)
    print("  • UNDER mean_CLV > 0 in the NON-anomaly seasons (2023-24, 2024-25) ⇒ the UNDER edge is")
    print("    real, confirmed by an independent low-variance lens (not a 2025-26 artifact).")
    print("  • HR|+CLV > HR|-CLV within a direction ⇒ CLV 'works' here (sanity that beating the")
    print("    close predicts winning). • OVER CLV near/below 0 ⇒ consistent with OVER fragility.")
    print("  Phase 2 (next): CLV on actual best-bets picks (signal_best_bets_picks), by signal tag;")
    print("  and a true-close cut on 2025-26 only (minutes_before_tipoff <= 15).")


if __name__ == '__main__':
    main()
