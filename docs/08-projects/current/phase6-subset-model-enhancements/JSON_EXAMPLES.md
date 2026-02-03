# Phase 6 JSON Examples - Subset & Model Data

**Session**: 86
**Date**: 2026-02-02

This document shows realistic JSON examples for all new/modified endpoints.

## New Endpoints

### 1. `/systems/subsets.json`
List all available subsets with metadata.

```json
{
  "generated_at": "2026-02-02T10:00:00Z",
  "metadata": {
    "total_subsets": 9,
    "active_subsets": 9,
    "system_id": "catboost_v9"
  },
  "subsets": [
    {
      "subset_id": "v9_high_edge_top1",
      "subset_name": "V9 High Edge Top 1 (Lock)",
      "subset_description": "Single best pick by composite score (edge × 10 + confidence × 0.5)",
      "system_id": "catboost_v9",
      "selection_strategy": "RANKED",
      "top_n": 1,
      "min_edge": 5.0,
      "min_confidence": null,
      "signal_condition": "ANY",
      "is_active": true,
      "typical_picks_per_day": 1,
      "historical_hit_rate": 76.3,
      "sample_size_days": 47,
      "notes": "Lock of the day - highest composite score",
      "recommended_for": "Conservative bettors, single-bet strategy"
    },
    {
      "subset_id": "v9_high_edge_top5",
      "subset_name": "V9 High Edge Top 5",
      "subset_description": "Top 5 picks ranked by composite score from high-edge pool (5+ point edge)",
      "system_id": "catboost_v9",
      "selection_strategy": "RANKED",
      "top_n": 5,
      "min_edge": 5.0,
      "min_confidence": null,
      "signal_condition": "ANY",
      "is_active": true,
      "typical_picks_per_day": 5,
      "historical_hit_rate": 74.6,
      "sample_size_days": 47,
      "notes": "Recommended default subset - balance of quality and volume",
      "recommended_for": "Most users, balanced strategy"
    },
    {
      "subset_id": "v9_high_edge_balanced",
      "subset_name": "V9 High Edge - Green Signal Only",
      "subset_description": "All high-edge picks (5+ edge) on GREEN signal days (25-40% OVER)",
      "system_id": "catboost_v9",
      "selection_strategy": "FILTERED",
      "top_n": null,
      "min_edge": 5.0,
      "min_confidence": null,
      "signal_condition": "GREEN",
      "is_active": true,
      "typical_picks_per_day": 12,
      "historical_hit_rate": 82.0,
      "sample_size_days": 47,
      "notes": "Best historical performance - only active on GREEN days",
      "recommended_for": "Users seeking highest hit rate, comfortable with variable volume"
    },
    {
      "subset_id": "v9_high_edge_warning",
      "subset_name": "V9 High Edge - Red Signal (Warning)",
      "subset_description": "All high-edge picks on RED signal days (<25% or >40% OVER) - shadow tracking",
      "system_id": "catboost_v9",
      "selection_strategy": "FILTERED",
      "top_n": null,
      "min_edge": 5.0,
      "min_confidence": null,
      "signal_condition": "RED",
      "is_active": true,
      "typical_picks_per_day": 8,
      "historical_hit_rate": 54.2,
      "sample_size_days": 47,
      "notes": "Warning: Lower hit rate on RED signal days - reduce bet sizing or skip",
      "recommended_for": "Research/tracking only - not recommended for betting"
    },
    {
      "subset_id": "v9_premium_safe",
      "subset_name": "V9 Premium - Safe Days",
      "subset_description": "Premium picks (92%+ confidence, 3+ edge) on GREEN or YELLOW signal days",
      "system_id": "catboost_v9",
      "selection_strategy": "FILTERED",
      "top_n": null,
      "min_edge": 3.0,
      "min_confidence": 0.92,
      "signal_condition": "GREEN_OR_YELLOW",
      "is_active": true,
      "typical_picks_per_day": 8,
      "historical_hit_rate": 71.2,
      "sample_size_days": 47,
      "notes": "High confidence filter, excludes RED signal days",
      "recommended_for": "Conservative bettors, high-confidence preference"
    }
    // ... 4 more subsets (v9_high_edge_top3, v9_high_edge_top10, v9_high_edge_any, v9_high_edge_top5_balanced)
  ]
}
```

