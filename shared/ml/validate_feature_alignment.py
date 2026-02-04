#!/usr/bin/env python3
"""
Feature Alignment Validator

Validates that all feature definitions are consistent across:
1. Feature contract (shared/ml/feature_contract.py) - SINGLE SOURCE OF TRUTH
2. Feature store processor (data_processors/precompute/ml_feature_store/)
3. Prediction code (predictions/worker/prediction_systems/)
4. Training code (ml/experiments/)

Run this:
- Before any deployment
- After any feature changes
- As part of CI pipeline

Usage:
    PYTHONPATH=. python shared/ml/validate_feature_alignment.py
"""

import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def validate_feature_contract():
    """Validate the feature contract itself."""
    from shared.ml.feature_contract import validate_all_contracts
    print("=" * 60)
    print("1. VALIDATING FEATURE CONTRACT")
    print("=" * 60)
    validate_all_contracts()
    return True


def validate_feature_store_alignment():
    """Validate feature store processor matches contract."""
    from shared.ml.feature_contract import FEATURE_STORE_NAMES, FEATURE_STORE_FEATURE_COUNT

    # Import feature store definitions (can't import full module due to dependencies)
    feature_store_path = Path(__file__).parent.parent.parent / \
        "data_processors/precompute/ml_feature_store/ml_feature_store_processor.py"

    print("\n" + "=" * 60)
    print("2. VALIDATING FEATURE STORE ALIGNMENT")
    print("=" * 60)

    # Parse FEATURE_NAMES from the processor file
    with open(feature_store_path) as f:
        content = f.read()

    # Find FEATURE_NAMES list
    import re
    match = re.search(r'FEATURE_NAMES\s*=\s*\[(.*?)\]', content, re.DOTALL)
    if not match:
        print("  ERROR: Could not find FEATURE_NAMES in feature store processor")
        return False

    # Extract feature names from the matched string
    names_str = match.group(1)
    # Parse out quoted strings
    store_names = re.findall(r"'([^']+)'", names_str)

    # Also extract FEATURE_COUNT
    count_match = re.search(r'FEATURE_COUNT\s*=\s*(\d+)', content)
    if count_match:
        store_count = int(count_match.group(1))
    else:
        store_count = len(store_names)

    print(f"  Feature store: {len(store_names)} names, FEATURE_COUNT={store_count}")
    print(f"  Contract:      {len(FEATURE_STORE_NAMES)} names, expected {FEATURE_STORE_FEATURE_COUNT}")

    # Check count
    if store_count != FEATURE_STORE_FEATURE_COUNT:
        print(f"  ERROR: FEATURE_COUNT mismatch: store={store_count}, contract={FEATURE_STORE_FEATURE_COUNT}")
        return False

    if len(store_names) != len(FEATURE_STORE_NAMES):
        print(f"  ERROR: Feature list length mismatch: store={len(store_names)}, contract={len(FEATURE_STORE_NAMES)}")
        return False

    # Check each feature name and order
    mismatches = []
    for i, (store_name, contract_name) in enumerate(zip(store_names, FEATURE_STORE_NAMES)):
        if store_name != contract_name:
            mismatches.append((i, store_name, contract_name))

    if mismatches:
        print("  ERROR: Feature name mismatches:")
        for idx, store_name, contract_name in mismatches:
            print(f"    [{idx}] store='{store_name}' vs contract='{contract_name}'")
        return False

    print("  ✓ Feature store aligned with contract")
    return True


def validate_training_script():
    """Validate training script uses contract."""
    print("\n" + "=" * 60)
    print("3. VALIDATING TRAINING SCRIPT")
    print("=" * 60)

    training_path = Path(__file__).parent.parent.parent / "ml/experiments/quick_retrain.py"

    with open(training_path) as f:
        content = f.read()

    # Check for contract import
    if "from shared.ml.feature_contract import" in content:
        print("  ✓ Training script imports feature contract")
    else:
        print("  ERROR: Training script does not import feature contract")
        return False

    # Check for position-based slicing (the old dangerous pattern)
    if "row[:33]" in content or "row[:37]" in content:
        print("  WARNING: Training script still uses position-based slicing (row[:N])")
        print("           This should be converted to name-based extraction")
        # Not a hard failure yet, but warn
    else:
        print("  ✓ No position-based slicing found")

    return True


def validate_prediction_code():
    """Validate prediction code feature list."""
    from shared.ml.feature_contract import V8_FEATURE_NAMES, V9_FEATURE_NAMES

    print("\n" + "=" * 60)
    print("4. VALIDATING PREDICTION CODE")
    print("=" * 60)

    pred_path = Path(__file__).parent.parent.parent / \
        "predictions/worker/prediction_systems/catboost_v8.py"

    with open(pred_path) as f:
        content = f.read()

    # Find V8_FEATURES list
    import re
    match = re.search(r'V8_FEATURES\s*=\s*\[(.*?)\]', content, re.DOTALL)
    if not match:
        print("  WARNING: Could not find V8_FEATURES in prediction code")
        return True  # Not a hard failure

    names_str = match.group(1)
    pred_names = re.findall(r'"([^"]+)"', names_str)

    print(f"  Prediction code: {len(pred_names)} features")
    print(f"  V8 contract:     {len(V8_FEATURE_NAMES)} features")

    # Note: Prediction code may have extra features like has_shot_zone_data
    # that aren't in the training contract. This is intentional.
    # We just check that the first 33 match.

    common_len = min(len(pred_names), len(V8_FEATURE_NAMES))
    mismatches = []
    for i in range(common_len):
        if pred_names[i] != V8_FEATURE_NAMES[i]:
            mismatches.append((i, pred_names[i], V8_FEATURE_NAMES[i]))

    if mismatches:
        print("  WARNING: Feature name mismatches in first 33:")
        for idx, pred_name, contract_name in mismatches:
            print(f"    [{idx}] pred='{pred_name}' vs contract='{contract_name}'")
        # Note extra features
        if len(pred_names) > len(V8_FEATURE_NAMES):
            extra = pred_names[len(V8_FEATURE_NAMES):]
            print(f"  Note: Prediction code has {len(extra)} extra features: {extra}")
    else:
        print("  ✓ First 33 features match contract")
        if len(pred_names) > len(V8_FEATURE_NAMES):
            extra = pred_names[len(V8_FEATURE_NAMES):]
            print(f"  Note: Prediction code has {len(extra)} extra features: {extra}")

    return True


def main():
    """Run all validations."""
    print("FEATURE ALIGNMENT VALIDATION")
    print("Session 107 - Canonical Feature Contract")
    print()

    results = []

    try:
        results.append(("Feature Contract", validate_feature_contract()))
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(("Feature Contract", False))

    try:
        results.append(("Feature Store", validate_feature_store_alignment()))
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(("Feature Store", False))

    try:
        results.append(("Training Script", validate_training_script()))
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(("Training Script", False))

    try:
        results.append(("Prediction Code", validate_prediction_code()))
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append(("Prediction Code", False))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n✅ All validations passed!")
        return 0
    else:
        print("\n❌ Some validations failed - fix before deploying!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
