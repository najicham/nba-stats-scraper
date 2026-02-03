# Implementation Update - Clean Single-File Approach

**Date:** 2026-02-03
**Changes:** Updated from 9 separate files to 1 combined file with clean API

## Key Changes

### 1. Single File Export ✅

**OLD Approach:**
- 9 separate files per day (one per subset)
- `/subsets/v9_high_edge_top5/2026-02-03.json`
- `/subsets/v9_high_edge_balanced/2026-02-03.json`
- ... 7 more files

**NEW Approach:**
- **1 combined file per day** with all subsets
- `/picks/2026-02-03.json`
- All 9 groups in one JSON response

**Benefits:**
- ✅ Simpler - One API call gets everything
- ✅ Easier testing - Frontend tests all groups at once
- ✅ Less overhead - 1 export vs 9 exports
- ✅ Better for comparison - Side-by-side group comparison

---

### 2. Clean API (No Proprietary Details) ✅

**REMOVED from API responses:**
- ❌ `system_id` (e.g., "catboost_v9")
- ❌ `subset_id` (e.g., "v9_high_edge_top5")
- ❌ `confidence_score`
- ❌ `edge` / `line_margin`
- ❌ `composite_score`
- ❌ Algorithm names
- ❌ Feature counts
- ❌ Training details
- ❌ Calculation formulas
- ❌ Filter criteria

**KEPT in API responses:**
- ✅ Player, team, opponent
- ✅ Prediction value
- ✅ Vegas line
- ✅ OVER/UNDER direction
- ✅ Generic group names
- ✅ Performance stats (hit_rate, roi)
- ✅ Model codename (e.g., "926A")

**Why:** Someone inspecting with dev tools cannot reverse-engineer strategy

---

### 3. Simple Codenames ✅

**Model codenames:**
- `catboost_v9` → **"926A"**
- `catboost_v9_202602` → **"926B"**
- `ensemble_v1` → **"E01"**

**Group names:**
- `v9_high_edge_top1` → **"Top Pick"** or **"1"**
- `v9_high_edge_top5` → **"Top 5"** or **"2"**
- `v9_high_edge_top10` → **"Top 10"** or **"3"**
- `v9_high_edge_balanced` → **"Best Value"** or **"4"**
- `v9_high_edge_any` → **"All Picks"** or **"5"**

---

## Updated Phase 1 Implementation

### Exporters Needed (4 total)

#### 1. SubsetDefinitionsExporter
**Output:** `/systems/subsets.json`
**Purpose:** List all available groups with metadata
**Changes:** Use generic names, hide subset_id

```json
{
  "groups": [
    {
      "id": "1",
      "name": "Top Pick",
      "model": "926A",
      "description": "Single best pick"
    }
  ]
}
```

---

#### 2. DailySignalsExporter
**Output:** `/signals/{date}.json`
**Purpose:** Market signal for the day
**Changes:** Minimal - signals are not proprietary

```json
{
  "date": "2026-02-03",
  "signal": "favorable",
  "metrics": {
    "conditions": "balanced"
  }
}
```

**Note:** Could simplify to just "favorable" / "neutral" / "challenging"

---

#### 3. AllSubsetsPicksExporter (NEW NAME)
**OLD:** SubsetPicksExporter (9 files)
**NEW:** AllSubsetsPicksExporter (1 file)

**Output:** `/picks/{date}.json`
**Purpose:** All groups' picks in one file

**Implementation:**
```python
# shared/config/subset_public_names.py
SUBSET_PUBLIC_NAMES = {
    'v9_high_edge_top1': {'id': '1', 'name': 'Top Pick'},
    'v9_high_edge_top5': {'id': '2', 'name': 'Top 5'},
    'v9_high_edge_top10': {'id': '3', 'name': 'Top 10'},
    'v9_high_edge_balanced': {'id': '4', 'name': 'Best Value'},
    'v9_high_edge_any': {'id': '5', 'name': 'All Picks'},
    'v9_premium_safe': {'id': '6', 'name': 'Premium'},
    'v9_high_edge_top3': {'id': '7', 'name': 'Top 3'},
    'v9_high_edge_warning': {'id': '8', 'name': 'Alternative'},
    'v9_high_edge_top5_balanced': {'id': '9', 'name': 'Best Value Top 5'},
}
```

```python
# data_processors/publishing/all_subsets_picks_exporter.py
from shared.config.model_codenames import get_model_codename
from shared.config.subset_public_names import SUBSET_PUBLIC_NAMES

class AllSubsetsPicksExporter(BaseExporter):
    def generate_json(self, target_date: str) -> dict:
        # Query all predictions
        predictions = self.get_all_predictions(target_date)

        # Get subset definitions
        subsets = self.get_subset_definitions()

        # Build clean output
        groups = []
        for subset in subsets:
            # Get public names
            public = SUBSET_PUBLIC_NAMES.get(subset['subset_id'])

            # Filter picks for this subset
            subset_picks = self.filter_picks_for_subset(
                predictions, subset
            )

            # Clean pick structure - NO TECHNICAL FIELDS
            clean_picks = []
            for pick in subset_picks:
                clean_picks.append({
                    'player': pick['player_name'],
                    'team': pick['team'],
                    'opponent': pick['opponent'],
                    'prediction': round(pick['predicted_points'], 1),
                    'line': round(pick['current_points_line'], 1),
                    'direction': pick['recommendation']
                })

            # Get performance stats
            stats = self.get_subset_performance(subset['subset_id'])

            groups.append({
                'id': public['id'],
                'name': public['name'],
                'stats': {
                    'hit_rate': round(stats['hit_rate'], 1),
                    'roi': round(stats['roi'], 1),
                    'days': 30
                },
                'picks': clean_picks
            })

        return {
            'date': target_date,
            'generated': datetime.utcnow().isoformat() + 'Z',
            'model': get_model_codename('catboost_v9'),  # '926A'
            'groups': groups
        }
```

