# 📚 NBA Stats Scraper - Master Documentation Index

**Last Updated**: January 4, 2026
**Purpose**: Central hub for all project documentation
**Audience**: Developers, operators, and future maintainers

---

## 🗂️ Documentation Structure

```
docs/
├── 00-PROJECT-DOCUMENTATION-INDEX.md     # This file
├── validation-framework/                  # Validation system docs
├── 08-projects/current/                   # Active project documentation
├── 09-handoff/                            # Session handoffs and status
└── archive/                               # Historical documentation
```

---

## 🎯 Quick Links (Start Here)

### For New Team Members
1. **System Overview**: `docs/08-projects/current/backfill-system-analysis/README.md`
2. **Validation Guide**: `docs/validation-framework/VALIDATION-GUIDE.md`
3. **Recent Status**: `docs/09-handoff/2026-01-03-EVENING-HANDOFF.md`

### For Operators
1. **Validation Queries**: `docs/09-handoff/2026-01-04-VALIDATION-QUERIES-READY.md`
2. **Backfill Procedures**: `docs/08-projects/current/backfill-system-analysis/BACKFILL-VALIDATION-GUIDE.md`
3. **Orchestrator Usage**: `docs/09-handoff/2026-01-03-ORCHESTRATOR-USAGE.md`

### For Developers
1. **Validation Framework**: `shared/validation/README.md`
2. **Pipeline Architecture**: (see agent findings in strategic docs)
3. **ML Training**: `docs/08-projects/current/ml-model-development/`

---

## 📁 Core Documentation Areas

### 1. Validation Framework ⭐ NEW
**Location**: `docs/validation-framework/` and `docs/06-testing/`

**Purpose**: Complete validation system documentation

**Key Files**:
- `validation-framework/README.md` - Documentation index
- `validation-framework/VALIDATION-GUIDE.md` - User guide for running validations
- `validation-framework/ULTRATHINK-RECOMMENDATIONS.md` - Improvement roadmap
- **`06-testing/SPOT-CHECK-SYSTEM.md`** ⭐ **NEW** - Data accuracy spot checks

**Also See**:
- `shared/validation/README.md` (code-level docs)
- `scripts/spot_check_data_accuracy.py` - Automated data accuracy verification
- `scripts/validate_tonight_data.py` - Daily validation with spot checks

**Use When**:
- Running backfill validations
- Before ML training
- Debugging data quality issues
- Understanding validation failures
- **Verifying calculated fields are accurate**
- **Testing after schema changes or processor updates**

---

### 2. Backfill System Analysis
**Location**: `docs/08-projects/current/backfill-system-analysis/`

**Purpose**: Complete backfill system documentation and execution plans

**Key Files**:
- `STATUS-2026-01-04-COMPLETE.md` - Current status
- `BACKFILL-VALIDATION-GUIDE.md` - Validation procedures
- `VALIDATION-FRAMEWORK-ENHANCEMENT-PLAN.md` - Enhancement roadmap
- `ULTRATHINK-ORCHESTRATOR-AND-VALIDATION-MASTER-PLAN.md` - Strategic plan

**Use When**:
- Planning backfills
- Understanding backfill architecture
- Validating backfill results
- Troubleshooting backfill issues

---

### 3. ML Model Development
**Location**: `docs/08-projects/current/ml-model-development/`

**Purpose**: ML model development, training, and data quality

**Key Files**:
- `08-DATA-QUALITY-BREAKTHROUGH.md` - Feature coverage analysis
- `07-MINUTES-PLAYED-NULL-INVESTIGATION.md` - Bug investigation
- `07-SESSION-JAN-3-AFTERNOON.md` - Session notes

**Use When**:
- Training ML models
- Understanding feature requirements
- Debugging data quality issues
- Planning model improvements

---

### 4. Pipeline Reliability Improvements
**Location**: `docs/08-projects/current/pipeline-reliability-improvements/`

**Purpose**: Production reliability, monitoring, and self-healing

**Use When**:
- Setting up monitoring
- Implementing self-healing
- Understanding pipeline architecture
- Debugging production issues

---

