# Source Coverage System - Review & Enhancements
## Additional Code and Recommendations from Design Review

**Created:** 2025-11-26
**Status:** Reference Material
**Purpose:** Preserves valuable enhancements identified during design review

---

## Overview

This document contains additional code and recommendations from the design review process.
The core recommendations have been incorporated into the main docs (Parts 1-4).
This file preserves the full implementations for future reference.

### What Was Incorporated into Main Docs

| Enhancement | Status | Location |
|-------------|--------|----------|
| Season-aware thresholds | Incorporated | Part 3: QualityMixin |
| BigQuery no-indexes note | Incorporated | Part 2: Schema Reference |
| Use existing notification system | Incorporated | Part 3: Implementation Guide |
| Historical backfill script | Incorporated | Part 2: Migration Scripts |
| Edge case tests | Incorporated | Part 4: Testing Strategy |
| Prerequisite callout | Incorporated | Part 3: Header |

### What's in This Document (Additional Reference)

| Enhancement | Section |
|-------------|---------|
| Full configurable audit tables config | [Configurable Audit Tables](#configurable-audit-tables) |
| Complete YAML config example | [YAML Configuration](#yaml-configuration) |
| Config validation helper | [Config Validation](#config-validation) |
| Dry-run mode for audit | [Audit Dry-Run Mode](#audit-dry-run-mode) |
| Auto-resolve for recovered sources | [Auto-Resolve Pattern](#auto-resolve-pattern) |
| Centralized source priority config | [Centralized Source Priority](#centralized-source-priority) |
| Quality issue format helper | [Quality Issue Formatting](#quality-issue-formatting) |
| Alert deduplication by batch | [Batch Alert Deduplication](#batch-alert-deduplication) |
| Implementation Q&A | [Implementation Questions](#implementation-questions) |

---

## Configurable Audit Tables

### Full Implementation: `/config/source_coverage_config.py`

```python
"""
Source Coverage Configuration

Centralizes configuration for the source coverage system.
Allows modification without code changes.
"""

from dataclasses import dataclass
from typing import List, Optional
import os
import yaml


@dataclass
class AuditTable:
    """Configuration for a table to check during audit"""
    table: str
    id_column: str
    priority: str = 'normal'  # 'critical', 'normal', 'low'


@dataclass
class AlertConfig:
    """Configuration for alert routing"""
    slack_channel: str
    slack_webhook_env_var: str = 'SLACK_WEBHOOK_URL'
    email_recipients: List[str] = None
    critical_escalation: List[str] = None


@dataclass
class SourceCoverageConfig:
    """Main configuration container"""
    audit_tables: List[AuditTable]
    alerts: AlertConfig

    # Quality thresholds
    gold_min_score: float = 95.0
    silver_min_score: float = 75.0
    bronze_min_score: float = 50.0
    poor_min_score: float = 25.0

    # Sample size defaults
    default_expected_sample: int = 10
    early_season_sample: int = 3
    mid_season_sample: int = 5

    @classmethod
    def from_yaml(cls, path: str) -> 'SourceCoverageConfig':
        """Load configuration from YAML file"""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        audit_tables = [
            AuditTable(**t) for t in data.get('audit_tables', [])
        ]

        alerts = AlertConfig(**data.get('alerts', {}))

        return cls(
            audit_tables=audit_tables,
            alerts=alerts,
            **{k: v for k, v in data.items()
               if k not in ['audit_tables', 'alerts']}
        )

    @classmethod
    def default(cls) -> 'SourceCoverageConfig':
        """Return default configuration"""
        return cls(
            audit_tables=[
                AuditTable('nba_raw.nbac_team_boxscore', 'game_id', 'critical'),
                AuditTable('nba_raw.nbac_player_boxscore', 'game_id', 'critical'),
                AuditTable('nba_analytics.player_game_summary', 'game_id', 'critical'),
                AuditTable('nba_analytics.team_offense_game_summary', 'game_id', 'normal'),
            ],
            alerts=AlertConfig(
                slack_channel='#nba-data-quality',
                email_recipients=['naji@example.com'],
                critical_escalation=['naji@example.com']
            )
        )


# Global config instance
_config: Optional[SourceCoverageConfig] = None


def get_config() -> SourceCoverageConfig:
    """Get or create configuration instance"""
    global _config

    if _config is None:
        config_path = os.environ.get('SOURCE_COVERAGE_CONFIG')
        if config_path and os.path.exists(config_path):
            _config = SourceCoverageConfig.from_yaml(config_path)
        else:
            _config = SourceCoverageConfig.default()

    return _config
```

---

## YAML Configuration

### Example: `/config/source_coverage.yaml`

```yaml
# Source Coverage Configuration
# Environment: Production

audit_tables:
  # Phase 2 - Critical
  - table: nba_raw.nbac_team_boxscore
    id_column: game_id
    priority: critical
  - table: nba_raw.nbac_player_boxscore
    id_column: game_id
    priority: critical

  # Phase 3 - Critical
  - table: nba_analytics.player_game_summary
    id_column: game_id
    priority: critical
  - table: nba_analytics.team_offense_game_summary
    id_column: game_id
    priority: normal
  - table: nba_analytics.team_defense_game_summary
    id_column: game_id
    priority: normal

  # Phase 4 - Normal
  - table: nba_precompute.player_daily_cache
    id_column: game_id
    priority: normal

alerts:
  slack_channel: "#nba-data-quality"
  slack_webhook_env_var: SLACK_WEBHOOK_URL
  email_recipients:
    - naji@example.com
  critical_escalation:
    - naji@example.com

# Quality score thresholds
gold_min_score: 95.0
silver_min_score: 75.0
bronze_min_score: 50.0
poor_min_score: 25.0

# Sample size expectations
default_expected_sample: 10
early_season_sample: 3
mid_season_sample: 5
```

---

## Config Validation

### Add to `source_coverage_config.py`

```python
def validate_config(self) -> List[str]:
    """Validate configuration and return any issues"""
    issues = []

    if not self.audit_tables:
        issues.append("No audit tables configured")

    if not self.alerts.slack_channel:
        issues.append("No Slack channel configured")

    # Check for duplicate tables
    table_names = [t.table for t in self.audit_tables]
    if len(table_names) != len(set(table_names)):
        issues.append("Duplicate tables in audit_tables")

    # Validate thresholds are in correct order
    if not (self.gold_min_score > self.silver_min_score >
            self.bronze_min_score > self.poor_min_score):
        issues.append("Quality thresholds not in descending order")

    return issues
```

---

## Audit Dry-Run Mode

### Add to `SourceCoverageAuditProcessor`

```python
class SourceCoverageAuditProcessor:
    """
    Daily audit with optional dry-run mode.
    """

    DRY_RUN = os.environ.get('AUDIT_DRY_RUN', 'false').lower() == 'true'

    def handle_coverage_issue(self, game: Dict, status: Dict):
        """Handle detected coverage issue"""
        if status['status'] == 'normal':
            return

        if self.DRY_RUN:
            # Log what would happen without making changes
            logger.info(f"[DRY RUN] Would create synthetic event for {game['game_id']}")
            logger.info(f"[DRY RUN] Severity: {status['severity']}")
            logger.info(f"[DRY RUN] Description: {status['description']}")

            if status['severity'] == 'critical':
                logger.info(f"[DRY RUN] Would send critical alert")

            return

        # Normal execution
        event_id = self.create_synthetic_event(game, status)
        # ... rest of method
```

**Usage:**
```bash
# Test audit logic without creating events
AUDIT_DRY_RUN=true python -m data_processors.source_coverage_audit
```

---

## Quality Version Tracking (Optional)

If you need to track re-calculations of quality scores:

```sql
-- Add to standard quality columns
ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN IF NOT EXISTS quality_version INT64 DEFAULT 1;

-- Increment when quality is recalculated
UPDATE nba_analytics.player_game_summary
SET
  quality_version = quality_version + 1,
  quality_tier = 'gold',
  quality_score = 95.0,
  quality_metadata = JSON_SET(
    quality_metadata,
    '$.recalculated_at', CAST(CURRENT_TIMESTAMP() AS STRING),
    '$.previous_tier', quality_tier
  )
WHERE game_id = 'XXX';
```

**Note:** This was marked as "optional - skip for now" in the review.
The existing `quality_metadata` JSON field can track backfills without an extra column.

---

## Auto-Resolve Pattern

Automatically mark events as resolved when sources recover:

```python
# Add to audit job or as separate cleanup job

class SourceRecoveryChecker:
    """Check if previously missing sources have recovered."""

    def auto_resolve_recovered_sources(self, lookback_days: int = 7):
        """
        Mark events as resolved when source subsequently succeeds.

        Logic:
        - If game X had 'source_missing' event yesterday
        - But game X now has data in raw tables
        - Auto-set is_resolved = TRUE, resolution_method = 'source_recovered'
        """
        query = """
        UPDATE nba_reference.source_coverage_log AS log
        SET
            is_resolved = TRUE,
            resolved_at = CURRENT_TIMESTAMP(),
            resolution_method = 'source_recovered',
            resolved_by = 'auto_recovery_checker'
        WHERE
            is_resolved = FALSE
            AND event_type IN ('source_missing', 'fallback_used')
            AND DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_days DAY)
            AND EXISTS (
                -- Check if data now exists in raw tables
                SELECT 1 FROM nba_raw.nbac_team_boxscore raw
                WHERE raw.game_id = log.game_id
            )
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days)
            ]
        )

        result = self.bq_client.query(query, job_config=job_config).result()
        logger.info(f"Auto-resolved {result.num_dml_affected_rows} events")
```

**Schedule:** Run daily after audit job, or as part of audit job.

---

## Centralized Source Priority

Instead of each processor defining its own sources:

### `/config/source_priority.yaml`

```yaml
# Centralized source priority configuration
# Makes it easy to adjust priority globally when a source becomes unreliable

team_boxscore:
  primary: nbac_team_boxscore
  fallbacks:
    - espn_team_boxscore
    - bdl_box_scores
  reconstruction_allowed: true
  reconstruction_method: sum_player_stats

player_boxscore:
  primary: nbac_gamebook_player_stats
  fallbacks:
    - bdl_player_boxscores
    - espn_game_boxscore
  reconstruction_allowed: false

play_by_play:
  primary: bigdataball_play_by_play
  fallbacks:
    - nbac_play_by_play
  reconstruction_allowed: false

betting_lines:
  primary: odds_api_player_props
  fallbacks:
    - bp_player_props
  reconstruction_allowed: false
```

### Usage in Processor

```python
from config.source_priority import get_source_config

class PlayerGameSummaryProcessor(FallbackSourceMixin, QualityMixin, BaseProcessor):

    def __init__(self):
        config = get_source_config('player_boxscore')
        self.PRIMARY_SOURCES = [config['primary']]
        self.FALLBACK_SOURCES = config['fallbacks']
        self.RECONSTRUCTION_ALLOWED = config['reconstruction_allowed']
```

---

## Quality Issue Formatting

Enforce consistent issue format with helper:

```python
# shared_services/utils/quality_helpers.py

def format_quality_issue(prefix: str, detail: str = None) -> str:
    """
    Create standardized quality issue string.

    Examples:
        format_quality_issue('thin_sample', '3/10') -> 'thin_sample:3/10'
        format_quality_issue('backup_source_used') -> 'backup_source_used'
    """
    if detail:
        return f"{prefix}:{detail}"
    return prefix


def parse_quality_issue(issue: str) -> tuple:
    """
    Parse quality issue string into prefix and detail.

    Examples:
        parse_quality_issue('thin_sample:3/10') -> ('thin_sample', '3/10')
        parse_quality_issue('backup_source_used') -> ('backup_source_used', None)
    """
    if ':' in issue:
        prefix, detail = issue.split(':', 1)
        return prefix, detail
    return issue, None


# Standard issue prefixes (for validation)
QUALITY_ISSUE_PREFIXES = {
    'thin_sample',
    'missing_required',
    'missing_optional',
    'high_null_rate',
    'backup_source_used',
    'reconstructed',
    'early_season',
    'stale_data',
}


def validate_quality_issue(issue: str) -> bool:
    """Check if issue uses a known prefix."""
    prefix, _ = parse_quality_issue(issue)
    return prefix in QUALITY_ISSUE_PREFIXES
```

---

## Batch Alert Deduplication

Use `batch_id` to avoid alert storms:

```python
def _should_send_alert(self, event_data: Dict) -> bool:
    """
    Determine if alert should be sent, considering batch deduplication.

    If this is part of a batch (e.g., 26 player fallbacks from same game),
    only send ONE alert for the batch, not 26 alerts.
    """
    batch_id = event_data.get('batch_id')

    if batch_id:
        # Check if we already sent an alert for this batch
        query = f"""
        SELECT COUNT(*) as alert_count
        FROM nba_reference.source_coverage_log
        WHERE batch_id = '{batch_id}'
          AND alert_sent = TRUE
        """
        result = self.bq_client.query(query).to_dataframe()

        if result.iloc[0]['alert_count'] > 0:
            # Already alerted for this batch
            return False

    # Check standard deduplication (same game + type in last 4 hours)
    return not self._already_alerted_recently(event_data)


def _create_batch_id(self, game_id: str) -> str:
    """Create batch ID for grouping related events."""
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M')
    return f"{self.__class__.__name__}_{game_id}_{timestamp}"
```

**Alert message for batched events:**
```python
def _format_batch_alert(self, batch_events: List[Dict]) -> str:
    """Format alert for a batch of events."""
    game_id = batch_events[0]['game_id']
    event_type = batch_events[0]['event_type']
    count = len(batch_events)

    return f"""
Source Coverage Alert: {event_type}

Game: {game_id}
Affected: {count} players
Batch ID: {batch_events[0]['batch_id']}

This is a batched alert. Individual events logged in source_coverage_log.
    """.strip()
```

---

## Implementation Questions

### Q1: What's the expected bronze rate tolerance?

**Answer:** Season-aware thresholds:

| Period | Bronze Rate Tolerance | Rationale |
|--------|----------------------|-----------|
| October (first 2 weeks) | 30% acceptable | Players have < 5 games |
| November | 20% acceptable | Players have 5-15 games |
| December onwards | < 10% target | Full sample available |
| Playoffs | < 5% target | Critical period |

**Implementation:**
```python
def get_bronze_rate_threshold(game_date: date) -> float:
    """Get acceptable bronze rate based on season progress."""
    games_into_season = _get_games_into_season(game_date)

    if games_into_season < 10:
        return 0.30  # 30% acceptable
    elif games_into_season < 30:
        return 0.20  # 20% acceptable
    else:
        return 0.10  # 10% target
```

### Q2: Should audit job check games more than 7 days old?

**Answer:** No, with exceptions:

- **Default:** Only check last 7 days (avoids noise from known historical gaps)
- **Exception:** Add `--full-audit` flag for monthly comprehensive check
- **Exception:** Specific game_ids can be checked on-demand

```python
def run_daily_audit(self, target_date: date = None, full_audit: bool = False):
    """
    Args:
        target_date: Specific date to audit (default: yesterday)
        full_audit: If True, check last 90 days (monthly maintenance)
    """
    if full_audit:
        start_date = target_date - timedelta(days=90)
    else:
        start_date = target_date - timedelta(days=7)
```

### Q3: What happens to unusable-tier predictions?

**Answer:** Three-tier handling:

1. **Skip prediction entirely** - Don't create a row in predictions table
2. **Log event** - Record why prediction was skipped
3. **API/UI handling** - Return "insufficient data" message

```python
def generate_prediction(self, player_id: str, game_id: str) -> Optional[Dict]:
    """Generate prediction with quality gate."""

    features = self.get_features(player_id, game_id)

    if features['quality_tier'] == 'unusable':
        self.log_quality_event(
            event_type=SourceCoverageEventType.QUALITY_DEGRADATION,
            severity=SourceCoverageSeverity.WARNING,
            description=f"Prediction skipped due to unusable quality tier",
            player_id=player_id,
            game_id=game_id,
            downstream_impact='prediction_skipped'
        )
        return None  # No prediction generated

    # Continue with prediction...
```

**API Response for Skipped Predictions:**
```json
{
  "player_id": "abc123",
  "game_id": "0022400001",
  "prediction": null,
  "reason": "insufficient_data",
  "quality_tier": "unusable",
  "quality_issues": ["missing_required:points_history", "thin_sample:1/10"]
}
```

---

## Review Summary

### Original Review Assessment: 9/10

**Strengths identified:**
- Season-aware thresholds (critical insight)
- Configurable audit tables (clear improvement)
- Explicit backfill script (fills documentation gap)
- Edge case tests (good safety net)

**What was skipped:**
- Quality version tracking (existing metadata is sufficient)

### Implementation Priority

1. **Streaming buffer migration** - Do first (prerequisite)
2. **Core source coverage** - Parts 1-4 of this documentation
3. **Configurable audit** - This file (optional enhancement)

---

## Change Log

| Date | Change |
|------|--------|
| 2025-11-26 | Created from Opus review recommendations |
| 2025-11-26 | Added: batch_id, auto-resolve, centralized config, batch deduplication, Q&A |

---

*This is reference material. The main implementation is in Parts 1-4.*
