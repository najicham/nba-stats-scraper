# Spot Check Integration with Data Lineage Integrity

**Date**: 2026-01-26
**Status**: Design Complete
**Related**: `/spot-check-*` skills, cascade contamination tracking

---

## Overview

The spot check skills are the **validation layer** of the data lineage integrity architecture. They detect gaps and contamination, while the prevention layer (ProcessingGate, WindowCompletenessValidator) prevents new contamination.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  DETECTION (Spot Check Skills)                                          │
│  ─────────────────────────────                                          │
│  • /spot-check-player - Deep dive on one player                        │
│  • /spot-check-gaps   - System-wide gap detection                      │
│  • /spot-check-date   - Single date audit                              │
│  • /spot-check-team   - Team roster audit                              │
│  • /spot-check-cascade - Downstream impact analysis                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  TRACKING (contamination_tracking table)                                │
│  ──────────────────────────────────────                                 │
│  • Record all gaps found                                                │
│  • Track backfill status                                                │
│  • Track remediation status                                             │
│  • Audit trail for compliance                                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  REMEDIATION (Cascade Reprocessing)                                     │
│  ─────────────────────────────────                                      │
│  • Backfill raw data                                                    │
│  • Reprocess player_game_summary                                        │
│  • Reprocess player_composite_factors                                   │
│  • Reprocess ml_feature_store                                           │
│  • Verify with /validate-lineage                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Spot Check Skills

### /spot-check-player

**Purpose**: Deep dive on a single player's game history

**Detects**:
- Games the player missed
- Whether absences are explained (injury, trade, DNP)
- Team changes and trade windows
- Data source inconsistencies

**When to Use**:
- Investigating a specific player's data
- After finding issues in `/spot-check-gaps`
- Verifying traded player's data is complete

### /spot-check-gaps

**Purpose**: System-wide audit of all unexplained gaps

**Detects**:
- ERROR_HAS_MINUTES: Player played but missing from analytics (BUG)
- ERROR_NOT_IN_BOXSCORE: Player missing from raw data
- DNP_NO_INJURY: Coach's decision (OK)
- INJURY_REPORT: Injury explains absence (OK)

**When to Use**:
- Weekly data quality audit
- After backfills to verify completeness
- Before ML model retraining

### /spot-check-date

**Purpose**: Check all players for a specific date

**Detects**:
- Players who played but are missing records
- Missing injury reports
- Scraper failures for specific dates

**When to Use**:
- After reports of missing data for a game
- Daily morning validation

### /spot-check-team

**Purpose**: Verify team roster data completeness

**Detects**:
- Players with incomplete coverage
- Trade window gaps
- Two-way player issues

**When to Use**:
- After trades affecting a team
- Team-specific investigations

### /spot-check-cascade (NEW)

**Purpose**: Analyze downstream impact of a gap

**Calculates**:
- Contamination windows (L5, L10, L15, L20)
- Affected tables and record counts
- Remediation commands

**When to Use**:
- After finding a gap, before/after backfilling
- Planning remediation scope
- Understanding historical contamination

---

## Gap Types and Actions

| Gap Type | Meaning | Cascade Impact | Action |
|----------|---------|----------------|--------|
| INJURY_REPORT | Player injured, properly flagged | None | None needed |
| DNP_NO_INJURY | Coach's decision | None | None needed |
| ERROR_NOT_IN_BOXSCORE | Missing from raw data | High if backfilled late | Investigate + remediate |
| ERROR_HAS_MINUTES | BUG - played but missing | High | Fix immediately + remediate |

---

## Cascade Contamination Tracking

### Three-Table Architecture

We track contamination through three related tables:

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. backfill_events (Immutable - what happened)                    │
│     - Record every backfill with timestamp, delay, scope           │
│     - Computed contamination windows (L5, L10, L15, L20)           │
│     - Never modified after creation                                │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│  2. contamination_records (Mutable - affected downstream)          │
│     - Links backfill to specific affected records                  │
│     - Quality scores: original → contaminated → final              │
│     - Remediation status tracked per record                        │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│  3. remediation_log (Audit - what we fixed)                        │
│     - Detailed log of each remediation job                         │
│     - Records processed, quality improvement metrics               │
│     - Links back to triggering backfill                            │
└─────────────────────────────────────────────────────────────────────┘
```

**Schema file**: `migrations/backfill_tracking_schema.sql`

### Why Three Tables?

| Table | Purpose | Mutability |
|-------|---------|------------|
| `backfill_events` | Audit trail of what was backfilled | Immutable |
| `contamination_records` | Track which downstream records are affected | Updated during remediation |
| `remediation_log` | Audit trail of fixes applied | Immutable |

This separation allows:
- **Compliance**: Immutable audit trail of events
- **Operations**: Track what still needs fixing
- **Analysis**: Measure quality improvement over time

### Views for Operations

```sql
-- What needs fixing?
SELECT * FROM nba_orchestration.v_pending_remediations;

