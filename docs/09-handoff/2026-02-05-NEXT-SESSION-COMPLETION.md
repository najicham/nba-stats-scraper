# Next Session: Complete Prevention Improvements

**Date:** 2026-02-05 (for next session)
**Context:** Session 132 completed 8/9 prevention improvement tasks
**Duration:** 30-45 minutes (quick session)
**Goal:** Complete dependency lock files and verify end-to-end system

---

## Quick Context

Session 132 successfully implemented prevention infrastructure to stop silent failure bugs:

✅ **Completed (8/9 tasks):**
- Fixed drift monitoring Slack alerts
- Made health endpoints publicly accessible
- Enhanced deep health checks (test actual operations)
- Created Dockerfile dependency validation script
- Integrated validation into deployment pipeline

⏸️ **Pending (1/9 tasks):**
- Generate dependency lock files for deterministic builds

---

## Your Mission

Complete the final prevention improvement and verify the system end-to-end.

### Task 1: Generate Dependency Lock Files (30 min)

**Why:** Pin all transitive dependencies for faster, deterministic builds.

**Benefits:**
- Faster builds (no pip dependency resolution)
- Deterministic builds (same versions every time)
- Prevents version drift issues like db-dtypes

**Services to update:**
1. predictions/worker
2. predictions/coordinator
3. data_processors/grading/nba
4. data_processors/analytics
5. data_processors/precompute

**Process for each service:**

```bash
# 1. Create lock file from current environment
cd <service-directory>
pip freeze > requirements-lock.txt

# 2. Review lock file
cat requirements-lock.txt | head -20

# 3. Update Dockerfile
# Change: RUN pip install -r requirements.txt
# To:     RUN pip install -r requirements-lock.txt

# 4. Test build (from repo root)
docker build -f <service>/Dockerfile -t test-build .

# 5. Verify dependencies loaded
docker run --rm test-build pip list | grep -E "(catboost|db-dtypes|pandas)"
```

**Example Dockerfile change:**

```dockerfile
# Before
COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# After
COPY ./requirements.txt .
COPY ./requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt
```

**Note:** Keep `requirements.txt` for documentation of direct dependencies. Use `requirements-lock.txt` for actual installation.

---

### Task 2: Test End-to-End Prevention System (15 min)

**Verify all 6 validation layers work:**

```bash
# Layer 0: Dockerfile Validation
./bin/validate-dockerfile-dependencies.sh predictions/worker
# Expected: ✅ Dockerfile validation passed

# Layer 3: Deep Health Checks
curl https://nba-grading-service-f7p3g7f6ya-wl.a.run.app/health/deep | jq '.status'
# Expected: "healthy"

curl https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/health/deep | jq '.status'
# Expected: "healthy"

# Layer 5: Drift Monitoring (create intentional drift)
echo "# Test comment" >> bin/deploy-service.sh
git add -A && git commit -m "test: Create intentional drift for monitoring test"
./bin/check-deployment-drift.sh
# Expected: Shows drift for affected services

# Trigger drift alert
gcloud pubsub topics publish deployment-drift-check \
  --message='{"test": true}' \
  --project=nba-props-platform

# Check Slack channel for alert (should appear within 1 minute)

# Clean up test
git reset --soft HEAD~1
```

---

### Task 3: Update Documentation (5 min)

**Update the prevention improvements handoff:**

Add lock file details to:
- `docs/09-handoff/2026-02-05-SESSION-132-PREVENTION-IMPROVEMENTS.md`

Mark task #7 as complete in the handoff.

---

## Current State (From Session 132)

### What's Deployed ✅
- nba-grading-service (enhanced /health/deep)
- prediction-coordinator (new /health/deep)
- prediction-worker (comprehensive health checks)
- deployment-drift-monitor (Slack webhooks working)
- All services have public health endpoints

### What's Committed ✅
- Commit: `b5e242b6`
- Branch: `main`
- Status: Ready to push (or already pushed)

### Validation Infrastructure Live ✅

```
Layer 0: Dockerfile Validation       ← Catches missing COPY
Layer 1: Docker Build                 ← Catches missing packages
Layer 2: Dependency Testing           ← Catches import errors
Layer 3: Deep Health Checks           ← Catches runtime issues
Layer 4: Smoke Tests                  ← Verifies functionality
Layer 5: Drift Monitoring             ← Detects stale code
```

---

## Testing Commands

### Quick Health Check

```bash
# Test all deep health endpoints
for service in nba-grading-service prediction-coordinator prediction-worker; do
  echo "Testing $service..."
  URL=$(gcloud run services describe $service --region=us-west2 --format='value(status.url)')
  STATUS=$(curl -s "$URL/health/deep" | jq -r '.status // "error"')
  echo "  Status: $STATUS"
done
```

