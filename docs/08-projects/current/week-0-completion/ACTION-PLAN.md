# Immediate Action Plan - Post Week 0 Audit
**Date:** January 21, 2026
**Priority:** Execute Tier 0 ASAP (8 hours)
**Goal:** Secure system + enable cost savings

---

## QUICK START - DO THIS FIRST

### Step 1: Rotate Exposed Secrets (2 hours) 🔴 CRITICAL

```bash
# 1. Create new secrets in Secret Manager
gcloud secrets create SENTRY_DSN_NEW --data-file=- <<EOF
<paste new Sentry DSN>
EOF

gcloud secrets create ANALYTICS_API_KEY_1_NEW --data-file=- <<EOF
<paste new API key>
EOF

gcloud secrets create ANALYTICS_API_KEY_2_NEW --data-file=- <<EOF
<paste new API key>
EOF

gcloud secrets create BREVO_SMTP_PASSWORD --data-file=- <<EOF
<paste SMTP password>
EOF

# 2. Update Phase 3 service to use Secret Manager
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --update-secrets=BREVO_SMTP_PASSWORD=BREVO_SMTP_PASSWORD:latest \
  --remove-env-vars=BREVO_SMTP_PASSWORD

# 3. Remove .env from git history (if committed)
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch .env" \
  --prune-empty --tag-name-filter cat -- --all

# 4. Force push (CAREFUL - coordinate with team)
git push origin --force --all
```

**Verification:**
```bash
# Check Phase 3 no longer has plain text password
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)"
```

---

### Step 2: Enable Query Caching (30 min) 💰 INSTANT $15-20/MONTH

```bash
# Update all Cloud Run services
for service in prediction-coordinator nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  echo "Updating $service..."
  gcloud run services update $service \
    --region=us-west2 \
    --set-env-vars=ENABLE_QUERY_CACHING=true,QUERY_CACHE_TTL_SECONDS=3600
done

# Update Cloud Functions (daily health check, etc.)
gcloud functions update daily-health-check \
  --region=us-west2 \
  --set-env-vars=ENABLE_QUERY_CACHING=true,QUERY_CACHE_TTL_SECONDS=3600

gcloud functions update daily-health-summary \
  --region=us-west2 \
  --set-env-vars=ENABLE_QUERY_CACHING=true,QUERY_CACHE_TTL_SECONDS=3600
```

**Verification:**
```bash
# Check environment variables
gcloud run services describe prediction-coordinator \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | grep CACHING

# Monitor cache hit rates (next day)
gcloud logging read 'jsonPayload.message=~"cache HIT"' \
  --limit=100 \
  --format=json \
  --freshness=1d
```

**Expected Savings:** $15-20/month immediately

---

### Step 3: Fix SQL Injection (4 hours) 🔴 CRITICAL

**File 1: `bin/infrastructure/monitoring/backfill_progress_monitor.py`**

```python
# BEFORE (Lines 105-110) - VULNERABLE
query = f"""
SELECT COUNT(DISTINCT game_date) as total
FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
WHERE game_status = 3
  AND game_date BETWEEN '{start}' AND '{end}'
"""

# AFTER - SECURE
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("start_date", "DATE", start),
        bigquery.ScalarQueryParameter("end_date", "DATE", end),
    ]
)
query = """
SELECT COUNT(DISTINCT game_date) as total
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE game_status = 3
  AND game_date BETWEEN @start_date AND @end_date
"""
result = self.client.query(query, job_config=job_config).result(timeout=60)
```

**File 2: `predictions/coordinator/missing_prediction_detector.py`**

```python
# BEFORE (Line 65) - VULNERABLE
WHERE game_date = '{game_date.isoformat()}'

# AFTER - SECURE
job_config = bigquery.QueryJobConfig(
    query_parameters=[
        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
    ]
)
# ... in query:
WHERE game_date = @game_date
```

