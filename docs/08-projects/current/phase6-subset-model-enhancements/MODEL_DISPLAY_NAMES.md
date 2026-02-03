# Model Display Names - Website Strategy

**Date:** 2026-02-03
**Context:** Phase 6 enhancement for exposing model info to website

## Problem Statement

Technical model names like `catboost_v9_feb_02_retrain.cbm` are:
- ❌ Not user-friendly
- ❌ Expose internal details (algorithm, version, retrain schedule)
- ❌ Change with each retrain (confusing to users)
- ❌ Could reveal competitive strategy

## Solution: Display Name System

### What to Show Users vs Internal

| Internal (DB) | Display to Users | Notes |
|---------------|------------------|-------|
| `catboost_v9_feb_02_retrain.cbm` | **"Pro Model V9"** | Simple, version-focused |
| `system_id: catboost_v9` | **"Pro Model V9"** | Consistent across systems |
| `ensemble_v1` | **"Ensemble Blend"** | Describes approach, not tech |
| `xgboost_v2` | **"Quick Pick Model"** | User benefit, not algorithm |
| `similarity_v1` | **"Game Matcher"** | Explains what it does |

### Recommended Display Names

| Model | Display Name | Tagline | When to Use |
|-------|--------------|---------|-------------|
| catboost_v9 | **Pro Model V9** | "Current season trained model with 79% high-edge hit rate" | Primary, most accurate |
| ensemble_v1 | **Ensemble Blend** | "Combines 4 models for consensus picks" | Balanced approach |
| xgboost_v2 | **Quick Pick** | "Fast predictions for all players" | Lower confidence ok |
| similarity_v1 | **Game Matcher** | "Matches similar past performances" | Explainable picks |

---

## Implementation Approach

### Option A: Database Field (Recommended) ✅

**Add `model_display_name` to relevant tables:**

```sql
-- Predictions table
ALTER TABLE `nba_predictions.player_prop_predictions`
ADD COLUMN IF NOT EXISTS model_display_name STRING;

-- Subset definitions
ALTER TABLE `nba_predictions.dynamic_subset_definitions`
ADD COLUMN IF NOT EXISTS model_display_name STRING;
```

**Populate in prediction worker:**
```python
# In predictions/worker/prediction_systems/catboost_v9.py
TRAINING_INFO = {
    "model_file": "catboost_v9_feb_02_retrain.cbm",
    "display_name": "Pro Model V9",  # NEW
    "display_tagline": "Current season trained model",  # NEW
    # ... rest of training info
}

# In predict() method
result['metadata']['model_display_name'] = self.TRAINING_INFO['display_name']
```

**Benefits:**
- ✅ Flexible - change display name without code deploy
- ✅ Consistent - same display name across all systems
- ✅ Queryable - can filter/group by display name in BQ

---

### Option B: Code-based Mapping (Alternative)

**Use existing `system_id` with display name mapping:**

```python
# In data_processors/publishing/exporter_utils.py
MODEL_DISPLAY_NAMES = {
    'catboost_v9': {
        'display_name': 'Pro Model V9',
        'tagline': 'Current season trained model',
        'show_tech_details': False,  # Hide file names
    },
    'ensemble_v1': {
        'display_name': 'Ensemble Blend',
        'tagline': 'Combines 4 models for consensus',
        'show_tech_details': False,
    },
    'catboost_v8': {
        'display_name': 'Legacy Model V8',
        'tagline': 'Historical baseline',
        'show_tech_details': False,
    },
}

def get_model_display_info(system_id: str) -> dict:
    """Get user-facing model information."""
    return MODEL_DISPLAY_NAMES.get(system_id, {
        'display_name': system_id,
        'tagline': '',
        'show_tech_details': False,
    })
```

**Benefits:**
- ✅ No schema change needed
- ✅ Quick to implement
- ✅ Centralized mapping

**Drawbacks:**
- ⚠️ Requires code deploy to change names
- ⚠️ Not queryable in BigQuery

---

## Website Display Examples

### Example 1: Subset Card

