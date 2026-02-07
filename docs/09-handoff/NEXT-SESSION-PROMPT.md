# Session 149 Prompt

Read the Session 148 handoff for full context: `docs/09-handoff/2026-02-07-SESSION-148-HANDOFF.md`

## Context

Session 148 fixed three systemic issues:
1. **Change detector** queried disabled BDL tables instead of nbac — caused Phase 3 to miss games. Fixed + backfilled Feb 6.
2. **GitHub Actions CD** silently swallowed deploy errors. Fixed to fail properly. Also granted `artifactregistry.writer` IAM role.
3. **prediction-worker model** was gitignored but Dockerfile tried to COPY it. Fixed via GCS download step in cloudbuild.yaml.

All 6 services deployed at commit `2e6e5386`. Pipeline healthy.

## Task 1: Fix Remaining BDL References (HIGH)

Several `shared/` modules still query `nba_raw.bdl_player_boxscores` which was disabled in Session 8. These silently return empty/stale data.

### Files to Fix

**`shared/utils/completeness_checker.py`** — 5 active queries:

| Method | Line | Purpose |
|--------|------|---------|
| `_query_dnp_games()` | ~628 | Counts DNP games (0 minutes) |
| `check_raw_boxscore_for_player()` | ~1171 | Checks if player appeared in raw boxscore |
| `check_raw_boxscore_batch()` | ~1225 | Batch version |
| `get_player_game_dates()` | ~1560 | Gets player games + team |
| `get_player_game_dates_batch()` | ~1673 | Batch version |

**`shared/utils/postponement_detector.py`** (line ~263) — games with boxscore data
**`shared/validation/continuous_validator.py`** (line ~454) — data freshness check
**`shared/validation/context/player_universe.py`** (line ~248) — player universe

**Fix:** Replace `bdl_player_boxscores` → `nbac_gamebook_player_stats` in all query methods.

**CRITICAL — Verify field compatibility first:**
```sql
-- Check that nbac table has the fields these queries use
SELECT column_name, data_type
FROM `nba-props-platform.nba_raw.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'nbac_gamebook_player_stats'
  AND column_name IN ('player_lookup', 'game_date', 'team_abbr', 'minutes')
```
The `minutes` field format may differ (BDL uses string '00'/'25', nbac may use different format). Adjust the `_query_dnp_games()` WHERE clause accordingly.

**Do NOT change:** Config files (fallback_config.yaml, validation/config.py, chain_config.py) — these correctly declare BDL as a fallback source. Leave anything outside `shared/`.

## Task 2: Optimize Cloud Build Performance (MEDIUM)

Current build times:

| Service | Time | Issues |
|---------|------|--------|
| prediction-worker | **6m18s** | GCS download adds ~2min, deps after code |
| nba-phase3-analytics | 4m44s | Deps after code |
| nba-scrapers | 4m39s | **No lock file**, `|| true` swallows errors |
| nba-phase2-raw | 4m21s | **No lock file** |
| prediction-coordinator | 4m16s | Deps after code |
| nba-phase4-precompute | 3m58s | Deps after code |

### A. Add lock files to raw + scrapers (~30-60s savings each)
```bash
cd data_processors/raw
docker run --rm -v $(pwd):/app -w /app python:3.11-slim bash -c \
  "pip install --quiet --upgrade pip && pip install --quiet -r requirements.txt && pip freeze > requirements-lock.txt"

cd ../../scrapers
docker run --rm -v $(pwd):/app -w /app python:3.11-slim bash -c \
  "pip install --quiet --upgrade pip && pip install --quiet -r requirements.txt && pip freeze > requirements-lock.txt"
```
Then update both Dockerfiles to use `requirements-lock.txt`.

### B. Reorder COPY/RUN for Docker layer caching (~1-2min savings on code-only changes)
All 6 Dockerfiles copy code BEFORE installing deps. Restructure:
```dockerfile
# Copy ONLY requirements first (cached layer)
COPY shared/requirements.txt ./shared/requirements.txt
COPY service/requirements-lock.txt ./service/requirements-lock.txt
RUN pip install --no-cache-dir -r shared/requirements.txt
RUN pip install --no-cache-dir -r service/requirements-lock.txt
# THEN copy code (code changes don't bust pip cache)
COPY shared/ ./shared/
COPY service/ ./service/
```
**Note:** Cloud Build doesn't cache Docker layers by default. Check if Kaniko or `--cache-from` is configured. If not, this only helps local builds.

### C. Fix scrapers error suppression
`scrapers/Dockerfile` line ~44: Remove `|| true` from pip install.

### D. Optimize GCS model download step
`cloudbuild.yaml` Step 0 pulls the full `cloud-sdk` image (~1.5GB) for every build. Consider:
- Use lighter `gcr.io/cloud-builders/gsutil` image
- Skip Step 0 for non-worker services (conditional on `_SERVICE`)

## Verification

```bash
# Check all services deployed
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=6 \
  --format="table(substitutions._SERVICE,status,createTime)"

# Run daily validation
/validate-daily

# After BDL fixes, verify completeness checker with nbac data
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_raw.nbac_gamebook_player_stats WHERE game_date = CURRENT_DATE() - 1"
```
