# Validation Framework Documentation

**Purpose**: Comprehensive documentation for the NBA Stats Scraper validation framework
**Audience**: Developers, operators, and future maintainers
**Last Updated**: January 4, 2026

---

## 📁 Documentation Index

### Core Documentation
1. **[VALIDATION-GUIDE.md](./VALIDATION-GUIDE.md)** - User guide for running validations
2. **[ARCHITECTURE.md](./ARCHITECTURE.md)** - System architecture and design
3. **[BACKFILL-VALIDATION.md](./BACKFILL-VALIDATION.md)** - Backfill-specific validation procedures
4. **[FEATURE-COVERAGE.md](./FEATURE-COVERAGE.md)** - ML feature coverage requirements
5. **[QUICK-REFERENCE.md](./QUICK-REFERENCE.md)** - Quick command reference

### Advanced Topics
6. **[REGRESSION-DETECTION.md](./REGRESSION-DETECTION.md)** - Detecting data quality degradation
7. **[BOOTSTRAP-PERIODS.md](./BOOTSTRAP-PERIODS.md)** - Understanding bootstrap skips
8. **[FALLBACK-CHAINS.md](./FALLBACK-CHAINS.md)** - Fallback source management
9. **[TROUBLESHOOTING.md](./TROUBLESHOOTING.md)** - Common issues and solutions

### Operations
10. **[DAILY-VALIDATION.md](./DAILY-VALIDATION.md)** - Daily validation workflows
11. **[MONITORING.md](./MONITORING.md)** - Real-time monitoring setup
12. **[ALERTS.md](./ALERTS.md)** - Alert configuration and response

---

## 🚀 Quick Start

### For Backfill Validation

```bash
# 1. Check backfill completion
ps aux | grep backfill | grep -v grep

# 2. Run Phase 2 validation (player_game_summary)
./scripts/validation/validate_player_summary.sh \
  --start-date 2024-05-01 \
  --end-date 2026-01-02

# 3. Check results
echo $?  # 0 = PASS, 1 = FAIL
```

See: [BACKFILL-VALIDATION.md](./BACKFILL-VALIDATION.md)

### For Daily Validation

```bash
# Run daily health check
./scripts/monitoring/weekly_pipeline_health.sh
```

See: [DAILY-VALIDATION.md](./DAILY-VALIDATION.md)

### For ML Training Validation

```python
from shared.validation.validators.feature_validator import check_ml_readiness

result = check_ml_readiness(
    training_start='2021-10-01',
    training_end='2024-05-01'
)

if result.ready:
    print("✅ Ready for ML training")
```

See: [FEATURE-COVERAGE.md](./FEATURE-COVERAGE.md)

---

## 🎯 What Gets Validated

### Phase 1 (GCS Raw Files)
- JSON file existence in `gs://nba-scraped-data/`
- File sizes and row counts
- Critical sources present (gamebooks, boxscores)

### Phase 2 (Raw BigQuery)
- Record counts in `nba_raw` tables
- Fallback coverage (NBA.com → BDL)
- Data completeness vs expected

### Phase 3 (Analytics)
- Record counts in `nba_analytics` tables
- Quality distribution (gold/silver/bronze)
- Feature coverage (minutes_played, usage_rate, etc.)
- Production readiness

### Phase 4 (Precompute)
- Coverage accounting for bootstrap periods
- Composite factor calculations
- ML feature store completeness

### Phase 5 (Predictions)
- Prediction coverage per system
- Quality scores
- Grading results

---

## 🔧 Integration Points

### Backfill Orchestrator
The orchestrator (`scripts/backfill_orchestrator.sh`) integrates validation:
1. Monitors Phase 1 completion
2. Runs Phase 1 validation
3. Auto-starts Phase 2 if validation passes
4. Runs Phase 2 validation
5. Generates final report

### Daily Pipeline
Processors use validation for self-checks:
- Output validation after processing
- Completeness checks
- Quality threshold enforcement

### ML Training
Pre-training validation ensures data quality:
- Feature coverage checks
- Sample volume verification
- Regression detection

---

## 📊 Validation Outputs

### Shell Scripts
- Exit code: `0` (PASS) or `1` (FAIL)
- Console output with color-coded results
- Summary statistics

### Python Validators
- `ValidationResult` objects with:
  - Status (COMPLETE, PARTIAL, MISSING, etc.)
  - Record counts
  - Coverage percentages
  - Quality distributions
  - Issues list

### Reports
- Terminal output (color-coded)
- JSON reports (machine-readable)
- Backfill reports (detailed)

---

## 🚨 Critical Thresholds

### Phase 2 (player_game_summary)
- **minutes_played**: ≥99% (CRITICAL)
- **usage_rate**: ≥95% (CRITICAL)
- **shot_zones**: ≥40% (2024+), ≥80% (historical)
- **Success rate**: ≥95%
- **Zero duplicates**: Required

### Phase 4 (player_composite_factors)
- **Coverage**: ≥88% (accounting for bootstrap)
- **Success rate**: ≥95%
- **Feature completeness**: ≥95%

### ML Training Data
- **Samples**: ≥50,000
- **usage_rate**: ≥90%
- **minutes_played**: ≥99%
- **Other features**: ≥95%

See: [FEATURE-COVERAGE.md](./FEATURE-COVERAGE.md) for complete list

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│ Validation Framework Architecture                   │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │ Shell Scripts│  │ Python Core  │  │ Monitoring│ │
│  │ (bash)       │  │ (validators) │  │ (Firestore│ │
│  └──────────────┘  └──────────────┘  └───────────┘ │
│         │                  │                │       │
│         └──────────────────┴────────────────┘       │
│                        │                            │
│         ┌──────────────┴──────────────┐             │
│         │                             │             │
│    ┌────▼────┐                  ┌────▼─────┐       │
│    │ BigQuery│                  │ Firestore│       │
│    │ (data)  │                  │ (state)  │       │
│    └─────────┘                  └──────────┘       │
│                                                      │
└─────────────────────────────────────────────────────┘
```

See: [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## 📚 Related Documentation

### Project Documentation
- **Backfill System**: `docs/08-projects/current/backfill-system-analysis/`
- **Pipeline Reliability**: `docs/08-projects/current/pipeline-reliability-improvements/`
- **ML Development**: `docs/08-projects/current/ml-model-development/`

### Code Documentation
- **Validation Code**: `shared/validation/README.md`
- **Shell Scripts**: `scripts/validation/README.md`
- **Configuration**: `scripts/config/backfill_thresholds.yaml`

### Handoff Documents
- **Latest Status**: `docs/09-handoff/2026-01-04-VALIDATION-QUERIES-READY.md`
- **Strategic Analysis**: `docs/09-handoff/2026-01-04-ULTRATHINK-STRATEGIC-ANALYSIS.md`

---

## 🤝 Contributing

When updating validation:
1. Update thresholds in `scripts/config/backfill_thresholds.yaml`
2. Update Python validators in `shared/validation/validators/`
3. Update shell scripts in `scripts/validation/`
4. Update documentation in `docs/validation-framework/`
5. Test with live data
6. Update CHANGELOG

---

## 📞 Getting Help

1. **Check documentation** in this directory
2. **Review examples** in `shared/validation/examples/`
3. **Check shell scripts** in `scripts/validation/`
4. **Review recent handoffs** in `docs/09-handoff/`

---

**Version**: 2.0
**Status**: Production
**Maintainer**: NBA Stats Scraper Team
**Last Review**: January 4, 2026