**GOOD - User-Friendly:**
```
╔══════════════════════════════════════╗
║  High Edge Top 5                     ║
║  Pro Model V9                        ║
╠══════════════════════════════════════╣
║  79.0% Hit Rate (last 30 days)       ║
║  +50.9% ROI                          ║
║  5 picks per day                     ║
╚══════════════════════════════════════╝
```

**BAD - Too Technical:**
```
╔══════════════════════════════════════╗
║  v9_high_edge_top5                   ║
║  catboost_v9_feb_02_retrain.cbm     ║
╠══════════════════════════════════════╣
║  system_id: catboost_v9              ║
║  composite_score: (edge*10)+conf*0.5 ║
╚══════════════════════════════════════╝
```

---

### Example 2: Model Info Card

**GOOD:**
```html
<div class="model-card">
  <h3>Pro Model V9</h3>
  <p class="tagline">Current season trained model</p>

  <div class="stats">
    <div class="stat">
      <span class="label">Hit Rate</span>
      <span class="value">79.0%</span>
      <span class="context">High edge picks</span>
    </div>
    <div class="stat">
      <span class="label">Accuracy</span>
      <span class="value">±4.1 points</span>
      <span class="context">Average error</span>
    </div>
  </div>

  <div class="training-period">
    Trained: Nov 2025 - Jan 2026
  </div>

  <!-- Optional: Show tech details in collapsed section -->
  <details class="tech-details">
    <summary>Technical Details</summary>
    <ul>
      <li>Algorithm: CatBoost Gradient Boosting</li>
      <li>Features: 33 statistical factors</li>
      <li>Version: V9</li>
    </ul>
  </details>
</div>
```

**BAD:**
```html
<div class="model-card">
  <h3>catboost_v9_feb_02_retrain.cbm</h3>
  <p>System ID: catboost_v9</p>
  <p>Commit: 0d872e31</p>
  <p>Deployed: prediction-worker-00081-z97</p>
</div>
```

---

### Example 3: Prediction Attribution

**GOOD - Simple:**
```
Generated by Pro Model V9
Expected accuracy: ±4.1 points
```

**GOOD - Detailed (expandable):**
```
Generated by Pro Model V9
  Trained Nov '25 - Jan '26
  79% hit rate on high-edge picks

  [Show Technical Details ▼]
```

**BAD:**
```
model_file_name: catboost_v9_feb_02_retrain.cbm
build_commit_sha: 0d872e31
deployment_revision: prediction-worker-00081-z97
```

---

## JSON Export Structure

### Recommended JSON for Website

```json
{
  "subset_id": "v9_high_edge_top5",
  "subset_name": "High Edge Top 5",
  "model": {
    "display_name": "Pro Model V9",
    "tagline": "Current season trained model",
    "version": "V9",
    "performance": {
      "hit_rate": 79.0,
      "mae": 4.1,
      "roi": 50.9
    },
    "training_period": {
      "start": "2025-11",
      "end": "2026-01",
      "description": "Nov 2025 - Jan 2026"
    }
  },
  "performance": {
    "last_30_days": {
      "picks": 147,
      "hit_rate": 79.0,
      "roi": 50.9
    }
  },
  "picks": [ /* ... */ ]
}
```

**Technical details (optional, for power users):**
```json
{
  "model": {
    "display_name": "Pro Model V9",
    "technical_details": {
      "system_id": "catboost_v9",
      "algorithm": "CatBoost Gradient Boosting",
      "features": 33,
      "model_file": "catboost_v9_feb_02_retrain.cbm"  // Only if show_tech_details: true
    }
  }
}
```

---

## Privacy & Competitive Considerations

### What to Hide

**Never show:**
- ❌ Exact file paths (`gs://nba-props-platform-models/...`)
- ❌ Git commit hashes (`0d872e31`)
- ❌ Deployment revision names (`prediction-worker-00081-z97`)
- ❌ Internal table names (`v_dynamic_subset_performance`)
- ❌ Query patterns or data sources
- ❌ Feature engineering details

