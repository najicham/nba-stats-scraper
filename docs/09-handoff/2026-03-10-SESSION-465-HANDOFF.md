# Session 465 Handoff — MLB Paper Trade Readiness + Replay Experiments + Combo Signals

**Date:** 2026-03-10
**Focus:** Verify paper trade readiness, run replay experiments, implement combo signals, wire catcher framing infrastructure
**Previous:** Session 464 (L2=10+D4 deploy, 2 signal promotions, 10 shadow signals)

## What Changed

### 1. Paper Trade Readiness — VERIFIED
- Model exists in GCS at correct path (`catboost_mlb_v1_40f_train20250517_20250914_20260308_090647.cbm`)
- Worker booted today, /health returns 200
- Env var `MLB_CATBOOST_V1_MODEL_PATH` correctly set
- Supplemental data (umpire, weather, game context, catcher framing) all wired
- Model loads lazily on first prediction — will auto-init on March 27

### 2. Replay Experiments — ALL COMPLETED

| Experiment | HR | Record | P&L | ROI | Verdict |
|-----------|-----|--------|-----|-----|---------|
| **Replay C: Dynamic blacklist** (1.25 away) | 65.9% | 548-283 | +249u | 20.0% | Only 3 pitchers suppressed — not worth complexity |
| **Replay D1: Away edge 1.0** | 65.8% | 574-298 | +258u | 20.0% | More picks, same ROI |
| **Replay D2: Away edge 1.5** | 66.0% | 530-273 | +250u | 20.5% | Fewer picks, slightly better HR |

**Conclusions:**
- **Dynamic blacklist:** Suppressed only Logan Webb (temporarily), Schwellenbach (1 day), Cade Horton (end-of-season). 12 total picks blocked. Not deploying.
- **Away edge floor:** 1.0/1.25/1.5 all within noise. Keep 1.25 (current production).
- **RSC gate:** RSC=2 picks = **75.9% HR** (N=29) — best RSC bucket! RSC=3 is weakest at 55.7%. Do NOT raise minimum RSC.

### 3. RSC Distribution (single-season 2025 replay)

| RSC | HR | N | Verdict |
|-----|-----|---|---------|
| 2 | 75.9% | 29 | Best bucket — keep gate at 2 |
| 3 | 55.7% | 79 | Weakest — noise |
| 4 | 59.7% | 149 | Solid |
| 5 | 62.6% | 163 | Good |
| 6 | 69.1% | 207 | Sweet spot |
| 7 | 72.1% | 147 | Elite |
| 8+ | 73.7% | 57 | Elite (low N) |

**Note:** S464 showed RSC=2 at 57.8% across 4 seasons. Single-season can diverge. The key insight: RSC=2 is NOT the problem bucket.

### 4. Combo + xFIP Signals Implemented (Shadow Mode)

| Signal | Replay HR | N | Mechanism |
|--------|----------|---|-----------|
| `xfip_elite_over` | **73.8%** | 202 | xFIP < 3.5 — elite underlying stuff regardless of ERA |
| `day_game_elite_peripherals_combo_over` | **86.7%** | 45 | Day game + FIP < 3.5 + K/9 >= 9.0 |
| `day_game_high_csw_combo_over` | **82.1%** | 28 | Day game visibility stress + elite CSW (>= 30%) |
| `high_csw_low_era_high_k_combo_over` | 67.3% | 55 | CSW >= 30% + ERA < 3.0 + K/9 >= 8.5 |

All registered as shadow (TRACKING_ONLY) in production exporter and replay script.

**Note:** Original `xfip_regression_over` (ERA >> xFIP gap) had structural misalignment — pitchers with high ERA get UNDER recommendations from the model, so they never appear in OVER best bets. Replaced with standalone xFIP quality signal.

**Signal count now: 18 active + 32 shadow + 6 filters = 56 total**

### 5. Catcher Framing Infrastructure — WIRED

