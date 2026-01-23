# Implementation Plan

**Last Updated:** 2026-01-22
**Status:** Planning

## Overview

This document outlines the step-by-step implementation plan for the Player Registry Auto-Resolution Pipeline.

## Phase 1: Diagnostics and Quick Wins (Day 1)

### 1.1 Verify Current Scheduled Jobs

**Task:** Check if existing resolution jobs are running

```bash
# Check job configuration
gcloud scheduler jobs describe registry-ai-resolution --location=us-west2

# Check recent runs
gcloud logging read 'resource.labels.job_name="registry-ai-resolution"' \
  --limit=20 --freshness=7d

# Check Cloud Run service logs
gcloud logging read 'resource.labels.service_name="nba-reference-service"' \
  --limit=50 --freshness=24h
```

**Expected Outcome:** Understand why existing jobs aren't resolving players.

### 1.2 Run Manual Batch Resolution

**Task:** Test the existing batch resolution tool

```bash
# Dry run first
python tools/player_registry/resolve_unresolved_batch.py --limit 100 --dry-run

# If dry run looks good, run for real
python tools/player_registry/resolve_unresolved_batch.py --limit 100
```

**Expected Outcome:** Resolve 50-80 of the 100 players (high confidence cases).

### 1.3 Quick Win: Fix High-Confidence Cases

**Task:** Auto-resolve fuzzy matches ≥95%

```python
# New script: tools/player_registry/auto_resolve_high_confidence.py
def auto_resolve_high_confidence():
    """Resolve unresolved names with ≥95% fuzzy match."""

    unresolved = query("""
        SELECT normalized_lookup, team_abbr, season
        FROM nba_reference.unresolved_player_names
        WHERE status = 'pending'
    """)

    for player in unresolved:
        # Get best fuzzy match from registry
        match = get_best_fuzzy_match(
            player.normalized_lookup,
            team_filter=player.team_abbr,
            season_filter=player.season
        )

        if match and match.score >= 0.95:
            # Verify same team/season
            if verify_team_season(match.canonical, player.team_abbr, player.season):
                create_alias(player.normalized_lookup, match.canonical)
                mark_resolved(player.normalized_lookup, method='fuzzy_auto')
                log_resolution(player, match, confidence=match.score)
```

**Expected Outcome:** Auto-resolve ~500-1000 players immediately.

---

## Phase 2: Enhanced Auto-Resolution Job (Days 2-3)

### 2.1 Create New Auto-Resolution Pipeline

**File:** `orchestration/jobs/auto_resolution_pipeline.py`

