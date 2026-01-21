# Monitoring Config Sync - Quick Reference

**One-Page Reference for Daily Operations**

---

## Where is Everything?

### Single Source of Truth (SSOT)
```
schemas/
  ├── processors/
  │   ├── phase2_raw_processors.yaml          # Phase 2 processor registry
  │   ├── phase3_analytics_processors.yaml    # Phase 3 processor registry
  │   └── phase4_precompute_processors.yaml   # Phase 4 processor registry
  └── infrastructure/
      ├── bigquery_tables.yaml                # All BigQuery tables
      ├── cloud_run_services.yaml             # All Cloud Run services
      └── pubsub_topics.yaml                  # All Pub/Sub topics
```

### Generated Configs (DO NOT EDIT MANUALLY)
```
shared/config/orchestration_config.py
orchestration/cloud_functions/phase*/shared/config/orchestration_config.py
predictions/*/shared/config/orchestration_config.py
```

### Tools & Scripts
```
bin/generate_configs.py          # Generate configs from SSOT
bin/validate_config_sync.sh      # Validate configs match infrastructure
bin/sync_monitoring_queries.py   # Update monitoring queries
bin/audit_config_drift.py        # Detect config drift
```

---

## Common Commands

### Validate SSOT
```bash
python bin/generate_configs.py --validate
```

### Generate All Configs
```bash
python bin/generate_configs.py --generate
```

### Verify Configs Match Infrastructure
```bash
python bin/generate_configs.py --verify
```

### Complete Workflow
```bash
python bin/generate_configs.py --all
```

### Check for Config Drift
```bash
python bin/audit_config_drift.py
```

### Run Config Validation Tests
```bash
pytest tests/config_validation/
```

---

## Quick Fixes

### Fix br_roster Issue (10 files)

**Problem:** Config says `br_roster`, table is `br_rosters_current`

**Fix:**
1. Edit `schemas/processors/phase2_raw_processors.yaml`
   ```yaml
   # Change name field:
   - name: br_rosters_current  # was: br_roster
   ```

2. Regenerate configs:
   ```bash
   python bin/generate_configs.py --generate
   ```

3. Deploy:
   ```bash
   # Deploy all orchestrators
   ./bin/deploy_orchestrators.sh
   ```

---

## Before Any Deployment

### Pre-Deployment Checklist

1. ✅ Validate SSOT
   ```bash
   python bin/generate_configs.py --validate
   ```

2. ✅ Run Tests
   ```bash
   pytest tests/config_validation/
   ```

3. ✅ Verify Infrastructure
   ```bash
   python bin/generate_configs.py --verify
   ```

4. ✅ Check Config Drift
   ```bash
   python bin/audit_config_drift.py
   ```

5. ✅ Test Monitoring Queries
   ```bash
   # Run queries in bin/operations/monitoring_queries.sql
   ```

---

## Adding New Processor

### Step-by-Step

1. **Update SSOT**
   ```bash
   vi schemas/processors/phase2_raw_processors.yaml
   ```

   Add:
   ```yaml
   - name: new_processor_name
     class: NewProcessorClass
     target_table: new_table_name
     schedule: post_game
     required: true
     description: "What it does"
   ```

2. **Create BigQuery Table**
   ```sql
   CREATE TABLE `nba-props-platform.nba_raw.new_table_name` (...)
   ```

3. **Generate Configs**
   ```bash
   python bin/generate_configs.py --all
   ```

4. **Review & Commit**
   ```bash
   git diff
   git add schemas/ shared/ orchestration/
   git commit -m "Add new_processor_name"
   ```

5. **Deploy**
   ```bash
   gcloud run deploy nba-phase2-raw-processors ...
   ```

6. **Validate**
   ```bash
   pytest tests/config_validation/
   ```

---

## Renaming Table

### Step-by-Step

1. **Create New Table**
   ```sql
   CREATE TABLE `...new_name` LIKE `...old_name`;
   INSERT INTO `...new_name` SELECT * FROM `...old_name`;
   ```

2. **Update SSOT**
   ```yaml
   target_table: new_name  # was: old_name
   ```

3. **Generate & Deploy**
   ```bash
   python bin/generate_configs.py --all
   # Deploy processor and orchestrator
   ```

4. **Verify**
   ```bash
   python bin/generate_configs.py --verify
   ```

5. **Drop Old Table** (after 30 days)
   ```sql
   DROP TABLE `...old_name`;
   ```

