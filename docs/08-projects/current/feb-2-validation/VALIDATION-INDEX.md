# Validation Index - Feb 2, 2026

Quick reference guide to all validation documents and findings.

---

## 📋 Main Documents

### 1. [MASTER-SUMMARY.md](./MASTER-SUMMARY.md) - **START HERE**
**Quick overview of all validation findings**
- Issue priority matrix (P1 Critical → P3 Low)
- Recommended action plan with commands
- Data quality assessment (Grade: B+)
- Next steps and follow-up questions

### 2. [VALIDATION-ISSUES-2026-02-02.md](../../VALIDATION-ISSUES-2026-02-02.md)
**Comprehensive validation from /validate-daily**
- Full pipeline health check
- Infrastructure issues (deployment drift, edge filter)
- Model performance analysis
- Investigation commands for each issue

### 3. [SPOT-CHECK-FINDINGS.md](./SPOT-CHECK-FINDINGS.md)
**Data quality validation from spot checks**
- 20-sample accuracy test (100% pass)
- Player name normalization issues
- Usage rate anomalies
- Feature store coverage analysis

---

## 🔴 Critical Issues (2)

| # | Issue | Severity | Status | Doc Reference |
|---|-------|----------|--------|---------------|
| 1 | Edge filter not working - 54 low-edge predictions | P1 | 🔴 OPEN | VALIDATION-ISSUES §2 |
| 2 | Deployment drift - 3 services stale | P1 | 🔴 OPEN | VALIDATION-ISSUES §1 |

**Action Required:** Both need immediate investigation (30-60 min)

---

## 🟡 Warnings (4)

| # | Issue | Severity | Status | Doc Reference |
|---|-------|----------|--------|---------------|
| 3 | Phase 3 incomplete (4/5 processors) | P2 | 🟡 OPEN | VALIDATION-ISSUES §3 |
| 4 | New model grading at 46.1% | P2 | 🟡 OPEN | VALIDATION-ISSUES §4 |
| 5 | Vegas line coverage at 27.4% | P2 | 🟡 OPEN | SPOT-CHECK §6 |
| 6 | Player name normalization (8 issues) | P2 | 🟡 OPEN | SPOT-CHECK §5 |

**Action Required:** Investigate within 24 hours (2-4 hours total)

---

## ✅ Passing Checks (7)

| Check | Result | Doc Reference |
|-------|--------|---------------|
| Spot check accuracy | 100% (20 samples) | SPOT-CHECK §1 |
| Minutes coverage (active players) | 100% | VALIDATION-ISSUES §9 |
| BDB coverage | 100% (10/10 games) | VALIDATION-ISSUES §7 |
| Partial game detection | 0 issues | SPOT-CHECK §4 |
| Heartbeat health | 30 docs, 0 bad format | VALIDATION-ISSUES §8 |
| Player coverage | 100% (name normalization issues only) | SPOT-CHECK §5 |
| Data corruption | None detected | SPOT-CHECK §1 |

---

## 📊 Log Files

| File | Size | Purpose | Issues Found |
|------|------|---------|--------------|
| `spot-check-20-samples.log` | ~8KB | 20-sample validation | 0 failures |
| `usage-rate-anomalies.txt` | ~300B | Usage >50% check | 3 suspicious |
| `partial-games-check.txt` | ~50B | Incomplete games | 0 issues |
| `missing-analytics-players.txt` | ~1KB | Cross-source coverage | 8 name issues |
| `missing-player-investigation.txt` | ~2KB | Deep dive on 8 players | All found |
| `feature-store-vegas-coverage.txt` | ~200B | Vegas line coverage | 27.4% |
| `golden-dataset-verification.log` | ~500B | Golden dataset check | Table not found |

---

## 🎯 Quick Actions

### If you have 5 minutes:
1. Read [MASTER-SUMMARY.md](./MASTER-SUMMARY.md) Quick Summary section
2. Review Issue Priority Matrix
3. Note the 2 P1 CRITICAL issues

