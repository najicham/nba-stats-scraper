# MLB Pitcher Early-Hook / Lineup-Quality Features — Project Spec

**Created:** 2026-05-20
**Status:** Phase 0 diagnosis complete. **Decision: A+B+C approved.** Part A (scheduler
jobs + dedup fix) **DONE + VERIFIED 2026-05-20**. Part B + Part C + Phases 1–3 scoped,
awaiting build approval.
**Origin:** Handoff `docs/09-handoff/2026-05-20-ENGINE-ROADMAP-HANDOFF.md` §3.
This is the proper rebuild of the abandoned `lineup_k_analysis` work (the "X1 rebuild").

---

## 1. Goal & rationale

The MLB model predicts pitcher **strikeouts**. Decompose:

```
strikeouts ≈ innings_pitched × K_rate
```

The model already handles **K_rate** well (pitch arsenal, opponent K%). The volatile,
under-modeled multiplier is **innings pitched** — a starter who gets shelled is pulled
after 4 IP and physically cannot reach a 6.5 K line. **Opposing lineup quality drives
early hooks, which cap strikeout upside.** That is the missing signal.

The project builds, in phases: (0) reliable pre-game lineups → (1) a lineup threat
score → (2) an expected-IP / early-hook model → (3) integration into the K predictions.

---

## 2. Phase 0 — Lineup data diagnosis (COMPLETE)

### 2.1 What's broken

`mlb_raw.mlb_lineup_batters` 2026 coverage, last 35 days:

| Game type | Capture rate |
|-----------|--------------|
| Day games (start ≤ 1 pm ET) | ~93% |
| Night games (start ≥ 6 pm ET) | **0%** (1 of 299) |

Capture rate collapses by game start hour: 12–1 pm ET starts ~93%, 3 pm 16%, 4 pm 5%,
6 pm+ 0%.

**Root cause: scraper timing.** The `mlb_lineups` scraper (`scrapers/mlb/mlbstatsapi/
mlb_lineups.py`, MLB Stats API `feed/live` boxscore endpoint) runs only at **11 am and
1 pm ET** (`mlb-lineups-morning`, `mlb-lineups-pregame` Cloud Scheduler jobs — both
ENABLED and firing). Night-game lineups post **~3–4 pm ET**, after the last scrape.
All `mlb_lineup_batters` rows in 2026 land at exactly 11 am ET — the 1 pm scrape adds
nothing.

**This is a 2026 regression, not a fundamental limit:**

| Season | Day capture | Night capture |
|--------|-------------|---------------|
| 2024 | 99.9% | 100% |
| 2025 | 100% | 100% |
| 2026 | 50.6% | 2.8% |

The scraper + Phase 2 processor are proven over **188K rows / 405 game-days / 2 full
seasons**, and when a lineup is captured it is always complete (9.0 batter rows per
team-game). 2024/2025 achieved 100% night capture — something in 2026's scheduling
lost the late/overnight capture.

### 2.2 What is NOT broken — training data is fully available

Confirmed historical lineups (the actual 9 batters + order the pitcher faced) exist at
100% coverage, including 2026:

| Source | Coverage | Notes |
|--------|----------|-------|
| `mlb_analytics.batter_game_summary.batting_order` | **100%**, all 30 teams, every game-day, incl. 2026 | Ground truth from completed games. 255/255 rows have `batting_order`. |
| `mlb_raw.mlb_lineup_batters` | 100% for 2024–2025 | Pre-game confirmed lineups. |
| `mlb_raw.mlb_game_feed` | PA-level (`batter_id`, `pitcher_id`) | Full sequence reconstructable. |

**Training is not blocked.** The handoff's worry that Phase 0 is a hard gating
dependency is overstated — historical model-building can proceed immediately.

### 2.3 The real constraint: pre-game prediction

Confirmed lineups fundamentally post **~3–4 pm ET**. That is:
- **Too late** for the main MLB best-bets export (~12:55 pm ET).
- **In time** for the `mlb-best-bets-generate-late` export (4:30 pm ET).

