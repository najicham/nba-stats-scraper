-- prediction_accuracy_deduped view
-- Self-healing dedup over prediction_accuracy for all consumers.
--
-- Root cause (Session 493): grading processor dedup partition included line_value,
-- so multiple line versions of the same player/game/model all survived into prediction_accuracy.
-- The EXISTS rescue clause was also too broad, letting all historical line versions
-- through for any player that had a BB pick.
--
-- This view picks the single best row per (player_lookup, game_date, system_id):
--   1. Prefer rows with a real direction (OVER/UNDER) over nulls
--   2. Prefer graded rows (prediction_correct IS NOT NULL)
--   3. Latest graded_at as tiebreaker
--
-- Migration path: all 22 consumers of prediction_accuracy should move to this view
-- after Layer 1 (grading processor fix) has been deployed and validated.
-- See: docs/09-handoff/2026-03-26-SESSION-493-DUPLICATE-PICKS-FIX.md

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.prediction_accuracy_deduped` AS
SELECT * EXCEPT(rn)
FROM (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup, game_date, system_id
      ORDER BY
        CASE WHEN recommendation IN ('OVER', 'UNDER') THEN 0 ELSE 1 END,
        CASE WHEN prediction_correct IS NOT NULL THEN 0 ELSE 1 END,
        graded_at DESC
    ) AS rn
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
)
WHERE rn = 1