**Be cautious about showing:**
- ⚠️ Algorithm names (CatBoost, XGBoost) - consider generic "gradient boosting"
- ⚠️ Feature count (33 features) - could reveal strategy
- ⚠️ Training schedule (monthly) - could reveal advantage window
- ⚠️ Exact training dates - reveals data recency

**Safe to show:**
- ✅ Display name ("Pro Model V9")
- ✅ Version number (V9)
- ✅ General training period ("Current season")
- ✅ Performance metrics (hit rate, MAE, ROI)
- ✅ Expected accuracy ranges
- ✅ General approach ("combines multiple factors")

---

## Implementation Steps

### Step 1: Add Display Name Field
```bash
# Add to schema
bq query --use_legacy_sql=false < /tmp/add_model_display_names.sql

# Verify
bq show --schema --format=prettyjson \
  nba_predictions.player_prop_predictions | \
  grep -A 3 "model_display_name"
```

### Step 2: Update Prediction Worker
```python
# In predictions/worker/prediction_systems/catboost_v9.py
TRAINING_INFO = {
    # ... existing fields ...
    "display_name": "Pro Model V9",
    "display_tagline": "Current season trained model with 79% high-edge hit rate",
    "show_tech_details": False,  # Don't expose technical details
}

# In predict() method
result['metadata']['model_display_name'] = self.TRAINING_INFO['display_name']
result['metadata']['display_tagline'] = self.TRAINING_INFO.get('display_tagline', '')
```

### Step 3: Backfill Display Names
```sql
-- Backfill existing predictions
UPDATE `nba_predictions.player_prop_predictions`
SET model_display_name = 'Pro Model V9'
WHERE system_id = 'catboost_v9' AND model_display_name IS NULL;

UPDATE `nba_predictions.player_prop_predictions`
SET model_display_name = 'Ensemble Blend'
WHERE system_id = 'ensemble_v1' AND model_display_name IS NULL;

-- Backfill subset definitions
UPDATE `nba_predictions.dynamic_subset_definitions`
SET model_display_name = 'Pro Model V9'
WHERE system_id = 'catboost_v9';
```

### Step 4: Update Phase 6 Exporters
```python
# In data_processors/publishing/subset_performance_exporter.py
def generate_json(self):
    # ... query logic ...

    for subset in subsets:
        subset_data = {
            'subset_id': subset['subset_id'],
            'subset_name': subset['subset_name'],
            'model_display_name': subset['model_display_name'],  # NEW
            'performance': { /* ... */ }
        }

        # Don't include technical details
        # subset_data['system_id'] = subset['system_id']  # HIDE THIS
```

### Step 5: Update JSON Examples
Update all JSON examples in `JSON_EXAMPLES.md` to use display names instead of technical names.

---

## Display Name Governance

### Naming Conventions

**Format:** `<Tier> Model <Version>`

**Tiers:**
- **Pro** - Primary production model, highest accuracy
- **Ensemble** - Multi-model blends
- **Quick** - Fast predictions, good for all players
- **Specialty** - Specific use cases (e.g., "Game Matcher")

**Examples:**
- ✅ "Pro Model V9"
- ✅ "Ensemble Blend"
- ✅ "Quick Pick"
- ❌ "catboost_v9" (too technical)
- ❌ "CatBoost Gradient Boosting Regressor V9" (too long)

### Version Numbering

**User-facing versions:**
- V9 = Major version (algorithm or approach change)
- V9.1 = Minor update (retrain with same approach)
- V9.1-Feb = Specific retrain (optional, only if multiple per month)

**Internal versions:**
- catboost_v9_feb_02_retrain.cbm (technical)
- Maps to: "Pro Model V9" (user-facing)

---

## Marketing Considerations

### Brand Identity

Consider names that:
- ✅ Build trust ("Pro", "Premium", "Elite")
- ✅ Explain benefit ("Game Matcher", "Ensemble Blend")
- ✅ Create tiers ("Pro" > "Plus" > "Quick")

**Potential rebranding:**
| Current | Potential Brand Names |
|---------|----------------------|
| CatBoost V9 | Pro Model, Elite Picks, Premium AI |
| Ensemble V1 | Blend Model, Consensus Picks, Multi-View |
| Similarity V1 | Game Matcher, Pattern Finder, HistoryMatch |

