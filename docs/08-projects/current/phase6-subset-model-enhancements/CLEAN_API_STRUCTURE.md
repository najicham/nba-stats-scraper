# Clean API Structure - No Proprietary Details

**Purpose:** API responses for testing that don't reveal strategy or competitive details

## Principles

**HIDE:**
- ❌ Algorithm names (CatBoost, XGBoost, ensemble)
- ❌ System IDs (catboost_v9, ensemble_v1)
- ❌ Technical field names (composite_score, edge, confidence_score)
- ❌ Calculation methods (edge * 10 + confidence * 0.5)
- ❌ Signal thresholds (25-40% = GREEN)
- ❌ Filter criteria (edge >= 5, confidence >= 0.92)
- ❌ Feature counts (33 features)
- ❌ Training details (dates, samples, approach)
- ❌ Data sources (BigQuery table names, views)
- ❌ Internal IDs (subset_id = v9_high_edge_top5)

**SHOW:**
- ✅ Pick recommendations (player, OVER/UNDER, line)
- ✅ Simple group names ("Group A", "Group B")
- ✅ Performance metrics (hit rate, ROI)
- ✅ Basic metadata (date, time)

---

## Clean JSON Structure

### All Subsets in One File

**Endpoint:** `/api/picks/2026-02-03.json`

```json
{
  "date": "2026-02-03",
  "generated": "2026-02-03T14:30:00Z",
  "groups": [
    {
      "id": "A1",
      "name": "Top 5",
      "model": "926A",
      "stats": {
        "hit_rate": 74.6,
        "roi": 8.4,
        "sample_days": 30
      },
      "picks": [
        {
          "player": "LeBron James",
          "team": "LAL",
          "opponent": "BOS",
          "prediction": 26.1,
          "line": 24.5,
          "direction": "OVER"
        },
        {
          "player": "Luka Doncic",
          "team": "DAL",
          "opponent": "PHX",
          "prediction": 32.4,
          "line": 29.5,
          "direction": "OVER"
        }
        // ... 3 more picks (total 5)
      ]
    },
    {
      "id": "A2",
      "name": "Top 10",
      "model": "926A",
      "stats": {
        "hit_rate": 76.0,
        "roi": 7.2,
        "sample_days": 30
      },
      "picks": [
        // ... 10 picks
      ]
    },
    {
      "id": "A3",
      "name": "Best Value",
      "model": "926A",
      "stats": {
        "hit_rate": 79.6,
        "roi": 12.1,
        "sample_days": 30
      },
      "picks": [
        // ... ~12 picks
      ]
    }
    // ... more groups
  ]
}
```

---

## Group Naming (Non-Revealing)

**Internal → External Mapping:**

| Internal (Hidden) | External (Shown) | Notes |
|-------------------|------------------|-------|
| v9_high_edge_top1 | **"A1" or "Top 1"** | Just shows size |
| v9_high_edge_top5 | **"A2" or "Top 5"** | No edge/confidence details |
| v9_high_edge_top10 | **"A3" or "Top 10"** | Generic ranking |
| v9_high_edge_balanced | **"B1" or "Best Value"** | No signal details |
| v9_high_edge_any | **"B2" or "All"** | Generic name |
| v9_premium_safe | **"C1" or "Premium"** | No confidence threshold |
| v9_high_edge_warning | **"D1" or "Alternative"** | No negative connotation |

**Alternative (even simpler):**
- Just use: Group 1, Group 2, Group 3, etc.
- Or: A, B, C, D, E, F, G, H, I

---

## Minimal Pick Structure

**Remove technical fields:**

```json
{
  "picks": [
    {
      "player": "LeBron James",
      "team": "LAL",
      "opponent": "BOS",
      "prediction": 26.1,
      "line": 24.5,
      "direction": "OVER"
    }
  ]
}
```

**Don't include:**
- ❌ `confidence_score` (reveals model internals)
- ❌ `edge` or `line_margin` (reveals calculation)
- ❌ `composite_score` (reveals formula)
- ❌ `similarity_baseline` (reveals component)
- ❌ `fatigue_adjustment` (reveals factor)
- ❌ `system_id` (reveals model)
- ❌ `prediction_id` (could be tracked)
- ❌ `features_snapshot` (reveals features)

---

## Performance Stats (Safe to Show)

```json
{
  "stats": {
    "hit_rate": 74.6,        // ✅ Outcome metric
    "roi": 8.4,              // ✅ Business metric
    "sample_days": 30,       // ✅ Context
    "picks": 147             // ✅ Volume
  }
}
```

**Don't include:**
- ❌ `mae` (reveals prediction accuracy method)
- ❌ `avg_edge` (reveals how picks are selected)
- ❌ `avg_confidence` (reveals confidence scoring)
- ❌ `within_3_pct` / `within_5_pct` (reveals thresholds)
- ❌ `signal_effectiveness` (reveals signal strategy)

---

## Complete Clean Example

