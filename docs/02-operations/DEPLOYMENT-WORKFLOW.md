# Deployment Workflow

Visual guide to the deployment process.

---

## Quick Deploy Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    START DEPLOYMENT                         │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  PRE-FLIGHT CHECKS                          │
│  • Authenticated with gcloud?                               │
│  • Correct project? (nba-props-platform)                    │
│  • Dockerfile exists?                                       │
│  • Git commit recorded?                                     │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
                        ┌────┴────┐
                        │  PASS?  │
                        └────┬────┘
                             │ Yes
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              CHOOSE DEPLOYMENT METHOD                       │
│                                                             │
│  Option 1: Quick Script                                    │
│  ./scripts/deploy/deploy-analytics.sh                      │
│                                                             │
│  Option 2: Full Script (with tests)                        │
│  ./bin/analytics/deploy/deploy_analytics_processors.sh     │
│                                                             │
│  Option 3: Manual                                           │
│  gcloud run deploy SERVICE --source=. --region=us-west2    │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  CLOUD BUILD PROCESS                        │
│  • Copy Dockerfile to root (if using --source)             │
│  • Build image in cloud                                     │
│  • Store in Artifact Registry                               │
│  • Tag with commit SHA                                      │
│  Duration: ~3-5 minutes                                     │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    CLOUD RUN DEPLOY                         │
│  • Create new revision                                      │
│  • Health check new revision                                │
│  • Route traffic to new revision                            │
│  • Scale up instances                                       │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
                        ┌────┴────┐
                        │SUCCESS? │
                        └────┬────┘
                             │ Yes
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  POST-DEPLOYMENT VERIFY                     │
│  • Check service status (green ✔?)                         │
│  • Test health endpoint                                     │
│  • Review logs for errors                                   │
│  • Verify commit SHA matches                                │
│  • Test functionality                                       │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   DEPLOYMENT COMPLETE                       │
│  • Document in deployment history                           │
│  • Notify team in Slack                                     │
│  • Monitor metrics for 24 hours                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Rollback Flow

```
┌─────────────────────────────────────────────────────────────┐
│               ISSUE DETECTED POST-DEPLOY                    │
│  • Service unhealthy                                        │
│  • Errors in logs                                           │
│  • Functionality broken                                     │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  DECIDE: ROLLBACK?                          │
│  • Can fix forward quickly? → Fix and redeploy              │
│  • Need time to investigate? → Rollback                     │
│  • Data loss risk? → ROLLBACK NOW                          │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼ Rollback
┌─────────────────────────────────────────────────────────────┐
│                  LIST REVISIONS                             │
│  gcloud run revisions list --service=SERVICE                │
│  --region=us-west2 --limit=5                                │
│                                                             │
│  Identify:                                                  │
│  • Current (broken) revision                                │
│  • Previous (working) revision                              │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              ROUTE TRAFFIC TO PREVIOUS                      │
│  gcloud run services update-traffic SERVICE                 │
│  --to-revisions=PREVIOUS_REVISION=100                       │
│  --region=us-west2                                          │
│                                                             │
│  Duration: ~30 seconds                                      │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   VERIFY ROLLBACK                           │
│  • Check service status                                     │
│  • Test health endpoint                                     │
│  • Verify logs are clean                                    │
│  • Test functionality                                       │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│               INVESTIGATE & FIX ISSUE                       │
│  • Review failed deployment logs                            │
│  • Identify root cause                                      │
│  • Fix code/config                                          │
│  • Test locally if possible                                 │
│  • Redeploy when ready                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Deployment Methods Comparison

```
┌───────────────────────────────────────────────────────────────────┐
│                    METHOD 1: SOURCE DEPLOY                        │
│                        (Recommended)                              │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Command:                                                         │
│  gcloud run deploy SERVICE --source=. --region=us-west2          │
│                                                                   │
│  Flow:                                                            │
│  Local Code → Cloud Build → Artifact Registry → Cloud Run       │
│                                                                   │
│  Pros:                                                            │
│  ✓ Simple one command                                            │
│  ✓ Automatic image building                                      │
│  ✓ Built-in caching                                              │
│  ✓ Registry handled automatically                                │
│                                                                   │
│  Cons:                                                            │
│  ✗ Longer deployment time (3-5 min)                              │
│  ✗ Less control over build                                       │
│  ✗ Can't test image locally first                                │
│                                                                   │
│  Use For:                                                         │
│  • All Phase 1-5 NBA processors                                  │
│  • Prediction coordinator                                        │
│  • Regular deployments                                           │
│  • When you trust the build process                              │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘


┌───────────────────────────────────────────────────────────────────┐
│                 METHOD 2: PRE-BUILT IMAGE                         │
│                     (Advanced)                                    │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Commands:                                                        │
│  1. docker build -f docker/SERVICE.Dockerfile -t IMAGE:TAG .     │
│  2. docker push us-west2-docker.pkg.dev/.../IMAGE:TAG            │
│  3. gcloud run deploy SERVICE --image=IMAGE_URL                  │
│                                                                   │
│  Flow:                                                            │
│  Local Code → Local Build → Artifact Registry → Cloud Run       │
│                                                                   │
│  Pros:                                                            │
│  ✓ Test image locally first                                      │
│  ✓ Faster subsequent deploys                                     │
│  ✓ More control over build                                       │
│  ✓ Can share images across services                              │
│                                                                   │
│  Cons:                                                            │
│  ✗ More complex workflow                                         │
│  ✗ Manual image management                                       │
│  ✗ Need Docker configured locally                                │
│  ✗ More steps = more places to fail                              │
│                                                                   │
│  Use For:                                                         │
│  • MLB services                                                  │
│  • Complex custom builds                                         │
│  • When source deploy fails                                      │
│  • When you need to test locally                                 │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

---

## Service Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│                  DEPLOYMENT ORDER                           │
│            (When deploying multiple services)               │
└─────────────────────────────────────────────────────────────┘

                    ┌──────────────────┐
                    │  Phase 1 Scrapers │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Phase 2 Raw Proc │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Phase 3 Analytics│
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │Phase 4 Precompute│
                    └────────┬─────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
                    ▼                 ▼
        ┌──────────────────┐  ┌──────────────────┐
        │Pred Coordinator  │  │ Prediction Worker│
        └──────────────────┘  └──────────────────┘
                    │                 │
                    └────────┬────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Phase 6 Grading │
                    └──────────────────┘

Note: Deploy in order shown for new features.
      For bug fixes, deploy only affected service.
```

---

## Container Registry Evolution

```
┌─────────────────────────────────────────────────────────────┐
│                    HISTORY                                  │
└─────────────────────────────────────────────────────────────┘

  OLD (Pre-2025)               NEW (Current)
  ──────────────               ─────────────

  gcr.io/                      us-west2-docker.pkg.dev/
  nba-props-platform/          nba-props-platform/
  ├── analytics                ├── cloud-run-source-deploy/
  ├── predictions              │   ├── nba-phase3-analytics...
  └── scrapers                 │   ├── prediction-coordinator
                               │   └── nba-phase1-scrapers...
                               └── nba-props/
                                   ├── mlb-analytics...
                                   └── mlb-precompute...

  ❌ Container Registry         ✅ Artifact Registry
  ❌ Global by default          ✅ Regional (us-west2)
  ❌ Being deprecated           ✅ Current standard
  ❌ --image flag               ✅ --source flag


┌─────────────────────────────────────────────────────────────┐
│                   MIGRATION IMPACT                          │
└─────────────────────────────────────────────────────────────┘

  Before:                      After:
  ───────                      ──────

  Manual push to gcr.io        Automatic build & push
  --image=gcr.io/...           --source=.
  Need Docker locally          Build happens in cloud
  Manage tags manually         Commit SHA tags automatic


