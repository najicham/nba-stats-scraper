# Model Management

This project covers ML model lifecycle management including training, versioning, registration, and deployment.

## Quick Links

- [Monthly Retraining Guide](MONTHLY-RETRAINING.md)
- [Model Registry Schema](MODEL-REGISTRY.md)
- [Troubleshooting](TROUBLESHOOTING.md)

## Key Tools

| Tool | Purpose |
|------|---------|
| `bin/retrain-monthly.sh` | Automate monthly retraining |
| `bin/model-registry.sh` | Query and validate model registry |
| `bin/deploy-service.sh` | Deploy with model path validation |

## Current Production Models

Run `./bin/model-registry.sh production` to see current production models.

As of Session 106:
- **V8**: Historical baseline (2021-2024) - for comparison only
- **V9**: Current season model (Nov 2025+) - production predictions

## Related Documentation

- `ml/experiments/quick_retrain.py` - Training script
- `schemas/model_registry.json` - Registry schema
- `predictions/worker/prediction_systems/catboost_v9.py` - Production prediction code