```python
"""
Automated Player Resolution Pipeline

Runs nightly at 3:00 AM ET. Processes unresolved players in stages:
1. High confidence fuzzy matching (≥95%)
2. AI resolution for medium confidence (80-95%)
3. Queue low confidence for manual review
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict

from shared.utils.player_registry.resolver import PlayerResolver
from shared.utils.player_registry.ai_resolver import AINameResolver
from shared.utils.player_registry.alias_manager import AliasManager
from shared.clients.bigquery_pool import get_bq_client

logger = logging.getLogger(__name__)

class AutoResolutionPipeline:

    def __init__(self):
        self.bq = get_bq_client()
        self.resolver = PlayerResolver()
        self.ai_resolver = AINameResolver()
        self.alias_manager = AliasManager()
        self.stats = {
            'fuzzy_resolved': 0,
            'ai_resolved': 0,
            'ai_new_player': 0,
            'ai_invalid': 0,
            'needs_review': 0,
            'errors': 0
        }

    def run(self, limit: int = 500) -> Dict:
        """Run the full resolution pipeline."""
        logger.info(f"Starting auto-resolution pipeline (limit={limit})")

        # Get pending unresolved players
        unresolved = self._get_pending_unresolved(limit)
        logger.info(f"Found {len(unresolved)} pending unresolved players")

        # Stage 1: High confidence fuzzy matching
        remaining = self._stage1_fuzzy_match(unresolved)

        # Stage 2: AI resolution
        remaining = self._stage2_ai_resolution(remaining)

        # Stage 3: Mark remaining for review
        self._stage3_queue_for_review(remaining)

        # Log summary
        self._log_summary()

        return self.stats

    def _stage1_fuzzy_match(self, unresolved: List[Dict]) -> List[Dict]:
        """Stage 1: Auto-resolve high confidence fuzzy matches."""
        logger.info("Stage 1: Fuzzy matching (≥95% confidence)")
        remaining = []

        for player in unresolved:
            match = self._get_best_fuzzy_match(player)

            if match and match['score'] >= 0.95:
                if self._verify_team_season(match, player):
                    self._create_alias_and_resolve(player, match, method='fuzzy_auto')
                    self.stats['fuzzy_resolved'] += 1
                else:
                    remaining.append(player)
            else:
                remaining.append(player)

        logger.info(f"Stage 1 complete: {self.stats['fuzzy_resolved']} resolved, {len(remaining)} remaining")
        return remaining

    def _stage2_ai_resolution(self, unresolved: List[Dict]) -> List[Dict]:
        """Stage 2: AI resolution for medium confidence cases."""
        logger.info("Stage 2: AI resolution")
        remaining = []

        # Batch process for efficiency
        batch_size = 50
        for i in range(0, len(unresolved), batch_size):
            batch = unresolved[i:i+batch_size]
            results = self.ai_resolver.resolve_batch(batch)

            for player, result in zip(batch, results):
                if result['decision'] == 'MATCH' and result['confidence'] >= 0.80:
                    self._create_alias_and_resolve(
                        player,
                        {'canonical': result['canonical_lookup']},
                        method='ai_resolution'
                    )
                    self.stats['ai_resolved'] += 1

                elif result['decision'] == 'NEW_PLAYER' and result['confidence'] >= 0.80:
                    self._create_new_registry_entry(player, result)
                    self.stats['ai_new_player'] += 1

                elif result['decision'] == 'DATA_ERROR' and result['confidence'] >= 0.80:
                    self._mark_invalid(player, result)
                    self.stats['ai_invalid'] += 1

                else:
                    # Low confidence - needs review
                    remaining.append(player)

        logger.info(f"Stage 2 complete: {self.stats['ai_resolved']} matched, "
                   f"{self.stats['ai_new_player']} new, {len(remaining)} remaining")
        return remaining

    def _stage3_queue_for_review(self, unresolved: List[Dict]):
        """Stage 3: Queue remaining for manual review."""
        logger.info(f"Stage 3: Queueing {len(unresolved)} for manual review")

        for player in unresolved:
            self._mark_needs_review(player)
            self.stats['needs_review'] += 1

    # ... helper methods ...
```

### 2.2 Create Scheduler Job

```bash
# Create Cloud Scheduler job
gcloud scheduler jobs create http auto-resolution-pipeline \
  --schedule="0 8 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-reference-service-xxx.run.app/auto-resolve" \
  --http-method=POST \
  --oidc-service-account-email="scheduler@nba-props-platform.iam.gserviceaccount.com" \
  --location=us-west2 \
  --description="Nightly auto-resolution of unresolved player names"
```

### 2.3 Add Endpoint to Reference Service

**File:** `services/reference_service/main.py`

```python
@app.route('/auto-resolve', methods=['POST'])
def auto_resolve():
    """Run automated player resolution pipeline."""
    from orchestration.jobs.auto_resolution_pipeline import AutoResolutionPipeline

    pipeline = AutoResolutionPipeline()
    stats = pipeline.run(limit=500)

    # Send summary to Slack
    send_resolution_summary(stats)

    return jsonify({
        'status': 'success',
        'stats': stats
    })
```

---

## Phase 3: Enhanced Game Tracking (Days 4-5)

