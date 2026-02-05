# Emergency Cache Regeneration Plan - Session 123

**Date:** 2026-02-04
**Severity:** P0 CRITICAL
**Scope:** ALL February 2026 caches (Feb 1-4)

---

## Situation Summary

DNP pollution discovered across all February caches:

| Date | DNP Pollution | Status |
|------|--------------|--------|
| Feb 1 | 78.2% (233/298) | 🔴 CRITICAL |
| Feb 2 | 71.5% (88/123) | 🔴 CRITICAL |
| Feb 3 | 80.4% (229/285) | 🔴 CRITICAL |
| Feb 4 | 78.9% (172/218) | 🔴 CRITICAL |

**Average:** 77.3% pollution (only ~23% valid data)

---

## Root Cause

DNP filter was missing from Phase 4 cache generation until commit `94087b90` (deployed Feb 4, 19:24 PST). All caches generated before this deployment are polluted.

---

## Regeneration Plan

### Phase 1: Verify Fix is Deployed ✅

```bash
# Check Phase 4 deployment
gcloud run services describe nba-phase4-precompute-processors \
  --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# Expected: ede3ab89 or later (contains DNP fix from 94087b90)
```

**Status:** ✅ VERIFIED - Phase 4 deployed at 19:24 PST with DNP fix

### Phase 2: Regenerate All February Caches

**Priority Order:** Most recent first (Feb 4 → Feb 1)

```bash
# Regenerate Feb 4 (highest priority - most recent)
python bin/regenerate_cache_bypass_bootstrap.py 2026-02-04

# Wait 5 minutes for BigQuery to process
sleep 300

# Regenerate Feb 3
python bin/regenerate_cache_bypass_bootstrap.py 2026-02-03

# Wait 5 minutes
sleep 300

# Regenerate Feb 2
python bin/regenerate_cache_bypass_bootstrap.py 2026-02-02

# Wait 5 minutes
sleep 300

# Regenerate Feb 1
python bin/regenerate_cache_bypass_bootstrap.py 2026-02-01
```

**Total time:** ~20-30 minutes (including wait times)

### Phase 3: Validate Regenerated Caches

After each regeneration, verify DNP pollution is 0%:

```sql
-- Check specific date
SELECT
  pdc.cache_date,
  COUNT(DISTINCT pdc.player_lookup) as total_cached,
  COUNT(DISTINCT CASE WHEN pgs.is_dnp = TRUE THEN pdc.player_lookup END) as dnp_polluted,
  ROUND(100.0 * COUNT(DISTINCT CASE WHEN pgs.is_dnp = TRUE THEN pdc.player_lookup END) /
    NULLIF(COUNT(DISTINCT pdc.player_lookup), 0), 1) as dnp_pct
FROM nba_precompute.player_daily_cache pdc
LEFT JOIN nba_analytics.player_game_summary pgs
  ON pdc.player_lookup = pgs.player_lookup
  AND pgs.game_date < pdc.cache_date
  AND pgs.game_date >= DATE_SUB(pdc.cache_date, INTERVAL 30 DAY)
WHERE pdc.cache_date = '2026-02-04'  -- Change date for each check
GROUP BY pdc.cache_date;

-- Expected: dnp_pct = 0.0
```

**Validation script:**
```bash
# Automated validation for all dates
python bin/audit/audit_cache_dnp_pollution.py \
    --start-date 2026-02-01 \
    --end-date 2026-02-04 \
    --detailed
```

**Expected output:** All dates show 0% or <1% DNP pollution

---

## Before/After Comparison

### Before Regeneration (Polluted)

| Date | Total | DNP | Valid | DNP % |
|------|-------|-----|-------|-------|
| Feb 1 | 298 | 233 | **65** | 78.2% |
| Feb 2 | 123 | 88 | **35** | 71.5% |
| Feb 3 | 285 | 229 | **56** | 80.4% |
| Feb 4 | 218 | 172 | **46** | 78.9% |

### After Regeneration (Expected)

| Date | Total | DNP | Valid | DNP % |
|------|-------|-----|-------|-------|
| Feb 1 | ~65-75 | 0 | **~65-75** | 0.0% |
| Feb 2 | ~35-45 | 0 | **~35-45** | 0.0% |
| Feb 3 | ~56-66 | 0 | **~56-66** | 0.0% |
| Feb 4 | ~46-56 | 0 | **~46-56** | 0.0% |

**Expected cache size reduction:** ~70-75% (removing DNP players)

---

## Impact Assessment

### Data Quality Impact

**Before Fix:**
- 77% of cached data was DNP players (no meaningful stats)
- Predictions using polluted cache had degraded feature quality
- Cache size artificially inflated by 3-4x

**After Fix:**
- 0% DNP pollution (only active players with stats)
- Clean cache with meaningful historical data
- Cache size reduced to actual valid players

### Prediction Quality Impact

**Potential issues from polluted cache:**
- Feature store may have included DNP player stats (zeros/NULLs)
- Average/aggregate features diluted by DNP players
- Player similarity calculations skewed

**Mitigation:**
- Regenerate caches immediately
- Consider regenerating predictions for Feb 1-4 games (if not already graded)
- Monitor prediction quality after cleanup

---

## Timeline

| Action | Status | Time |
|--------|--------|------|
| DNP fix deployed | ✅ DONE | Feb 4, 19:24 PST |
| Scope audit complete | ✅ DONE | Feb 4, 19:30 PST |
| Regeneration plan created | ✅ DONE | Feb 4, 19:35 PST |
| Regenerate Feb 4 | ⏳ PENDING | ~5 min |
| Regenerate Feb 3 | ⏳ PENDING | ~5 min |
| Regenerate Feb 2 | ⏳ PENDING | ~5 min |
| Regenerate Feb 1 | ⏳ PENDING | ~5 min |
| Validation | ⏳ PENDING | ~5 min |
| **Total** | | **~25 min** |

---

## Risk Assessment

### Risks of NOT Regenerating

**HIGH RISK:**
- Predictions continue using polluted cache data
- Feature quality degraded by 70-80%
- Potential model performance impact
- Cache pollution persists in historical data

### Risks of Regenerating

**LOW RISK:**
- 25 minutes of cache generation time
- Predictions may be delayed if regeneration runs during prediction time
- No data loss (regeneration is idempotent)

**Recommendation:** ✅ REGENERATE IMMEDIATELY

---

## Post-Regeneration Verification Checklist

After regeneration completes:

- [ ] All caches show 0% DNP pollution (audit script)
- [ ] Cache sizes reduced by ~70-75% (expected)
- [ ] No errors in Phase 4 logs
- [ ] Next prediction run uses clean cache
- [ ] Add DNP check to daily validation (`/validate-daily`)
- [ ] Update Session 122 handoff with corrections
- [ ] Document in session learnings

---

## Prevention (Already Implemented)

✅ **Deployed:** DNP fix in Phase 4 (commit 94087b90)
✅ **Implemented:** Pre-commit hook catches validation anti-patterns
✅ **Created:** Validation test framework
✅ **Built:** Cache audit tool

**Next:** Add to `/validate-daily` skill for continuous monitoring

---

**Prepared by:** Claude Sonnet 4.5
**Session:** 123
**Priority:** P0 CRITICAL
**Action Required:** Regenerate ALL February caches immediately
