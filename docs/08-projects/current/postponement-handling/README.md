# Postponed Game Handling Project

**Started:** 2026-01-25
**Status:** In Progress
**Trigger:** GSW@MIN postponed due to Minneapolis shooting incident

---

## Overview

This project implements detection and handling of postponed/rescheduled games across NBA (and eventually MLB) pipelines.

## Problem Statement

On 2026-01-24, the GSW@MIN game was postponed ~2 hours before tip-off. Our system:
- Made 55 predictions for a game that didn't happen
- Didn't detect the postponement despite having news articles about it
- Had corrupted schedule data showing "Final" with NULL scores
- Had no mechanism to cascade updates when the game was rescheduled to Jan 25

## Documents

| Document | Description |
|----------|-------------|
| [POSTPONEMENT-HANDLING-DESIGN.md](./POSTPONEMENT-HANDLING-DESIGN.md) | Full technical design |
| [IMPLEMENTATION-LOG.md](./IMPLEMENTATION-LOG.md) | Implementation progress |
| [RUNBOOK.md](./RUNBOOK.md) | Operational procedures |

## Components Implemented

### Detection
- [x] Schedule anomaly detection (Final + NULL scores)
- [x] News article parsing for postponements
- [x] Cross-source validation
- [x] Same game_id on multiple dates detection

### Data Model
- [x] game_postponements tracking table
- [x] Prediction invalidation columns (`invalidation_reason`, `invalidated_at`)
- [x] Schedule status enhancement (Postponed status)

### Automation
- [x] Daily health check integration (local script)
- [x] **Production cloud function integration** (daily_health_summary)
- [x] Automated prediction invalidation (via `fix_postponed_game.py`)
- [x] Grading processor excludes invalidated predictions
- [ ] Cascade trigger when rescheduled game plays

### Alerting
- [x] Slack notification on postponement detection (`--slack` flag)
- [x] **Daily 7AM summary includes postponements** (via daily_health_summary)
- [x] Prediction counts shown in alerts

### Rate Limiting & Resilience
- [x] Retry logic in `force_predictions.sh` (exponential backoff)
- [x] Handles HTTP 429/503 from Cloud Run

### Code Quality
- [x] **Refactored to shared module** (`shared/utils/postponement_detector.py`)
- [x] **All anomaly types logged to BigQuery** (complete audit trail)

## Quick Links

- **Tracking Table:** `nba_orchestration.game_postponements`
- **Shared Module:** `shared/utils/postponement_detector.py`
- **Detection Script:** `bin/validation/detect_postponements.py`
- **Fix Script:** `bin/fixes/fix_postponed_game.py`
- **Cloud Function:** `orchestration/cloud_functions/daily_health_summary/main.py`

## Applicability

This system is designed to be sport-agnostic and will be extended to:
- [x] NBA
- [ ] MLB (future)
