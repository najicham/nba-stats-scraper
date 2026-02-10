# Session 185: Prevention Mechanisms for Pipeline Bugs

**Date:** 2026-02-10
**Context:** Session 184 found 3 code bugs. Session 185 added prevention to catch entire bug classes.

## Pre-Commit Hook: validate_pipeline_patterns.py

**File:** `.pre-commit-hooks/validate_pipeline_patterns.py`

Catches three categories of production bugs before they reach deployment:

### 1. Invalid Enum Member Usage

**Bug class:** Using an enum member that doesn't exist (e.g., `SourceCoverageSeverity.ERROR` when only INFO, WARNING, CRITICAL exist). Causes `AttributeError` at runtime.

**How it works:**
- Loads enum definitions from source files (or uses hardcoded fallback)
- Scans all Python files for `EnumName.MEMBER` patterns
- Validates each member exists in the enum
- Skips docstrings, comments, and string literals

**Enums validated:**
| Enum | Members | Location |
|------|---------|----------|
| `SourceCoverageSeverity` | INFO, WARNING, CRITICAL | `shared/config/source_coverage/__init__.py` |
| `SourceCoverageEventType` | DEPENDENCY_STALE, SOURCE_BLOCKED, etc. | Same file |
| `SourceStatus` | AVAILABLE, UNAVAILABLE, BLOCKED, ERROR, etc. | Same file |

### 2. Processor Name Mapping Completeness

**Bug class:** CLASS_TO_CONFIG_MAP in the Phase 2→3 orchestrator missing a processor name. When that processor reports completion, the orchestrator can't match it, so the Firestore completion tracking breaks and Phase 3 is never triggered.

**How it works:**
- Reads `EXPECTED_PROCESSORS` list from the orchestrator
- Reads `CLASS_TO_CONFIG_MAP` values
- Verifies every expected config has at least one map entry
- Flags non-ASCII characters in map keys (typo indicator)

### 3. Flask get_json() Safety

**Bug class:** Cloud Scheduler sends requests without `Content-Type: application/json`. Flask's bare `request.get_json()` returns None or raises 415, silently breaking scheduler-triggered endpoints.

**How it works:**
- Scans Flask service files for bare `request.get_json()` calls
- Checks surrounding context for Pub/Sub indicators (which are exempt — Pub/Sub sends valid JSON)
- Flags any non-Pub/Sub handler missing `force=True, silent=True`
- Only checks relevant directories (predictions, data_processors, orchestration, scrapers, services)

## Phase 3 Season Audit Script

**File:** `bin/monitoring/phase3_season_audit.py`

Comprehensive Phase 3 completeness and quality check across the entire season.

**Usage:**
```bash
# Full season audit
PYTHONPATH=. python bin/monitoring/phase3_season_audit.py

# Date range with fix commands
PYTHONPATH=. python bin/monitoring/phase3_season_audit.py --start 2026-01-01 --end 2026-02-10 --fix
```

**Checks:**
1. Player game summary coverage vs schedule
2. Team offense game summary coverage vs schedule
3. Usage rate coverage and anomaly detection
4. Monthly completeness summary

**Season Audit Results (2025-11 to 2026-02-10):**
- Player game summary: 100% complete
- Team offense: 12 gaps (Jan 21, 24, 26 — likely timing cascade)
- Usage rate: 2 dates at 0% (Nov 13, 20), rest above 93%

## Validation Skill

**Skill:** `/validate-phase3-season`

Runs the Phase 3 season audit as a Claude Code skill with interpretation guidance.

## How to Run

```bash
# Pre-commit hook (runs automatically on commit)
python .pre-commit-hooks/validate_pipeline_patterns.py

# Phase 3 audit (run periodically or on demand)
PYTHONPATH=. python bin/monitoring/phase3_season_audit.py --fix

# Skill
/validate-phase3-season
```