**Apply Changes:**
```bash
# 1. Make changes in files
# 2. Test locally
python -m pytest tests/unit/monitoring/
python -m pytest tests/unit/predictions/coordinator/

# 3. Commit
git add bin/infrastructure/monitoring/backfill_progress_monitor.py
git add predictions/coordinator/missing_prediction_detector.py
git commit -m "fix: Convert to parameterized BigQuery queries

Fixes SQL injection vulnerabilities in:
- backfill_progress_monitor.py (5 locations)
- missing_prediction_detector.py (1 location)

Uses query parameters instead of f-string interpolation.

Security: Prevents potential SQL injection attacks
Impact: No functional changes, queries work identically

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# 4. Push and deploy
git push origin week-1-improvements
```

---

### Step 4: Fix Bare Except Blocks (2 hours) 🔴 CRITICAL

**File: `scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py`**

```python
# BEFORE (Line 416) - DANGEROUS
def _safe_perf(self, performance: Dict, period: str, side: str) -> Optional[int]:
    try:
        return performance.get(period, {}).get(side)
    except:  # Bare except!
        return None

# AFTER - SAFE
def _safe_perf(self, performance: Dict, period: str, side: str) -> Optional[int]:
    try:
        return performance.get(period, {}).get(side)
    except (KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Error extracting performance for {period}/{side}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in _safe_perf: {e}", exc_info=True)
        return None
```

**Apply to all 7 instances:**
1. `scripts/mlb/historical_bettingpros_backfill/backfill_all_props.py:416`
2. `scripts/mlb/historical_bettingpros_backfill/check_progress.py:108`
3. `scripts/mlb/baseline_validation.py:156`
4. `scripts/mlb/training/walk_forward_validation.py:269`
5. `scripts/mlb/build_bdl_player_mapping.py:270`
6. `scripts/mlb/collect_season.py:358`
7. `ml/experiment_runner.py:94`

```bash
# Commit
git add scripts/mlb/ ml/experiment_runner.py
git commit -m "fix: Replace bare except blocks with specific exception handling

Fixes 7 bare except blocks that were swallowing all exceptions
including SystemExit and KeyboardInterrupt.

Changes:
- Catch specific exceptions (KeyError, TypeError, AttributeError)
- Add proper error logging with context
- Preserve stack traces for unexpected errors

Security: Prevents masking of critical errors
Reliability: Enables proper debugging and monitoring

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

git push origin week-1-improvements
```

---

## TIER 0 CHECKLIST

### Priority 1: Security (6.5 hours)
- [ ] **Rotate all exposed API keys** (2h)
  - [ ] Create new secrets in Secret Manager
  - [ ] Update all services
  - [ ] Remove from git history
  - [ ] Verify no plain text credentials

- [ ] **Fix SQL injection** (4h)
  - [ ] Convert backfill_progress_monitor.py to parameterized queries
  - [ ] Convert missing_prediction_detector.py to parameterized queries
  - [ ] Test all queries
  - [ ] Deploy changes

- [ ] **Fix bare except blocks** (2h)
  - [ ] Replace 7 instances with specific exception handling
  - [ ] Add proper error logging
  - [ ] Test error paths
  - [ ] Deploy changes

### Priority 2: Cost Optimization (30 min)
- [ ] **Enable query caching** (30min)
  - [ ] Set ENABLE_QUERY_CACHING=true on all Cloud Run services
  - [ ] Set ENABLE_QUERY_CACHING=true on all Cloud Functions
  - [ ] Monitor cache hit rates
  - [ ] **Expected savings: $15-20/month**

### Priority 3: Documentation (30 min)
- [ ] **Update project docs**
  - [ ] Mark Tier 0 items complete
  - [ ] Document changes made
  - [ ] Update STATUS-DASHBOARD.md

---

## VERIFICATION & MONITORING

### After Step 1 (Secrets)
```bash
# Verify no plain text passwords
gcloud run services list --region=us-west2 --format=json | \
  jq -r '.[] | .spec.template.spec.containers[0].env[] | select(.name=="BREVO_SMTP_PASSWORD")'
# Should return empty

# Verify using Secret Manager
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format=json | jq '.spec.template.spec.containers[0].env'
# Should show secretKeyRef instead of value
```