┌─────────────────────────────────────────────────────────────┐
│                    WHY IT MATTERS                           │
└─────────────────────────────────────────────────────────────┘

  Most confusion in previous sessions came from:

  1. Trying to use gcr.io (old) when it's been migrated
  2. Not knowing about --source flag (new way)
  3. Thinking manual Docker build required (it's not)

  Solution: Use --source=. and forget about registry
```

---

## Troubleshooting Decision Tree

```
                    ┌──────────────────┐
                    │ Deployment Failed│
                    └────────┬─────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
    ┌──────────────────┐        ┌──────────────────┐
    │  Build Failed?   │        │  Deploy Failed?  │
    └────────┬─────────┘        └────────┬─────────┘
             │                            │
             │                            │
    ┌────────┴────────┐          ┌────────┴────────┐
    │                 │          │                 │
    ▼                 ▼          ▼                 ▼
┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐
│Build   │    │Docker  │    │Auth    │    │Service │
│timeout │    │errors  │    │failed  │    │config  │
└────┬───┘    └───┬────┘    └───┬────┘    └───┬────┘
     │            │              │              │
     ▼            ▼              ▼              ▼
Check logs    Fix Docker    Check auth    Update config
Stream build  Test local    Re-auth       Check limits
Cancel/retry  Fix file      Switch proj   Update env vars


                ┌──────────────────┐
                │ Service Unhealthy│
                └────────┬─────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
    ┌──────────┐              ┌──────────────┐
    │Yellow !  │              │ 404 Errors   │
    └────┬─────┘              └─────┬────────┘
         │                           │
         ▼                           ▼
  Check logs               Check Flask routes
  Check health             Check CMD in Docker
  Check resources          Test locally
  Wait 2-3 min             Check port (8080)


                ┌──────────────────┐
                │Runtime Errors    │
                └────────┬─────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
    ┌──────────┐              ┌──────────────┐
    │Import    │              │ Memory/CPU   │
    │errors    │              │ exceeded     │
    └────┬─────┘              └─────┬────────┘
         │                           │
         ▼                           ▼
  Check COPY               Increase limits
  Check PYTHONPATH         Check memory leaks
  Test imports             Optimize code
  Fix Dockerfile           Scale resources
```

---

## Resource Sizing Guide

```
┌─────────────────────────────────────────────────────────────┐
│              SERVICE RESOURCE REQUIREMENTS                  │
└─────────────────────────────────────────────────────────────┘

Service                Memory    CPU    Timeout   Concurrency
─────────────────────  ────────  ─────  ────────  ───────────
Phase 1 Scrapers       2 GiB     2      540s      1
Phase 2 Raw            4 GiB     2      3600s     1
Phase 3 Analytics      8 GiB     4      3600s     1  ← Memory intensive
Phase 4 Precompute     8 GiB     4      3600s     1  ← ML features
Phase 5 Coordinator    2 GiB     2      1800s     8  ← Multi-thread
Phase 5 Worker         4 GiB     2      1800s     1


┌─────────────────────────────────────────────────────────────┐
│                    WHY THESE SIZES?                         │
└─────────────────────────────────────────────────────────────┘

Phase 1 (Scrapers):
  • I/O bound, not CPU/memory intensive
  • Just fetching and parsing JSON
  • 2 GiB plenty for external API calls

Phase 2 (Raw Processing):
  • Data validation and cleaning
  • Moderate memory for JSON parsing
  • 4 GiB handles batch operations

Phase 3 (Analytics):
  • Large in-memory calculations
  • Aggregations across many games
  • 8 GiB needed for complex analytics

Phase 4 (Precompute):
  • ML feature generation
  • Large DataFrames in memory
  • 8 GiB for rolling windows

Phase 5 (Predictions):
  • Coordinator: Lightweight orchestration
  • Worker: Model inference + feature prep
  • Different concurrency needs


┌─────────────────────────────────────────────────────────────┐
│                 SCALING STRATEGY                            │
└─────────────────────────────────────────────────────────────┘

Service              Min    Max    Why
──────────────────   ───    ───    ───────────────────────────
All Processors       0      5-10   Scale to zero when idle
Coordinator          0      1      Single coordinator per batch
Workers              0      50     Parallel player processing

Cost Optimization:
• Scale to 0 when idle (save $$$)
• Use minimum CPU/memory that works
• Increase only if seeing issues
• Monitor actual usage vs limits
```

---

## Quick Commands Reference

```bash
# ──────────────────────────────────────────────────────────
# DEPLOYMENT
# ──────────────────────────────────────────────────────────

# Quick deploy (analytics)
./scripts/deploy/deploy-analytics.sh

# Quick deploy (predictions)
./scripts/deploy/deploy-predictions.sh prod

# Manual deploy
gcloud run deploy SERVICE --source=. --region=us-west2


# ──────────────────────────────────────────────────────────
# VERIFICATION
# ──────────────────────────────────────────────────────────

# Check service status
gcloud run services list --region=us-west2 | grep SERVICE

# Test health (requires auth)
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://SERVICE-URL/health"

# View logs
gcloud run services logs read SERVICE --region=us-west2 --limit=50


# ──────────────────────────────────────────────────────────
# ROLLBACK
# ──────────────────────────────────────────────────────────

# List revisions
gcloud run revisions list --service=SERVICE --region=us-west2 --limit=5

# Rollback
gcloud run services update-traffic SERVICE \
  --to-revisions=PREVIOUS_REVISION=100 \
  --region=us-west2


# ──────────────────────────────────────────────────────────
# TROUBLESHOOTING
# ──────────────────────────────────────────────────────────

# Check build logs
gcloud builds list --limit=5
gcloud builds log BUILD_ID

# Check for errors
gcloud run services logs read SERVICE \
  --region=us-west2 --limit=100 | grep -i error

# Describe service
gcloud run services describe SERVICE --region=us-west2
```

---

**Quick Reference Version:** 1.0
**Last Updated:** 2026-01-27
**See Also:** [DEPLOYMENT.md](./DEPLOYMENT.md), [DEPLOYMENT-QUICK-REFERENCE.md](./DEPLOYMENT-QUICK-REFERENCE.md)
