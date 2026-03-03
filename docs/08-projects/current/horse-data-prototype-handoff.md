# Horse Data Prototype — Handoff

**Date:** 2026-02-28
**Repo:** `~/code/horse-data`
**Branch:** `main` (1 unpushed commit from prior session + new uncommitted work)

## What Was Done

Built Phases 1-4 of the prototype data plan — three new scrapers, entity resolution, and a seed pipeline.

### New Scrapers

1. **`kwpn_horse_search`** (`src/horse_data/scrapers/kwpn_horse_search.py`)
   - KWPN Dutch Warmblood REST API: `GET /kwpnwebapi/horses/searchtext/nl-NL/{stallionsOnly}/{query}/{direction}/{year}/{showDeceased}/false`
   - Returns up to 100 horses with name, sire ("Father"), damsire ("MothersFather"), registration, color
   - No auth needed. Breeding direction codes: J=jumping, D=dressage

2. **`kwpn_pedigree`** (`src/horse_data/scrapers/kwpn_pedigree.py`)
   - Fetches `/database?paard={horse_code}` HTML page
   - Extracts `var datasource = {...}` JS object (single-quoted JSON tree)
   - Parses nested `children[]` arrays into `Pedigree` model with position codes (S, D, SS, SD, etc.)
   - 3 generations deep

3. **`blup_pedigree`** (`src/horse_data/scrapers/blup_pedigree.py`)
   - Fetches `/sv-SE/horses/{blup_id}` HTML page
   - Parses `<table class="genealogical">` — rowspan-based binary tree (16/8/4/2/1)
   - 4 generations deep, up to 30 ancestors

### Entity Resolution

`src/horse_data/transforms/entity_resolution.py`
- `EntityResolver` class merges horses across KWPN, BLUP, USEF
- Dual-key matching: `name|year|sire` (full) and `name|year` (basic)
- `normalize_name()` strips accents, "(SF)" suffixes, special chars
- Saves/loads JSON for incremental builds
- Confidence: low → medium (name+year+sire) → high (multi-source match)

### Seed Pipeline

`src/horse_data/pipeline/seed.py`
- Orchestrates: BLUP rankings → BLUP pedigrees → KWPN search → KWPN pedigrees → USEF search → entity resolution
- CLI: `python -m horse_data seed --limit 100 --output data/seed`
- Outputs: `unified_horses.json`, `pedigrees.json`, `stats.json`

### Other Changes

- `KwpnHorse` dataclass added to `models.py`
- 3 new scrapers registered in `registry.py`
- `scraper-registry.yaml` updated (8 → 11 scrapers)
- `cli.py` extended with `seed` subcommand + `scrape`/`list` subcommands (backward compatible)

### Tests

146 tests total (was 126), all passing. New test files:
- `tests/test_kwpn_scrapers.py` (16 tests)
- `tests/test_blup_pedigree.py` (9 tests)
- `tests/test_entity_resolution.py` (17 tests)
- `tests/test_seed_pipeline.py` (3 tests)

## What's Next (in priority order)

### Phase 5: Run the Seed Pipeline
The pipeline is built but hasn't been run against live APIs yet. Run:
```bash
cd ~/code/horse-data
python -m horse_data seed --limit 100 --output data/seed
```
Check `data/seed/stats.json` for coverage. If counts are low, increase `--limit 350`.

### Phase 5b: Data Loading into Postgres
Get data into a queryable serving DB for horse-web:
- Create Postgres schema: `unified_horses`, `pedigrees`, `sport_results`, `breeding_values`
- Write a loader that reads `data/seed/*.json` and inserts into Postgres
- Location: `src/horse_data/loaders/postgres.py`
- Connect horse-web (`~/code/horse-web`) to read from this DB

### Phase 6: Horse Telex (if needed)
Only build if KWPN + BLUP pedigree coverage has gaps. Test at `horsetelex.com`:
- `POST /horses/jsonsearch` for search
- `/horses/pedigree/{id}` for pedigree pages
- May have Cloudflare protection — use browser infrastructure in `base.py`

### Phase 7: WBFSH Rankings (nice-to-have)
- Scrape world sire/dam/studbook rankings from wbfsh.org
- Adds "World Ranking: #3 Jumping Sire" to stallion profiles

## Key Technical Details

### KWPN API Quirks
- The searchtext endpoint URL has positional path params, not query params
- The `Count` field returns negative numbers (e.g., -914) — ignore it, use `len(Top100)`
- Gender codes: 1=stallion, 2=gelding, 3=mare
- The pedigree is NOT from an API — it's a JS variable embedded in the HTML detail page

### BLUP Pedigree Table Structure
- `<table class="genealogical">` with 17 rows (1 header + 16 data)
- Column 1: subject horse (rowspan=16)
- Column 2: sire (rowspan=8) + dam (rowspan=8)
- Column 3: 4 grandparents (rowspan=4 each)
- Column 4: 8 great-grandparents (rowspan=2 each)
- Column 5: 16 great-great-grandparents (rowspan=1 each)
- Sire cells have CSS class `father`

### Entity Resolution Matching
- Uses `_by_full_key` (name|year|sire) and `_by_basic_key` (name|year)
- KWPN has sire info → indexed in both
- BLUP/USEF search don't return sire → indexed in basic only
- Cross-source matching works: KWPN full key → basic key matches BLUP basic key

## Project Docs
- `docs/projects/current/prototype-data-pipeline-2026-02/README.md`
- `docs/projects/current/prototype-data-pipeline-2026-02/PROGRESS.md`
