# Future Improvements: Prediction Coverage

**Created:** December 30, 2025
**Status:** Backlog for consideration

This document captures additional improvements and investigations identified during the prediction coverage fix project.

---

## P1 - High Priority (This Week)

### 1. Test Staging Pattern in Production

**Status:** CRITICAL - Fix deployed but not tested

**Action:** Trigger Dec 30 predictions and verify:
- [ ] Staging tables created correctly
- [ ] Consolidation completes without error
- [ ] All expected players get predictions
- [ ] Staging tables cleaned up after

**Verification:**
```bash
# After predictions run
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as preds, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2025-12-30' AND is_active = TRUE GROUP BY 1"

# Check for orphaned staging tables
bq query --use_legacy_sql=false "
SELECT table_id FROM \`nba-props-platform.nba_predictions.__TABLES__\`
WHERE table_id LIKE '_staging_%'"
```

### 2. Add Remaining Player Aliases

**Status:** 7 of ~15 aliases added

**Missing aliases to add:**
```sql
INSERT INTO `nba-props-platform.nba_reference.player_aliases`
(alias_lookup, nba_canonical_lookup, alias_type, alias_source, is_active, created_by, created_at, processed_at)
VALUES
('kevinporterjr', 'kevinporter', 'suffix_variation', 'odds_api', TRUE, 'fix_dec30', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('timhardawayjr', 'timhardaway', 'suffix_variation', 'odds_api', TRUE, 'fix_dec30', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('wendellcarterjr', 'wendellcarter', 'suffix_variation', 'odds_api', TRUE, 'fix_dec30', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()),
('nicolasclaxton', 'nicclaxton', 'nickname', 'odds_api', TRUE, 'fix_dec30', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP());
```

**Note:** Need to verify canonical names exist in registry before adding.

### 3. Backfill Dec 29 Predictions

**Status:** Dec 29 has only 68 players (43% coverage)

**Options:**
1. Force re-run Dec 29 with fixed code
2. Mark Dec 29 as known-incomplete
3. Wait for next game day to validate fix first

**Command:**
```bash
curl -X POST https://prediction-coordinator-756957797294.us-west2.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-12-29", "force": true}'
```

---

## P2 - Medium Priority (Next Week)

### 4. Integrate RegistryReader into OddsApiPropsProcessor

**Problem:** Odds processor uses `normalize_name()` without registry lookup, causing name mismatches.

**Current code (broken):**
```python
# data_processors/raw/oddsapi/odds_api_props_processor.py:482
'player_lookup': normalize_name(player_name)
```

**Proposed fix:**
```python
from shared.utils.player_registry import RegistryReader

class OddsApiPropsProcessor:
    def __init__(self):
        self.registry = RegistryReader(
            source_name='odds_api_props',
            cache_ttl_seconds=300
        )

    def _resolve_player_lookup(self, player_name: str) -> str:
        """Resolve player name to canonical lookup."""
        raw_lookup = normalize_name(player_name)

        try:
            uid = self.registry.get_universal_id(raw_lookup, required=False)
            if uid:
                # Extract canonical lookup from universal_player_id
                return uid.rsplit('_', 1)[0]
        except Exception as e:
            logger.debug(f"Registry lookup failed for {raw_lookup}: {e}")

        return raw_lookup  # Fallback to raw
```

**Files to update:**
- `data_processors/raw/oddsapi/odds_api_props_processor.py`
- `data_processors/raw/bettingpros/bettingpros_player_props_processor.py`

### 5. Configure Cloud Monitoring Alert Policies

**Missing alerts:**
1. DML rate limit errors (metric: `prediction_dml_rate_limit_total`)
2. Coverage below 95% (metric: `predictions/coverage_percent`)
3. Coverage below 85% (critical)
4. Consolidation failures
5. Write latency > 10s (p95)

**Action:** Create alert policies in Cloud Monitoring console or via Terraform.

### 6. Add Coverage Dashboard Page

**Problem:** Admin dashboard doesn't have dedicated coverage visibility.

**Proposed:**
- `/api/coverage-metrics/<date>` endpoint
- Coverage trend visualization
- Per-system breakdown
- Missing players list

### 7. Fix Registry Duplicate Entries

**Problem:** Same player has multiple universal_player_ids:
```
garytrent   → garytrent_001
garytrentjr → garytrentjr_001  -- Should be same player!
```

**Solution:**
1. Identify all duplicate entries (base name + suffix variations)
2. Select canonical universal_player_id
3. Create aliases for variants
4. Update all references in downstream tables

