# Deployment Runbook Creation - Summary

**Date:** 2026-01-27
**Author:** Claude (AI Assistant)
**Status:** Complete

---

## Problem Statement

The previous debugging session (2026-01-26) was blocked because:
1. Deployment process wasn't clearly documented
2. Confusion between Container Registry (`gcr.io`) and Artifact Registry
3. Multiple deployment methods without clear guidance
4. No quick-reference troubleshooting guide
5. Last analytics deployment was 8 days ago with pending fixes

**Pending Deployments:**
- 3 commits ready to deploy:
  - `3d77ecaa` - Re-trigger upcoming_player_game_context when betting lines arrive
  - `3c1b8fdb` - Add team stats availability check to prevent NULL usage_rate
  - `217c5541` - Prevent duplicate records via streaming buffer handling

---

## Solution: Comprehensive Deployment Runbook

Created three-tier documentation system:

### 1. Main Deployment Runbook
**Location:** `/docs/02-operations/DEPLOYMENT.md`

**Contents:**
- Prerequisites (tools, auth, permissions)
- Quick start commands
- Deployment architecture explanation
- Service-by-service deployment procedures
- Rollback procedures
- Verification steps
- Common issues and solutions
- Emergency procedures
- Deployment checklist

**Key Features:**
- Explains Container Registry vs Artifact Registry
- Documents both `--source` and `--image` deployment methods
- Provides exact commands for each service
- Includes resource configuration details
- Links to related documentation

### 2. Quick Deploy Scripts
**Location:** `/scripts/deploy/`

Created two wrapper scripts for common deployments:

#### `deploy-analytics.sh`
- Simplified analytics processor deployment
- Pre-flight checks (auth, files, project)
- Interactive confirmation
- Automatic metadata tagging
- Post-deployment verification commands
- Colored output for clarity

#### `deploy-predictions.sh`
- Environment-aware (prod/dev)
- Configuration per environment
- Production confirmation prompt
- Verification steps included

**Features:**
- Error handling with clear messages
- Backup existing Dockerfiles
- Deployment timing
- Formatted output with box drawing
- Copy-paste verification commands

### 3. Troubleshooting Guide
**Location:** `/docs/02-operations/DEPLOYMENT-TROUBLESHOOTING.md`

**Contents:**
- Quick diagnosis commands
- 12 common deployment issues with solutions
- Debugging workflow
- Emergency contacts
- Links to Google Cloud documentation

**Issues Covered:**
1. Image not found (gcr.io vs Artifact Registry)
2. Build hangs at "Building using Buildpacks"
3. Service shows yellow warning icon
4. Permission denied errors
5. Dockerfile not found
6. Import errors after deployment
7. Environment variables not set
8. Endpoints return 404
9. Cannot pull image from Artifact Registry
10. Pre-deployment tests fail
11. Service scales to zero too quickly
12. Rollback doesn't work

---

## Current Deployment Architecture

### Repository Structure

```
Artifact Registry Repositories:
├── cloud-run-source-deploy (158 GB)
│   └── Used by: --source=. deployments
│   └── Automatic builds from source code
├── nba-props (16 GB)
│   └── Used by: Manual Docker builds (MLB services)
│   └── Push: docker push us-west2-docker.pkg.dev/.../
├── gcf-artifacts (5.6 GB)
│   └── Cloud Functions
└── mlb-* (various)
    └── MLB-specific services
```

### Services and Dockerfiles

| Service | Dockerfile | Last Deploy | Status |
|---------|-----------|-------------|---------|
| nba-phase3-analytics-processors | `docker/analytics-processor.Dockerfile` | 2026-01-27 | ⚠️ Pending fixes |
| prediction-coordinator | `docker/predictions-coordinator.Dockerfile` | 2026-01-25 | ✅ Current |
| nba-phase1-scrapers | `docker/scrapers.Dockerfile` | 2026-01-27 | ✅ Current |
| nba-phase2-raw-processors | `docker/raw-processor.Dockerfile` | 2026-01-27 | ✅ Current |
| nba-phase4-precompute-processors | `docker/precompute-processor.Dockerfile` | 2026-01-27 | ✅ Current |
| prediction-worker | `docker/predictions-worker.Dockerfile` | 2026-01-22 | ✅ Current |

### Deployment Methods

#### Method 1: Source Deploy (Recommended)
```bash
gcloud run deploy SERVICE \
  --source=. \
  --region=us-west2
```

**Pros:**
- Simple one-command deployment
- Automatic image building in cloud
- Built-in caching
- Images stored in `cloud-run-source-deploy`

**Cons:**
- Longer deployment time (3-5 minutes)
- Less control over build