The betting-market proxy (`oddsa_batter_props` / `oddsa_batter_k_lines` /
`oddsa_lineup_expected_ks`) — books post K props only for expected starters — is itself
**empty in recent days**, so it is not a usable free source.

→ For the **morning prediction window**, the system needs a **projected lineup**, not
a confirmed one.

---

## 3. Phase 0 — The fix (the unblock)

Three parts, **all approved (A+B+C)**. A is a pure infra change (DONE); B is new
precompute code; C is a new scraper.

### Part A — Restore confirmed-lineup capture (ground truth + late export) — DONE 2026-05-20

The `feed/live` boxscore endpoint **retains the lineup permanently after the game**, so
a late scrape gets 100% capture — exactly how 2024/2025 worked. Two Cloud Scheduler
jobs added (no scraper code change), matching the config of the existing
`mlb-lineups-morning` / `mlb-lineups-pregame` siblings:

1. **`mlb-lineups-afternoon`** — `0 16 * * *` America/New_York (4 pm ET),
   `date: "TODAY"`. Catches night-game confirmed lineups in time for the 4:30 pm
   `mlb-best-bets-generate-late` export.
2. **`mlb-lineups-overnight`** — `0 3 * * *` America/New_York (3 am ET),
   `date: "YESTERDAY"`. Re-scrapes the prior day's completed games → 100%
   confirmed-lineup coverage for the historical record.

The Phase 2 processor is `MERGE_UPDATE` (delete + reinsert per `game_pk`), so
re-scrapes are safe and idempotent. `YESTERDAY` resolves to ET-minus-1-day in
`config_mixin.py`, so the 3 am job targets the correct date even after midnight.