-- Impact summary per backfill
SELECT * FROM nba_orchestration.v_backfill_impact_summary;
```

### Full Workflow

```
1. DETECT GAP
   /spot-check-gaps finds missing data

2. BACKFILL RAW DATA
   Run scraper/backfill job
   → INSERT INTO backfill_events

3. ANALYZE CASCADE
   /spot-check-cascade computes downstream impact
   → INSERT INTO contamination_records (one per affected downstream record)

4. REMEDIATE
   Run reprocessing scripts for downstream tables
   → INSERT INTO remediation_log
   → UPDATE contamination_records SET remediation_status='completed'

5. VERIFY
   /validate-lineage confirms quality improved
```

### Example: Full Backfill Flow

```sql
-- Step 1: Record backfill event
INSERT INTO nba_orchestration.backfill_events
(backfill_id, table_name, entity_id, game_date, hours_delayed,
 backfill_source, l5_contamination_end, l10_contamination_end)
VALUES
('bf-001', 'nba_raw.bdl_player_boxscores', 'lebron_james',
 '2026-01-15', 240, 'manual', '2026-01-22', '2026-01-26');

-- Step 2: Record contaminated downstream records
INSERT INTO nba_orchestration.contamination_records
(contamination_id, backfill_id, downstream_table, entity_id, game_date,
 affected_windows, contaminated_quality_score, remediation_status)
VALUES
('cr-001', 'bf-001', 'nba_precompute.player_composite_factors',
 'lebron_james', '2026-01-16', ['L5', 'L10'], 0.8, 'pending'),
('cr-002', 'bf-001', 'nba_precompute.player_composite_factors',
 'lebron_james', '2026-01-17', ['L5', 'L10'], 0.8, 'pending');
-- ... more records

-- Step 3: After remediation
INSERT INTO nba_orchestration.remediation_log
(remediation_id, target_table, player_lookup, start_date, end_date,
 records_processed, avg_quality_before, avg_quality_after, status)
VALUES
('rm-001', 'nba_precompute.player_composite_factors', 'lebron_james',
 '2026-01-16', '2026-01-26', 10, 0.8, 1.0, 'completed');

UPDATE nba_orchestration.contamination_records
SET remediation_status = 'completed',
    final_quality_score = 1.0,
    remediated_at = CURRENT_TIMESTAMP()
WHERE backfill_id = 'bf-001';
```

---

## Findings from Initial Audit (Jan 26, 2026)

### Data Coverage Gaps

| Data Source | Coverage | Issue |
|-------------|----------|-------|
| `nbac_injury_report` | Dec 19, 2025+ | Empty files Nov 14 - Dec 18 (bug fixed) |
| `nbac_player_movement` | Through Aug 2025 | Scraper not scheduled for production |

### Gap Detection Results

| Gap Type | Count | Players | Status |
|----------|-------|---------|--------|
| INJURY_REPORT | 826 | 217 | OK - expected |
| DNP_NO_INJURY | 979 | 296 | OK - coach's decision |
| ERROR_NOT_IN_BOXSCORE | 76 | 46 | Investigate |
| ERROR_HAS_MINUTES | 20 | 7 | **FIX REQUIRED** |

### Critical Issues Found

20 cases where players played actual minutes but are missing from analytics:

| Player | Date | Team | Minutes | Points | Likely Cause |
|--------|------|------|---------|--------|--------------|
| jimmybutler | Jan 19 | GSW | 21 | 17 | Just traded |
| kasparasjakuionis | Multiple | MIA | 1-27 | 0-12 | Recent trade |
| hansonsyang | Multiple | POR | 2-17 | 0-4 | New roster addition |
| nicolasclaxton | Jan 21 | BKN | 23 | 4 | Unknown |
| nahshonhyland | Multiple | MIN | 4-16 | 0-5 | Unknown |

---

## Recommended Weekly Workflow

### Monday Morning Audit

```bash
# 1. Run system-wide gap detection
/spot-check-gaps

# 2. For any ERROR_HAS_MINUTES, investigate immediately
/spot-check-cascade <player> <date>

# 3. For any concerning patterns, deep dive
/spot-check-player <player> 20

# 4. Update tracking table with findings
# INSERT INTO contamination_tracking ...

# 5. Run remediation for critical issues
# See /spot-check-cascade --backfilled output

# 6. Verify fixes
/validate-lineage
```

### After Any Backfill

```bash
# 1. Identify what was backfilled
# Check backfill logs for date range and scope

# 2. Calculate cascade impact
/spot-check-cascade <player> <date> --backfilled

# 3. Run remediation commands
# (Output from step 2)

# 4. Verify correctness
/validate-lineage
```

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [DESIGN-DECISIONS.md](./DESIGN-DECISIONS.md) | 4-layer architecture |
| [IMPLEMENTATION-REQUEST.md](./IMPLEMENTATION-REQUEST.md) | Technical specs for prevention layer |
| [PLAYER-SPOT-CHECK-GUIDE.md](../../../validation/guides/PLAYER-SPOT-CHECK-GUIDE.md) | Operational guide |
| `/validate-lineage` skill | Correctness validation via recomputation |