---

### 2. `/signals/2026-02-02.json`
Daily signal metrics and status.

```json
{
  "game_date": "2026-02-02",
  "system_id": "catboost_v9",
  "generated_at": "2026-02-02T14:30:21Z",
  "signal_metrics": {
    "total_picks": 142,
    "high_edge_picks": 28,
    "premium_picks": 12,
    "pct_over": 32.4,
    "pct_under": 67.6,
    "avg_confidence": 0.68,
    "avg_edge": 2.3,
    "skew_category": "UNDER_HEAVY"
  },
  "signal_status": {
    "daily_signal": "GREEN",
    "signal_color_code": "#10B981",
    "signal_explanation": "Balanced market with 32.4% OVER picks. Historical 82% hit rate on GREEN signal days.",
    "confidence": "HIGH",
    "recommendation": "Normal bet sizing recommended. GREEN signal indicates balanced market conditions."
  },
  "signal_performance": {
    "green_days_historical_hr": 82.0,
    "green_days_sample": 23,
    "yellow_days_historical_hr": 89.0,
    "yellow_days_sample": 18,
    "red_days_historical_hr": 54.2,
    "red_days_sample": 6,
    "total_sample_days": 47
  },
  "signal_thresholds": {
    "green_range": "25-40% OVER",
    "yellow_range": ">40% OVER",
    "red_range": "<25% OVER",
    "statistical_significance": "p=0.0065"
  },
  "market_context": {
    "today_schedule_size": "10 games",
    "avg_line": 18.5,
    "top_overs": ["LeBron James", "Luka Doncic", "Giannis Antetokounmpo"],
    "top_unders": ["Stephen Curry", "Kevin Durant", "Jayson Tatum"]
  }
}
```

---

### 3. `/subsets/v9_high_edge_top5/2026-02-02.json`
Picks from specific subset for a date.

