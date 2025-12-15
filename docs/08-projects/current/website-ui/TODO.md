# Website UI Project - Implementation Todo List

**Created:** 2025-12-11
**Status:** Ready for implementation

---

## Phase 6 Backend (This Repo)

### High Priority - Required for Website Launch

- [x] **Add `player_full_name` to PlayerProfileExporter index.json** ✅ Session 126
  - File: `data_processors/publishing/player_profile_exporter.py`
  - Change: Join with `nba_reference.nba_players_registry` to get full name

- [x] **Create TonightAllPlayersExporter** ✅ Session 126-127
  - File: `data_processors/publishing/tonight_all_players_exporter.py`
  - Output: `/v1/tonight/all-players.json`
  - Data: All players in tonight's games with card-level data
  - Tested: 93 players, 76 with lines, 5 games on 2021-12-25

- [x] **Create TonightPlayerExporter** ✅ Session 126-127
  - File: `data_processors/publishing/tonight_player_exporter.py`
  - Output: `/v1/tonight/player/{lookup}.json`
  - Data: Tonight tab detail (factors, fatigue, recent form, prediction)
  - Includes: splits, streak, quick numbers

- [x] **Enhance PlayerProfileExporter** ✅ Session 126
  - File: `data_processors/publishing/player_profile_exporter.py`
  - Changes:
    - [x] Expand game log from 20 to 50 games
    - [x] Add full box score fields to game log
    - [x] Add splits (rest, location, opponents)
    - [x] Add `our_track_record` with OVER/UNDER breakdown
    - [ ] Add `vs_line_pct` to each split (future)
    - [ ] Add `next_game` field (future)

- [x] **Update daily_export.py CLI** ✅ Session 126
  - File: `backfill_jobs/publishing/daily_export.py`
  - Changes:
    - [x] Add TonightAllPlayersExporter (`--only tonight`)
    - [x] Add TonightPlayerExporter (`--only tonight-players`)

### Medium Priority - Polish

- [x] **Add fatigue fields to BestBetsExporter** ✅ Session 128
  - File: `data_processors/publishing/best_bets_exporter.py`
  - Added: `fatigue_score`, `fatigue_level` to each pick
  - Added: fatigue to rationale ("Well-rested" / "Elevated fatigue")

- [x] **Add `player_full_name` to BestBetsExporter** ✅ Session 126
  - File: `data_processors/publishing/best_bets_exporter.py`

- [x] **Add edge case flags** ✅ Session 128
  - Added `limited_data: true` when games_played < 10
  - Added to: TonightAllPlayersExporter, TonightPlayerExporter
  - [ ] `points_available: false` (deferred - not needed for current use case)

- [x] **Add current streak computation** ✅ Session 126
  - Already in TonightPlayerExporter (`current_streak` field)

- [x] **Add vs_line_pct to splits** ✅ Session 128
  - Added to TonightPlayerExporter splits query
  - Displayed in tonight's factors descriptions

### Low Priority - V1.5

- [ ] **Create StreaksExporter**
  - Output: `/v1/streaks/today.json`
  - Data: Players on OVER/UNDER/prediction streaks
  - Effort: 2 hrs

- [ ] **Add defense tier ranking**
  - Precompute daily team defense tier (1-30)
  - Add to player splits and tonight factors
  - Effort: 1 hr

---

## Frontend (Separate Repo: nba-props-website)

### Setup

- [ ] **Create GitHub repo `nba-props-website`**
- [ ] **Initialize Next.js 14+ project**
  ```bash
  npx create-next-app@latest nba-props-website --typescript --tailwind --app
  ```
- [ ] **Configure for static export**
  - Set `output: 'export'` in next.config.js
- [ ] **Initialize Firebase Hosting**
  ```bash
  firebase init hosting
  ```
- [ ] **Set up CI/CD**
  - GitHub Actions → Firebase deploy on main branch

### Core Pages

- [ ] **Tonight page (default `/`)**
  - [ ] Best Bets horizontal scroll section
  - [ ] Player grid with cards
  - [ ] Two tabs: Tonight's Picks / All Players
  - [ ] Filters (game, recommendation, healthy only)
  - [ ] Sort options (PPG, confidence, edge, game time)

- [ ] **Player Detail Panel**
  - [ ] Slide-out panel (desktop) / bottom sheet (mobile)
  - [ ] Tonight tab content
  - [ ] Profile tab content (lazy loaded)

- [ ] **Results page (`/results`)**
  - [ ] Yesterday's results
  - [ ] Rolling performance (7-day, 30-day, season)
  - [ ] Highlights (best/worst predictions)

- [ ] **Player Profile page (`/players/[lookup]`)**
  - [ ] For players not playing today
  - [ ] Reuse Profile tab component
  - [ ] Next game banner