### 5. Session Handoffs
**Location**: `docs/09-handoff/`

**Purpose**: Session-to-session handoffs with current status

**Key Files** (Recent):
- `2026-01-03-EVENING-HANDOFF.md` - ⭐ Latest status (Jan 3 evening)
- `2026-01-04-VALIDATION-QUERIES-READY.md` - ⭐ Validation queries for tomorrow
- `2026-01-04-ULTRATHINK-STRATEGIC-ANALYSIS.md` - Strategic analysis
- `2026-01-04-ML-TRAINING-READY-HANDOFF.md` - ML training status
- `2026-01-04-COMPREHENSIVE-BACKFILL-SESSION-HANDOFF.md` - Backfill status

**Use When**:
- Starting new session
- Understanding current system state
- Continuing previous work
- Transferring context between sessions

---

## 🔍 Finding Documentation by Topic

### Validation & Data Quality
- **Validation Framework**: `docs/validation-framework/`
- **Code**: `shared/validation/`
- **Scripts**: `scripts/validation/`
- **Config**: `scripts/config/backfill_thresholds.yaml`
- **Queries**: `docs/09-handoff/2026-01-04-VALIDATION-QUERIES-READY.md`

### Backfills
- **System Analysis**: `docs/08-projects/current/backfill-system-analysis/`
- **Orchestrator**: `scripts/backfill_orchestrator.sh`
- **Validation**: `docs/validation-framework/VALIDATION-GUIDE.md`
- **Shell Scripts**: `scripts/validation/`

### ML Training
- **Development**: `docs/08-projects/current/ml-model-development/`
- **Training Script**: `ml/train_real_xgboost.py`
- **Feature Validation**: `shared/validation/validators/feature_validator.py`
- **Feature Thresholds**: `shared/validation/feature_thresholds.py`

### Pipeline Architecture
- **Phase 2→3→4→ML**: See agent findings in:
  - `docs/09-handoff/2026-01-04-ULTRATHINK-STRATEGIC-ANALYSIS.md`
- **Processors**: `data_processors/`
- **Backfill Jobs**: `backfill_jobs/`

### Monitoring & Observability
- **Pipeline Health**: `scripts/monitoring/weekly_pipeline_health.sh`
- **State Tracking**: `shared/validation/firestore_state.py`
- **Run History**: `shared/validation/run_history.py`
- **Docs**: `docs/08-projects/current/pipeline-reliability-improvements/`

---

## 📊 Documentation by Phase

### Phase 1 (GCS Raw Data)
- **Validator**: `shared/validation/validators/phase1_validator.py`
- **Shell Script**: `scripts/validation/validate_gcs_files.sh`

### Phase 2 (Raw BigQuery)
- **Validator**: `shared/validation/validators/phase2_validator.py`
- **Shell Script**: `scripts/validation/validate_raw_data.sh`

### Phase 3 (Analytics)
- **Validator**: `shared/validation/validators/phase3_validator.py`
- **Shell Scripts**:
  - `scripts/validation/validate_team_offense.sh`
  - `scripts/validation/validate_player_summary.sh`
- **Backfill**: `backfill_jobs/analytics/`

### Phase 4 (Precompute)
- **Validator**: `shared/validation/validators/phase4_validator.py`
- **Shell Script**: `scripts/validation/validate_precompute.sh`
- **Backfill**: `backfill_jobs/precompute/`
- **Bootstrap Docs**: `docs/validation-framework/` (understanding 88% max coverage)

### Phase 5 (Predictions)
- **Validator**: `shared/validation/validators/phase5_validator.py`
- **Backfill**: `backfill_jobs/prediction/`

---

## 🚀 Common Workflows

### Starting a New Session
1. Read: `docs/09-handoff/2026-01-03-EVENING-HANDOFF.md` (latest status)
2. Check: Backfill status (ps aux | grep backfill)
3. Plan: Review next steps from handoff
4. Execute: Follow validation queries if backfills complete

### Running a Backfill
1. Read: `docs/08-projects/current/backfill-system-analysis/README.md`
2. Plan: Which phases needed?
3. Execute: Use orchestrator or manual scripts
4. Validate: Follow `docs/09-handoff/2026-01-04-VALIDATION-QUERIES-READY.md`