---

## Emergency Sync Procedure

### When Config Issues Discovered

1. **Document Mismatch**
   - What config says
   - What reality is
   - Impact assessment

2. **Determine SSOT**
   - Is config correct? Update infrastructure
   - Is infrastructure correct? Update SSOT

3. **Update SSOT YAML**
   ```bash
   vi schemas/processors/phase2_raw_processors.yaml
   ```

4. **Generate Configs**
   ```bash
   python bin/generate_configs.py --all
   ```

5. **Deploy Critical Fixes**
   ```bash
   # P0: Deploy immediately
   # P1: Deploy next release
   # P2: Schedule for sprint
   ```

6. **Add Test**
   ```python
   # tests/config_validation/test_issue_123.py
   def test_br_roster_name():
       """Prevent br_roster vs br_rosters_current recurrence."""
       ...
   ```

7. **Document**
   - Update incident report
   - Add to lessons learned
   - Update quick ref if needed

---

## Troubleshooting

### Config Not Updating After Generation

**Check:**
1. SSOT file saved correctly?
2. Ran `generate_configs.py --generate`?
3. Correct file location?
4. File permissions OK?

**Debug:**
```bash
# Verify SSOT syntax
python -c "import yaml; yaml.safe_load(open('schemas/processors/phase2_raw_processors.yaml'))"

# Check what would be generated
python bin/generate_configs.py --generate --dry-run
```

### Tests Failing After Config Change

**Check:**
1. Did you regenerate configs?
2. Did you update expected counts?
3. Did you create BigQuery tables?
4. Did you deploy services?

**Debug:**
```bash
# See detailed test output
pytest tests/config_validation/ -v

# Run specific test
pytest tests/config_validation/test_orchestration_consistency.py::test_processor_names_match_ssot -v
```

### Monitoring Queries Using Wrong Names

**Fix:**
1. Update SSOT with correct names
2. Run `python bin/sync_monitoring_queries.py`
3. Review generated queries
4. Test in BigQuery console

### Firestore Not Tracking Processor

**Check:**
1. Processor name matches SSOT?
2. Orchestrator deployed with updated config?
3. Processor publishing completion message?
4. Message format correct?

**Debug:**
```python
# Check Firestore document
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase2_completion').document('2026-01-21').get()
print(doc.to_dict())
```

---

## Key Concepts

### Single Source of Truth (SSOT)
**Definition:** One authoritative location for each configuration value

**Benefit:** Change once, propagates everywhere

**Location:** `schemas/` directory

### Config Generation
**Definition:** Automatically create config files from SSOT

**Benefit:** No manual updates, no partial updates, no mistakes

**Tool:** `bin/generate_configs.py`

### Validation Tests
**Definition:** Automated tests that configs match infrastructure

**Benefit:** Catch drift before deployment

**Run:** `pytest tests/config_validation/`

### Config Drift
**Definition:** When configs don't match SSOT or infrastructure

**Detection:** `bin/audit_config_drift.py`

**Prevention:** Always use SSOT, never edit generated files

---

## Best Practices

### Do's ✅
- ✅ Always update SSOT first
- ✅ Run validation before deployment
- ✅ Regenerate configs after SSOT changes
- ✅ Test configs in staging first
- ✅ Commit SSOT and generated configs together
- ✅ Document changes in commit message

### Don'ts ❌
- ❌ Never edit generated config files directly
- ❌ Never commit SSOT without regenerating configs
- ❌ Never deploy without running validation
- ❌ Never skip pre-deployment checklist
- ❌ Never hardcode values (use SSOT)

---

## Getting Help

### Documentation
- Full System: `docs/.../MONITORING-CONFIG-SYNC-SYSTEM.md`
- Implementation: `docs/.../MONITORING-SYNC-IMPLEMENTATION-PLAN.md`
- Pre-Deployment: `docs/deployment/PRE-DEPLOYMENT-CHECKLIST.md`

### Commands
```bash
# Help for config generation
python bin/generate_configs.py --help

# Help for validation
python bin/validate_config_sync.sh --help

# Help for tests
pytest tests/config_validation/ --help
```

### Support
- Slack: #nba-pipeline-alerts
- On-Call: PagerDuty rotation
- Documentation: Confluence wiki

---

**Quick Reference Version:** 1.0
**Last Updated:** January 21, 2026
**Maintained By:** Data Platform Team