**JSON Output:** See `CLEAN_API_STRUCTURE.md`

---

#### 4. SubsetPerformanceExporter
**Output:** `/subsets/performance.json`
**Purpose:** Compare all groups' performance
**Changes:** Use generic names, hide technical details

```json
{
  "windows": {
    "last_30_days": {
      "groups": [
        {
          "id": "1",
          "name": "Top Pick",
          "model": "926A",
          "stats": {
            "hit_rate": 81.8,
            "roi": 15.2,
            "picks": 22
          }
        }
      ]
    }
  }
}
```

---

## Updated Testing

### Integration Tests

```bash
# 1. Verify single picks file exists
gsutil ls gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json
# Expected: File exists

# 2. Verify contains all groups
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  jq '.groups | length'
# Expected: 9

# 3. Verify NO technical details leaked
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  grep -E "(system_id|subset_id|confidence_score|edge|composite_score|catboost|xgboost)" && \
  echo "❌ Technical details leaked!" || \
  echo "✅ Clean API"

# 4. Verify generic names used
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  jq '.groups[0] | {id, name, model}'
# Expected: {"id": "1", "name": "Top Pick", "model": "926A"}

# 5. Verify pick structure is clean
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  jq '.groups[0].picks[0] | keys'
# Expected: ["player", "team", "opponent", "prediction", "line", "direction"]
# Should NOT contain: confidence_score, edge, composite_score, etc.
```

---

## Updated File Structure

### Phase 6 Exports

```
gs://nba-props-platform-api/v1/
├── picks/
│   ├── 2026-02-03.json          ← ALL 9 groups in one file
│   ├── 2026-02-02.json
│   └── 2026-02-01.json
│
├── signals/
│   ├── 2026-02-03.json          ← Daily signal
│   └── ...
│
├── systems/
│   ├── subsets.json             ← Group definitions
│   └── performance.json         ← Enhanced with model info
│
└── subsets/
    └── performance.json         ← Group comparison
```

**OLD structure (removed):**
```
subsets/
├── v9_high_edge_top5/
│   └── 2026-02-03.json
├── v9_high_edge_balanced/
│   └── 2026-02-03.json
└── ... (7 more subdirectories)
```

---

## Updated Orchestration

### daily_export.py Changes

```python
# OLD
EXPORT_TYPES = {
    'subset_picks': SubsetPicksExporter,  # Created 9 files
}

# Export loop
if 'subset_picks' in export_types:
    subset_ids = [...9 subset IDs...]
    for subset_id in subset_ids:
        exporter = SubsetPicksExporter(subset_id=subset_id)
        exporter.export(date_str)

# NEW
EXPORT_TYPES = {
    'all_picks': AllSubsetsPicksExporter,  # Creates 1 file
}

# Export - much simpler
if 'all_picks' in export_types:
    exporter = AllSubsetsPicksExporter()
    results['all_picks'] = exporter.export(date_str)
```

---

## Security Checklist

Before deploying, verify JSON output:

- [ ] No `system_id` fields
- [ ] No `subset_id` fields
- [ ] No `confidence_score` fields
- [ ] No `edge` / `line_margin` fields
- [ ] No `composite_score` fields
- [ ] No algorithm names (CatBoost, XGBoost)
- [ ] No technical thresholds (>= 5, >= 0.92)
- [ ] No training details (dates, samples)
- [ ] No feature information
- [ ] Generic group names only (1, 2, 3 or Top 5, Top 10)
- [ ] Model codenames only (926A, not catboost_v9)

---

## Documentation References

**Updated docs:**
- `CLEAN_API_STRUCTURE.md` - Clean JSON structure specifications
- `CODENAME_EXAMPLES.md` - Model codename examples
- `MODEL_DISPLAY_NAMES.md` - Display name strategy (background)
- `IMPLEMENTATION_UPDATE.md` - This file

**Original docs (still valid for background):**
- `IMPLEMENTATION_PLAN.md` - Original detailed plan
- `FINDINGS_SUMMARY.md` - Research findings
- `JSON_EXAMPLES.md` - Original examples (now use CLEAN_API_STRUCTURE instead)
- `ACTION_PLAN.md` - Implementation timeline

---

## Timeline Impact

**No change to timeline:**
- Phase 1 still 3-4 days (actually simpler now with 1 exporter instead of 9-file loop)
- Phase 2 still 2-3 days (model attribution unchanged)

**Simplified implementation:**
- Fewer exporters to create (1 combined vs 9 separate)
- Simpler orchestration logic
- Easier testing (1 file to validate vs 9)
- Cleaner code (mapping layer for names)

---

## Summary of Changes

| Aspect | OLD | NEW |
|--------|-----|-----|
| Files per day | 9 (one per subset) | 1 (all subsets) |
| Endpoint | `/subsets/{id}/{date}.json` | `/picks/{date}.json` |
| Group names | `v9_high_edge_top5` | `"Top 5"` or `"2"` |
| Model names | `catboost_v9` | `"926A"` |
| Technical details | Included | **Removed** |
| API inspection | Reveals strategy | **No info leaked** |

**Result:** Cleaner, simpler, more secure! ✅