### If you have 30 minutes:
1. Run the "Step 1: Immediate" commands from MASTER-SUMMARY
2. Determine if edge filter needs redeployment
3. Check if deployment drift affects yesterday's data

### If you have 2 hours:
1. Complete Step 1 (Immediate actions)
2. Run Step 2 (High Priority actions)
3. Investigate Phase 3 missing processor
4. Monitor new model grading progress

---

## 🔍 Key Metrics Summary

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Spot check pass rate | 100% | ≥95% | ✅ PASS |
| Minutes coverage (active) | 100% | ≥90% | ✅ PASS |
| BDB coverage | 100% | ≥90% | ✅ PASS |
| Vegas line coverage | 27.4% | ≥80% | ⚠️ WARN |
| Phase 3 completion | 4/5 | 5/5 | ⚠️ WARN |
| Low-edge predictions | 54 | 0 | 🔴 CRITICAL |
| Deployment drift | 3 services | 0 | 🔴 CRITICAL |
| Usage rate anomalies | 3 | 0 | ⚠️ WARN |
| Model grading | 46.1% | ≥80% | ⚠️ WARN |
| catboost_v9 hit rate (week) | 69.1% | ≥55% | ✅ PASS |

---

## 📝 Investigation Commands

### Edge Filter Investigation
```bash
# Check env var
gcloud run services describe prediction-coordinator \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env[?(@.name=='MIN_EDGE_THRESHOLD')].value)"

# Check when low-edge predictions created
bq query --use_legacy_sql=false "
SELECT MIN(created_at) as first, MAX(created_at) as last
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-02'
  AND line_source != 'NO_PROP_LINE'
  AND ABS(predicted_points - current_points_line) < 3"
```

### Deployment Drift Investigation
```bash
# Check what changed in stale services
git show 2993e9fd --stat | grep -E "(phase3|phase4|coordinator)"

# Deploy if needed
./bin/deploy-service.sh prediction-coordinator
./bin/deploy-service.sh nba-phase3-analytics-processors
./bin/deploy-service.sh nba-phase4-precompute-processors
```

### Phase 3 Investigation
```bash
# Check missing processor logs
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=50 | grep "upcoming_team_game_context"
```

---

## 📅 Timeline

| Time | Event | Status |
|------|-------|--------|
| 2026-02-01 | Games played (10 games) | ✅ Complete |
| 2026-02-02 06:00 | Scrapers run (overnight) | ✅ Complete |
| 2026-02-02 07:00 | Phase 3 analytics (4/5) | ⚠️ Incomplete |
| 2026-02-02 18:51 | Coordinator deployed | ⏰ Before commit |
| 2026-02-02 19:26 | Phase 3 deployed | ⏰ Before commit |
| 2026-02-02 19:28 | Phase 4 deployed | ⏰ Before commit |
| 2026-02-02 19:36 | Commit 2993e9fd (Phase 6) | 🔴 Not deployed |
| 2026-02-02 21:38 | Low-edge predictions created | 🔴 Filter failed |
| 2026-02-02 21:43 | Validation started | ✅ Complete |
| 2026-02-02 22:20 | Validation finished | ✅ Complete |

---

## 🔗 Related Documents

- [Session 81 - Edge Filter Implementation](../../EDGE-FILTER-SESSION-81.md) *(if exists)*
- [Session 77 - Vegas Line Monitoring](../../VEGAS-LINE-SESSION-77.md) *(if exists)*
- [Session 62 - Feature Store Fix](../../FEATURE-STORE-SESSION-62.md) *(if exists)*
- [Session 87 - Player Resolution](../../PLAYER-RESOLUTION-SESSION-87.md) *(if exists)*

---

**Last Updated:** 2026-02-02 22:25 PST
**Next Validation:** 2026-02-03 morning (verify edge filter fix)