### Dockerfile Validation

```bash
# Validate all services
for dir in predictions/worker predictions/coordinator data_processors/grading/nba; do
  echo "Validating $dir..."
  ./bin/validate-dockerfile-dependencies.sh "$dir"
done
```

### Check Deployment Drift

```bash
./bin/check-deployment-drift.sh --verbose
```

---

## Success Criteria

After completing this session, you should have:

- [ ] Dependency lock files generated for 5 services
- [ ] Dockerfiles updated to use lock files
- [ ] All services still build successfully
- [ ] Deep health checks still pass
- [ ] Drift monitoring tested end-to-end with Slack alert
- [ ] Documentation updated
- [ ] All changes committed and pushed

**Completion:** 9/9 tasks (100%)

---

## If You Run Into Issues

### Lock File Generation Fails

**Problem:** `pip freeze` produces huge file or fails

**Solution:** Use virtual environment with only service dependencies:
```bash
python -m venv temp_env
source temp_env/bin/activate
pip install -r requirements.txt
pip freeze > requirements-lock.txt
deactivate
rm -rf temp_env
```

### Docker Build Fails After Lock File

**Problem:** Lock file has conflicting versions

**Solution:** Regenerate lock file in clean environment (see above)

### Drift Monitoring Doesn't Alert

**Problem:** No Slack alert appears

**Solutions:**
1. Check function logs: `gcloud logging read 'resource.labels.service_name="deployment-drift-monitor"' --limit=20`
2. Verify secrets: `gcloud secrets list | grep slack`
3. Test webhook directly: `curl -X POST <webhook-url> -d '{"text": "test"}'`

---

## Time Estimates

| Task | Estimated Time |
|------|----------------|
| Generate lock files (5 services) | 20 min |
| Update Dockerfiles | 5 min |
| Test builds | 5 min |
| Test end-to-end prevention | 10 min |
| Update documentation | 5 min |
| **Total** | **45 min** |

---

## Optional Enhancements

If you have extra time, consider:

1. **Add deep health to analytics/precompute services**
   - Follow grading service pattern
   - 15-20 min per service

2. **Create pre-commit hook for Dockerfile validation**
   ```bash
   # .pre-commit-hooks/validate-dockerfiles.sh
   ./bin/validate-dockerfile-dependencies.sh <changed-services>
   ```

3. **Set up automated drift monitoring schedule**
   - Currently runs every 2 hours
   - Could add daily summary report
   - Could add auto-remediation

---

## Key Files

**From Session 132:**
- `bin/validate-dockerfile-dependencies.sh` (Dockerfile validator)
- `docs/09-handoff/2026-02-05-SESSION-132-PREVENTION-IMPROVEMENTS.md` (full session docs)

**To Create:**
- `*/requirements-lock.txt` (5 files - one per service)

**To Modify:**
- `*/Dockerfile` (5 files - update pip install command)

---

## Quick Start

```bash
# 1. Check current state
git status
./bin/check-deployment-drift.sh

# 2. Generate lock files
cd predictions/worker
pip freeze > requirements-lock.txt
cd ../coordinator
pip freeze > requirements-lock.txt
# ... repeat for other services

# 3. Update Dockerfiles
# Change all to use requirements-lock.txt

# 4. Test
./bin/validate-dockerfile-dependencies.sh predictions/worker
docker build -f predictions/worker/Dockerfile -t test .

# 5. Verify prevention system
# Run all testing commands from above

# 6. Commit
git add -A
git commit -m "feat: Add dependency lock files for deterministic builds"
git push origin main
```

---

## Expected Outcome

After this session:
- **100% task completion** (9/9)
- **Fully deterministic builds** (no more dependency resolution)
- **Verified end-to-end prevention** (all 6 layers tested)
- **Production-ready infrastructure** (catches bugs in seconds)

**This completes the prevention improvements project!** 🚀

---

## Reference

**Previous Sessions:**
- Session 129: Discovered grading service silent failure (39 hours down)
- Session 130: Still broken after fix (db-dtypes missing)
- Session 132: Implemented prevention infrastructure (this session)

**Documentation:**
- Prevention improvements: `docs/09-handoff/2026-02-05-SESSION-132-PREVENTION-IMPROVEMENTS.md`
- Health checks guide: `docs/05-development/health-checks-and-smoke-tests.md`
- Deployment guide: `docs/02-operations/deployment.md`

Good luck! This is the final piece to complete the prevention improvements. 🎉
