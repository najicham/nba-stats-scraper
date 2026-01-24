# Shared Code Duplication Analysis

**Created:** 2026-01-24
**Session:** 122 Morning Checkup
**Status:** Analysis Complete

---

## Executive Summary

Cloud Functions contain duplicated copies of the `shared/` utilities. This creates:
- **~12MB of duplicated code** across 7 Cloud Functions
- **~800 duplicated Python files**
- **Sync drift** between canonical and copied versions
- **Maintenance burden** for any changes

A sync script exists (`bin/maintenance/sync_shared_utils.py`) but is not run regularly.

---

## Current State

### Cloud Functions with shared/ Directories

| Cloud Function | shared/ Size | Python Files |
|----------------|--------------|--------------|
| phase2_to_phase3 | 2.0 MB | 141 |
| phase3_to_phase4 | 1.9 MB | 135 |
| phase4_to_phase5 | 1.9 MB | 132 |
| phase5_to_phase6 | 1.9 MB | 137 |
| daily_health_summary | 1.9 MB | 137 |
| self_heal | 1.9 MB | 134 |
| prediction_monitoring | 20 KB | 3 |
| **Total** | **~12 MB** | **~819** |

### Canonical shared/ Directory
- Size: 4.0 MB
- Contains: Latest versions with improvements (caching, retry logic, etc.)

### Current Drift Status (from sync script)

```
Files checked: 18
Identical (skipped): 79
Different: 12
Errors: 0
```

Files currently out of sync:
- `sport_config.py` - 6 copies differ (231 vs 233 lines)
- `storage_client.py` - 6 copies differ (245 vs 185 lines)

---

## Why This Happens

### Cloud Functions Deployment Model

Cloud Functions use `--source=<directory>` which bundles everything in that directory:

```bash
gcloud functions deploy phase4-to-phase5 \
  --source=orchestration/cloud_functions/phase4_to_phase5 \
  ...
```

This means dependencies must be **physically present** in the source directory.

### Options for Dependency Management

| Option | Pros | Cons |
|--------|------|------|
| **Current: Copy shared/** | Works, simple | Duplication, drift |
| **pip install from GCS** | No duplication | Build complexity, versioning |
| **Artifact Registry package** | Clean, versioned | Setup overhead |
| **Cloud Build with copy step** | Automated sync | Build complexity |
| **Git submodule** | Single source | Submodule complexity |

---

## Existing Sync Infrastructure

### Sync Script: `bin/maintenance/sync_shared_utils.py`

```bash
# Check drift
python bin/maintenance/sync_shared_utils.py --diff

# Dry run
python bin/maintenance/sync_shared_utils.py --dry-run

# Actually sync
python bin/maintenance/sync_shared_utils.py
```

The script syncs 18 key files from canonical `shared/` to Cloud Function copies.

### Deployment Scripts

Some deployment scripts copy shared/ during deployment:
- `bin/deploy_robustness_fixes.sh` - Copies shared module before deploy

---

## Recommendations

### Short-term (Low Effort)

1. **Run sync script now** to fix current drift
   ```bash
   python bin/maintenance/sync_shared_utils.py
   ```

2. **Add to CI/CD** - Run sync check in PRs
   ```yaml
   - name: Check shared/ sync
     run: python bin/maintenance/sync_shared_utils.py --diff
   ```

3. **Expand sync script** - Currently only syncs 18 files, should sync all of shared/

### Medium-term (Medium Effort)

4. **Create pre-deploy hook** - Auto-sync before any CF deployment

5. **Create shared package** - Package shared/ as installable module
   ```
   shared/
   ├── setup.py
   └── nba_shared/
       ├── utils/
       ├── config/
       └── ...
   ```

### Long-term (High Effort)

6. **Artifact Registry** - Publish shared package to Google Artifact Registry
   - Cloud Functions can pip install from there
   - Proper versioning
   - No more copies

7. **Monorepo Build System** - Use Bazel or similar
   - Automatic dependency resolution
   - No duplication

---

## Immediate Actions

### Fix Current Drift
```bash
# Run sync
python bin/maintenance/sync_shared_utils.py

# Commit
git add -A
git commit -m "fix: Sync shared utilities to Cloud Functions"
```

### Verify After Sync
```bash
python bin/maintenance/sync_shared_utils.py --diff
# Should show: Different: 0
```

---

## Files in Sync Script (18 files)

| File | Category |
|------|----------|
| sport_config.py | config |
| slack_channels.py | utils |
| metrics_utils.py | utils |
| storage_client.py | utils |
| auth_utils.py | utils |
| mlb_game_id_converter.py | utils |
| game_id_converter.py | utils |
| nba_team_mapper.py | utils |
| mlb_team_mapper.py | utils |
| travel_team_info.py | utils |
| sentry_config.py | utils |
| rate_limiter.py | alerts |
| alert_types.py | alerts |
| email_alerting.py | alerts |
| backfill_progress_tracker.py | alerts |
| checkpoint.py | backfill |
| schedule_utils.py | backfill |
| bigquery_retry.py | clients |

---

## Related Files

- `bin/maintenance/sync_shared_utils.py` - Sync script
- `bin/deploy_robustness_fixes.sh` - Deployment with copy
- `orchestration/cloud_functions/*/shared/` - Copied directories
