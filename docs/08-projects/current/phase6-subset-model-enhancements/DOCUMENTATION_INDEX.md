# Phase 6 Enhancement Documentation Index

**Last Updated:** 2026-02-03
**Status:** Ready for implementation

## Quick Start Guide

### For Implementation (Start Here)

1. **Read:** `IMPLEMENTATION_UPDATE.md` ⭐
   - Current approach: single file, clean API
   - Exporter specifications
   - Testing procedures

2. **Reference:** `CLEAN_API_STRUCTURE.md` 🎨
   - JSON structure specifications
   - What to show/hide
   - Security checklist

3. **Reference:** `CODENAME_EXAMPLES.md` 🏷️
   - Model codename mappings (926A, 926B)
   - Group name mappings (Top 5, Best Value)

4. **Reference:** `ACTION_PLAN.md` 📅
   - Implementation timeline
   - Step-by-step guide
   - Verification commands

### For Context (Background Reading)

5. **Read:** `FINDINGS_SUMMARY.md` 📊
   - Why we're building this
   - What's currently missing
   - Business value

6. **Read:** `OPUS_REVIEW_FINDINGS.md` ✅
   - Architectural review results
   - What was verified
   - Critical fixes applied

## Document Status

### Current Implementation Docs (Use These)

| Document | Purpose | Status |
|----------|---------|--------|
| `IMPLEMENTATION_UPDATE.md` | Current approach specs | ✅ Current |
| `CLEAN_API_STRUCTURE.md` | Clean JSON design | ✅ Current |
| `CODENAME_EXAMPLES.md` | Model/group codenames | ✅ Current |
| `ACTION_PLAN.md` | Implementation timeline | ✅ Current |

### Background/Reference Docs

| Document | Purpose | Status |
|----------|---------|--------|
| `FINDINGS_SUMMARY.md` | Research summary | ✅ Reference |
| `IMPLEMENTATION_PLAN.md` | Original detailed plan | ⚠️ Superseded by UPDATE |
| `JSON_EXAMPLES.md` | Original API examples | ⚠️ Superseded by CLEAN |
| `MODEL_DISPLAY_NAMES.md` | Display name strategy | 📋 Future branding |
| `OPUS_REVIEW_FINDINGS.md` | Review results | ✅ Reference |

### Review Prompts (Archive)

| Document | Purpose | Status |
|----------|---------|--------|
| `OPUS_REVIEW_PROMPT.md` | Detailed review prompt | 📦 Archive |
| `OPUS_REVIEW_PROMPT_SHORT.txt` | Quick review prompt | 📦 Archive |

## Key Implementation Changes

### Original Plan → Current Plan

| Aspect | Original | Current | Reason |
|--------|----------|---------|--------|
| **Files per day** | 9 separate | 1 combined | Simpler testing |
| **Endpoint** | `/subsets/{id}/{date}` | `/picks/{date}` | One API call |
| **Group names** | `v9_high_edge_top5` | "Top 5" or "2" | Hide internals |
| **Model names** | `catboost_v9` | "926A" | Testing codename |
| **Technical details** | Included | **Removed** | Prevent reverse-engineering |

## Implementation Checklist

### Phase 0: Prerequisites ✅
- [x] Model attribution deployed (prediction-worker rev 00081-z97)
- [x] Waiting for verification (next prediction run)

### Phase 1: Subset Exporters (3-4 days)
- [ ] Create `shared/config/model_codenames.py` ✅ Done
- [ ] Create `shared/config/subset_public_names.py`
- [ ] Create `SubsetDefinitionsExporter`
- [ ] Create `DailySignalsExporter`
- [ ] Create `AllSubsetsPicksExporter` (main endpoint)
- [ ] Create `SubsetPerformanceExporter`
- [ ] Update `daily_export.py` orchestration
- [ ] Integration testing

### Phase 2: Model Attribution (2-3 days)
- [ ] Create `ModelRegistryExporter`
- [ ] Modify `SystemPerformanceExporter`
- [ ] Modify `PredictionsExporter`
- [ ] Modify `BestBetsExporter`
- [ ] Integration testing

## Quick Reference

### Endpoints Being Created

| Endpoint | Purpose | File Count |
|----------|---------|------------|
| `/picks/{date}.json` | **All 9 groups' picks** | 1/day |
| `/signals/{date}.json` | Daily market signal | 1/day |
| `/systems/subsets.json` | Group definitions | 1 total |
| `/subsets/performance.json` | Group comparison | 1 total |
| `/systems/models.json` | Model registry | 1 total |

### Codename Mappings

**Models:**
- catboost_v9 → 926A
- catboost_v9_202602 → 926B
- ensemble_v1 → E01

**Groups:**
- v9_high_edge_top1 → "Top Pick" or "1"
- v9_high_edge_top5 → "Top 5" or "2"
- v9_high_edge_top10 → "Top 10" or "3"
- v9_high_edge_balanced → "Best Value" or "4"

### What NOT to Export

**Never include in API responses:**
- ❌ `system_id` (catboost_v9)
- ❌ `subset_id` (v9_high_edge_top5)
- ❌ `confidence_score`
- ❌ `edge` / `line_margin`
- ❌ `composite_score`
- ❌ Algorithm names
- ❌ Feature counts
- ❌ Training details
- ❌ Formulas or thresholds

## Testing Commands

```bash
# Verify clean API
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  grep -E "(system_id|subset_id|confidence|edge|composite)" && \
  echo "❌ Leaked!" || echo "✅ Clean!"

# Verify structure
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  jq '{model, groups: (.groups | length)}'
# Expected: {"model": "926A", "groups": 9}

# Verify pick fields
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  jq '.groups[0].picks[0] | keys'
# Expected: ["player", "team", "opponent", "prediction", "line", "direction"]
```

## Questions?

1. **Implementation questions** → See `IMPLEMENTATION_UPDATE.md`
2. **API design questions** → See `CLEAN_API_STRUCTURE.md`
3. **Timeline questions** → See `ACTION_PLAN.md`
4. **"Why these decisions?"** → See `FINDINGS_SUMMARY.md`
5. **"Was this validated?"** → See `OPUS_REVIEW_FINDINGS.md`

## Next Steps

1. Wait for model attribution verification (tomorrow morning)
2. Create config files (`model_codenames.py`, `subset_public_names.py`)
3. Begin Phase 1 exporter implementation
4. Test with clean API structure
5. Deploy and monitor

**Ready to implement!** 🚀