```json
{
  "game_date": "2026-02-02",
  "subset_id": "v9_high_edge_top5",
  "subset_name": "V9 High Edge Top 5",
  "generated_at": "2026-02-02T14:30:21Z",
  "daily_signal": "GREEN",
  "signal_matches_subset": true,
  "metadata": {
    "total_picks": 5,
    "avg_edge": 6.8,
    "avg_confidence": 0.87,
    "avg_composite_score": 111.5,
    "overs": 2,
    "unders": 3,
    "expected_hit_rate": 74.6,
    "historical_sample_days": 47
  },
  "warning": null,
  "picks": [
    {
      "rank": 1,
      "prediction_id": "abc123def456",
      "player_lookup": "lebronjames",
      "player_name": "LeBron James",
      "team": "LAL",
      "opponent": "BOS",
      "game_id": "0022600456",
      "game_time": "2026-02-02T19:30:00-08:00",
      "predicted_points": 26.1,
      "line_value": 24.5,
      "edge": 1.6,
      "confidence_score": 0.92,
      "composite_score": 115.5,
      "recommendation": "OVER",
      "line_source": "ACTUAL_PROP",
      "sportsbook": "DRAFTKINGS",
      "injury_status": null,
      "recent_form": {
        "last_5_avg": 26.3,
        "last_10_avg": 25.1,
        "season_avg": 24.8
      },
      "matchup_notes": "Strong matchup vs BOS (allows 25.2 PPG to forwards)",
      "key_factors": [
        "Similar games baseline: 25.8 (+0.3)",
        "Home game boost: +0.3",
        "Opponent defense tier: Tier 2 (favorable)"
      ]
    },
    {
      "rank": 2,
      "prediction_id": "def456ghi789",
      "player_lookup": "lukadoncic",
      "player_name": "Luka Doncic",
      "team": "DAL",
      "opponent": "PHX",
      "game_id": "0022600457",
      "game_time": "2026-02-02T20:00:00-06:00",
      "predicted_points": 32.4,
      "line_value": 29.5,
      "edge": 2.9,
      "confidence_score": 0.88,
      "composite_score": 114.0,
      "recommendation": "OVER",
      "line_source": "ACTUAL_PROP",
      "sportsbook": "FANDUEL",
      "injury_status": null,
      "recent_form": {
        "last_5_avg": 31.8,
        "last_10_avg": 30.2,
        "season_avg": 29.5
      },
      "matchup_notes": "PHX ranks 22nd in guard defense (27.8 PPG allowed)",
      "key_factors": [
        "Usage spike: 38.2% (up from 35.1%)",
        "Pace advantage: +3.2 possessions",
        "Rest advantage: 2 days rest vs PHX B2B"
      ]
    },
    {
      "rank": 3,
      "prediction_id": "ghi789jkl012",
      "player_lookup": "stephencurry",
      "player_name": "Stephen Curry",
      "team": "GSW",
      "opponent": "LAC",
      "game_id": "0022600458",
      "game_time": "2026-02-02T19:00:00-08:00",
      "predicted_points": 23.2,
      "line_value": 26.5,
      "edge": -3.3,
      "confidence_score": 0.85,
      "composite_score": 112.5,
      "recommendation": "UNDER",
      "line_source": "ACTUAL_PROP",
      "sportsbook": "DRAFTKINGS",
      "injury_status": "QUESTIONABLE",
      "injury_reason": "Ankle soreness",
      "recent_form": {
        "last_5_avg": 22.8,
        "last_10_avg": 24.1,
        "season_avg": 25.3
      },
      "matchup_notes": "LAC elite guard defense (22.1 PPG allowed, 1st in league)",
      "key_factors": [
        "Injury flag: Questionable with ankle soreness",
        "Tough matchup: LAC allows 4.4 PPG below avg to guards",
        "Fatigue: 3rd game in 4 nights"
      ]
    },
    {
      "rank": 4,
      "prediction_id": "jkl012mno345",
      "player_lookup": "giannisantetokounmpo",
      "player_name": "Giannis Antetokounmpo",
      "team": "MIL",
      "opponent": "ATL",
      "game_id": "0022600459",
      "game_time": "2026-02-02T19:30:00-05:00",
      "predicted_points": 34.8,
      "line_value": 32.5,
      "edge": 2.3,
      "confidence_score": 0.89,
      "composite_score": 111.5,
      "recommendation": "OVER",
      "line_source": "ACTUAL_PROP",
      "sportsbook": "BETMGM",
      "injury_status": null,
      "recent_form": {
        "last_5_avg": 33.6,
        "last_10_avg": 32.8,
        "season_avg": 31.2
      },
      "matchup_notes": "ATL 28th in paint defense (56.2 PPG allowed)",
      "key_factors": [
        "Paint advantage: ATL allows 12.8 paint PPG above avg",
        "Usage spike opportunity: Dame Lillard out",
        "Historical: 38.2 PPG avg vs ATL (6 games)"
      ]
    },
    {
      "rank": 5,
      "prediction_id": "mno345pqr678",
      "player_lookup": "jaysontatum",
      "player_name": "Jayson Tatum",
      "team": "BOS",
      "opponent": "LAL",
      "game_id": "0022600456",
      "game_time": "2026-02-02T19:30:00-08:00",
      "predicted_points": 24.1,
      "line_value": 27.5,
      "edge": -3.4,
      "confidence_score": 0.82,
      "composite_score": 110.0,
      "recommendation": "UNDER",
      "line_source": "ACTUAL_PROP",
      "sportsbook": "FANDUEL",
      "injury_status": null,
      "recent_form": {
        "last_5_avg": 24.8,
        "last_10_avg": 26.2,
        "season_avg": 27.1
      },
      "matchup_notes": "LAL improved defense (18th in league, was 24th)",
      "key_factors": [
        "Road game: -2.1 PPG vs home avg",
        "Back-to-back: 2nd of B2B (fatigue adjustment -1.2)",
        "LAL Anthony Davis rim protection impact"
      ]
    }
  ]
}
```

---

### 4. `/subsets/performance.json`
Compare performance across all subsets.

