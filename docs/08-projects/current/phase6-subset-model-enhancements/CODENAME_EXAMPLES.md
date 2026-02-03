# Model Codename Examples for Testing

**Purpose:** Simple alphanumeric codes for testing phase

## Codename Scheme

### Current Models

| system_id | Codename | Description |
|-----------|----------|-------------|
| catboost_v9 | **926A** | Original V9 (Nov-Jan training) |
| catboost_v9_202602 | **926B** | Feb 2026 retrain |
| ensemble_v1 | **E01** | Ensemble blend |
| similarity_v1 | **S01** | Game similarity matcher |
| xgboost_v2 | **X02** | XGBoost V2 |
| catboost_v8 | **825A** | Legacy baseline |

### Naming Pattern

- **9XX** = CatBoost V9 family (e.g., 926A, 926B)
- **8XX** = CatBoost V8 family
- **E0X** = Ensemble models
- **S0X** = Similarity models
- **X0X** = XGBoost models

## JSON Export Examples

### Subset Definitions with Codenames

```json
{
  "generated_at": "2026-02-03T10:00:00Z",
  "subsets": [
    {
      "subset_id": "v9_high_edge_top5",
      "subset_name": "High Edge Top 5",
      "model_code": "926A",
      "system_id": "catboost_v9",
      "is_active": true
    },
    {
      "subset_id": "v9_high_edge_balanced",
      "subset_name": "High Edge Balanced (GREEN only)",
      "model_code": "926A",
      "system_id": "catboost_v9",
      "is_active": true
    }
  ]
}
```

### Subset Performance with Codenames

```json
{
  "performance_windows": {
    "last_30_days": {
      "subsets": [
        {
          "subset_id": "v9_high_edge_top5",
          "model_code": "926A",
          "picks": 147,
          "hit_rate": 74.6,
          "roi": 8.4
        }
      ]
    }
  }
}
```

### Subset Picks with Codenames

```json
{
  "game_date": "2026-02-03",
  "subset_id": "v9_high_edge_top5",
  "model_code": "926A",
  "picks": [
    {
      "rank": 1,
      "player_name": "LeBron James",
      "prediction": 26.1,
      "line": 24.5,
      "recommendation": "OVER",
      "model_code": "926A"
    }
  ]
}
```

### Model Registry with Codenames

```json
{
  "models": [
    {
      "model_code": "926A",
      "system_id": "catboost_v9",
      "description": "Current season model",
      "status": "PRODUCTION",
      "performance": {
        "hit_rate": 79.0,
        "mae": 4.1,
        "roi": 50.9
      }
    },
    {
      "model_code": "926B",
      "system_id": "catboost_v9_202602",
      "description": "Feb 2026 retrain",
      "status": "TESTING",
      "performance": {
        "hit_rate": 80.2,
        "mae": 3.9,
        "roi": 52.1
      }
    }
  ]
}
```

## Usage in Phase 6 Exporters

### Example Exporter Code

```python
from shared.config.model_codenames import get_model_codename

class SubsetPerformanceExporter(BaseExporter):
    def generate_json(self):
        query = """
        SELECT
          subset_id,
          subset_name,
          system_id,
          SUM(graded_picks) as picks,
          ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate
        FROM nba_predictions.v_dynamic_subset_performance
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        GROUP BY subset_id, subset_name, system_id
        """

        results = self.query_to_list(query)

        # Add codenames to results
        for row in results:
            row['model_code'] = get_model_codename(row['system_id'])
            # Optionally remove system_id for testing
            # del row['system_id']

        return {
            'generated_at': datetime.utcnow().isoformat(),
            'subsets': results
        }
```

## Website Display Examples

### Testing UI - Simple Display

```
╔═══════════════════════════════════╗
║  High Edge Top 5                  ║
║  Model: 926A                      ║
╠═══════════════════════════════════╣
║  79.0% Hit Rate                   ║
║  +50.9% ROI                       ║
║  147 picks (30 days)              ║
╚═══════════════════════════════════╝
```

### Testing UI - Comparison View

```
Compare Models:

┌──────────┬─────────┬──────────┬───────┐
│ Model    │ Picks   │ Hit Rate │ ROI   │
├──────────┼─────────┼──────────┼───────┤
│ 926A     │ 147     │ 74.6%    │ +8.4% │
│ 926B     │ 89      │ 76.2%    │ +9.8% │
│ E01      │ 147     │ 71.3%    │ +5.2% │
└──────────┴─────────┴──────────┴───────┘
```

### Testing UI - Model Info

```html
<div class="model-card">
  <h3>Model 926A</h3>
  <p class="description">Current season model</p>

  <div class="stats">
    <span>79.0% Hit Rate</span>
    <span>±4.1 pts accuracy</span>
  </div>

  <div class="status">
    <span class="badge production">Production</span>
  </div>
</div>
```

## Future Evolution

These simple codenames can evolve:

**Phase 1 (Now):** Testing
- Use: `926A`, `926B`, `E01`
- Purpose: Internal testing, development

**Phase 2:** Public Beta
- Use: `Model A`, `Model B`, `Ensemble`
- Purpose: User testing, feedback

**Phase 3:** Production
- Use: `Pro Model V9`, `Ensemble Blend`
- Purpose: Marketing, brand identity

## Implementation Checklist

- [x] Create `model_codenames.py` config
- [ ] Update Phase 6 exporters to include `model_code` field
- [ ] Test JSON output contains codenames
- [ ] Update frontend to display codenames
- [ ] Document codename → system_id mapping for team

## Quick Test

```bash
# Test the codename mapping
python -c "
from shared.config.model_codenames import get_model_codename
print('catboost_v9 →', get_model_codename('catboost_v9'))
print('ensemble_v1 →', get_model_codename('ensemble_v1'))
"

# Expected output:
# catboost_v9 → 926A
# ensemble_v1 → E01
```