### 3.1 Expand Game Tracking Beyond 10 Examples

**Current Issue:** `example_games` array only stores 10 game IDs.

**Solution:** Create separate table for full game tracking.

```sql
-- New table: registry_affected_games
CREATE TABLE nba_processing.registry_affected_games (
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  team_abbr STRING,
  source_table STRING,
  first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  reprocessed_at TIMESTAMP,
  PRIMARY KEY (player_lookup, game_id)
)
PARTITION BY DATE(game_date)
CLUSTER BY player_lookup;
```

**Update logging code:**

```python
# In shared/utils/player_registry/reader.py
def _log_unresolved_player(self, player_lookup: str, context: dict):
    """Log unresolved player with full game tracking."""

    # Existing: Log to unresolved_player_names (summary)
    self._log_to_unresolved_names(player_lookup, context)

    # NEW: Log to registry_affected_games (full tracking)
    self._log_affected_game(
        player_lookup=player_lookup,
        game_id=context.get('game_id'),
        game_date=context.get('game_date'),
        team_abbr=context.get('team_abbr'),
        source_table=context.get('source_table')
    )
```

---

## Phase 4: Auto-Reprocessing Pipeline (Days 6-7)

### 4.1 Create Reprocessing Orchestrator

**File:** `orchestration/jobs/reprocessing_orchestrator.py`

```python
"""
Reprocessing Orchestrator

Runs after auto-resolution (3:30 AM ET).
Finds games affected by newly resolved players and reprocesses them.
"""

class ReprocessingOrchestrator:

    def __init__(self):
        self.bq = get_bq_client()
        self.processor = PlayerGameSummaryProcessor()
        self.stats = {
            'players_processed': 0,
            'games_reprocessed': 0,
            'games_failed': 0,
            'cascade_triggered': 0
        }

    def run(self, since_hours: int = 24) -> Dict:
        """Reprocess games for recently resolved players."""

        # Find newly resolved players
        resolved_players = self._get_recently_resolved(since_hours)
        logger.info(f"Found {len(resolved_players)} recently resolved players")

        for player in resolved_players:
            self._reprocess_player_games(player)

        return self.stats

    def _reprocess_player_games(self, player: Dict):
        """Reprocess all affected games for a player."""

        # Get ALL affected games (not just 10)
        games = self._get_affected_games(player['player_lookup'])

        # Sort by date DESCENDING (newest first - most important)
        games = sorted(games, key=lambda g: g['game_date'], reverse=True)

        # Apply age-based filtering
        games = self._filter_by_age(games)

        logger.info(f"Reprocessing {len(games)} games for {player['player_lookup']}")

        for game in games:
            try:
                result = self.processor.process_single_game(
                    game_id=game['game_id'],
                    season=game['season']
                )

                if result['success']:
                    self._mark_game_reprocessed(player['player_lookup'], game['game_id'])
                    self.stats['games_reprocessed'] += 1

                    # Trigger downstream cascade
                    self._trigger_cascade(game, result['players_updated'])
                else:
                    self.stats['games_failed'] += 1

            except Exception as e:
                logger.error(f"Failed to reprocess game {game['game_id']}: {e}")
                self.stats['games_failed'] += 1

        self.stats['players_processed'] += 1

    def _filter_by_age(self, games: List[Dict]) -> List[Dict]:
        """Apply age-based filtering rules."""
        today = date.today()
        filtered = []

        for game in games:
            age_days = (today - game['game_date']).days

            # Always include games < 7 days old
            if age_days < 7:
                filtered.append(game)

            # Include 7-30 day games if they had prop lines
            elif age_days < 30 and game.get('had_prop_lines'):
                filtered.append(game)

            # Skip older games (can be backfilled separately)

        return filtered

    def _trigger_cascade(self, game: Dict, players: List[str]):
        """Trigger Phase 4/5 cascade for affected players."""
        for player_id in players:
            publish_message('phase4-precompute-trigger', {
                'player_id': player_id,
                'game_id': game['game_id'],
                'trigger_source': 'registry_resolution',
                'timestamp': datetime.utcnow().isoformat()
            })
            self.stats['cascade_triggered'] += 1
```

