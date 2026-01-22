# January 17-18, 2026 Debugging Archive

## Overview
This directory contains debugging artifacts and analysis from January 17-18, 2026, when the team was investigating model version discrepancies and Phase 3 failures.

## Status
**Period:** January 17-18, 2026
**Status:** ✅ ARCHIVED - Issues resolved
**Current Location:** Historical archive

## Contents

### Model Version Analysis (v1 vs v1.6)
Comparison of two prediction model versions:

- `v1_6_daily_volume.csv` - Daily prediction volume for v1.6
- `v1_vs_v16_agreement_20260117_092746.csv` - Agreement rate between versions
- `v1_vs_v16_by_recommendation_20260117_092746.csv` - Breakdown by recommendation type
- `v1_vs_v16_confidence_20260117_092746.csv` - Confidence score comparison
- `v1_vs_v16_overall_20260117_092746.csv` - Overall metrics
- `prediction_analysis_queries.sql` - SQL queries used for analysis

### Debugging Reports
- `phase3_root_cause_analysis_20260118_1528.txt` - Root cause analysis for Phase 3 failures
- `model_version_investigation_20260118_1532.txt` - Investigation into model version issues
- `7pm_verification_bug_report_20260118_1632.txt` - Bug report from evening verification

### Verification Results
- `verification_results_20260118_1411.txt` - Afternoon verification run
- `verification_results_20260118_1510.txt` - Follow-up verification

## Key Findings

**Model Version Issues:**
- v1.6 showed different prediction patterns than v1
- Agreement rate analysis revealed systematic differences
- Led to model deployment rollback and fixes

**Phase 3 Failures:**
- Root cause identified as stale data dependencies
- Fixed in subsequent deployments
- Validation checks enhanced

## Resolution
All issues from this period were resolved by January 20, 2026. This archive is maintained for historical reference and pattern analysis.

## Related Projects
- **Model Deployment:** See `/docs/08-projects/current/ml-model-v8-deployment/`
- **Phase 3 Fixes:** See `/docs/08-projects/current/robustness-improvements/`

---
**Archived:** January 22, 2026
**Retention:** Keep indefinitely for historical analysis
