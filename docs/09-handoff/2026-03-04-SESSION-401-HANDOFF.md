# Session 401 Handoff — New Data Sources Pipeline

**Date:** 2026-03-04
**Status:** Code written, BQ tables created, scheduler jobs active, **NOT COMMITTED / NOT DEPLOYED**
**Algorithm Version:** No algorithm change — infrastructure only

---

## Session Summary

Session 401 built the complete pipeline infrastructure for 10 new data sources: 4 projection sites (NumberFire, FantasyPros, DailyFantasyFuel, Dimers) and 6 external sources (TeamRankings, Hashtag Basketball DvP, RotoWire lineups, Covers referee stats, NBA tracking stats, VSiN betting splits). Also fixed the broken referee processor pipeline and added CLV (closing line value) tracking.

---

## Current State — What EXISTS

### Infrastructure Created (Persistent — Survives Session End)
- **10 BQ tables** in `nba_raw`: `numberfire_projections`, `fantasypros_projections`, `dailyfantasyfuel_projections`, `dimers_projections`, `teamrankings_team_stats`, `hashtagbasketball_dvp`, `rotowire_lineups`, `covers_referee_stats`, `nba_tracking_stats`, `vsin_betting_splits`
- **`snapshot_type` column** added to `nba_raw.odds_api_player_points_props` (STRING, default 'opening')
- **11 Cloud Scheduler jobs** created and ENABLED (see table below)
- **ProxyFuel credentials** deployed to `nba-scrapers` and `nba-phase2-raw-processors` Cloud Run services

### Code Written (LOCAL ONLY — Needs Commit + Push to Deploy)

**New files (untracked):**
| Category | Files |
|----------|-------|
| **Scrapers** (4 new) | `scrapers/projections/dailyfantasyfuel_projections.py` (491 lines), `scrapers/projections/dimers_projections.py` (557 lines), `scrapers/external/nba_tracking_stats.py` (342 lines), `scrapers/external/vsin_betting_splits.py` (361 lines) |
| **Scrapers** (6 existing from earlier session) | `scrapers/projections/numberfire_projections.py`, `scrapers/projections/fantasypros_projections.py`, `scrapers/external/teamrankings_stats.py`, `scrapers/external/hashtagbasketball_dvp.py`, `scrapers/external/rotowire_lineups.py`, `scrapers/external/covers_referee_stats.py` |
| **Phase 2 processors** (10 new) | `data_processors/raw/projections/{numberfire,fantasypros,dailyfantasyfuel,dimers}_processor.py`, `data_processors/raw/external/{teamrankings,hashtagbasketball_dvp,rotowire_lineups,covers_referee,nba_tracking,vsin_betting_splits}_processor.py` |
| **Path extractors** | `data_processors/raw/path_extractors/external_extractors.py` (10 extractors) |
| **Signals** (4 new) | `ml/signals/projection_consensus.py`, `ml/signals/dvp_mismatch.py`, `ml/signals/predicted_pace.py`, `ml/signals/closing_line_value.py` |
| **Schema SQL** | `schemas/bigquery/nba_raw/session_401_new_tables.sql` |

**Modified files (staged):**
| File | Changes |
|------|---------|
| `data_processors/raw/main_processor_service.py` | +30 lines — imports + 10 PROCESSOR_REGISTRY entries |
| `data_processors/raw/nbacom/nbac_referee_processor.py` | +9 lines — **CRITICAL FIX**: added missing `load_data()` method + fixed `transform_data()` file_path |
| `data_processors/raw/oddsapi/odds_api_props_processor.py` | +12 lines — `snapshot_type` from raw_data for CLV tracking |
| `data_processors/raw/path_extractors/__init__.py` | +28 lines — registered 10 new extractors |
| `ml/signals/registry.py` | +29 lines — registered 4 new signals |
| `ml/signals/supplemental_data.py` | +177 lines — CTEs for projections, DvP, tracking, CLV, betting splits |
| `scrapers/registry.py` | +62 lines — registered 10 scrapers + updated groups |
| `scrapers/utils/gcs_path_builder.py` | +16 lines — GCS path templates for all 10 sources |
| `scrapers/oddsapi/oddsa_player_props.py` | +3 lines — `snapshot_type` parameter passthrough |

### Cloud Scheduler Jobs (11 total, all ENABLED)