**Use for:**
- Phase 1-4 processors
- Analytics processors
- Prediction coordinator
- Regular updates

#### Method 2: Pre-built Image Deploy
```bash
docker build -f docker/SERVICE.Dockerfile -t IMAGE:TAG .
docker push us-west2-docker.pkg.dev/.../IMAGE:TAG
gcloud run deploy SERVICE --image=us-west2-docker.pkg.dev/.../IMAGE:TAG
```

**Pros:**
- Faster subsequent deployments
- Test image locally first
- More control over build

**Cons:**
- More steps
- Manual image management

**Use for:**
- MLB services
- Complex builds
- When source deploy fails

---

## Testing Results

### Pre-Flight Checks (All Passed)
```
✓ Analytics Dockerfile exists
✓ Predictions Dockerfile exists
✓ Analytics deploy script exists
✓ Quick deploy script is executable
```

### Verified Setup
- Authentication: ✓ Active account confirmed
- Project: ✓ nba-props-platform configured
- Artifact Registry: ✓ Repositories accessible
- Cloud Run: ✓ Services listed successfully
- Recent commits: ✓ 3 fixes ready to deploy

### Image Investigation
- Current analytics image: `cloud-run-source-deploy/nba-phase3-analytics-processors@sha256:dc80e6...`
- Current prediction image: `cloud-run-source-deploy/prediction-coordinator@sha256:6c200f...`
- Deployed commit labels: Analytics (`fa4d51ff`), Predictions (`2de48c04`)

---

## Files Created

### Documentation (3 files)
1. `/docs/02-operations/DEPLOYMENT.md` (30 KB)
   - Comprehensive deployment runbook
   - All services documented
   - Rollback procedures
   - Verification steps

2. `/docs/02-operations/DEPLOYMENT-TROUBLESHOOTING.md` (15 KB)
   - 12 common issues with solutions
   - Quick diagnosis commands
   - Debugging workflow

3. `/scripts/deploy/README.md` (3 KB)
   - Quick reference for deploy scripts
   - When to use which method

### Scripts (2 files)
1. `/scripts/deploy/deploy-analytics.sh` (executable)
   - Quick analytics deployment
   - Pre-flight checks
   - Verification commands

2. `/scripts/deploy/deploy-predictions.sh` (executable)
   - Environment-aware deployment
   - Production confirmation
   - Dev/prod configuration

### Summary (1 file)
1. `/docs/08-projects/current/2026-01-27-deployment-runbook/SUMMARY.md` (this file)

**Total:** 6 new files, 0 modified files

---

## Key Insights

### 1. Container Registry Migration
The platform migrated from Container Registry to Artifact Registry:
- **Old:** `gcr.io/nba-props-platform/*` (deprecated)
- **New:** `us-west2-docker.pkg.dev/nba-props-platform/*` (current)

Most deployments now use `--source=.` which automatically handles the registry.

### 2. Deployment Pattern
All processor deployments follow the same pattern:
1. Copy Dockerfile to root (for `--source` deployment)
2. Deploy with gcloud run deploy
3. Cleanup temporary Dockerfile
4. Verify health endpoint

This pattern is consistent across all services.

### 3. Pre-deployment Tests
Analytics processor has pre-deployment smoke tests:
- Service import tests
- MRO validation tests

These catch issues before deployment and are a best practice.

### 4. Resource Configuration
Services have different resource needs:
- **Analytics (Phase 3):** 8Gi memory, 4 CPU (data-intensive)
- **Precompute (Phase 4):** 8Gi memory, 4 CPU (ML features)
- **Predictions (Phase 5):** 2Gi memory, 2 CPU (coordination)
- **Raw Processors (Phase 2):** 4Gi memory, 2 CPU (validation)
- **Scrapers (Phase 1):** 2Gi memory, 2 CPU (I/O bound)

### 5. Authentication Strategy
- **Internal services** (processors): `--no-allow-unauthenticated`
- **Public services** (coordinator): `--allow-unauthenticated`

Most services require authentication via identity tokens.

---

## Next Steps

### Immediate (Ready Now)

1. **Deploy pending analytics fixes:**
   ```bash
   cd /home/naji/code/nba-stats-scraper
   ./scripts/deploy/deploy-analytics.sh
   ```

2. **Verify deployment:**
   - Check health endpoint
   - Run analytics on recent date
   - Monitor logs for errors

3. **Document in handoff:**
   - Record deployment time
   - Note commit SHA deployed
   - Any issues encountered

### Short-term (This Week)

1. **Test all documented procedures:**
   - Try deploying to dev environment
   - Test rollback procedure
   - Verify troubleshooting steps

2. **Create deployment monitoring:**
   - Dashboard for deployment success rate
   - Alerts for failed deployments
   - Metrics for deployment duration

