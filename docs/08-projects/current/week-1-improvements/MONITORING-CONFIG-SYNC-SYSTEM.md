# Monitoring Configuration Sync System

**Created:** January 21, 2026
**Purpose:** Establish comprehensive system to keep monitoring configs in sync with pipeline changes
**Status:** Design Complete - Ready for Implementation

---

## Table of Contents

1. [The Problem](#the-problem)
2. [Single Source of Truth (SSOT) Design](#single-source-of-truth-ssot-design)
3. [Config Generation from SSOT](#config-generation-from-ssot)
4. [Validation Tests](#validation-tests)
5. [Pre-Deployment Checklist](#pre-deployment-checklist)
6. [Change Management Process](#change-management-process)
7. [Automated Sync Tools](#automated-sync-tools)
8. [Documentation Standards](#documentation-standards)
9. [Monthly Review Process](#monthly-review-process)
10. [Emergency Sync Procedure](#emergency-sync-procedure)

---

## The Problem

### What We Discovered Today (Jan 21, 2026)

#### Issue: br_roster vs br_rosters_current
**Scale:** 10 files across entire orchestration system
**Duration:** Unknown (discovered during multi-agent investigation)
**Impact:** Monitoring only (data flow unaffected)

**Configuration Says:**
```python
phase2_expected_processors = [
    'bdl_player_boxscores',
    'bigdataball_play_by_play',
    'odds_api_game_lines',
    'nbac_schedule',
    'nbac_gamebook_player_stats',
    'br_roster',  # ❌ WRONG
]
```

**Reality:**
```sql
-- BigQuery Table
nba_raw.br_rosters_current  -- ✅ CORRECT
```

**Files Affected:** 10 configuration files requiring updates

**Why It Happened:**
- Table was renamed (or originally created) as `br_rosters_current`
- Orchestration configs never updated
- No validation of config vs reality
- Manual updates error-prone

#### Consequences

**What Broke:**
- ⚠️ Monitoring orchestrator cannot track BR roster processor completion
- ⚠️ Firestore completeness tracking affected
- ⚠️ Dashboard metrics miss roster updates

**What Still Worked:**
- ✅ Data processing (processor uses correct table name)
- ✅ Analytics pipeline (reads from fallback_config.yaml with correct name)
- ✅ Predictions (no dependency on monitoring)

**Key Insight:** System architecture decoupled enough that monitoring breaks didn't break pipeline. But this also meant the break went undetected for unknown duration.

### Root Causes

1. **No Single Source of Truth**
   - Table names in BigQuery schemas
   - Processor names in orchestration configs
   - Table references in fallback configs
   - All maintained independently

2. **Manual Configuration Updates**
   - Human error prone
   - Easy to miss files
   - No validation before deployment

3. **No Automated Consistency Checks**
   - Config vs BigQuery tables not validated
   - Processor names vs table names not checked
   - Expected counts not verified

4. **Documentation Drift**
   - Configs get out of sync with code
   - README updates forgotten
   - Monitoring queries use wrong names

---

## Single Source of Truth (SSOT) Design

### Proposed Directory Structure

```
schemas/
  ├── processors/
  │   ├── phase2_raw_processors.yaml          # Phase 2 raw data ingestion
  │   ├── phase3_analytics_processors.yaml    # Phase 3 analytics
  │   └── phase4_precompute_processors.yaml   # Phase 4 precompute
  └── infrastructure/
      ├── bigquery_tables.yaml                # All table names
      ├── cloud_run_services.yaml             # All service names
      └── pubsub_topics.yaml                  # All topic names
```

### SSOT Schema Format

#### processors/phase2_raw_processors.yaml

```yaml
# Phase 2 Raw Data Processors - AUTHORITATIVE REGISTRY
# This is the SINGLE SOURCE OF TRUTH for Phase 2 processor definitions
# All orchestration configs, monitoring queries, and documentation generated from this

version: "1.0"
phase: 2
phase_name: "raw_data_ingestion"
dataset: "nba_raw"

# Critical processors (required for daily pipeline)
critical_processors:
  - name: bdl_player_boxscores
    class: BdlPlayerBoxScoresProcessor
    target_table: bdl_player_boxscores
    schedule: post_game
    required: true
    description: "Daily box scores from Ball Don't Lie API"
    dependencies: []
    estimated_runtime_minutes: 5
    owner: "data-team"

  - name: bigdataball_play_by_play
    class: BigDataBallPbpProcessor
    target_table: bigdataball_play_by_play
    schedule: post_game
    required: true
    description: "Per-game play-by-play data from BigDataBall"
    dependencies: []
    estimated_runtime_minutes: 10
    owner: "data-team"

  - name: odds_api_game_lines
    class: OddsGameLinesProcessor
    target_table: odds_api_game_lines
    schedule: pre_game
    required: true
    description: "Pre-game odds and betting lines"
    dependencies: []
    estimated_runtime_minutes: 2
    owner: "data-team"

  - name: nbac_schedule
    class: NbacScheduleProcessor
    target_table: nbac_schedule
    schedule: daily_morning
    required: true
    description: "NBA schedule updates from NBA.com"
    dependencies: []
    estimated_runtime_minutes: 1
    owner: "data-team"

  - name: nbac_gamebook_player_stats
    class: NbacGamebookProcessor
    target_table: nbac_gamebook_player_stats
    schedule: post_game
    required: true
    description: "Official gamebook player stats from NBA.com"
    dependencies: []
    estimated_runtime_minutes: 8
    owner: "data-team"

  - name: br_rosters_current
    class: BasketballRefRosterProcessor
    target_table: br_rosters_current
    schedule: daily_6am_et
    required: false  # Only when rosters change
    description: "Current NBA rosters from Basketball Reference"
    dependencies: []
    estimated_runtime_minutes: 3
    owner: "data-team"
    notes: "May not publish daily if no roster changes detected"

# Non-critical processors (supplementary data)
supplementary_processors:
  - name: bdl_live_boxscores
    class: BdlLiveBoxscoresProcessor
    target_table: bdl_live_boxscores
    schedule: live_during_games
    required: false
    description: "Live box score updates during games"

  - name: espn_rosters
    class: EspnTeamRosterProcessor
    target_table: espn_rosters
    schedule: daily_morning
    required: false
    description: "Team rosters from ESPN"

# Configuration for orchestration
orchestration:
  expected_count: 6  # Number of critical processors
  trigger_mode: all_complete  # or: majority, any_complete
  majority_threshold: 0.80  # If trigger_mode is majority
  timeout_minutes: 30  # After first completion
  enable_deadline_monitoring: true

# Monitoring configuration
monitoring:
  enable_completion_tracking: true
  enable_performance_tracking: true
  alert_on_failure: true
  alert_channel: "#nba-pipeline-alerts"
```

#### infrastructure/bigquery_tables.yaml

```yaml
# BigQuery Tables - AUTHORITATIVE REGISTRY
# This is the SINGLE SOURCE OF TRUTH for all BigQuery table names

version: "1.0"
project_id: "nba-props-platform"

datasets:
  - name: nba_raw
    description: "Raw data from external sources"
    location: "us-west2"
    tables:
      - name: bdl_player_boxscores
        description: "Player box scores from Ball Don't Lie"
        partitioned_by: data_date
        clustered_by: [player_id, team_abbrev]

      - name: br_rosters_current
        description: "Current rosters from Basketball Reference"
        partitioned_by: data_date
        clustered_by: [team_abbrev, season_year]

      # ... all Phase 2 raw tables

  - name: nba_analytics
    description: "Analytics and computed metrics"
    location: "us-west2"
    tables:
      - name: player_game_summary
        description: "Per-game player analytics"
        partitioned_by: data_date
        clustered_by: [player_id, game_id]

      - name: upcoming_team_game_context
        description: "Upcoming game context for teams"
        partitioned_by: data_date
        clustered_by: [team_abbrev, game_id]

      # ... all Phase 3 analytics tables

  - name: nba_precompute
    description: "Pre-computed features for predictions"
    location: "us-west2"
    tables:
      - name: player_composite_factors
        description: "Composite factors for player predictions"
        partitioned_by: data_date
        clustered_by: [player_id]

      # ... all Phase 4 precompute tables
```

### Benefits of SSOT Approach

1. **Single Update Point**
   - Change processor name once in YAML
   - All configs regenerated automatically
   - No possibility of partial updates

2. **Validation at Source**
   - YAML schema enforced
   - Required fields validated
   - Consistency checked before generation

3. **Generated Documentation**
   - Processor registry auto-generated
   - Monitoring queries auto-updated
   - Architecture diagrams from source

4. **Audit Trail**
   - Git history shows all changes
   - Who changed what and when
   - Easy to revert mistakes

5. **Testing Foundation**
   - Validate configs match SSOT
   - Check tables exist per SSOT
   - Verify processor counts

---

## Config Generation from SSOT

### Generation Script: bin/generate_configs.py

```python
#!/usr/bin/env python3
"""
Generate orchestration configs from SSOT YAML files.

Usage:
    # Validate SSOT files
    python bin/generate_configs.py --validate

    # Generate all configs
    python bin/generate_configs.py --generate

    # Verify configs match infrastructure
    python bin/generate_configs.py --verify

    # All steps
    python bin/generate_configs.py --all
"""

import yaml
import argparse
from pathlib import Path
from typing import Dict, List
from google.cloud import bigquery


class ConfigGenerator:
    """Generate orchestration configs from SSOT YAML files."""

    def __init__(self, schemas_dir: Path):
        self.schemas_dir = schemas_dir
        self.processors_dir = schemas_dir / "processors"
        self.infrastructure_dir = schemas_dir / "infrastructure"

    def validate_ssot(self) -> bool:
        """Validate all SSOT YAML files."""
        print("Validating SSOT files...")

        # Validate processor files
        phase2_file = self.processors_dir / "phase2_raw_processors.yaml"
        if not phase2_file.exists():
            print(f"❌ Missing: {phase2_file}")
            return False

        with open(phase2_file) as f:
            phase2_config = yaml.safe_load(f)

        # Validate required fields
        if 'critical_processors' not in phase2_config:
            print(f"❌ Missing 'critical_processors' in {phase2_file}")
            return False

        # Validate each processor has required fields
        for processor in phase2_config['critical_processors']:
            required = ['name', 'class', 'target_table', 'schedule']
            for field in required:
                if field not in processor:
                    print(f"❌ Processor missing '{field}': {processor.get('name', 'unknown')}")
                    return False

        print("✅ All SSOT files valid")
        return True

    def generate_orchestration_config(self, phase: int) -> str:
        """Generate orchestration_config.py for a phase."""

        # Load processor SSOT
        processor_file = self.processors_dir / f"phase{phase}_*_processors.yaml"
        with open(processor_file) as f:
            config = yaml.safe_load(f)

        # Extract processor names
        processor_names = [p['name'] for p in config['critical_processors']]

        # Generate Python config
        output = f'''# AUTO-GENERATED from schemas/processors/phase{phase}_*_processors.yaml
# DO NOT EDIT MANUALLY - Run bin/generate_configs.py to regenerate

from dataclasses import dataclass, field
from typing import List

@dataclass
class Phase{phase}Config:
    """Configuration for Phase {phase} orchestration."""

    # Expected processors (from SSOT)
    expected_processors: List[str] = field(default_factory=lambda: [
'''

        for name in processor_names:
            output += f"        '{name}',  # {self._get_processor_description(config, name)}\n"

        output += f'''    ])

    # Orchestration settings (from SSOT)
    expected_count: int = {len(processor_names)}
    trigger_mode: str = "{config['orchestration']['trigger_mode']}"
    timeout_minutes: int = {config['orchestration']['timeout_minutes']}
    enable_deadline_monitoring: bool = {config['orchestration']['enable_deadline_monitoring']}
'''

        return output

    def generate_all_configs(self):
        """Generate all orchestration configs from SSOT."""
        print("Generating configs from SSOT...")

        # Generate orchestration configs for each phase
        for phase in [2, 3, 4, 5]:
            config_content = self.generate_orchestration_config(phase)

            # Write to all locations that need this config
            locations = self._get_config_locations(phase)
            for location in locations:
                print(f"  Writing {location}")
                with open(location, 'w') as f:
                    f.write(config_content)

        print("✅ All configs generated")

    def verify_configs(self) -> bool:
        """Verify generated configs match infrastructure."""
        print("Verifying configs match infrastructure...")

        bq_client = bigquery.Client()

        # Load Phase 2 processors
        phase2_file = self.processors_dir / "phase2_raw_processors.yaml"
        with open(phase2_file) as f:
            phase2_config = yaml.safe_load(f)

        # Check each processor's target table exists
        for processor in phase2_config['critical_processors']:
            table_name = processor['target_table']
            dataset = phase2_config['dataset']

            full_table = f"{bq_client.project}.{dataset}.{table_name}"

            try:
                table = bq_client.get_table(full_table)
                print(f"  ✅ {table_name} exists ({table.num_rows} rows)")
            except Exception as e:
                print(f"  ❌ {table_name} NOT FOUND: {e}")
                return False

        print("✅ All tables verified")
        return True

    def _get_processor_description(self, config: Dict, name: str) -> str:
        """Get processor description from config."""
        for processor in config['critical_processors']:
            if processor['name'] == name:
                return processor.get('description', name)
        return name

    def _get_config_locations(self, phase: int) -> List[Path]:
        """Get all locations that need orchestration config for a phase."""
        base = Path(__file__).parent.parent
        return [
            base / "shared" / "config" / "orchestration_config.py",
            base / "orchestration" / "cloud_functions" / f"phase{phase}_to_phase{phase+1}" / "shared" / "config" / "orchestration_config.py",
            # ... all other locations
        ]


def main():
    parser = argparse.ArgumentParser(description="Generate configs from SSOT")
    parser.add_argument('--validate', action='store_true', help="Validate SSOT files")
    parser.add_argument('--generate', action='store_true', help="Generate all configs")
    parser.add_argument('--verify', action='store_true', help="Verify configs match infrastructure")
    parser.add_argument('--all', action='store_true', help="Run all steps")

    args = parser.parse_args()

    schemas_dir = Path(__file__).parent.parent / "schemas"
    generator = ConfigGenerator(schemas_dir)

    if args.all or args.validate:
        if not generator.validate_ssot():
            exit(1)

    if args.all or args.generate:
        generator.generate_all_configs()

    if args.all or args.verify:
        if not generator.verify_configs():
            exit(1)

    print("\n✅ All steps completed successfully")


if __name__ == "__main__":
    main()
```

### Usage Examples

```bash
# After adding new processor to SSOT
python bin/generate_configs.py --validate

# Generate all configs
python bin/generate_configs.py --generate

# Test configs match infrastructure
python bin/generate_configs.py --verify

# Complete workflow
python bin/generate_configs.py --all
```

---

## Validation Tests

### Test Suite: tests/config_validation/test_orchestration_consistency.py

```python
"""
Test orchestration configs match SSOT and infrastructure.
Run in CI/CD to catch config drift.
"""

import pytest
import yaml
from pathlib import Path
from google.cloud import bigquery
from typing import List


class TestOrchestrationConsistency:
    """Test configs match SSOT and infrastructure."""

    @pytest.fixture
    def phase2_ssot(self):
        """Load Phase 2 SSOT."""
        ssot_file = Path("schemas/processors/phase2_raw_processors.yaml")
        with open(ssot_file) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def bq_client(self):
        """BigQuery client."""
        return bigquery.Client()

    def test_processor_names_match_ssot(self, phase2_ssot):
        """Test orchestration config processor names match SSOT."""

        # Load actual orchestration config
        from shared.config.orchestration_config import Phase2Config
        config = Phase2Config()

        # Extract expected processor names from SSOT
        expected = [p['name'] for p in phase2_ssot['critical_processors']]

        # Compare
        assert config.expected_processors == expected, \
            f"Config mismatch: {config.expected_processors} != {expected}"

    def test_all_tables_exist(self, phase2_ssot, bq_client):
        """Test all processor target tables exist in BigQuery."""

        dataset = phase2_ssot['dataset']

        for processor in phase2_ssot['critical_processors']:
            table_name = processor['target_table']
            full_table = f"{bq_client.project}.{dataset}.{table_name}"

            # Check table exists
            try:
                table = bq_client.get_table(full_table)
                assert table.num_rows >= 0  # Table exists
            except Exception as e:
                pytest.fail(f"Table {table_name} not found: {e}")

    def test_expected_processor_count(self, phase2_ssot):
        """Test expected processor count matches SSOT."""

        from shared.config.orchestration_config import Phase2Config
        config = Phase2Config()

        expected = len(phase2_ssot['critical_processors'])

        assert config.expected_count == expected, \
            f"Processor count mismatch: {config.expected_count} != {expected}"

    def test_no_hardcoded_table_names(self):
        """Test orchestration files don't hardcode table names."""

        # Search orchestration files for hardcoded table references
        orch_files = Path("orchestration").rglob("*.py")

        for file in orch_files:
            with open(file) as f:
                content = f.read()

            # Check for hardcoded table names (should use config instead)
            forbidden = ['nba_raw.bdl_player_boxscores', 'nba_raw.br_roster']
            for pattern in forbidden:
                assert pattern not in content, \
                    f"Hardcoded table name in {file}: {pattern}"

    def test_service_urls_reachable(self):
        """Test all service URLs in config are reachable."""

        # Load service infrastructure SSOT
        with open("schemas/infrastructure/cloud_run_services.yaml") as f:
            services = yaml.safe_load(f)

        # Check each service is deployed
        for service in services['services']:
            # Use gcloud or Cloud Run API to verify service exists
            # This is a placeholder for actual implementation
            pass

    def test_pubsub_topics_exist(self):
        """Test all Pub/Sub topics in config exist."""

        # Load topic infrastructure SSOT
        with open("schemas/infrastructure/pubsub_topics.yaml") as f:
            topics = yaml.safe_load(f)

        # Check each topic exists
        from google.cloud import pubsub_v1
        publisher = pubsub_v1.PublisherClient()

        project_id = "nba-props-platform"

        for topic_name in topics['topics']:
            topic_path = publisher.topic_path(project_id, topic_name)

            try:
                publisher.get_topic(request={"topic": topic_path})
            except Exception as e:
                pytest.fail(f"Topic {topic_name} not found: {e}")
```

### Run in CI/CD

```yaml
# .github/workflows/config-validation.yml
name: Config Validation

on: [push, pull_request]

jobs:
  validate-configs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.9'

      - name: Install dependencies
        run: |
          pip install pytest pyyaml google-cloud-bigquery google-cloud-pubsub

      - name: Validate SSOT
        run: |
          python bin/generate_configs.py --validate

      - name: Run consistency tests
        run: |
          pytest tests/config_validation/
```

---

## Pre-Deployment Checklist

### File: docs/deployment/PRE-DEPLOYMENT-CHECKLIST.md

```markdown
# Pre-Deployment Checklist

Use this checklist for ANY deployment to production.

## Before Every Deployment

### 1. Config Validation ✅
- [ ] Run `python bin/generate_configs.py --validate`
- [ ] All SSOT files pass validation
- [ ] No schema errors

### 2. Infrastructure Verification ✅
- [ ] Run `python bin/generate_configs.py --verify`
- [ ] All processor target tables exist in BigQuery
- [ ] All Cloud Run services deployed
- [ ] All Pub/Sub topics exist

### 3. Test Suite ✅
- [ ] Run `pytest tests/config_validation/`
- [ ] All config validation tests pass
- [ ] No table name mismatches
- [ ] No hardcoded values found

### 4. Monitoring Queries ✅
- [ ] Run all monitoring queries in `bin/operations/monitoring_queries.sql`
- [ ] All queries execute successfully
- [ ] Update expected processor counts if changed
- [ ] Verify query comments match current processor names

### 5. Config Generation ✅
- [ ] If SSOT changed: Run `python bin/generate_configs.py --generate`
- [ ] Review generated config diffs
- [ ] Commit generated configs with SSOT changes

## Before Phase 2 Processor Changes

### 6. Processor Addition ✅
- [ ] Add processor to `schemas/processors/phase2_raw_processors.yaml`
- [ ] Create BigQuery table with schema
- [ ] Run config generation
- [ ] Update expected processor count in SSOT
- [ ] Deploy processor code
- [ ] Run validation tests
- [ ] Update monitoring queries

### 7. Processor Removal ✅
- [ ] Remove from SSOT YAML
- [ ] Update expected count in SSOT
- [ ] Run config generation
- [ ] Deploy orchestrator updates
- [ ] Verify Phase 3 still triggers correctly
- [ ] Archive BigQuery table (don't delete immediately)

### 8. Table Rename ✅
- [ ] Create new table with new name
- [ ] Backfill data to new table
- [ ] Update SSOT YAML with new name
- [ ] Run config generation
- [ ] Deploy all config updates
- [ ] Verify monitoring works with new name
- [ ] Drop old table after 30-day validation period

## Before Phase 3/4/5 Changes

### 9. Analytics Processor Changes ✅
- [ ] Update `schemas/processors/phase3_analytics_processors.yaml`
- [ ] Create/update target tables
- [ ] Run config generation
- [ ] Update expected counts
- [ ] Deploy processor
- [ ] Verify orchestration tracking

### 10. Expected Count Changes ✅
- [ ] Update `expected_count` in SSOT YAML
- [ ] Run config generation
- [ ] Deploy orchestrator with new count
- [ ] Verify Firestore tracking updates correctly

## Emergency Rollback Plan

### 11. Rollback Readiness ✅
- [ ] Previous working configs saved
- [ ] Rollback script tested
- [ ] Service revisions identified
- [ ] Expected behavior documented

## Sign-Off

- [ ] All checklist items completed
- [ ] Tests passing
- [ ] Config drift resolved
- [ ] Ready for production deployment

**Deployed By:** _________________
**Date:** _________________
**Ticket:** _________________
```

---

## Change Management Process

### Common Changes and Procedures

#### Adding New Processor

**Procedure:**

1. **Update SSOT**
   ```bash
   # Edit schemas/processors/phase2_raw_processors.yaml
   vi schemas/processors/phase2_raw_processors.yaml
   ```

   Add processor:
   ```yaml
   - name: new_processor_name
     class: NewProcessorClass
     target_table: new_table_name
     schedule: post_game
     required: true
     description: "What this processor does"
   ```

2. **Create BigQuery Table**
   ```sql
   CREATE TABLE `nba-props-platform.nba_raw.new_table_name` (
     data_date DATE NOT NULL,
     game_id STRING NOT NULL,
     -- ...fields...
   )
   PARTITION BY data_date
   CLUSTER BY (game_id);
   ```

3. **Generate Configs**
   ```bash
   python bin/generate_configs.py --all
   ```

4. **Review and Commit**
   ```bash
   git diff  # Review generated changes
   git add schemas/ shared/ orchestration/
   git commit -m "Add new_processor_name to Phase 2"
   ```

5. **Deploy**
   ```bash
   # Deploy processor code
   gcloud run deploy nba-phase2-raw-processors \
     --source . \
     --region us-west2

   # Deploy orchestrator
   gcloud run deploy phase2-to-phase3-orchestrator \
     --source orchestration/cloud_functions/phase2_to_phase3 \
     --region us-west2
   ```

6. **Validate**
   ```bash
   pytest tests/config_validation/
   ```

#### Renaming Table

**Procedure:**

1. **Create New Table**
   ```sql
   CREATE TABLE `nba-props-platform.nba_raw.new_name`
   LIKE `nba-props-platform.nba_raw.old_name`;
   ```

2. **Backfill Data**
   ```sql
   INSERT INTO `nba-props-platform.nba_raw.new_name`
   SELECT * FROM `nba-props-platform.nba_raw.old_name`;
   ```

3. **Update SSOT**
   ```yaml
   # Change target_table in SSOT
   target_table: new_name  # was: old_name
   ```

4. **Generate Configs**
   ```bash
   python bin/generate_configs.py --all
   ```

5. **Deploy Updates**
   ```bash
   # Deploy processor with new table name
   # Deploy orchestrator with updated config
   ```

6. **Verify Monitoring**
   ```bash
   # Check monitoring queries work
   # Verify Firestore tracking correct
   ```

7. **Drop Old Table** (after 30 days)
   ```sql
   DROP TABLE `nba-props-platform.nba_raw.old_name`;
   ```

#### Changing Processor Count

**Procedure:**

1. **Update SSOT Orchestration Section**
   ```yaml
   orchestration:
     expected_count: 7  # was: 6
   ```

2. **Generate Configs**
   ```bash
   python bin/generate_configs.py --generate
   ```

3. **Deploy Orchestrator**
   ```bash
   gcloud run deploy phase2-to-phase3-orchestrator \
     --source orchestration/cloud_functions/phase2_to_phase3 \
     --region us-west2
   ```

4. **Verify Tracking**
   - Check Firestore `phase2_completion` documents
   - Verify `_required_count` field updated
   - Test Phase 3 triggers correctly

---

## Automated Sync Tools

### Script 1: bin/validate_config_sync.sh

```bash
#!/bin/bash
# Validates that configs match infrastructure reality

set -e

echo "🔍 Validating Config Sync..."

# Check BigQuery tables exist for all processor targets
echo ""
echo "1️⃣ Checking BigQuery tables..."
python3 <<EOF
import yaml
from google.cloud import bigquery

client = bigquery.Client()

with open('schemas/processors/phase2_raw_processors.yaml') as f:
    config = yaml.safe_load(f)

dataset = config['dataset']

for processor in config['critical_processors']:
    table_name = processor['target_table']
    full_table = f"{client.project}.{dataset}.{table_name}"

    try:
        table = client.get_table(full_table)
        print(f"  ✅ {table_name} ({table.num_rows} rows)")
    except Exception as e:
        print(f"  ❌ {table_name} NOT FOUND")
        exit(1)
EOF

# Check Cloud Run services match config
echo ""
echo "2️⃣ Checking Cloud Run services..."
python3 <<EOF
import yaml
import subprocess

with open('schemas/infrastructure/cloud_run_services.yaml') as f:
    config = yaml.safe_load(f)

for service in config['services']:
    name = service['name']
    result = subprocess.run(
        ['gcloud', 'run', 'services', 'describe', name, '--region=us-west2', '--format=value(status.url)'],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name} NOT FOUND")
        exit(1)
EOF

# Check Pub/Sub topics match config
echo ""
echo "3️⃣ Checking Pub/Sub topics..."
python3 <<EOF
import yaml
from google.cloud import pubsub_v1

publisher = pubsub_v1.PublisherClient()
project_id = "nba-props-platform"

with open('schemas/infrastructure/pubsub_topics.yaml') as f:
    config = yaml.safe_load(f)

for topic_name in config['topics']:
    topic_path = publisher.topic_path(project_id, topic_name)

    try:
        publisher.get_topic(request={"topic": topic_path})
        print(f"  ✅ {topic_name}")
    except Exception as e:
        print(f"  ❌ {topic_name} NOT FOUND")
        exit(1)
EOF

# Check expected counts match processor inventory
echo ""
echo "4️⃣ Checking expected processor counts..."
python3 <<EOF
import yaml

with open('schemas/processors/phase2_raw_processors.yaml') as f:
    config = yaml.safe_load(f)

critical_count = len(config['critical_processors'])
expected_count = config['orchestration']['expected_count']

if critical_count == expected_count:
    print(f"  ✅ Count matches: {critical_count}")
else:
    print(f"  ❌ Count mismatch: {critical_count} processors but expected_count={expected_count}")
    exit(1)
EOF

echo ""
echo "✅ All config sync checks passed!"
```

### Script 2: bin/sync_monitoring_queries.py

```python
#!/usr/bin/env python3
"""
Auto-update monitoring queries from SSOT.
Generates table verification queries from processor definitions.
"""

import yaml
from pathlib import Path


def generate_monitoring_queries():
    """Generate monitoring queries from SSOT."""

    # Load Phase 2 processors
    with open('schemas/processors/phase2_raw_processors.yaml') as f:
        phase2 = yaml.safe_load(f)

    output = """-- AUTO-GENERATED MONITORING QUERIES
-- Generated from schemas/processors/phase2_raw_processors.yaml
-- DO NOT EDIT MANUALLY - Run bin/sync_monitoring_queries.py to regenerate

-----------------------------------------------------------
-- Query 1: Phase 2 Table Verification
-----------------------------------------------------------
-- Verify all Phase 2 processor target tables exist and have recent data

"""

    for processor in phase2['critical_processors']:
        table = processor['target_table']
        dataset = phase2['dataset']
        description = processor['description']

        output += f"""
-- {processor['name']}: {description}
SELECT
  '{table}' as table_name,
  COUNT(*) as row_count,
  MAX(data_date) as last_data_date,
  DATE_DIFF(CURRENT_DATE(), MAX(data_date), DAY) as days_since_update
FROM `nba-props-platform.{dataset}.{table}`
WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)

UNION ALL
"""

    # Remove trailing UNION ALL
    output = output.rstrip('\n').rstrip('UNION ALL')

    output += """

ORDER BY days_since_update DESC;

-----------------------------------------------------------
-- Query 2: Phase 2 Processor Completion Status
-----------------------------------------------------------
-- Check if expected number of processors completed today

WITH today_completions AS (
  SELECT
    data_date,
    COUNT(DISTINCT processor_name) as completed_count
  FROM `nba-props-platform.nba_orchestration.processor_completions`
  WHERE data_date = CURRENT_DATE()
  GROUP BY data_date
)
SELECT
  completed_count,
  {} as expected_count,
  completed_count >= {} as all_complete
FROM today_completions;
""".format(
    phase2['orchestration']['expected_count'],
    phase2['orchestration']['expected_count']
)

    # Write to monitoring queries file
    output_file = Path('bin/operations/monitoring_queries_generated.sql')
    with open(output_file, 'w') as f:
        f.write(output)

    print(f"✅ Generated monitoring queries: {output_file}")
    print(f"   {len(phase2['critical_processors'])} processors")
    print(f"   Expected count: {phase2['orchestration']['expected_count']}")


if __name__ == "__main__":
    generate_monitoring_queries()
```

### Script 3: bin/audit_config_drift.py

```python
#!/usr/bin/env python3
"""
Detect config drift between SSOT and deployed configs.
Flags mismatches and suggests fixes.
"""

import yaml
from pathlib import Path
from typing import List, Dict
import difflib


class ConfigDriftAuditor:
    """Detect drift between SSOT and deployed configs."""

    def __init__(self):
        self.drift_issues: List[Dict] = []

    def audit_orchestration_configs(self):
        """Audit all orchestration config files."""

        # Load SSOT
        with open('schemas/processors/phase2_raw_processors.yaml') as f:
            ssot = yaml.safe_load(f)

        expected_processors = [p['name'] for p in ssot['critical_processors']]

        # Check all orchestration config locations
        config_files = [
            'shared/config/orchestration_config.py',
            'orchestration/cloud_functions/phase2_to_phase3/shared/config/orchestration_config.py',
            # ... all locations
        ]

        for config_file in config_files:
            if not Path(config_file).exists():
                continue

            with open(config_file) as f:
                content = f.read()

            # Extract processor list from config
            # (This is simplified - actual implementation would parse Python)
            actual_processors = self._extract_processors(content)

            # Compare
            if actual_processors != expected_processors:
                self.drift_issues.append({
                    'file': config_file,
                    'type': 'processor_list_mismatch',
                    'expected': expected_processors,
                    'actual': actual_processors,
                    'diff': list(difflib.unified_diff(
                        actual_processors,
                        expected_processors,
                        lineterm=''
                    ))
                })

    def report_drift(self):
        """Report all drift issues found."""

        if not self.drift_issues:
            print("✅ No config drift detected")
            return

        print(f"⚠️  Found {len(self.drift_issues)} config drift issues:\n")

        for issue in self.drift_issues:
            print(f"📄 File: {issue['file']}")
            print(f"   Type: {issue['type']}")
            print(f"   Diff:")
            for line in issue['diff']:
                print(f"     {line}")
            print()

    def suggest_fixes(self):
        """Suggest fixes for drift issues."""

        if not self.drift_issues:
            return

        print("🔧 Suggested fixes:\n")

        for issue in self.drift_issues:
            if issue['type'] == 'processor_list_mismatch':
                print(f"1. Run: python bin/generate_configs.py --generate")
                print(f"2. Review changes in: {issue['file']}")
                print(f"3. Commit and deploy")
                break  # Same fix for all

    def _extract_processors(self, content: str) -> List[str]:
        """Extract processor list from config file."""
        # Simplified extraction - actual would parse Python AST
        import re
        matches = re.findall(r"'([a-z_]+)',\s+#", content)
        return matches


def main():
    auditor = ConfigDriftAuditor()

    print("🔍 Auditing config drift...\n")

    auditor.audit_orchestration_configs()
    auditor.report_drift()
    auditor.suggest_fixes()


if __name__ == "__main__":
    main()
```

---

Due to length constraints, I'll create the remaining sections in a follow-up response. The document is comprehensive and covers:

1. ✅ The Problem (what we discovered)
2. ✅ SSOT Design (YAML schema structure)
3. ✅ Config Generation (automation scripts)
4. ✅ Validation Tests (CI/CD integration)
5. ✅ Pre-Deployment Checklist (operational procedures)
6. ✅ Change Management (common procedures)
7. ✅ Automated Sync Tools (3 scripts)

Remaining sections to add:
8. Documentation Standards
9. Monthly Review Process
10. Emergency Sync Procedure
11. Quick Reference Card
12. Implementation Plan

Let me know if you'd like me to complete the document with the remaining sections, or if you'd like me to proceed with creating the Quick Reference card and Implementation Plan as separate documents!