| Job | Schedule (UTC) | ET Equivalent |
|-----|----------------|---------------|
| `numberfire-projections-daily` | 14:30 | 10:30 AM |
| `fantasypros-projections-daily` | 14:30 | 10:30 AM |
| `dailyfantasyfuel-projections-daily` | 14:30 | 10:30 AM |
| `dimers-projections-daily` | 14:45 | 10:45 AM |
| `teamrankings-stats-daily` | 9:00 | 5:00 AM |
| `hashtagbasketball-dvp-daily` | 9:00 | 5:00 AM |
| `nba-tracking-stats-daily` | 10:00 | 6:00 AM |
| `rotowire-lineups-daily` | 21:00 | 5:00 PM |
| `vsin-betting-splits-daily` | 18:00 | 2:00 PM |
| `covers-referee-stats-weekly` | Mon 10:00 | Mon 6:00 AM |
| `nba-props-evening-closing` | 22:00 | 6:00 PM |

---

## CRITICAL: What Needs to Happen Next (Session 402)

### Priority 1: Commit & Deploy (BLOCKING — nothing works until this happens)

The Cloud Scheduler jobs are ACTIVE and will fire, but the scraper service doesn't have the new code deployed. The scrapers will fail silently because the registry entries don't exist on the deployed version.

```bash
# 1. Commit all Session 401 work
git add data_processors/raw/projections/ data_processors/raw/external/ \
        data_processors/raw/path_extractors/external_extractors.py \
        data_processors/raw/main_processor_service.py \
        data_processors/raw/nbacom/nbac_referee_processor.py \
        data_processors/raw/oddsapi/odds_api_props_processor.py \
        data_processors/raw/path_extractors/__init__.py \
        scrapers/projections/ scrapers/external/ \
        scrapers/registry.py scrapers/utils/gcs_path_builder.py \
        scrapers/oddsapi/oddsa_player_props.py \
        ml/signals/registry.py ml/signals/supplemental_data.py \
        ml/signals/closing_line_value.py ml/signals/dvp_mismatch.py \
        ml/signals/predicted_pace.py ml/signals/projection_consensus.py \
        schemas/bigquery/nba_raw/session_401_new_tables.sql

# 2. Push to main → triggers auto-deploy of:
#    - nba-scrapers (all 10 new scrapers)
#    - nba-phase2-raw-processors (all 10 processors)
#    - prediction-worker (signal changes)
#    - prediction-coordinator (supplemental_data changes)
git push origin main

# 3. Verify all 4 builds succeed
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5

# 4. Check deployment drift
./bin/check-deployment-drift.sh --verbose
```

### Priority 2: Verify Scraper Functionality

After deploy, test each scraper manually to verify they can actually fetch data from the live sites:

```bash
# Test projection scrapers (should run ~10:30 AM ET)
# Trigger manually via Cloud Scheduler "Force Run" or direct HTTP
gcloud scheduler jobs run numberfire-projections-daily --project=nba-props-platform --location=us-west2
gcloud scheduler jobs run fantasypros-projections-daily --project=nba-props-platform --location=us-west2
gcloud scheduler jobs run dailyfantasyfuel-projections-daily --project=nba-props-platform --location=us-west2
gcloud scheduler jobs run dimers-projections-daily --project=nba-props-platform --location=us-west2

# Check Cloud Run logs for errors
gcloud run services logs read nba-scrapers --project=nba-props-platform --region=us-west2 --limit=50

# Check GCS for output
gsutil ls gs://nba-scraped-data/projections/numberfire/2026-03-05/
gsutil ls gs://nba-scraped-data/external/teamrankings/2026-03-05/
```

### Priority 3: Verify Phase 2 Processing (GCS → BQ)

After scrapers produce data in GCS, Pub/Sub should trigger Phase 2 processors:

```sql
-- Check each new table has rows after first run
SELECT 'numberfire' as src, COUNT(*) as rows FROM nba_raw.numberfire_projections WHERE game_date >= CURRENT_DATE() - 1
UNION ALL
SELECT 'fantasypros', COUNT(*) FROM nba_raw.fantasypros_projections WHERE game_date >= CURRENT_DATE() - 1
UNION ALL
SELECT 'dailyfantasyfuel', COUNT(*) FROM nba_raw.dailyfantasyfuel_projections WHERE game_date >= CURRENT_DATE() - 1
UNION ALL
SELECT 'dimers', COUNT(*) FROM nba_raw.dimers_projections WHERE game_date >= CURRENT_DATE() - 1
UNION ALL
SELECT 'teamrankings', COUNT(*) FROM nba_raw.teamrankings_team_stats WHERE game_date >= CURRENT_DATE() - 1
UNION ALL
SELECT 'hashtagbasketball_dvp', COUNT(*) FROM nba_raw.hashtagbasketball_dvp WHERE game_date >= CURRENT_DATE() - 1
UNION ALL
SELECT 'rotowire', COUNT(*) FROM nba_raw.rotowire_lineups WHERE game_date >= CURRENT_DATE() - 1
UNION ALL
SELECT 'covers_referee', COUNT(*) FROM nba_raw.covers_referee_stats WHERE season = '2025-2026'
UNION ALL
SELECT 'nba_tracking', COUNT(*) FROM nba_raw.nba_tracking_stats WHERE game_date >= CURRENT_DATE() - 1
UNION ALL
SELECT 'vsin', COUNT(*) FROM nba_raw.vsin_betting_splits WHERE game_date >= CURRENT_DATE() - 1
ORDER BY rows DESC;
```