### After Step 2 (Query Caching)
```bash
# Check environment variables
for service in prediction-coordinator nba-phase2-raw-processors; do
  echo "=== $service ==="
  gcloud run services describe $service --region=us-west2 \
    --format="value(spec.template.spec.containers[0].env)" | grep CACHING
done

# Monitor logs for cache hits (wait 24 hours)
gcloud logging read 'jsonPayload.message=~"cache"' \
  --limit=100 \
  --format=json \
  --freshness=1d | jq -r '.[] | select(.jsonPayload.message | contains("HIT")) | .timestamp'
```

### After Steps 3-4 (Code Changes)
```bash
# Run tests
python -m pytest tests/unit/monitoring/
python -m pytest tests/unit/predictions/
python -m pytest tests/unit/mlb/

# Check for remaining bare excepts
grep -r "except:" --include="*.py" . | grep -v "except (" | wc -l
# Should be 0 or very few

# Verify parameterized queries
grep -r "@start_date\|@end_date\|@game_date" --include="*.py" .
# Should show query parameters in use
```

---

## TIER 1 PREVIEW (THIS WEEK)

After completing Tier 0, move to these items:

1. **Add Missing Timeouts** (4h) - Prevent worker hangs
2. **Add Partition Filters** (4h) - Save $22-27/month
3. **Create Materialized Views** (8h) - Save $14-18/month
4. **Add Tests for Critical Files** (12h) - Prevent regressions
5. **Fix SSL Verification** (2h) - Security hardening

**Tier 1 Total:** 30 hours, $36-45/month savings

---

## SUCCESS METRICS

### After Tier 0 Completion

**Security:**
- ✅ No exposed credentials in code or env vars
- ✅ No SQL injection vulnerabilities
- ✅ No bare except blocks in critical paths
- ✅ All secrets in Secret Manager

**Cost:**
- ✅ Query caching enabled across all services
- ✅ Cache hit rate: 30-50% (target)
- ✅ Monthly savings: $15-20
- ✅ Annual savings: $180-240

**Reliability:**
- ✅ Proper exception handling with logging
- ✅ Error classification for retry logic
- ✅ No silent failures from bare excepts

---

## ESTIMATED TIMELINE

**Tonight (Optional):**
- Step 2: Enable query caching (30 min)

**Tomorrow Morning:**
- Step 1: Rotate secrets (2 hours)
- Step 2: Enable caching (if not done tonight)

**Tomorrow Afternoon:**
- Step 3: Fix SQL injection (4 hours)

**Day After Tomorrow:**
- Step 4: Fix bare except blocks (2 hours)
- Verification & monitoring

**Total:** 8.5 hours over 2-3 days

---

## SUPPORT & REFERENCES

### Documentation
- **Full Analysis:** `docs/09-handoff/2026-01-21-AGENT-FINDINGS-COMPREHENSIVE.md`
- **Session Summary:** `docs/09-handoff/2026-01-21-SESSION-SUMMARY.md`
- **Week 0 Status:** `docs/08-projects/current/week-0-completion/COMPREHENSIVE-STATUS.md`

### Agent Transcripts
- **Security:** `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/afacc1f.output`
- **Performance:** `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/a571bff.output`
- **Error Handling:** `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/a0d8a29.output`
- **BigQuery Cost:** `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/ab7998e.output`
- **Testing:** `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/af57fe8.output`

### Quick Commands
```bash
# View current branch
git status

# See all untracked docs
ls docs/09-handoff/*.md

# Check service health
gcloud run services list --region=us-west2

# Monitor BigQuery costs
bq ls -j --max_results=20
```

---

**Created:** 2026-01-21 5:40 PM PT
**Status:** Ready to execute
**Next:** Start with Step 1 (Rotate secrets)
**Goal:** Complete Tier 0 in 8.5 hours
