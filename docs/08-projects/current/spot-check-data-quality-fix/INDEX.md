# Spot Check Data Quality Fix - Documentation Index

**Project**: spot-check-data-quality-fix
**Date**: 2026-01-26
**Status**: Phase 1 complete, awaiting full season regeneration

---

## Quick Navigation

### 🚀 Start Here
- **[HANDOFF.md](./HANDOFF.md)** - Complete session handoff for next person
- **[TODO.md](./TODO.md)** - Checklist of remaining tasks
- **[SESSION-SUMMARY.md](./SESSION-SUMMARY.md)** - One-page summary

### 📋 Project Docs
- **[README.md](./README.md)** - Project overview and status
- **[REGENERATION-QUICKSTART.md](./REGENERATION-QUICKSTART.md)** - Quick commands reference
- **[PHASE-1-COMPLETE.md](./PHASE-1-COMPLETE.md)** - Phase 1 validation results

### 🔍 Investigation
- **[../../investigations/SPOT-CHECK-FINDINGS-2026-01-26.md](../../investigations/SPOT-CHECK-FINDINGS-2026-01-26.md)** - Detailed root cause analysis
- **[../../investigations/SPOT-CHECK-FIX-SUMMARY-2026-01-26.md](../../investigations/SPOT-CHECK-FIX-SUMMARY-2026-01-26.md)** - Executive summary

---

## Files by Purpose

### If you want to...

**Resume the work**
→ Read: `HANDOFF.md` then `TODO.md`
→ Run: Commands in `TODO.md` Task 1

**Understand what happened**
→ Read: `SESSION-SUMMARY.md` then `SPOT-CHECK-FINDINGS-2026-01-26.md`

**Run regeneration commands**
→ Reference: `REGENERATION-QUICKSTART.md` or `TODO.md`

**Validate the fix**
→ See: `PHASE-1-COMPLETE.md` for verification examples

**Understand the bug**
→ Read: `SPOT-CHECK-FINDINGS-2026-01-26.md` section "Root Cause: FOUND"

**Check project status**
→ Read: `README.md` Implementation Status section

---

## Document Hierarchy

```
spot-check-data-quality-fix/
├── INDEX.md              ← You are here
├── HANDOFF.md           ← Most important for next session
├── TODO.md              ← Task checklist
├── SESSION-SUMMARY.md   ← Quick overview
├── README.md            ← Project overview
├── REGENERATION-QUICKSTART.md  ← Command reference
└── PHASE-1-COMPLETE.md  ← Validation results

../../investigations/
├── SPOT-CHECK-FINDINGS-2026-01-26.md    ← Detailed analysis
└── SPOT-CHECK-FIX-SUMMARY-2026-01-26.md ← Executive summary
```

---

## Key Facts

### The Bug
Date filter used `<=` instead of `<` in cache queries
→ Included games ON cache_date instead of only BEFORE
→ Rolling averages off by 2-37%

### The Fix
Changed `game_date <= analysis_date` to `game_date < analysis_date`
→ Files: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
→ Lines: 425, 454

### The Script
Created `scripts/regenerate_player_daily_cache.py`
→ Standalone regeneration using MERGE
→ Fast (~3 sec/date), safe, tested

### Current Status
✅ Code fixed and verified
✅ Recent 31 days regenerated (4,179 records)
✅ Fix validated (Mo Bamba 28%→0%, Josh Giddey 27%→0%)
⏳ Full season pending (~5 min execution)
⏳ ML features update pending (~15 min execution)

---

## Next Session Action

1. Open `HANDOFF.md`
2. Read "Quick Start Commands" section
3. Run Task 1: Full season regeneration
4. Validate results
5. Run Task 2: ML features update
6. Final validation
7. Mark project complete

**Total time**: ~30-35 minutes

---

**Created**: 2026-01-26
**Last Updated**: 2026-01-26