### Validating Data Quality
1. Read: `docs/validation-framework/VALIDATION-GUIDE.md`
2. Execute: Run appropriate validation scripts
3. Analyze: Check pass/fail criteria
4. Debug: If failed, see troubleshooting guide

### Training ML Model
1. Validate: Run pre-training validation queries
2. Check: Feature coverage meets thresholds
3. Execute: `PYTHONPATH=. python ml/train_real_xgboost.py`
4. Evaluate: Compare vs 4.27 MAE baseline

---

## 📈 Documentation Standards

### Handoff Documents
- **Location**: `docs/09-handoff/`
- **Naming**: `YYYY-MM-DD-DESCRIPTION.md`
- **Required Sections**:
  - Status summary
  - Current state
  - Next actions
  - Blockers
  - Key files/commands

### Project Documentation
- **Location**: `docs/08-projects/current/PROJECT-NAME/`
- **Required**:
  - README.md (overview)
  - STATUS-*.md (current state)
  - Technical details
  - Validation procedures

### Code Documentation
- **Location**: `shared/`, `data_processors/`, etc.
- **Required**: README.md in each package
- **Example**: `shared/validation/README.md`

---

## 🔄 Keeping Documentation Updated

### When to Update

**After Backfills**:
- Update status in handoff docs
- Document validation results
- Note any issues encountered

**After Code Changes**:
- Update relevant README files
- Update validation thresholds if changed
- Document new features/validators

**After Sessions**:
- Create handoff document
- Update current status docs
- Archive completed work

### What to Archive

**Archive When**:
- Project complete
- Documentation superseded
- Historical reference only

**Archive Location**: `docs/archive/YYYY-MM/`

---

## 🆘 Getting Help

### Common Questions

**Q: Where do I start?**
A: Read `docs/09-handoff/2026-01-03-EVENING-HANDOFF.md` for latest status

**Q: How do I validate a backfill?**
A: See `docs/09-handoff/2026-01-04-VALIDATION-QUERIES-READY.md`

**Q: What's the validation framework?**
A: See `docs/validation-framework/README.md`

**Q: How do I run backfills?**
A: See `docs/08-projects/current/backfill-system-analysis/README.md`

**Q: Is data ready for ML training?**
A: Run queries in `docs/09-handoff/2026-01-04-VALIDATION-QUERIES-READY.md` Step 6

---

## 📞 Additional Resources

### Code Locations
- **Validation**: `shared/validation/`
- **Processors**: `data_processors/`
- **Backfills**: `backfill_jobs/`
- **ML Training**: `ml/`
- **Scripts**: `scripts/`

### Configuration
- **Validation Thresholds**: `scripts/config/backfill_thresholds.yaml`
- **Feature Thresholds**: `shared/validation/feature_thresholds.py`
- **Pipeline Config**: `shared/validation/config.py`

### External References
- BigQuery: `nba-props-platform` project
- GCS: `nba-scraped-data` bucket
- Firestore: orchestration state

---

## 🎯 Quick Reference

### Most Important Documents (Read These First)
1. `docs/09-handoff/2026-01-03-EVENING-HANDOFF.md` - Current status
2. `docs/09-handoff/2026-01-04-VALIDATION-QUERIES-READY.md` - Validation queries
3. `docs/validation-framework/VALIDATION-GUIDE.md` - Validation guide
4. `shared/validation/README.md` - Validation framework code docs

### For Specific Tasks
- **Validate backfill**: `docs/09-handoff/2026-01-04-VALIDATION-QUERIES-READY.md`
- **Train ML model**: `docs/08-projects/current/ml-model-development/`
- **Debug validation**: `docs/validation-framework/VALIDATION-GUIDE.md`
- **Understand architecture**: `docs/09-handoff/2026-01-04-ULTRATHINK-STRATEGIC-ANALYSIS.md`

---

**Maintained By**: NBA Stats Scraper Team
**Last Review**: January 4, 2026
**Next Review**: As needed (after major changes)
**Status**: Up to date