```json
{
  "generated_at": "2026-02-02T10:00:00Z",
  "system_id": "catboost_v9",
  "metadata": {
    "total_subsets": 9,
    "evaluation_period": "2025-12-17 to 2026-02-01",
    "total_days": 47
  },
  "performance_windows": {
    "last_7_days": {
      "start_date": "2026-01-26",
      "end_date": "2026-02-01",
      "days": 7,
      "subsets": [
        {
          "subset_id": "v9_high_edge_top1",
          "picks": 7,
          "graded_picks": 6,
          "wins": 5,
          "losses": 1,
          "hit_rate": 83.3,
          "avg_edge": 7.1,
          "avg_confidence": 0.91,
          "avg_composite_score": 117.5,
          "roi_estimate": 15.2,
          "overs": 3,
          "unders": 3
        },
        {
          "subset_id": "v9_high_edge_top5",
          "picks": 35,
          "graded_picks": 32,
          "wins": 24,
          "losses": 8,
          "hit_rate": 75.0,
          "avg_edge": 6.2,
          "avg_confidence": 0.86,
          "avg_composite_score": 110.8,
          "roi_estimate": 9.1,
          "overs": 18,
          "unders": 14
        },
        {
          "subset_id": "v9_high_edge_balanced",
          "picks": 68,
          "graded_picks": 61,
          "wins": 52,
          "losses": 9,
          "hit_rate": 85.2,
          "avg_edge": 6.3,
          "avg_confidence": 0.72,
          "avg_composite_score": 99.0,
          "roi_estimate": 13.8,
          "overs": 28,
          "unders": 33
        }
        // ... 6 more subsets
      ]
    },
    "last_30_days": {
      "start_date": "2026-01-03",
      "end_date": "2026-02-01",
      "days": 30,
      "subsets": [
        {
          "subset_id": "v9_high_edge_top5",
          "picks": 147,
          "graded_picks": 132,
          "wins": 98,
          "losses": 34,
          "hit_rate": 74.2,
          "avg_edge": 6.4,
          "avg_confidence": 0.87,
          "avg_composite_score": 112.1,
          "roi_estimate": 8.3,
          "overs": 71,
          "unders": 61,
          "mae": 3.8,
          "within_3_pct": 68.9,
          "within_5_pct": 84.1
        }
        // ... 8 more subsets
      ]
    },
    "season": {
      "start_date": "2025-12-17",
      "end_date": "2026-02-01",
      "days": 47,
      "subsets": [
        {
          "subset_id": "v9_high_edge_top5",
          "picks": 235,
          "graded_picks": 212,
          "wins": 158,
          "losses": 54,
          "hit_rate": 74.6,
          "avg_edge": 6.2,
          "avg_confidence": 0.87,
          "avg_composite_score": 111.5,
          "roi_estimate": 8.4,
          "overs": 112,
          "unders": 100,
          "mae": 3.9,
          "within_3_pct": 67.5,
          "within_5_pct": 83.8
        }
        // ... 8 more subsets
      ]
    }
  },
  "signal_breakdown": {
    "v9_high_edge_top5": {
      "green_days": {
        "days": 23,
        "picks": 115,
        "hit_rate": 82.1,
        "avg_edge": 6.3,
        "roi_estimate": 12.4
      },
      "yellow_days": {
        "days": 18,
        "picks": 90,
        "hit_rate": 76.8,
        "avg_edge": 6.1,
        "roi_estimate": 9.8
      },
      "red_days": {
        "days": 6,
        "picks": 30,
        "hit_rate": 56.7,
        "avg_edge": 6.0,
        "roi_estimate": -3.2
      }
    },
    "v9_high_edge_balanced": {
      "green_days": {
        "days": 23,
        "picks": 276,
        "hit_rate": 82.0,
        "avg_edge": 6.4,
        "roi_estimate": 12.1
      },
      "yellow_days": {
        "days": 0,
        "picks": 0,
        "hit_rate": null,
        "avg_edge": null,
        "roi_estimate": null
      },
      "red_days": {
        "days": 0,
        "picks": 0,
        "hit_rate": null,
        "avg_edge": null,
        "roi_estimate": null
      }
    }
    // ... other subsets
  },
  "subset_rankings": {
    "by_hit_rate": [
      {"subset_id": "v9_high_edge_balanced", "hit_rate": 82.0},
      {"subset_id": "v9_high_edge_top1", "hit_rate": 76.3},
      {"subset_id": "v9_high_edge_top5", "hit_rate": 74.6}
      // ... 6 more
    ],
    "by_roi": [
      {"subset_id": "v9_high_edge_balanced", "roi": 12.1},
      {"subset_id": "v9_high_edge_top1", "roi": 10.8},
      {"subset_id": "v9_high_edge_top5", "roi": 8.4}
      // ... 6 more
    ],
    "by_volume": [
      {"subset_id": "v9_high_edge_any", "picks_per_day": 28},
      {"subset_id": "v9_high_edge_balanced", "picks_per_day": 12},
      {"subset_id": "v9_high_edge_top10", "picks_per_day": 10}
      // ... 6 more
    ]
  }
}
```