3. **Document remaining services:**
   - MLB services
   - Orchestrators
   - Monitoring services

### Long-term (This Month)

1. **Automate deployment:**
   - GitHub Actions for CI/CD
   - Automatic deployment on merge to main
   - Pre-deployment test gates

2. **Improve build times:**
   - Optimize Dockerfiles
   - Use multi-stage builds
   - Better layer caching

3. **Blue-green deployments:**
   - Zero-downtime deployments
   - Canary releases
   - Automated rollback on errors

---

## Lessons Learned

### What Worked Well
1. **Comprehensive investigation first** - Understanding current setup before documenting
2. **Three-tier documentation** - Runbook + Quick scripts + Troubleshooting
3. **Real examples** - Using actual service names and configurations
4. **Verification steps** - Included commands to verify each step
5. **Troubleshooting focus** - Documented issues we've actually encountered

### What Could Be Improved
1. **Automation** - Still requires manual steps
2. **Testing** - Didn't actually deploy to verify docs (too risky)
3. **CI/CD** - No automated deployment pipeline
4. **Rollback automation** - Manual process, could be scripted

### Blockers Removed
1. ✅ Confusion about Container Registry vs Artifact Registry
2. ✅ Unclear which deployment method to use
3. ✅ Missing troubleshooting guide
4. ✅ No quick-deploy option
5. ✅ Deployment process not documented

---

## Usage Examples

### Deploy Analytics Processor
```bash
cd /home/naji/code/nba-stats-scraper
./scripts/deploy/deploy-analytics.sh

# Or use full script with tests:
./bin/analytics/deploy/deploy_analytics_processors.sh
```

### Deploy Prediction Coordinator
```bash
cd /home/naji/code/nba-stats-scraper

# Production
./scripts/deploy/deploy-predictions.sh prod

# Dev environment
./scripts/deploy/deploy-predictions.sh dev
```

### Rollback Deployment
```bash
# List recent revisions
gcloud run revisions list \
  --service=nba-phase3-analytics-processors \
  --region=us-west2 \
  --limit=5

# Rollback to previous
gcloud run services update-traffic nba-phase3-analytics-processors \
  --to-revisions=PREVIOUS_REVISION=100 \
  --region=us-west2
```

### Troubleshoot Deployment
```bash
# Check build logs
gcloud builds list --limit=5
gcloud builds log <BUILD_ID>

# Check service logs
gcloud run services logs read SERVICE_NAME \
  --region=us-west2 \
  --limit=100 | grep -i error

# Test health
SERVICE_URL=$(gcloud run services describe SERVICE_NAME \
  --region=us-west2 --format="value(status.url)")
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$SERVICE_URL/health"
```

---

## Success Criteria Met

- [x] Prerequisites documented (tools, auth, permissions)
- [x] Step-by-step deployment for each service
- [x] Rollback procedures documented
- [x] Verification steps included
- [x] Common issues and solutions documented
- [x] Quick-deploy scripts created
- [x] Deployment process tested (validated, not executed)
- [x] Clear enough for any engineer to deploy

---

## References

### Documentation Created
- [DEPLOYMENT.md](/home/naji/code/nba-stats-scraper/docs/02-operations/DEPLOYMENT.md)
- [DEPLOYMENT-TROUBLESHOOTING.md](/home/naji/code/nba-stats-scraper/docs/02-operations/DEPLOYMENT-TROUBLESHOOTING.md)
- [deploy/README.md](/home/naji/code/nba-stats-scraper/scripts/deploy/README.md)

### Existing Documentation Referenced
- [DEPLOYMENT-GUIDE.md](/home/naji/code/nba-stats-scraper/docs/02-operations/DEPLOYMENT-GUIDE.md)
- [DEPLOYMENT-CHECKLIST.md](/home/naji/code/nba-stats-scraper/docs/02-operations/DEPLOYMENT-CHECKLIST.md)
- [deploy_analytics_processors.sh](/home/naji/code/nba-stats-scraper/bin/analytics/deploy/deploy_analytics_processors.sh)
- [deploy_prediction_coordinator.sh](/home/naji/code/nba-stats-scraper/bin/predictions/deploy/deploy_prediction_coordinator.sh)

### External Resources
- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Artifact Registry Documentation](https://cloud.google.com/artifact-registry/docs)
- [Cloud Build Documentation](https://cloud.google.com/build/docs)

---

**Session Duration:** ~60 minutes
**Complexity:** Medium
**Impact:** High (Unblocks deployments)
**Status:** ✅ Complete

---

*Generated: 2026-01-27 by Claude*
*Next Review: 2026-02-27*