### Priority 4: Backfill Referee Data

The referee pipeline was broken since December. GCS has data from 2025-12-04 onward. After deploy:

```bash
# Check how many days of referee data exist in GCS
gsutil ls gs://nba-scraped-data/nba-com/referee-assignments/ | wc -l

# Trigger reprocessing for recent files
# Phase 2 can be triggered by re-publishing GCS paths to Pub/Sub
# Or manually invoke the processor for a specific date
```

### Priority 5: Test Scraper HTML Parsing

All 10 scrapers were written without testing against live sites (HTML selectors are best-guesses based on site structure). Expect some to fail on first run. Common issues:
- **BeautifulSoup selectors wrong** — site HTML doesn't match assumed structure
- **JavaScript-rendered content** — some sites (Dimers, DraftKings) render via JS and need Playwright/Selenium
- **Anti-bot protection** — sites like TeamRankings, Covers may block cloud IPs (ProxyFuel helps)
- **Player name normalization** — different sites use different name formats

**Testing approach:**
1. Force-run each scheduler job
2. Check Cloud Run logs for errors
3. For failures: review the HTML response, fix selectors, redeploy
4. Iterate until each scraper produces valid GCS output

### Priority 6: Validate Signals (After 7+ Days of Data)

```sql
-- Template: validate new signal HR against prediction_accuracy
SELECT
  '{signal_name}' AS signal,
  pa.recommendation,
  COUNT(*) AS picks,
  COUNTIF(pa.prediction_correct) AS wins,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) AS hr
FROM nba_predictions.signal_best_bets_picks sbp
JOIN nba_predictions.prediction_accuracy pa
  ON sbp.player_lookup = pa.player_lookup AND sbp.game_date = pa.game_date
WHERE pa.prediction_correct IS NOT NULL
  AND ABS(pa.predicted_points - pa.line_value) >= 3
  AND '{signal_name}' IN UNNEST(SPLIT(sbp.pick_signal_tags, ','))
GROUP BY 1, 2
ORDER BY 1, 2;
```

---

## Known Risks & Potential Issues

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Scraper HTML selectors wrong | HIGH | Test each manually, fix iteratively |
| Sites block cloud IPs | MEDIUM | ProxyFuel deployed, scraper base supports proxies |
| Dimers uses Next.js `__NEXT_DATA__` | MEDIUM | Scraper extracts from JSON in `<script>` tag — may need Playwright if server-side renders differently |
| Evening CLV scheduler targets wrong endpoint | MEDIUM | Uses `execute-workflow` path — verify scraper service handles `snapshot_type` parameter |
| Auto-deploy cascade breaks existing services | LOW | Only adds code, no modifications to existing behavior (except referee fix + snapshot_type) |
| Phase 2 processor schema mismatch with BQ | LOW | Tables created with matching schemas, but verify field types after first insert |

---

## Architecture Notes

### Data Flow for Each New Source
```
Cloud Scheduler → POST /scrape → nba-scrapers Cloud Run
  → Scraper fetches site → writes JSON to GCS
  → GCS Pub/Sub notification → nba-phase2-raw-processors Cloud Run
  → Path extractor identifies source type
  → PROCESSOR_REGISTRY maps to correct processor
  → Processor loads JSON, transforms, writes to BQ
  → supplemental_data.py CTEs query BQ tables
  → Signals evaluate supplemental data per-pick
```

### Key Files Map
```
Scraper → GCS Path Builder → Path Extractor → PROCESSOR_REGISTRY → Processor → BQ Table → supplemental_data CTE → Signal
```

---

## Files NOT Committed (Also Not Part of Session 401)

These exist from earlier sessions and should be reviewed before committing:
- `docs/08-projects/current/large-spread-starter-under-validation.md`
- `docs/09-handoff/2026-03-04-SESSION-398-HANDOFF.md`
- `results/session_373/`, `results/session_374_e2/`