---

## Modified Endpoints

### 5. `/systems/performance.json` (ENHANCED)
Add model info and tier breakdown to existing structure.

```json
{
  "generated_at": "2026-02-02T10:00:00Z",
  "systems": [
    {
      "system_id": "catboost_v9",
      "display_name": "CatBoost V9",
      "description": "CatBoost gradient boosting with current season training",
      "is_primary": true,
      "ranking": 1,

      // EXISTING FIELDS (keep all current structure)
      "last_7": {
        "prediction_count": 847,
        "win_rate": 0.564,
        "mae": 4.18,
        "bias": -0.12,
        "over_count": 412,
        "over_win_rate": 0.571,
        "under_count": 435,
        "under_win_rate": 0.558
      },
      "last_30": { /* ... */ },
      "season": { /* ... */ },

      // NEW: Model metadata
      "model_info": {
        "model_file": "catboost_v9_feb_02_retrain.cbm",
        "model_version": "v9.0",
        "trained_at": "2026-02-02T10:15:00Z",
        "training_period": {
          "start_date": "2025-11-02",
          "end_date": "2026-01-31",
          "days": 91
        },
        "training_approach": "current_season_only",
        "feature_count": 33,
        "feature_version": "v2_33features",
        "expected_mae": 4.12,
        "expected_hit_rate": 74.6,
        "retraining_schedule": {
          "frequency": "MONTHLY",
          "next_retrain_date": "2026-03-01"
        }
      },

      // NEW: Tier breakdown
      "tier_breakdown": {
        "premium": {
          "filter_description": "confidence >= 92% AND edge >= 3 points",
          "last_30_days": {
            "picks": 84,
            "hit_rate": 56.5,
            "avg_edge": 4.8,
            "mae": 3.2,
            "roi_estimate": 2.1
          }
        },
        "high_edge": {
          "filter_description": "edge >= 5 points (any confidence)",
          "last_30_days": {
            "picks": 142,
            "hit_rate": 72.2,
            "avg_edge": 6.4,
            "mae": 3.8,
            "roi_estimate": 7.8
          }
        },
        "all_predictions": {
          "filter_description": "All predictions with lines",
          "last_30_days": {
            "picks": 847,
            "hit_rate": 56.4,
            "avg_edge": 2.1,
            "mae": 4.18,
            "roi_estimate": 1.2
          }
        }
      }
    },
    {
      "system_id": "ensemble_v1",
      "display_name": "Ensemble V1",
      // ... existing fields ...
      "model_info": { /* ... */ },
      "tier_breakdown": { /* ... */ }
    }
    // ... other systems
  ]
}
```

---

### 6. `/predictions/2026-02-02.json` (ENHANCED)
Add model attribution to each prediction.

```json
{
  "game_date": "2026-02-02",
  "generated_at": "2026-02-02T14:30:21Z",
  "metadata": {
    "total_predictions": 142,
    "total_games": 10
  },
  "games": [
    {
      "game_id": "0022600456",
      "home_team": "LAL",
      "away_team": "BOS",
      "game_time": "2026-02-02T19:30:00-08:00",
      "predictions": [
        {
          "prediction_id": "abc123def456",
          "player_lookup": "lebronjames",
          "player_name": "LeBron James",
          "team": "LAL",
          "system_id": "catboost_v9",

          // EXISTING FIELDS (keep all current structure)
          "predicted_points": 26.1,
          "confidence_score": 0.92,
          "current_points_line": 24.5,
          "line_margin": 1.6,
          "recommendation": "OVER",
          "has_prop_line": true,
          "line_source": "ACTUAL_PROP",
          "sportsbook": "DRAFTKINGS",

          // ... all other existing fields ...

          // NEW: Model attribution
          "model_attribution": {
            "model_file_name": "catboost_v9_feb_02_retrain.cbm",
            "model_version": "v9.0",
            "model_trained_at": "2026-02-02T10:15:00Z",
            "training_start_date": "2025-11-02",
            "training_end_date": "2026-01-31",
            "model_expected_mae": 4.12,
            "model_expected_hit_rate": 74.6,
            "build_commit_sha": "a1b2c3d4e5f",
            "deployment_revision": "prediction-worker-00042-abc",
            "predicted_at": "2026-02-02T14:30:00Z",
            "prediction_run_mode": "OVERNIGHT"
          }
        }
        // ... more predictions for this game
      ]
    }
    // ... more games
  ]
}
```

