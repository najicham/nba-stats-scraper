# MLB 2026 — Dead Ends (Don't Revisit)

Everything below was tested with walk-forward data across 2024-2025 and rejected. Do not re-explore without new evidence.

## Model Architecture

| Approach | Result | Why It Failed |
|----------|--------|---------------|
| LightGBM Regressor | 55.7% HR (vs CatBoost 57.8%) | Lower accuracy, higher MAE |
| XGBoost Regressor | 55.7% HR | Same as LightGBM |
| Ridge Regression | 56.2% HR | Linear model can't capture interactions |
| Ensemble (avg 3 trees) | 57.5% HR | Averaging dilutes CatBoost's unique signal |
| Ensemble (stacked) | 57.5% HR | Meta-learner adds complexity for -0.2pp |
| Weighted ensemble | 57.4% HR | No weighting scheme beats solo CatBoost |
| Cross-model agreement | -3.1pp when unanimous | Agreement is anti-correlated with winning |

## Hyperparameters

| Change | Result | Why It Failed |
|--------|--------|---------------|
| depth=8 (vs 5) | More picks, lower HR per pick | Deeper = less selective |
| depth=10 | Same HR, 5-10x training time | No benefit |
| lr=0.10 (vs 0.015) | -2pp HR | Overfits to recent noise |
| iterations=2000 | Same HR as 1000 | Overfitting plateau |
| MAE loss | -1.7pp HR | Worse at extremes |
| Quantile 0.55 loss | -2.1pp HR, 73% OVER rate | Biases predictions, no accuracy gain |
| Quantile 0.60 loss | -1.4pp HR | Same problem |
| Huber loss | -6.1pp HR, 45% OVER rate | Massive UNDER bias |

## Features

| Feature | Result | Why It Failed |
|---------|--------|---------------|
| f15 opponent K rate | NOISE (57.58% vs 57.70% baseline) | Market already prices this |
| f16 ballpark K factor | NOISE | Same — already in the line |
| is_day_game | Zero effect (56.7% vs 57.0%) | Not a real signal |
| k_home_interaction | NOISE (+0.3pp, within noise) | CatBoost captures internally |
| k_form_vs_line_ratio | NOISE (+0.3pp) | Same |
| season_vs_recent_delta | NOISE (+0.3pp) | Same |
| k_cv (coeff of variation) | NOISE (+0.7pp) | Same |
| projection_vs_recent | NOISE (+0.7pp) | Same |
| opp_pitcher_k_interaction | NOISE (+0.5pp) | Same |
| month_of_season | ZERO importance | Constant within training window |
| days_into_season | ZERO importance | Same |
| is_postseason | ZERO importance | No postseason in training data |

**Lesson: CatBoost's tree structure captures non-linear interactions internally. Explicit derived features add noise.**

## Pick Selection

| Approach | Result | Why It Failed |
|----------|--------|---------------|
| Composite scoring | +1.2pp in-sample, +0.4pp out-of-sample | Fails cross-season validation |
| edge + 0.3*proj + 0.2*home | 57.3% top-3 (vs 58.4% pure edge) | Adding features hurts ranking |
| Logistic regression ranking | AUC 0.5385 | Zero significant predictors |
| Tiered ranking (hybrid #1, edge #2-3) | +0.4pp | Not worth the complexity |
| k_form_above_line signal | -2.8pp | Recent hot form doesn't predict next start |

## Filters (Cross-Season Unstable)

| Filter | In-Sample | Cross-Season | Why It Failed |
|--------|-----------|-------------|---------------|
| Bad opponents (KC/MIA/CWS) | +1.7pp | r=-0.29 anti-correlated | Teams change year to year |
| Bad venues | +0.5pp | eta²=0.006, p=0.13 | Confounded with home team |
| K/9 9.0-9.5 zone | +4pp block | 6.9pp cross-season gap | Small N, unstable |
| Day-of-week filter | None | All p > 0.3 | Pure noise |
| Series Game 3 | 44.7% (N=76) | 50.4% at edge >= 0.5 | Noise |
| June tightening | Inconsistent | Worse in bad years | S7 unified handles it better |

## Seasonal Adjustments

| Approach | Result | Why It Failed |
|----------|--------|---------------|
| Phase 1 (Apr: edge >= 2.0) | 47.5% April HR | Selects overconfident picks |
| Phase 2 (May+: edge >= 1.0) | Fine but Phase 1 drags average | Phase 1 is broken |
| June tightening (edge >= 1.5) | 48.7% June 2025 | Worse than unified in bad years |
| ASB adjustment | Opposite effects 2024 vs 2025 | Noise |
| Trade deadline adjustment | Post-deadline trends above avg | Not toxic |
| September callup adjustment | No negative effect | Sep is best month |

## Retraining

| Approach | Result | Why It Failed |
|----------|--------|---------------|
| 7-day retrain | +0.6pp vs 14d | Not worth 2x compute (noise-level gain) |
| 28-day retrain | -1.8pp vs 14d | Real degradation |
| Trigger-based (HR < 52%) | -0.5pp vs fixed 14d | Reactive, destabilizes model |
| 56-day window | +0.2pp vs 120d | Within noise |
| 180-day window | -0.2pp vs 120d | Within noise |
| 365-day window | +0.1pp vs 120d | Within noise |

## Staking

| Approach | Result | Why It Failed |
|----------|--------|---------------|
| Kelly criterion | 32.6% ROI | 97% max drawdown — impractical |
| Edge-proportional | 15.1% ROI | No improvement over flat |
| Progressive | 15.9% ROI | No improvement over flat |
| Adaptive volume (rolling HR) | +4.6u season | Not worth the complexity |
