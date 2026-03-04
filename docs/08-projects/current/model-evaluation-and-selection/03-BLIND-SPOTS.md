# Blind Spots in the Current Approach

## Blind Spot 1: Edge-Dominant Selection Penalizes Well-Calibrated Models

**The problem:** Per-player selection picks the prediction with the highest `edge * model_hr_weight`. This means a model that wildly over-predicts (edge=7) beats a model that accurately predicts (edge=3.5), even if the accurate model is right more often.

**Example:**
- Model A predicts 27 points (edge 7.0 from a 20 line). Player scores 23. Model A "wins" (OVER) but predicted badly.
- Model B predicts 23.5 points (edge 3.5). Player scores 23. Model B was more accurate but had lower edge and lost selection.

**Impact:** V16 models have 66.7% overall HR but produce edges of 3.7-4.0 avg. They NEVER win selection against V9/V12 models producing edges of 5-7+. We might be leaving high-quality predictions on the table.

**The HR weight partially compensates** but not enough. At 55% HR baseline, a model needs to be 20+ percentage points better to overcome a 2-point edge gap:
- Edge 7.0 × weight 0.91 = 6.37
- Edge 4.0 × weight 1.00 = 4.00

The accurate model would need to overcome a 2.37 point gap — impossible with a weight capped at 1.0.

## Blind Spot 2: Uniform Filter Stack for All Models

**The problem:** Every model's predictions are processed through the same filter stack, but different models have different failure modes:

- **V9 AWAY** = 48.1% HR → AWAY block applied
- **V12_noveg AWAY** = 43.8% HR → AWAY block applied
- **V16 AWAY** = unknown (never sources enough picks to measure)
- **V12_vegas AWAY** = unknown

We block ALL v12_noveg/v9 AWAY predictions, but newer model families (V16, V12_vegas, LightGBM) may not have the same AWAY weakness. We'll never know because they can't break through selection.

**Specific filter issues:**
- **OVER edge floor (5.0)** was calibrated on V9/V12 data. V16 barely generates edge 5+ — this filter blocks 100% of V16 OVER picks.
- **Model-direction affinity** only has data for v9 and v12_noveg/v12_vegas groups. No data exists for V16, LightGBM, or other newer families.
- **Star UNDER block** applies globally but some models may handle star players better than others.

## Blind Spot 3: Selection Bias in Evaluation Data

**The problem:** We evaluate best bets HR, but best bets picks are the RESULT of the current selection system. This creates circular logic:

1. V9 wins selection → V9 picks get graded → V9 has HR data → V9's HR affects future selection
2. V16 never wins selection → V16 never gets best bets data → Can't evaluate V16 for best bets

We can measure V16's overall HR (66.7%) but not its "would-be" best bets HR because it never produces best bets picks. The only way to evaluate it is through simulation or by giving it explicit selection opportunities.

## Blind Spot 4: No Per-Model Quality Profile

**The problem:** We treat "best bets quality" as a single metric (HR after filters). But models may have different quality profiles:

- **Model A:** Great at OVER, terrible at UNDER
- **Model B:** Great at stars, terrible at bench
- **Model C:** Great at edge 4-6, terrible at edge 7+
- **Model D:** Great at HOME, terrible at AWAY

Currently, we apply the same filters and thresholds to all models. If Model A is 90% HR on OVER but 40% on UNDER, we'd want to keep its OVER picks and block its UNDER. The model-direction affinity system partially does this for the V9 group, but it's crude and limited.

## Blind Spot 5: SC=3 Volume Problem

**The problem:** 41.5% of best bets picks have SC=3 and only 55.1% HR. Raising the floor to SC=4 would eliminate 49 picks but boost overall HR from 66.9% to 76.1% (on the remaining 69 picks).

**Trade-off:** Fewer picks but much higher quality. On 0-pick days (like today), this would mean even more 0-pick days. But the picks we DO make would be significantly more profitable.

**Open question:** Is 49 fewer picks over 3 months (roughly 0.5 picks/day) worth +10pp HR?

## Blind Spot 6: Confidence Score is Wasted

**The problem:** Confidence score is set to 9.999 for all CatBoost predictions. This field is transmitted through the entire pipeline (BQ, JSON, frontend) but carries zero information.

**Opportunity:** Repurpose confidence as a meaningful signal:
- CatBoost can output prediction intervals (quantile regression)
- Could compute confidence = 1 - (prediction_std / predicted_points)
- Could derive confidence from feature quality, model staleness, player consistency
- Could use it as a selection tiebreaker or a filter input

## Blind Spot 7: Training Window Evaluation is Ad-Hoc

**The problem:** We know 56-day window is "optimal" from Session 369 experiments, but:
- This was tested on a single evaluation period
- Different models may have different optimal windows
- The optimal window may shift over the season (more data available as season progresses)
- We don't have a systematic way to compare training windows across model architectures

**Current approach:** Manual `quick_retrain.py` experiments with `--skip-register`, comparing backtest HR. No automated training window search. No cross-validation across multiple eval periods.