---

### 7. `/systems/models.json` (NEW)
Model registry with training details.

```json
{
  "generated_at": "2026-02-02T10:00:00Z",
  "production_model": "catboost_v9",
  "metadata": {
    "total_models": 6,
    "active_models": 6,
    "last_deployment": "2026-02-02T10:15:00Z"
  },
  "models": [
    {
      "system_id": "catboost_v9",
      "model_name": "CatBoost V9 - Current Season",
      "model_file_name": "catboost_v9_feb_02_retrain.cbm",
      "model_version": "v9.0",
      "status": "PRODUCTION",
      "deployed_at": "2026-02-02T10:15:00Z",
      "deployment_session": 82,

      "training_info": {
        "training_start_date": "2025-11-02",
        "training_end_date": "2026-01-31",
        "training_days": 91,
        "training_samples": 180000,
        "evaluation_samples": 8500,
        "training_approach": "current_season_only",
        "training_rationale": "V8 showed data leakage from multi-season training. V9 trained on current season only for cleaner validation.",
        "feature_count": 33,
        "feature_version": "v2_33features",
        "feature_categories": [
          "Player averages (season, last 10, last 5)",
          "Opponent defense metrics",
          "Pace and possessions",
          "Usage rate",
          "Home/away splits",
          "Rest days",
          "Injury status",
          "Shot zone matchups",
          "Referee tendencies",
          "Vegas lines"
        ]
      },

      "expected_performance": {
        "mae": 4.12,
        "high_edge_hit_rate": 74.6,
        "premium_hit_rate": 56.5,
        "evaluation_period": "2026-01-01 to 2026-01-31"
      },

      "actual_performance_last_30d": {
        "mae": 4.18,
        "high_edge_hit_rate": 72.2,
        "premium_hit_rate": 56.5,
        "total_predictions": 4247,
        "performance_vs_expected": "Within 1.5% of expected (good)"
      },

      "retraining_schedule": {
        "frequency": "MONTHLY",
        "next_retrain_date": "2026-03-01",
        "strategy": "rolling_90_day_window",
        "triggers": [
          "Monthly schedule",
          "MAE degradation >10%",
          "Hit rate drop >5% for 7 consecutive days"
        ]
      },

      "model_path": "gs://nba-props-platform-models/catboost/v9/catboost_v9_feb_02_retrain.cbm",
      "model_size_mb": 0.8,
      "model_framework": "CatBoost 1.2",

      "comparison_to_predecessor": {
        "previous_model": "catboost_v8",
        "mae_improvement": "23% better (5.36 → 4.12)",
        "hit_rate_improvement": "+6.3 percentage points (50.2% → 56.5%)",
        "key_changes": [
          "Current season training only (no data leakage)",
          "Enhanced shot zone features",
          "Improved fatigue modeling",
          "Updated referee adjustments"
        ]
      }
    },
    {
      "system_id": "ensemble_v1",
      "model_name": "Ensemble V1",
      "model_version": "v1.0",
      "status": "PRODUCTION",
      "deployed_at": "2025-12-15T08:00:00Z",

      "training_info": {
        "approach": "weighted_ensemble",
        "component_models": [
          {"model": "catboost_v9", "weight": 0.45},
          {"model": "xgboost_v2", "weight": 0.25},
          {"model": "similarity_v1", "weight": 0.20},
          {"model": "zone_matchup_v1", "weight": 0.10}
        ],
        "ensemble_method": "weighted_average",
        "weight_optimization": "Bayesian optimization on validation set"
      },

      "expected_performance": {
        "mae": 4.24,
        "high_edge_hit_rate": 71.8,
        "premium_hit_rate": 54.2
      },

      "retraining_schedule": {
        "frequency": "QUARTERLY",
        "next_retrain_date": "2026-03-15",
        "strategy": "reoptimize_weights"
      }
    },
    {
      "system_id": "xgboost_v2",
      "model_name": "XGBoost V2",
      "model_version": "v2.0",
      "status": "PRODUCTION",
      "deployed_at": "2025-11-20T14:00:00Z",
      // ... similar structure ...
    },
    {
      "system_id": "similarity_v1",
      "model_name": "Similarity Matching V1",
      "model_version": "v1.0",
      "status": "PRODUCTION",
      "deployed_at": "2025-10-01T10:00:00Z",

      "training_info": {
        "approach": "nearest_neighbors",
        "similarity_features": [
          "Opponent",
          "Home/Away",
          "Rest days",
          "Recent usage",
          "Season period"
        ],
        "k_neighbors": 10,
        "distance_metric": "weighted_euclidean"
      }
      // ... rest of structure ...
    }
    // ... more models
  ],

  "model_comparison_last_30d": [
    {
      "system_id": "catboost_v9",
      "predictions": 4247,
      "hit_rate": 56.4,
      "mae": 4.18,
      "rank": 1
    },
    {
      "system_id": "ensemble_v1",
      "predictions": 4247,
      "hit_rate": 54.8,
      "mae": 4.35,
      "rank": 2
    },
    {
      "system_id": "xgboost_v2",
      "predictions": 3891,
      "hit_rate": 52.1,
      "mae": 4.68,
      "rank": 3
    }
    // ... other models
  ]
}
```

