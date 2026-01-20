# 🏀 NBA Props Platform

**Production-ready NBA player props prediction and grading system**

[![Status](https://img.shields.io/badge/status-production-success)](./docs/STATUS-DASHBOARD.md)
[![Python](https://img.shields.io/badge/python-3.11-blue)](https://www.python.org/)
[![GCP](https://img.shields.io/badge/cloud-google%20cloud-4285F4)](https://cloud.google.com/)
[![License](https://img.shields.io/badge/license-proprietary-red)]()

---

## 🎯 What Is This?

A comprehensive data pipeline that:
- **Scrapes** NBA game data, player stats, and betting lines from multiple sources
- **Processes** raw data into analytics features (1000+ metrics per player/game)
- **Predicts** player prop outcomes using 7 ML systems (including ensemble models)
- **Grades** predictions against actual outcomes with 70-90% coverage
- **Monitors** system health with Grafana dashboards and automated alerts

**Current Status**: All 6 phases operational, 614 predictions generated daily across 7 systems

---

## 📚 Documentation

### 🚀 Quick Start

| I need to... | Go here |
|--------------|---------|
| **Get oriented** | [`docs/00-start-here/README.md`](./docs/00-start-here/README.md) |
| **Check system health** | [`docs/STATUS-DASHBOARD.md`](./docs/STATUS-DASHBOARD.md) |
| **Daily operations** | [`docs/00-start-here/DAILY-SESSION-START.md`](./docs/00-start-here/DAILY-SESSION-START.md) |
| **Recent changes** | [`docs/09-handoff/`](./docs/09-handoff/) (latest session handoffs) |
| **System architecture** | [`docs/01-architecture/quick-reference.md`](./docs/01-architecture/quick-reference.md) |
| **Troubleshooting** | [`docs/02-operations/troubleshooting-matrix.md`](./docs/02-operations/troubleshooting-matrix.md) |

### 📖 Full Documentation

**All documentation lives in [`docs/`](./docs/):**

```
docs/
├── 00-start-here/          ⭐ Start here for navigation
├── 01-architecture/        System design & decisions
├── 02-operations/          Daily ops, troubleshooting
├── 03-phases/              6 pipeline phases (orchestration → publishing)
├── 04-deployment/          Deployment guides & status
├── 05-development/         How to build (patterns, testing)
├── 06-reference/           Quick lookups (processor cards, data flow)
├── 07-monitoring/          Grafana, alerts, observability
├── 08-projects/            Active work & completed projects
└── 09-handoff/             Session handoffs & status updates
```

**Documentation Index**: [`docs/00-PROJECT-DOCUMENTATION-INDEX.md`](./docs/00-PROJECT-DOCUMENTATION-INDEX.md)

---

## 🏗️ System Architecture

### Pipeline Overview

```
Phase 1: Orchestration  →  Daily scheduling & coordination
Phase 2: Raw Data       →  Scrape from NBA.com, BallDontLie, OddsAPI
Phase 3: Analytics      →  1000+ features per player/game
Phase 4: Precompute     →  ML feature store, zone analysis
Phase 5: Predictions    →  7 systems (XGBoost, CatBoost, Ensembles)
Phase 6: Publishing     →  API endpoints, dashboards
```

**Tech Stack:**
- **Compute**: Google Cloud Run, Cloud Functions, Cloud Scheduler
- **Storage**: BigQuery (10+ datasets), Cloud Storage
- **Orchestration**: Firestore-based distributed locks
- **ML**: XGBoost, CatBoost, custom ensemble models
- **Monitoring**: Cloud Monitoring, Grafana, custom alerting

---

## 📊 System Status

**Last Updated**: 2026-01-19 (Session 112)

### Core Services

| Service | Status | Last Deploy | Notes |
|---------|--------|-------------|-------|
| **Prediction Worker** | ✅ Operational | 2026-01-19 07:55 UTC | All 7 systems working |
| **Prediction Coordinator** | ✅ Operational | 2026-01-19 06:07 UTC | Fixed deployment script |
| **Analytics Processors** | ✅ Operational | 2026-01-19 06:23 UTC | Session 107 metrics deployed |
| **Grading Function** | ✅ Operational | Phase 5b | 70-90% coverage |
| **Cloud Schedulers** | ✅ Enabled | Multiple | Daily triggers working |

### Prediction Systems

| System | Status | Performance | Volume (Jan 19) |
|--------|--------|-------------|-----------------|
| Moving Average | ✅ | Baseline | 91 predictions |
| Zone Matchup V1 | ✅ | Matchup analysis | 91 predictions |
| Similarity Balanced V1 | ✅ | Historical | 69 predictions |
| XGBoost V1 | ✅ | ML baseline | 91 predictions |
| CatBoost V8 | ✅ | **3.40 MAE** (champion) | 91 predictions |
| Ensemble V1 | ✅ | Weighted | 91 predictions |
| **Ensemble V1.1** | ✅ | **Performance-based (NEW)** | **91 predictions** |

**Total**: 614 predictions per day across all systems

**Recent Fix** (Session 112): Fixed 37-hour outage caused by missing `google-cloud-firestore` dependency

---

## 🚨 Recent Changes

### Week 0 Security (2026-01-19) 🔒
- ✅ **Fixed 13 critical security vulnerabilities** (97+ individual issues)
- ✅ **SQL injection**: 47 queries converted to parameterized format
- ✅ **Authentication**: Added API key validation to analytics service
- ✅ **Removed RCE risks**: Fixed eval() and pickle deserialization
- ✅ **Input validation**: New validation library for all user inputs
- 📝 [Security log](./docs/08-projects/current/daily-orchestration-improvements/WEEK-0-SECURITY-LOG.md)

### Session 112 (2026-01-19) 🎉
- ✅ **Fixed prediction pipeline outage** (37+ hours down)
- ✅ **Root cause**: Missing `google-cloud-firestore==2.14.0` dependency
- ✅ **Result**: All 7 systems operational, 614 predictions generated
- 📝 [Full handoff](./docs/09-handoff/SESSION-112-PREDICTION-WORKER-FIRESTORE-FIX.md)

### Session 111 (2026-01-19)
- ✅ Deployed 7 Session 107 metrics (variance + star tracking)
- ✅ Fixed analytics processor schema evolution
- ✅ Investigated prediction failures (fixed in Session 112)

### Session 110 (2026-01-18)
- ✅ Deployed Ensemble V1.1 with performance-based weights
- ✅ Added CatBoost V8 to ensemble (45% weight)
- ✅ Expected MAE improvement: 5.41 → 4.9-5.1 (6-9% better)

See full timeline: [`docs/STATUS-DASHBOARD.md`](./docs/STATUS-DASHBOARD.md)

---

## 🛠️ Development

### Prerequisites

- Python 3.11+
- Google Cloud SDK
- BigQuery access
- Service account with appropriate permissions

### Environment Variables

**Required (All Services):**
- `GCP_PROJECT_ID` - GCP project identifier (e.g., `nba-props-platform`)
- `ENVIRONMENT` - Environment name (`dev`, `staging`, `prod`)

**Security (Week 0 - Required as of 2026-01-19):**
- `VALID_API_KEYS` - Comma-separated API keys for analytics service authentication
- `BETTINGPROS_API_KEY` - BettingPros API key (moved from hardcoded)
- `SENTRY_DSN` - Sentry monitoring DSN (moved from hardcoded)

**Optional:**
- `SLACK_WEBHOOK_URL` - Slack notifications
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to service account key file

See [deployment guide](./docs/04-deployment/) for configuration details.

### Quick Commands

```bash
# Check system health
./monitoring/check-system-health.sh

# Deploy prediction worker
bash bin/predictions/deploy/deploy_prediction_worker.sh

# Deploy analytics processors
bash bin/analytics/deploy/deploy_analytics_processors.sh

# Trigger manual predictions
curl -X POST "https://prediction-coordinator-[PROJECT].run.app/start" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"force": true, "game_date": "2026-01-19"}'
```

### Project Structure

```
├── bin/                    # Deployment scripts
├── data_processors/        # Analytics & precompute processors
├── predictions/            # ML prediction systems
│   ├── coordinator/        # Batch coordinator
│   └── worker/             # Prediction worker (7 systems)
├── scrapers/               # Raw data scrapers
├── shared/                 # Shared utilities
├── monitoring/             # Health checks & alerts
├── schemas/                # BigQuery schemas
└── docs/                   # Documentation (main resource)
```

---

## 📞 Support & Contact

### For Issues

1. **Check recent handoffs**: [`docs/09-handoff/`](./docs/09-handoff/)
2. **Review troubleshooting guide**: [`docs/02-operations/troubleshooting-matrix.md`](./docs/02-operations/troubleshooting-matrix.md)
3. **Check system status**: [`docs/STATUS-DASHBOARD.md`](./docs/STATUS-DASHBOARD.md)

### For AI Sessions

**Starting a new Claude Code session?**
1. Read [`docs/09-handoff/`](./docs/09-handoff/) for latest status
2. Review [`docs/00-start-here/DAILY-SESSION-START.md`](./docs/00-start-here/DAILY-SESSION-START.md)
3. Check [`docs/STATUS-DASHBOARD.md`](./docs/STATUS-DASHBOARD.md) for current health

---

## 📊 Key Metrics

- **Prediction Coverage**: 150+ players per day
- **Grading Coverage**: 70-90%
- **Best Model**: CatBoost V8 (3.40 MAE)
- **Systems**: 7 concurrent prediction systems
- **Daily Volume**: 614 predictions
- **Uptime**: 99%+ (after Session 112 fix)

---

## 📄 License

Proprietary - All Rights Reserved

---

**Project Contact**: NBA Props Platform Team
**GCP Project**: `nba-props-platform`
**Region**: `us-west2` (Los Angeles)
**Documentation**: [`docs/`](./docs/)