**Jobs created 2026-05-20.** Overnight job test-fired — the **scraper works perfectly**
(`lineups_available: 15` for all 15 of 2026-05-19's games, 78 KB GCS file written).

**A blocker was found and fixed.** The first overnight test-fire was silently dropped
by the Phase 2 `MlbLineupsProcessor`:

```
⏭️  Skipping MlbLineupsProcessor for 2026-05-19 - already processed
MlbLineupsProcessor already processed 2026-05-19 with status 'success' and 15 records
```

Root cause: the `run_history_mixin` dedup guard (`check_already_processed`,
`shared/processors/mixins/run_history_mixin.py:536`) skips a date once a prior run
recorded `records_processed > 0`. The 11 am scrape sees 15 *games* and writes 15
`mlb_game_lineups` envelope rows (so `records_processed = 15`) — **but zero
`mlb_lineup_batters` rows** because night-game lineups aren't posted yet. The dedup's
`records_processed == 0 → allow retry` escape hatch never triggers, so every later
re-scrape of that date was discarded. This dedup guard is itself the most likely
**2026 regression** cause — it let the 11 am scrape "win" the date and blocked the 1 pm
scrape; 2024/2025 predate this behavior.

**Fix (committed `eb056db4`):** `SKIP_DEDUPLICATION = True` on `MlbLineupsProcessor`
(`data_processors/raw/mlb/mlb_lineups_processor.py:55`) — the documented use of the flag
("LIVE processors that run repeatedly", same idiom as `BdlLiveBoxscoresProcessor`). The
processor is `MERGE_UPDATE` per `game_pk`, so re-processing is idempotent. Trade-off:
this also drops the dedup's Pub/Sub-redelivery concurrency guard; acceptable because
processing is ~90 s (well inside ack deadlines) and MERGE_UPDATE is idempotent.

**Deploy:** `mlb-phase2-raw-processors` deploys via `cloudbuild-nba-phase2.yaml` Step 4
(shares the nba-phase2 image — it IS auto-deployed, bundled in the
`deploy-nba-phase2-raw-processors` trigger). Deployed manually 2026-05-20 via
`gcloud builds submit` → revision `mlb-phase2-raw-processors-00018-h58`.

**VERIFIED end-to-end 2026-05-20.** Re-fired the overnight job → 2026-05-19 went from
**0 → 15 games / 30 teams / 325 batter rows** in `mlb_lineup_batters`.

> **Data-shape note for Phase 1:** the overnight scrape reads *completed* games, so the
> boxscore `battingOrder` includes substitutes — each `batting_order` slot has ~1.5
> entries (e.g. slot 8 had 44 rows across 30 team-games). A *pre-game* scrape gives a
> clean 9 starters per team. Since the processor is `MERGE_UPDATE`, the overnight run
> overwrites the clean pre-game lineup with the post-game starter+sub record. Phase 1
> must disambiguate the **starter** per slot when reading `mlb_lineup_batters` for a
> completed game (e.g. earliest-entering batter, or cross-ref `batter_game_summary`).

> **Follow-up (still open):** register `mlb_lineups` in `expected_outputs_planner` so
> future coverage regressions are caught by gap detection instead of going silent.

> **Stale deploy script:** `bin/raw/deploy/mlb/deploy_mlb_processors.sh` references a
> non-existent `docker/raw-processor.Dockerfile` — superseded by `cloudbuild-nba-phase2.yaml`.
> Should be deleted or fixed (not done here — out of scope).

### Part B — Projected lineup for the morning window

New precompute table `mlb_precompute.projected_lineup` — for each team's next game, the
9 most-likely batters and batting order, computed **with zero external dependency**:

- Derive from the trailing-N-games batting orders in `batter_game_summary`.
- **Key the projection on opposing-pitcher handedness**: use the most recent lineup the
  team fielded against a same-handed starter (MLB lineups platoon heavily L/R).
- Fall back to overall most-recent regulars when handedness history is thin.

Expected accuracy ~85–90% of the 8 regular position-player slots. Misses day-of changes
(rest days, late scratches, call-ups) — Part C and the 4:30 pm confirmed scrape cover
those.

**Critical:** this same projection logic is used in **training too** (see §4). Computed
identically in train and serve → no train/serve skew, no look-ahead.

**Effort:** one precompute processor + table + Pub/Sub wiring. Medium.

### Part C — Real projected-lineup scraper (IN SCOPE)

A dedicated projected-lineup source — more accurate for day-of changes (rest days, late
scratches, call-ups) than the §3-B derived projection. There is **no MLB
projected-lineup scraper in the repo today** (`rotowire_lineups.py` is NBA-only).

Build a new MLB projected-lineup scraper. Candidate sources, to evaluate during build:
- **RotoWire MLB daily lineups** (`rotowire.com/baseball/daily-lineups.php`) — the MLB
  analogue of the existing NBA `rotowire_lineups` scraper; posts confirmed + projected.
- **MLB.com starting-lineups page** — official, projected lineups morning-of.
- **Baseball Press** — projected lineups, historically scraper-friendly.

New artifacts: a scraper in `scrapers/mlb/`, registry entry in `MLB_SCRAPER_REGISTRY`,
a Phase 2 processor → new `mlb_raw.mlb_projected_lineups` table, Cloud Scheduler job(s),
and `deploy_mlb_scrapers.sh` wiring (`mlb-phase1-scrapers` is NOT auto-deployed).

**Relationship to Part B:** B (derive projection from our own batting-order history) is
the zero-dependency baseline and still ships first — it has no external point of
failure and guarantees a value for every game. C is the accuracy upgrade layered on
top: when a fresh scraped projection exists, prefer it; else fall back to B. The
`projected_lineup` precompute consumes whichever is best available.

---

## 4. Look-ahead discipline (NON-NEGOTIABLE)

The #1 hazard. Reference lesson: `bench_under` used post-game `starter_flag` and
inflated HR from ~52% to 76% — a pure leak.

Rules for every feature in this project:

1. **Train and serve use the same lineup object.** In training, do **not** use the
   confirmed lineup the pitcher actually faced — reconstruct what the §3-B projection
   *would have produced* as of game morning, and build features from that. This both
   eliminates look-ahead and removes train/serve skew.
2. Every batter form/stat uses games **strictly before** `game_date` (`< game_date`,
   never `<=`; window functions `1 PRECEDING`, never `CURRENT ROW` — see the standing
   leakage warning).
3. Archetype/pitch-mix tags for the pitcher use only data available pre-game.
4. No feature may read `mlb_lineup_batters` confirmed rows, `batter_game_summary` of
   the target game, or any post-first-pitch field.

A regression test (à la `test_v12_augmentation_leakage.py`) should assert that shifting
the projection's as-of date does not change feature values.

---

## 5. Phase 1 — Lineup threat score (SCOPE)

For the 9 projected batters in tonight's lineup, compute strictly pre-game:

### 5.1 Per-batter recent form
From `batter_game_summary` rolling columns (`k_rate_last_5/10`, `k_avg_last_10`,
`k_std_last_10`, `season_k_rate`, `season_batting_avg`) plus derivable rate stats
(OBP and ISO are reconstructable from `hits/walks/at_bats/doubles/triples/home_runs`;
**true wOBA is not directly available** — Phase 1 data task: decide on an OBP+ISO
composite or pull a wOBA source).

### 5.2 Per-batter archetype matchup
Match the batter against the **pitcher's archetype**, not batter-vs-this-pitcher (BvP
samples are too small/noisy):
- **Handedness** — batter L/R platoon split vs the starter's throwing hand.
- **Pitch-mix bucket** — high-velo FB / breaking-ball-heavy / sinkerballer, tagged from
  `mlb_analytics.pitcher_pitch_arsenal_latest` / `pitcher_pitch_arsenal_season` /
  `pitcher_advanced_arsenal_latest` (Session 529 arsenal data).