| Component | Status |
|-----------|--------|
| Scraper (`mlb_catcher_framing.py`) | **Fixed** (DownloadType.HTML, type=catcher, correct columns) |
| BQ table (`mlb_raw.catcher_framing`) | **Created** (0 rows, ready for data) |
| Processor (`mlb_catcher_framing_processor.py`) | **Created** |
| Scraper registry entry | **Added** |
| Supplemental loader (`_load_catcher_framing()`) | **Wired** — maps team → primary catcher → framing_runs |
| Signals (`catcher_framing_over`, `catcher_framing_poor_under`) | Already existed (shadow, waiting for data) |

Data will populate when scraper runs during season (weekly cadence). Tested locally: 57 catchers parsed for 2025.

### 6. Umpire Historical Backfill

- Created `scripts/mlb/backfill_umpire_assignments.py` — date range backfill from MLB Stats API
- Fixed schema (added `source_file_path`, `processed_at` required fields)
- Fixed team abbr mapping (MLB API doesn't include abbreviation in schedule endpoint)
- 2025 full season loaded: 2,400+ records across 179 dates
- Added umpire K-rate join to replay SQL + signal evaluation

### 7. Signal Promotions (Cross-Season Validated)

| Signal | 4-Season HR | N | Decision |
|--------|-----------|---|----------|
| `xfip_elite_over` | **67.5%** | 704 | **PROMOTED** — 63-72% all 4 seasons |
| `day_game_high_csw_combo_over` | **73.0%** | 122 | **PROMOTED** — 65-82% all 4 seasons |
| `day_game_elite_peripherals_combo_over` | 72.0% | 182 | Keep shadow — 2023: 55.2% |
| `high_csw_low_era_high_k_combo_over` | 70.6% | 170 | Keep shadow — 2023: 50.0% |

**Impact on 2025 replay:** HR 66.2% (was 65.9%), P&L +255.6u (was +249u). Marginal improvement — signals mostly overlap with existing elite_peripherals/high_csw.

## Files Modified (7) + Created (1)

| File | Change |
|------|--------|
| `ml/signals/mlb/signals.py` | +3 combo signal classes (~120 lines) |
| `ml/signals/mlb/registry.py` | +3 imports, +3 registrations, updated count |
| `ml/signals/mlb/best_bets_exporter.py` | +3 tags in TRACKING_ONLY_SIGNALS |
| `scripts/mlb/training/season_replay.py` | +3 tags in TRACKING_ONLY_SIGNALS |
| `scrapers/mlb/registry.py` | +catcher_framing entry + source map |
| `predictions/mlb/supplemental_loader.py` | +`_load_catcher_framing()` + wiring + logging |
| **NEW:** `data_processors/raw/mlb/mlb_catcher_framing_processor.py` | Full processor (MERGE_UPDATE pattern) |

## What's Next

### Pre-Season (Mar 18-23) — CRITICAL PATH
1. **Retrain final model** (Mar 18-20): `train_regressor_v2.py --training-end 2026-03-20 --window 120`
2. **Upload to GCS** + update env var
3. **Deploy MLB worker** (manual: `gcloud builds submit --config cloudbuild-mlb-worker.yaml`)
4. **Resume schedulers** (Mar 24): `./bin/mlb-season-resume.sh`

### Opening Day (Mar 27)
1. Verify predictions generating
2. Check /best-bets endpoint
3. Monitor filter audit
4. Verify supplemental data flowing (umpire, weather, game context)

### Paper Trade (Mar 27 - Apr 14)
1. Monitor shadow signal fire rates (especially 3 new combos)
2. Validate promoted signals in live conditions
3. Check catcher framing data populating
4. First retrain at Apr 14 (14d cadence)

### Signal Research (Ongoing)
- Monitor `k_rate_bounce_over` — 76.1% HR but N=46 (need more data)
- Monitor `low_era_high_k_combo_over` — inconsistent across seasons
- Evaluate combo signals from live data
- Chase_rate_over + contact_specialist_under from production data

### NOT Doing (Dead Ends from S465)
- Dynamic blacklist — too few pitchers suppressed (3), marginal impact
- Raising RSC gate to 3 — RSC=2 is actually the best bucket
- Changing away edge floor — 1.25 is fine