### Components

- [ ] **PlayerCard** - Grid card for player
- [ ] **BestBetCard** - Compact card for best bets section
- [ ] **PlayerDetailPanel** - Slide-out/bottom sheet
- [ ] **TonightTab** - Tonight tab content
- [ ] **ProfileTab** - Profile tab content
- [ ] **GameLogGrid** - GitHub-style game history grid
- [ ] **FatigueIndicator** - 🟢🟡🔴 badge
- [ ] **Last10MiniGrid** - ●○ pattern display
- [ ] **SearchBar** - With autocomplete
- [ ] **GameFilter** - Game selector dropdown
- [ ] **BottomNav** - Mobile navigation

### Data Layer

- [ ] **API fetch helpers** (`lib/api.ts`)
- [ ] **TypeScript types** (`lib/types.ts`)
- [ ] **React Query or SWR setup** for caching

### Styling & Polish

- [ ] **Mobile-first responsive design**
- [ ] **Dark mode support** (optional V1.5)
- [ ] **Loading states / skeletons**
- [ ] **Error states**
- [ ] **Empty states** (no games today, etc.)

---

## Testing & Validation

### Backend Testing

- [x] **Test TonightAllPlayersExporter** ✅ Session 127
  - Tested with 2021-12-25 (Christmas games)
  - 93 players, 76 with lines, 5 games
  - Uploads to GCS successfully (75KB)

- [x] **Test TonightPlayerExporter** ✅ Session 127
  - Tested with clintcapela, lebronjames
  - Splits compute correctly
  - Fatigue level/score working
  - Recent form (10 games) populated

- [x] **Test enhanced PlayerProfileExporter** ✅ Session 126
  - 50 games returned
  - Splits have correct aggregations
  - Track record with OVER/UNDER breakdown

### Frontend Testing

- [ ] **Mobile responsiveness** - Test on various screen sizes
- [ ] **Search functionality** - Autocomplete works
- [ ] **Panel behavior** - Slide-out/bottom sheet works
- [ ] **Data loading** - Correct endpoints called
- [ ] **Cache behavior** - Appropriate revalidation

---

## Documentation

- [x] **MASTER-SPEC.md** - Complete UI/API specification
- [x] **PHASE6-PUBLISHING-ARCHITECTURE.md** - Backend architecture
- [x] **UI-SPEC-V2.md** - Original UI brainstorm
- [x] **DATA-INVESTIGATION-RESULTS.md** - Data availability
- [ ] **How It Works page content** - Methodology explanation (static content)
- [ ] **README for frontend repo** - Setup instructions

---

## Deployment

### Backend (Phase 6)

- [x] **Test exports locally** ✅ Session 127
- [x] **Run full export for 2021-12-25** ✅ Session 127
- [x] **Verify JSON files on GCS** ✅ Session 127
  - `gs://nba-props-platform-api/v1/tonight/all-players.json`
  - `gs://nba-props-platform-api/v1/tonight/player/{lookup}.json`
- [ ] **Set up Cloud Scheduler for daily export** (if not already)

### Frontend

- [ ] **Test build locally** (`npm run build`)
- [ ] **Deploy to Firebase Hosting** (`firebase deploy`)
- [ ] **Configure custom domain** (if applicable)
- [ ] **Set up Firebase Hosting preview channels** for PRs

---

## Quick Reference - File Locations

### Backend (this repo)
```
data_processors/publishing/
├── tonight_all_players_exporter.py   # NEW
├── tonight_player_exporter.py        # NEW
├── player_profile_exporter.py        # ENHANCE
├── best_bets_exporter.py             # ENHANCE
└── base_exporter.py                  # No change

backfill_jobs/publishing/
└── daily_export.py                   # UPDATE
```

### Frontend (new repo)
```
nba-props-website/
├── app/
│   ├── page.tsx                      # Tonight (home)
│   ├── results/page.tsx              # Results
│   └── players/[lookup]/page.tsx     # Player profile
├── components/
├── lib/
│   ├── api.ts
│   └── types.ts
├── firebase.json
└── next.config.js
```

---

## Estimated Effort Summary

| Category | Tasks | Effort |
|----------|-------|--------|
| Phase 6 Backend (High Priority) | 5 tasks | ~8-10 hrs |
| Phase 6 Backend (Medium Priority) | 4 tasks | ~2 hrs |
| Frontend Setup | 5 tasks | ~2 hrs |
| Frontend Core Pages | 4 pages | ~8-12 hrs |
| Frontend Components | 11 components | ~6-8 hrs |
| Testing | Various | ~4 hrs |
| **Total** | | **~30-40 hrs** |

---

*Last updated: 2025-12-11*
