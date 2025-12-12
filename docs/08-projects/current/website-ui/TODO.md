# Website UI Project - Implementation Todo List

**Created:** 2025-12-11
**Status:** Ready for implementation

---

## Phase 6 Backend (This Repo)

### High Priority - Required for Website Launch

- [ ] **Add `player_full_name` to PlayerProfileExporter index.json**
  - File: `data_processors/publishing/player_profile_exporter.py`
  - Change: Join with `nba_reference.nba_players_registry` to get full name
  - Effort: 15 min

- [ ] **Create TonightAllPlayersExporter**
  - File: `data_processors/publishing/tonight_all_players_exporter.py`
  - Output: `/v1/tonight/all-players.json`
  - Data: All players in tonight's games with card-level data
  - Schema: MASTER-SPEC.md §7.2
  - Effort: 3-4 hrs

- [ ] **Create TonightPlayerExporter**
  - File: `data_processors/publishing/tonight_player_exporter.py`
  - Output: `/v1/tonight/player/{lookup}.json`
  - Data: Tonight tab detail (factors, fatigue, recent form, prediction)
  - Schema: MASTER-SPEC.md §7.3
  - Effort: 2-3 hrs

- [ ] **Enhance PlayerProfileExporter**
  - File: `data_processors/publishing/player_profile_exporter.py`
  - Changes:
    - [ ] Expand game log from 20 to 50 games
    - [ ] Add full box score fields to game log
    - [ ] Add splits (rest, location, defense_tier, opponents)
    - [ ] Add `vs_line_pct` to each split
    - [ ] Add `next_game` field
    - [ ] Add `our_track_record` with OVER/UNDER breakdown
  - Schema: MASTER-SPEC.md §7.4
  - Effort: 2-3 hrs

- [ ] **Update daily_export.py CLI**
  - File: `backfill_jobs/publishing/daily_export.py`
  - Changes:
    - [ ] Add TonightAllPlayersExporter to export flow
    - [ ] Add TonightPlayerExporter (export all players with games today)
    - [ ] Add `--tonight` flag for website-specific exports
  - Effort: 1 hr

### Medium Priority - Polish

- [ ] **Add fatigue fields to BestBetsExporter**
  - File: `data_processors/publishing/best_bets_exporter.py`
  - Add: `fatigue_score`, `fatigue_level` to each pick
  - Effort: 30 min

- [ ] **Add `player_full_name` to BestBetsExporter**
  - File: `data_processors/publishing/best_bets_exporter.py`
  - Effort: 15 min

- [ ] **Add edge case flags**
  - Add `limited_data: true` when games_played < 10
  - Add `points_available: false` when game final but no boxscore yet
  - Effort: 30 min

- [ ] **Add current streak computation**
  - Compute from recent `player_game_summary` data
  - Add to TonightPlayerExporter output
  - Effort: 30 min

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

- [ ] **Test TonightAllPlayersExporter**
  - Date with games vs no games
  - Players with lines vs without
  - OUT players appear correctly
  - Verify JSON matches spec schema

- [ ] **Test TonightPlayerExporter**
  - Verify all splits compute correctly
  - Fatigue context JSON parses
  - System agreement correct

- [ ] **Test enhanced PlayerProfileExporter**
  - 50 games returned
  - Splits have correct aggregations
  - vs_line_pct accurate

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

- [ ] **Test exports locally**
- [ ] **Run full export for today's date**
- [ ] **Verify JSON files on GCS**
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
