# Feature Contract Architecture

**Created:** Session 107 (2026-02-03)
**Status:** Implemented

## Problem Statement

Before this session, feature definitions were duplicated in multiple places:
- Feature store processor (`FEATURE_NAMES` list)
- Training scripts (`FEATURES` list)
- Prediction code (`V8_FEATURES` list)
- Model contract file (`V8_FEATURE_NAMES`)

This led to:
1. **Position-based extraction** - Training used `row[:33]` which breaks if feature order changes
2. **No validation** - No automated check that all definitions match
3. **Silent corruption** - If someone changed one list but not others, model would train on wrong features

## Solution: Single Source of Truth

Created `shared/ml/feature_contract.py` as the canonical definition:

```
┌─────────────────────────────────────────┐
│     shared/ml/feature_contract.py       │
│  ─────────────────────────────────────  │
│  FEATURE_STORE_NAMES (37 features)      │
│  V8_FEATURE_NAMES (33 features)         │
│  V9_FEATURE_NAMES (33 features)         │
│  V10_FEATURE_NAMES (37 features)        │
│  ModelFeatureContract class             │
│  FEATURE_DEFAULTS                       │
└─────────────────────────────────────────┘
            │
            ├──► Training scripts import FEATURES = V9_FEATURE_NAMES
            │
            ├──► Feature store uses FEATURE_STORE_NAMES (must match)
            │
            ├──► Prediction code uses V8_FEATURE_NAMES
            │
            └──► Validation script checks alignment
```

## Key Components

### 1. Feature Contract File

**Location:** `shared/ml/feature_contract.py`

```python
# Import in training scripts:
from shared.ml.feature_contract import (
    V9_CONTRACT,
    V9_FEATURE_NAMES,
    FEATURE_DEFAULTS,
)

# Use contract for safe extraction
contract = V9_CONTRACT
features_dict = dict(zip(feature_names, feature_values))
vector = contract.extract_from_dict(features_dict, defaults=FEATURE_DEFAULTS)
```

### 2. Model Contracts

Each model version has a contract:

| Contract | Features | Description |
|----------|----------|-------------|
| V8_CONTRACT | 33 | Historical baseline (2021-2024) |
| V9_CONTRACT | 33 | Current production (Nov 2025+) |
| V10_CONTRACT | 37 | Future with trajectory features |

### 3. Validation Script

**Location:** `shared/ml/validate_feature_alignment.py`

```bash
PYTHONPATH=. python shared/ml/validate_feature_alignment.py
```

Checks:
1. Contract internal consistency
2. Feature store alignment with contract
3. Training script uses contract
4. Prediction code matches contract

### 4. Name-Based Extraction

**Before (DANGEROUS):**
```python
# Position-based - breaks if order changes!
X = pd.DataFrame([row[:33] for row in df['features'].tolist()], columns=FEATURES)
```

**After (SAFE):**
```python
# Name-based - order doesn't matter
features_dict = dict(zip(feature_names, feature_values))
for name in contract.feature_names:
    row_data[name] = features_dict.get(name, default)
```

## Files Modified

| File | Change |
|------|--------|
| `shared/ml/feature_contract.py` | NEW - Canonical feature definitions |
| `shared/ml/validate_feature_alignment.py` | NEW - Validation script |
| `shared/ml/__init__.py` | NEW - Package init |
| `ml/experiments/quick_retrain.py` | Updated to import from contract, use name-based extraction |

## Usage Guidelines

### When Adding New Features

1. Add to `FEATURE_STORE_NAMES` in `feature_contract.py` (APPEND only!)
2. Update `FEATURE_STORE_FEATURE_COUNT`
3. Create new model contract if needed (e.g., V11_CONTRACT)
4. Run validation: `python shared/ml/validate_feature_alignment.py`
5. Update feature store processor to generate the new feature
6. Update prediction code if using new feature

### When Training New Models

```python
from shared.ml.feature_contract import V9_CONTRACT, V9_FEATURE_NAMES

# Use contract for validation
print(f"Training with {V9_CONTRACT.feature_count} features")
V9_CONTRACT.validate()

# Use feature names from contract
FEATURES = V9_FEATURE_NAMES
```

### Running Validation

```bash
# Before deployment
PYTHONPATH=. python shared/ml/validate_feature_alignment.py

# Or as part of training
from shared.ml.feature_contract import validate_all_contracts
validate_all_contracts()
```

## Why Feature Store Uses Arrays

The feature store stores features as:
- `features ARRAY<FLOAT>` - Values
- `feature_names ARRAY<STRING>` - Names (for debugging)

This allows:
1. **Schema flexibility** - Add features without ALTER TABLE
2. **Variable counts** - Different records can have 33 vs 37 features
3. **Self-documenting** - Names stored alongside values

The key insight: **names ARE stored, the training code just wasn't using them**.

## Backward Compatibility

- Old records with 33 features still work (contract extracts what it needs)
- Training on mixed data (33 + 37 features) works via name-based extraction
- No migration needed for existing data

## Future Work

1. Add to CI pipeline (run validation on every PR)
2. Consider migrating feature store processor to import from contract
3. Add feature importance tracking to contract metadata