### 5.3 Aggregate
Combine the nine batters → a **lineup threat score** → expected baserunners / expected
runs / expected pitches-faced. Output: a small set of features.

### 5.4 Deliverable
Lineup-quality features attached to the `pitcher_features` precompute, plus the
`projected_lineup` table from §3-B. **No model training in Phase 1** — features only,
with the leakage regression test green.

---

## 6. Phase 2 — Expected-IP / early-hook model (LATER)

Predict how deep the starter goes: inputs = lineup threat score, pitcher recent
pitch-count tendency, days rest, score-context priors. Output = expected outs / pitch
count → expected IP.

## 7. Phase 3 — Integration (LATER)

Test all three: (a) lineup-threat + expected-IP as **features** in
`train_regressor_v2.py`; (b) a **two-stage** model (expected IP × K/9); (c) an
**early-hook filter/signal** in the MLB BB pipeline (block OVER picks vs dangerous
lineups).

## 8. Validation

Walk-forward replay (`scripts/mlb/training/season_replay.py`). Bar to clear: improved
K MAE and/or improved MLB BB hit rate. Compare against the current model
(`mlb-prediction-worker` rev `00055-pv8`, 36 features).

---

## 9. Decisions

| # | Decision | Resolution (2026-05-20) |
|---|----------|--------------------------|
| 1 | Phase 0 lineup-source strategy | **A+B+C** — all three. |
| 2 | Do Part A now as a standalone change | **Yes** — done 2026-05-20. |
| 3 | wOBA source for §5.1 | **Open** — decide at Phase 1 start: OBP+ISO composite from `batter_game_summary` vs a real wOBA source. |

## 10. Sequencing & effort

| Step | Effort | Status / gating |
|------|--------|-----------------|
| Phase 0-A — afternoon + overnight schedulers + dedup fix | Low | **DONE + VERIFIED 2026-05-20** |
| Phase 0-A follow-up — register `mlb_lineups` in `expected_outputs_planner` | Low | open |
| Phase 0-B — `projected_lineup` precompute (derive from history) | Medium | next |
| Phase 0-C — MLB projected-lineup scraper + processor + table | Medium–High | parallel with / after B |
| Phase 1 — lineup threat score features + leak test | Medium–High | after B |
| Phase 2 — expected-IP model | Medium | after Phase 1 |
| Phase 3 — integration + walk-forward | Medium | after Phase 2 |

**No feature code is written until the user approves proceeding to Phase 0-B.**