```json
{
  "date": "2026-02-03",
  "generated": "2026-02-03T14:30:00Z",
  "model": "926A",
  "groups": [
    {
      "id": "1",
      "name": "Top Pick",
      "stats": {
        "hit_rate": 81.8,
        "roi": 15.2,
        "days": 30
      },
      "picks": [
        {
          "player": "LeBron James",
          "team": "LAL",
          "opponent": "BOS",
          "prediction": 26.1,
          "line": 24.5,
          "direction": "OVER"
        }
      ]
    },
    {
      "id": "2",
      "name": "Top 5",
      "stats": {
        "hit_rate": 75.0,
        "roi": 9.1,
        "days": 30
      },
      "picks": [
        {
          "player": "LeBron James",
          "team": "LAL",
          "opponent": "BOS",
          "prediction": 26.1,
          "line": 24.5,
          "direction": "OVER"
        },
        {
          "player": "Luka Doncic",
          "team": "DAL",
          "opponent": "PHX",
          "prediction": 32.4,
          "line": 29.5,
          "direction": "OVER"
        },
        {
          "player": "Stephen Curry",
          "team": "GSW",
          "opponent": "LAC",
          "prediction": 23.2,
          "line": 26.5,
          "direction": "UNDER"
        },
        {
          "player": "Giannis Antetokounmpo",
          "team": "MIL",
          "opponent": "ATL",
          "prediction": 34.8,
          "line": 32.5,
          "direction": "OVER"
        },
        {
          "player": "Jayson Tatum",
          "team": "BOS",
          "opponent": "LAL",
          "prediction": 24.1,
          "line": 27.5,
          "direction": "UNDER"
        }
      ]
    },
    {
      "id": "3",
      "name": "Top 10",
      "stats": {
        "hit_rate": 76.0,
        "roi": 8.8,
        "days": 30
      },
      "picks": [
        // ... 10 picks (same format)
      ]
    },
    {
      "id": "4",
      "name": "Best Value",
      "stats": {
        "hit_rate": 79.6,
        "roi": 12.1,
        "days": 30
      },
      "picks": [
        // ... ~12 picks
      ]
    },
    {
      "id": "5",
      "name": "All Picks",
      "stats": {
        "hit_rate": 79.4,
        "roi": 11.8,
        "days": 30
      },
      "picks": [
        // ... ~28 picks
      ]
    }
  ]
}
```

---

## Field Naming (Non-Technical)

**Use generic field names:**

| Technical (Don't Use) | Generic (Use) |
|----------------------|---------------|
| `confidence_score` | (omit entirely) |
| `edge`, `line_margin` | (omit entirely) |
| `composite_score` | (omit entirely) |
| `system_id` | `model` |
| `subset_id` | `id` |
| `game_date` | `date` |
| `generated_at` | `generated` |
| `hit_rate` | `hit_rate` ✅ |
| `roi_pct` | `roi` ✅ |
| `sample_days` | `days` ✅ |

---

## Exporter Implementation

```python
from shared.config.model_codenames import get_model_codename

# Mapping internal names to public names
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

class AllSubsetsPicksExporter(BaseExporter):
    def generate_json(self, target_date: str) -> dict:
        # Query all subsets
        subsets_data = self.get_all_subset_picks(target_date)

        # Clean output
        groups = []
        for subset in subsets_data:
            # Get public names
            public = SUBSET_PUBLIC_NAMES.get(subset['subset_id'], {
                'id': subset['subset_id'],
                'name': subset['subset_name']
            })

            # Build clean group
            group = {
                'id': public['id'],
                'name': public['name'],
                'stats': {
                    'hit_rate': subset['hit_rate'],
                    'roi': subset['roi'],
                    'days': 30
                },
                'picks': []
            }

            # Clean picks - ONLY show user-facing data
            for pick in subset['picks']:
                clean_pick = {
                    'player': pick['player_name'],
                    'team': pick['team'],
                    'opponent': pick['opponent'],
                    'prediction': round(pick['predicted_points'], 1),
                    'line': round(pick['line_value'], 1),
                    'direction': pick['recommendation']
                }
                group['picks'].append(clean_pick)

            groups.append(group)

        # Return clean structure
        return {
            'date': target_date,
            'generated': datetime.utcnow().isoformat() + 'Z',
            'model': get_model_codename('catboost_v9'),  # Just '926A'
            'groups': groups
        }
```

---

## Testing Detection

Someone inspecting the API **cannot determine:**
- ❌ What algorithm is used
- ❌ What features are considered
- ❌ How picks are scored/ranked
- ❌ What filters are applied
- ❌ What thresholds exist
- ❌ How groups differ from each other
- ❌ What training data is used
- ❌ How confidence is calculated

They **can only see:**
- ✅ Player predictions
- ✅ OVER/UNDER recommendations
- ✅ Historical performance
- ✅ Generic group names

---

## Security Checklist

Before deploying, verify:

- [ ] No `system_id`, `subset_id` fields
- [ ] No `confidence_score`, `edge`, `composite_score`
- [ ] No algorithm names (CatBoost, XGBoost, etc.)
- [ ] No technical thresholds (>= 5, >= 0.92)
- [ ] No calculation formulas
- [ ] No training dates/details
- [ ] No feature lists or counts
- [ ] No data source references
- [ ] No BigQuery table names
- [ ] Generic group names only (1, 2, 3 or Top 5, Top 10)

---

## Example Dev Tools Inspection

**What someone would see:**

```javascript
// Network tab: GET /api/picks/2026-02-03.json
{
  "date": "2026-02-03",
  "generated": "2026-02-03T14:30:00Z",
  "model": "926A",
  "groups": [
    {
      "id": "2",
      "name": "Top 5",
      "stats": {"hit_rate": 75.0, "roi": 9.1, "days": 30},
      "picks": [
        {"player": "LeBron James", "team": "LAL", "opponent": "BOS",
         "prediction": 26.1, "line": 24.5, "direction": "OVER"}
      ]
    }
  ]
}
```

**What they CANNOT learn:**
- Why is this in "Top 5"? (ranking algorithm hidden)
- How are predictions calculated? (model hidden)
- Why OVER vs UNDER? (logic hidden)
- What makes "Top 5" different from "Top 10"? (criteria hidden)
- What is "926A"? (just a code, no details)

**Perfect!** ✅
