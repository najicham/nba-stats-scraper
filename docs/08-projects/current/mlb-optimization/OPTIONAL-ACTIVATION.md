# Optional: Activate All 3 MLB Systems

**Current State**: Only `v1_baseline` is active (conservative deployment)
**Optional**: Activate all 3 systems for full optimization benefits

## Why Keep Only V1 Active?

✅ **Safe deployment** - Validate optimizations work correctly first
✅ **Monitor performance** - Ensure no issues before scaling up
✅ **All code ready** - Can activate anytime with one command

## To Activate All 3 Systems (Optional)

### Option 1: Via Google Cloud Console (Easiest)

1. Go to: https://console.cloud.google.com/run/detail/us-west2/mlb-prediction-worker/variables
2. Find environment variable `MLB_ACTIVE_SYSTEMS`
3. Change value to: `v1_baseline,v1_6_rolling,ensemble_v1`
4. Click "Deploy"

### Option 2: Via gcloud CLI

```bash
# Update using YAML file (avoids escaping issues)
cat > /tmp/mlb-env.yaml << 'EOF'
MLB_ACTIVE_SYSTEMS: "v1_baseline,v1_6_rolling,ensemble_v1"
EOF

gcloud run services update mlb-prediction-worker \
  --region=us-west2 \
  --env-vars-file=/tmp/mlb-env.yaml
```

## What Happens When Activated

✅ All 3 systems run in parallel:
- `v1_baseline` - Original 25-feature model
- `v1_6_rolling` - Enhanced 35-feature model with Statcast
- `ensemble_v1` - Combines both models

✅ Performance improvements kick in:
- **66% fewer BigQuery queries** (3 queries → 1 query per batch)
- **30-40% faster** batch predictions
- **3 predictions per pitcher** (one from each system)

✅ Feature coverage tracks all systems

## Recommendation

**Wait 24-48 hours** to ensure current deployment is stable, then activate if desired.

Current setup (v1_baseline only) still benefits from:
- ✅ Feature coverage monitoring
- ✅ IL cache improvements (retry + 3hr TTL)
- ✅ Shared feature loader (when ready for multi-system)

---
**Status**: Optional enhancement, no urgency
**Risk**: LOW - Easy to rollback by changing env var back