### Competitive Positioning

**Don't reveal:**
- Algorithm names (competitors could replicate)
- Feature counts (reveals complexity)
- Training frequency (reveals refresh advantage)
- Data sources (reveals edge)

**Do highlight:**
- Performance (79% hit rate)
- Recency ("current season trained")
- Validation ("tested on 8,500 games")
- Transparency ("±4.1 point accuracy")

---

## Configuration Management

### Centralized Display Name Config

**Create:** `shared/config/model_display_config.py`

```python
"""
Model display configuration for user-facing names.
"""

MODEL_DISPLAY_CONFIG = {
    'catboost_v9': {
        'display_name': 'Pro Model V9',
        'display_tagline': 'Current season trained model',
        'show_technical_details': False,
        'tier': 'pro',
        'marketing_name': 'Premium AI',  # Optional branding
    },
    'ensemble_v1': {
        'display_name': 'Ensemble Blend',
        'display_tagline': 'Combines 4 models for consensus',
        'show_technical_details': False,
        'tier': 'premium',
    },
    'catboost_v8': {
        'display_name': 'Legacy Model V8',
        'display_tagline': 'Historical baseline',
        'show_technical_details': False,
        'tier': 'legacy',
        'deprecated': True,
    },
}

def get_display_name(system_id: str) -> str:
    """Get user-facing display name for a model."""
    config = MODEL_DISPLAY_CONFIG.get(system_id, {})
    return config.get('display_name', system_id)

def get_display_tagline(system_id: str) -> str:
    """Get user-facing tagline for a model."""
    config = MODEL_DISPLAY_CONFIG.get(system_id, {})
    return config.get('display_tagline', '')

def should_show_technical_details(system_id: str) -> bool:
    """Check if technical details should be exposed."""
    config = MODEL_DISPLAY_CONFIG.get(system_id, {})
    return config.get('show_technical_details', False)
```

**Usage in exporters:**
```python
from shared.config.model_display_config import get_display_name, get_display_tagline

# In exporter
subset_data['model_name'] = get_display_name(system_id)
subset_data['tagline'] = get_display_tagline(system_id)
```

---

## Testing

### Verify Display Names in Exports

```bash
# Check subset definitions
gsutil cat gs://nba-props-platform-api/v1/systems/subsets.json | \
  jq '.subsets[] | {subset_id, model_display_name}'

# Expected:
# {
#   "subset_id": "v9_high_edge_top5",
#   "model_display_name": "Pro Model V9"
# }

# Check predictions
gsutil cat gs://nba-props-platform-api/v1/predictions/$(date +%Y-%m-%d).json | \
  jq '.predictions[0] | {player_name, model_display_name}'

# Should NOT see technical names like:
# ❌ "catboost_v9_feb_02_retrain.cbm"
# ❌ "system_id": "catboost_v9"
```

### Verify No Technical Leaks

```bash
# Search for technical terms in exports
gsutil cat gs://nba-props-platform-api/v1/**/*.json | \
  grep -E "(\.cbm|commit|revision|deployment|system_id)" && \
  echo "⚠️ Technical details leaked!" || \
  echo "✅ Clean exports"
```

---

## Recommendation Summary

**Recommended Approach:**
1. ✅ Add `model_display_name` field to database (flexible)
2. ✅ Use simple, user-friendly names ("Pro Model V9")
3. ✅ Hide technical details (file names, commits, deployments)
4. ✅ Create centralized config for display names
5. ✅ Update all Phase 6 exporters to use display names
6. ✅ Add optional "technical details" section for power users (collapsed by default)

**Display Name Examples:**
- catboost_v9 → **"Pro Model V9"**
- ensemble_v1 → **"Ensemble Blend"**
- similarity_v1 → **"Game Matcher"**

**What to Show:**
- ✅ Display name, version, performance, training period (general)

**What to Hide:**
- ❌ File names, commits, deployments, algorithms, features, queries