---

## Implementation Notes

### Cache Headers

Recommended cache TTLs for each endpoint:

```
/systems/subsets.json → Cache-Control: max-age=86400 (1 day)
/signals/{date}.json → Cache-Control: max-age=300 (5 minutes)
/subsets/{subset_id}/{date}.json → Cache-Control: max-age=300 (5 minutes)
/subsets/performance.json → Cache-Control: max-age=3600 (1 hour)
/systems/models.json → Cache-Control: max-age=86400 (1 day)
/systems/performance.json → Cache-Control: max-age=3600 (1 hour)
/predictions/{date}.json → Cache-Control: max-age=300 (5 minutes)
```

---

### Frontend API Client Example

```javascript
class NBAPropsAPI {
  constructor(baseUrl = 'https://api.nba-props.com/v1') {
    this.baseUrl = baseUrl;
  }

  // Fetch available subsets
  async getSubsets() {
    const response = await fetch(`${this.baseUrl}/systems/subsets.json`);
    return response.json();
  }

  // Get today's signal
  async getTodaySignal() {
    const today = this.formatDate(new Date());
    const response = await fetch(`${this.baseUrl}/signals/${today}.json`);
    return response.json();
  }

  // Get picks from specific subset
  async getSubsetPicks(subsetId, date = null) {
    const dateStr = date || this.formatDate(new Date());
    const response = await fetch(
      `${this.baseUrl}/subsets/${subsetId}/${dateStr}.json`
    );
    return response.json();
  }

  // Get subset performance comparison
  async getSubsetPerformance() {
    const response = await fetch(`${this.baseUrl}/subsets/performance.json`);
    return response.json();
  }

  // Get model registry
  async getModels() {
    const response = await fetch(`${this.baseUrl}/systems/models.json`);
    return response.json();
  }

  formatDate(date) {
    return date.toISOString().split('T')[0];
  }
}

// Usage example
const api = new NBAPropsAPI();

// Homepage: Show today's best picks with signal awareness
async function displayTodaysBestPicks() {
  const signal = await api.getTodaySignal();

  // Choose subset based on signal
  let subsetId;
  if (signal.signal_status.daily_signal === 'GREEN') {
    subsetId = 'v9_high_edge_balanced'; // 82% hit rate
  } else {
    subsetId = 'v9_high_edge_top5'; // Default, 75% hit rate
  }

  const picks = await api.getSubsetPicks(subsetId);

  return {
    signal,
    picks,
    expectedHitRate: picks.metadata.expected_hit_rate
  };
}
```

---

This structure provides frontend developers with:
1. Clear, consistent JSON structure
2. Realistic data examples
3. All necessary metadata for display
4. Signal awareness for smart subset selection
5. Model transparency and attribution
6. Performance tracking for validation