**Investigation query:**
```sql
SELECT
  REGEXP_REPLACE(player_lookup, r'(jr|sr|ii|iii|iv)$', '') as base_name,
  COUNT(DISTINCT universal_player_id) as id_count,
  STRING_AGG(DISTINCT player_lookup) as lookups,
  STRING_AGG(DISTINCT universal_player_id) as ids
FROM `nba-props-platform.nba_players_registry`
GROUP BY base_name
HAVING id_count > 1
ORDER BY id_count DESC;
```

---

## P3 - Future Improvements

### 8. Auto-Reduce Concurrency on DML Errors

**Current:** Manual `gcloud run services update` command.

**Proposed:** Automatic via Cloud Run Admin API when threshold exceeded.

**Implementation sketch:**
```python
def auto_reduce_concurrency():
    """Reduce concurrency via Cloud Run API."""
    from google.cloud import run_v2

    client = run_v2.ServicesClient()
    service = client.get_service(name="projects/.../services/prediction-worker")

    # Reduce max instances
    service.template.max_instance_request_concurrency = 3
    service.template.scaling.max_instance_count = 4

    client.update_service(service=service)
```

**Concerns:**
- Need proper IAM permissions
- Should have cooldown to prevent flapping
- Need notification on auto-reduce

### 9. Streaming Buffer Alternative

**Idea:** Use BigQuery streaming inserts instead of batch loads.

**Pros:**
- Real-time data availability
- No staging tables needed

**Cons:**
- Streaming quota limits (100k rows/sec/project)
- 90-minute buffer before DML allowed
- More expensive

**Decision:** Staging pattern is better for our use case.

### 10. Prediction System Latency Tracking

**Missing metrics:**
- Per-system prediction latency (moving_average, xgboost, etc.)
- Feature loading latency
- Historical games loading latency

**Value:** Identify slow systems for optimization.

### 11. Dead Letter Queue for Failed Predictions

**Problem:** If a prediction fails after retries, it's lost.

**Proposed:**
- Pub/Sub dead letter topic for failed messages
- Periodic retry of dead letter messages
- Dashboard visibility into failures

### 12. Integration Tests for Staging Pattern

**Current:** No tests for staging write → consolidation flow.

**Proposed tests:**
1. Single worker writes to staging successfully
2. Multiple workers write without conflict
3. Consolidation merges correctly with deduplication
4. Staging tables cleaned up after success
5. Orphaned tables cleaned up on failure

---

## Investigation Items

### Why Some Players Have No Context

15 players had odds lines but were NOT_IN_CONTEXT. Need to investigate:
- Are they on active rosters?
- Do they have sufficient minutes projection?
- Is schedule data missing for their games?

### Consolidation Performance at Scale

With 158 staging tables, the MERGE query unions all of them. Questions:
- How long does this take?
- Does it hit any BigQuery limits?
- Should we batch the consolidation (merge 50 at a time)?

### Write Success vs Coverage Gap

The staging pattern fixes write success, but coverage depends on more:
- Feature quality thresholds
- Min minutes filtering
- Circuit breaker state
- Model prediction failures

Need to distinguish between:
1. Predictions generated but not written (DML - fixed)
2. Predictions not generated (different issue)

### Alias Resolution Timing

Aliases are resolved at different stages:
1. Odds ingestion → Not resolved (bug)
2. Context building → Resolved via registry
3. Prediction worker → Uses context lookup

Should we resolve at ingestion or leave for context?

---

## Decision Log

### Dec 30, 2025: Staging Pattern vs Retry

**Decision:** Implement staging pattern, not just retry.

**Reasoning:**
- Retry with backoff would slow down predictions
- 100 workers × 3 retries × 5s backoff = 25+ minutes
- Staging pattern eliminates the problem entirely
- Single MERGE is more efficient than 100 individual MERGEs

### Dec 29, 2025: Reduce Concurrency vs Full Fix

**Decision:** Reduce concurrency as emergency fix while implementing full solution.

**Reasoning:**
- Immediate relief: 12 concurrent < 20 DML limit
- Allows time to implement staging pattern properly
- Predictions run slower but at least complete

---

## Related Documentation

- [README.md](./README.md) - Project overview
- [INVESTIGATION-REPORT.md](./INVESTIGATION-REPORT.md) - Root cause analysis
- [PROGRESS-LOG.md](./PROGRESS-LOG.md) - Implementation progress
- [Handoff](../../09-handoff/2025-12-30-EARLY-MORNING-HANDOFF.md) - Session handoff