### 4.2 Create Scheduler Job for Reprocessing

```bash
gcloud scheduler jobs create http registry-reprocessing \
  --schedule="30 8 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-reference-service-xxx.run.app/reprocess-resolved" \
  --http-method=POST \
  --oidc-service-account-email="scheduler@nba-props-platform.iam.gserviceaccount.com" \
  --location=us-west2 \
  --description="Reprocess games for recently resolved players"
```

---

## Phase 5: Monitoring and Alerting (Day 8)

### 5.1 Daily Summary Slack Notification

**File:** `orchestration/jobs/registry_daily_summary.py`

```python
def send_daily_summary():
    """Send daily registry resolution summary to Slack."""

    stats = query("""
        SELECT
            COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
            COUNT(CASE WHEN status = 'resolved' AND resolved_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR) THEN 1 END) as resolved_24h,
            COUNT(CASE WHEN status = 'needs_review' THEN 1 END) as needs_review,
            COUNT(CASE WHEN status = 'invalid' THEN 1 END) as invalid
        FROM nba_reference.unresolved_player_names
    """)

    reprocess_stats = query("""
        SELECT COUNT(*) as games_reprocessed
        FROM nba_processing.registry_affected_games
        WHERE reprocessed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    """)

    message = f"""
:robot_face: *Daily Player Registry Summary*

*Resolution Stats (24h):*
• Resolved: {stats.resolved_24h}
• Pending: {stats.pending}
• Needs Review: {stats.needs_review}

*Reprocessing:*
• Games Reprocessed: {reprocess_stats.games_reprocessed}

{':warning: Action needed: ' + str(stats.needs_review) + ' players need manual review' if stats.needs_review > 0 else ':white_check_mark: No manual review needed'}
    """

    send_slack_message('#registry-alerts', message)
```

### 5.2 Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Pending unresolved | >100 new/day | >500 new/day |
| Resolution failure rate | >10% | >25% |
| Reprocessing failure rate | >5% | >15% |
| AI cost per day | >$0.50 | >$1.00 |

---

## Implementation Timeline

| Phase | Description | Duration | Dependencies |
|-------|-------------|----------|--------------|
| Phase 1 | Diagnostics + Quick Wins | 1 day | None |
| Phase 2 | Auto-Resolution Pipeline | 2 days | Phase 1 |
| Phase 3 | Enhanced Game Tracking | 2 days | Phase 2 |
| Phase 4 | Auto-Reprocessing | 2 days | Phase 2, 3 |
| Phase 5 | Monitoring & Alerting | 1 day | Phase 2, 4 |
| **Total** | | **8 days** | |

## Success Criteria

| Metric | Before | Target | How to Measure |
|--------|--------|--------|----------------|
| Manual review rate | 100% | <5% | `needs_review / total_resolved` |
| Time to resolution | Never (stuck) | <24h | `resolved_at - first_seen_at` |
| Reprocessing coverage | 0% | 100% | `reprocessed / resolved` |
| Prediction gap | Unknown | 0 | Players with lines but no prediction |

## Rollback Plan

If issues occur:

1. **Disable scheduler jobs**
   ```bash
   gcloud scheduler jobs pause auto-resolution-pipeline --location=us-west2
   gcloud scheduler jobs pause registry-reprocessing --location=us-west2
   ```

2. **Revert to manual resolution**
   ```bash
   python -m tools.player_registry.resolve_unresolved_names interactive
   ```

3. **Investigate and fix**
   - Check logs: `gcloud logging read 'resource.labels.service_name="nba-reference-service"'`
   - Review failed resolutions in `resolution_audit_log`
   - Fix issues and re-enable jobs
