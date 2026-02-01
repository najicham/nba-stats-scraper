#!/usr/bin/env python3
"""
Verify Monthly Model System

Tests that:
1. Monthly models can be loaded
2. Each model has correct system_id
3. Models can generate predictions (dry-run)
4. Worker can import and use monthly models
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def test_monthly_model_loading():
    """Test loading monthly models from config."""
    print("=" * 70)
    print("TEST 1: Load Monthly Models")
    print("=" * 70)

    from predictions.worker.prediction_systems.catboost_monthly import (
        get_enabled_monthly_models,
        MONTHLY_MODELS
    )

    print(f"\nConfigured monthly models: {list(MONTHLY_MODELS.keys())}")
    print(f"Enabled models: {[k for k, v in MONTHLY_MODELS.items() if v.get('enabled')]}")

    models = get_enabled_monthly_models()
    print(f"\nLoaded {len(models)} monthly model(s)")

    for model in models:
        info = model.get_model_info()
        print(f"\n  Model: {info['system_id']}")
        print(f"    Path: {info['model_path']}")
        print(f"    Status: {info['status']}")
        print(f"    Training: {info['config']['train_start']} to {info['config']['train_end']}")
        print(f"    MAE: {info['config'].get('mae', 'N/A')}")
        print(f"    Hit Rate: {info['config'].get('hit_rate_overall', 'N/A')}%")

    assert len(models) > 0, "No monthly models loaded"
    print("\n✅ Monthly models loaded successfully")
    return models


def test_model_prediction_interface(models):
    """Test prediction interface (dry-run with mock data)."""
    print("\n" + "=" * 70)
    print("TEST 2: Prediction Interface")
    print("=" * 70)

    # Mock features (33 features expected by CatBoost)
    mock_features = {
        "feature_version": "v2_33features",
        "points_avg_last_5": 20.0,
        "points_avg_last_10": 19.5,
        "points_avg_season": 18.8,
        "points_std_last_10": 5.2,
        "games_in_last_7_days": 3.0,
        "fatigue_score": 0.5,
        "shot_zone_mismatch_score": 0.3,
        "pace_score": 0.6,
        "usage_spike_score": 0.2,
        "rest_advantage": 1.0,
        "injury_risk": 0.1,
        "recent_trend": 0.4,
        "minutes_change": 2.0,
        "opponent_def_rating": 110.5,
        "opponent_pace": 100.2,
        "home_away": 1.0,
        "back_to_back": 0.0,
        "playoff_game": 0.0,
        "pct_paint": 0.35,
        "pct_mid_range": 0.25,
        "pct_three": 0.30,
        "pct_free_throw": 0.10,
        "team_pace": 98.5,
        "team_off_rating": 112.3,
        "team_win_pct": 0.55,
        "vegas_points_line": 22.5,
        "vegas_opening_line": 22.0,
        "vegas_line_move": 0.5,
        "has_vegas_line": 1.0,
        "avg_points_vs_opponent": 21.0,
        "games_vs_opponent": 5.0,
        "minutes_avg_last_10": 32.5,
        "ppm_avg_last_10": 0.65,
    }

    for model in models:
        print(f"\n  Testing {model.model_id}...")

        try:
            result = model.predict(
                player_lookup="test_player_2026_002345",
                features=mock_features,
                betting_line=22.5
            )

            print(f"    System ID: {result['system_id']}")
            print(f"    Predicted Points: {result['predicted_points']:.2f}")
            print(f"    Confidence: {result['confidence_score']:.2f}")
            print(f"    Recommendation: {result['recommendation']}")
            print(f"    Training Period: {result['training_period']}")
            print(f"    Training MAE: {result.get('training_mae', 'N/A')}")

            # Verify system_id matches model_id
            assert result['system_id'] == model.model_id, \
                f"System ID mismatch: {result['system_id']} != {model.model_id}"

            print(f"    ✅ Prediction successful")

        except Exception as e:
            print(f"    ❌ Prediction failed: {e}")
            raise

    print("\n✅ All models can generate predictions")


def test_worker_integration():
    """Test that worker can import and use monthly models."""
    print("\n" + "=" * 70)
    print("TEST 3: Worker Integration")
    print("=" * 70)

    # Test worker can import monthly model module
    try:
        from predictions.worker.prediction_systems.catboost_monthly import (
            get_enabled_monthly_models
        )
        print("  ✅ Worker can import catboost_monthly module")
    except ImportError as e:
        print(f"  ❌ Worker cannot import catboost_monthly: {e}")
        raise

    # Test that the monthly model code is syntactically valid
    # (We can't actually import worker.py without env vars, but we can verify the file)
    try:
        worker_path = Path(__file__).parent / "predictions" / "worker" / "worker.py"
        if not worker_path.exists():
            raise FileNotFoundError(f"Worker file not found: {worker_path}")

        # Check that worker.py contains our monthly model integration
        worker_code = worker_path.read_text()

        checks = [
            ("catboost_monthly import", "from prediction_systems.catboost_monthly import"),
            ("_monthly_models global", "_monthly_models: Optional[list] = None"),
            ("get_enabled_monthly_models", "get_enabled_monthly_models()"),
            ("monthly model loop", "if _monthly_models:"),
            ("monthly model prediction", "for monthly_model in _monthly_models:"),
        ]

        for check_name, check_string in checks:
            if check_string in worker_code:
                print(f"  ✅ Worker has {check_name}")
            else:
                print(f"  ❌ Worker missing {check_name}")
                raise ValueError(f"Worker missing integration: {check_name}")

    except Exception as e:
        print(f"  ❌ Worker integration check failed: {e}")
        raise

    print("\n✅ Worker integration verified")


def main():
    """Run all verification tests."""
    print("\n" + "=" * 70)
    print("MONTHLY MODEL SYSTEM VERIFICATION")
    print("=" * 70)

    try:
        # Test 1: Load models
        models = test_monthly_model_loading()

        # Test 2: Test prediction interface
        test_model_prediction_interface(models)

        # Test 3: Test worker integration
        test_worker_integration()

        print("\n" + "=" * 70)
        print("ALL TESTS PASSED ✅")
        print("=" * 70)
        print("\nSummary:")
        print(f"  - {len(models)} monthly model(s) loaded")
        print(f"  - Each model produces predictions with correct system_id")
        print(f"  - Worker can import and use monthly models")
        print("\nNext Steps:")
        print("  1. Deploy worker: ./bin/deploy-service.sh prediction-worker")
        print("  2. Monitor logs for monthly model predictions")
        print("  3. Query predictions by system_id to verify separation")

    except Exception as e:
        print("\n" + "=" * 70)
        print("VERIFICATION FAILED ❌")
        print("=" * 70)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
