# NBA Props Platform - UI Specification v2

**Last Updated:** 2025-12-11 (v2.0 - Major revision)
**Status:** Draft - Ready for wireframing
**Source:** Claude web chat brainstorm session

> Note: This is the original UI spec from the brainstorming session. See MASTER-SPEC.md for the consolidated specification with data implementation details.

---

## Changelog from v1

| Change | Description |
|--------|-------------|
| Tabbed player modal | Added "Tonight" and "Profile" tabs to detail panel |
| Best Bets section | Top 5-10 picks displayed above main grid |
| Default sort by PPG | Star players first, with sort options |
| Player Profile page | Standalone page for players without games (reuses Profile tab) |
| All Players default state | Requires game selection before showing players |
| OUT players visible | Shown grayed out on All Players tab |
| Simplified GitHub grid | No intensity shading, added ●/○ icons for accessibility |
| Mobile navigation | Bottom nav spec added |
| In-progress handling | Cards update during/after games |

---

## Product Philosophy

### Core Principle
**Research-first, prediction-supplemented.** The organized, contextualized data is the product. The prediction is one data point that supports the user's own decision-making.

### Target Users (V1)

**Primary: Sports Bettor**
- See who's playing tonight
- Research player stats and situational data
- Form their own opinion
- Consider our prediction as one input
- Make betting decision

**Secondary: Casual Fan**
- Browse players by team
- Check how players are performing
- General NBA stats interest
- May not be betting

### Differentiator
Clean presentation of relevant data, surfaced intelligently based on tonight's context. Not just predictions, not just raw stats - the intersection.

---

## Information Architecture

### V1 Structure

```
┌─────────────────────────────────────────────────────┐
│  [Logo]              [Search]           [Results]   │  ← Header
├─────────────────────────────────────────────────────┤
│  ┌─────────────────┬───────────────┐                │
│  │ Tonight's Picks │  All Players  │                │  ← Main tabs
│  └─────────────────┴───────────────┘                │
│  [Filter controls]                   [Sort: PPG ▼]  │
│                                                     │
│  ┌─────────────────────────────────┐                │
│  │ 🏆 BEST BETS                    │                │  ← Featured section
│  │ [Top 5-10 picks in compact row] │                │
│  └─────────────────────────────────┘                │
│                                                     │
│  [Player Grid]                                      │
│                                                     │
│              [Slide-out Detail Panel] ──────────→   │
│              ┌────────────────────────────────┐     │
│              │ [Tonight] [Profile]  ← tabs    │     │
│              │                                │     │
│              │ [Tab content]                  │     │
│              └────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

### Navigation

| Item | Purpose | V1 Scope |
|------|---------|----------|
| Tonight's Picks (Default Tab) | Bettable players with spreads + predictions | ✅ Build |
| All Players (Tab) | Everyone playing today, for casual fans | ✅ Build |
| Results | Yesterday's outcomes, rolling accuracy | ✅ Build |
| Search | Find any player by name | ✅ Build |
| Player Profile | Standalone page for players without games | ✅ Build |

### Mobile Navigation

Bottom navigation bar with 3 items:

| Icon | Label | Destination |
|------|-------|-------------|
| 🏀 | Tonight | Two-tab view (Picks/All Players) |
| 📊 | Results | Results page |
| 🔍 | Search | Search overlay or page |

Tab switching (Picks ↔ All Players) via horizontal swipe or tab pills at top of content area.

---

## Page Definitions

### Tonight's Picks (Default Tab)
- **Best Bets section** at top (5-10 highest confidence picks)
- Grid of all players with spreads + predictions
- Filterable by game, recommendation, healthy only
- **Default sort: Season PPG** (star players first)
- Click player → detail panel with Tonight/Profile tabs

### All Players (Tab)
- **Requires game selection first** (prevents 100+ player dump)
- Shows everyone playing in selected game, including OUT players
- Filterable by team within game
- Click player → detail panel
- Players without spreads show stats focus

### Results
- Yesterday's predictions vs actual outcomes
- Win/loss record, accuracy metrics
- Rolling performance (7-day, 30-day, season)

### Search
- Search bar in header (always visible)
- Type player name → autocomplete → results
- **If player has game today**: Opens detail panel
- **If player has no game today**: Opens Player Profile page

### Player Profile Page
- Standalone page for players not playing today
- Reuses "Profile" tab content from detail panel
- Shows season stats, game log, all splits
- Banner if upcoming game: "Next game: Dec 14 vs PHX"

### Player Detail (Panel)
- Slides in from right (desktop) or bottom sheet (mobile)
- **Two tabs: "Tonight" and "Profile"**
- Tonight tab: Focused on today's betting decision
- Profile tab: Complete historical view

---

## Tab 1: Tonight's Picks

### Best Bets Section

Displayed above the main grid. Shows top 5-10 picks ranked by confidence × edge.

```
🏆 BEST BETS

┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ Jokic    │ │ Tatum    │ │ Booker   │ │ Edwards  │ │ Morant   │
│ UNDER    │ │ OVER     │ │ UNDER    │ │ OVER     │ │ UNDER    │
│ 82%      │ │ 78%      │ │ 76%      │ │ 74%      │ │ 72%      │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
           ← scroll on mobile →
```

**Card mini format:**
- Player name (last name or short)
- Recommendation (OVER/UNDER)
- Confidence percentage
- Click → opens detail panel

### Inclusion Criteria

```
Show player if:
  has_spread = true
  AND has_prediction = true
```

This naturally excludes:
- Players confirmed OUT (spreads pulled)
- Deep bench players (no betting market)
- Most DOUBTFUL players (spreads usually pulled)

### Player Card Design (Picks Tab)

**Standard Card (Healthy/Probable)**
```
┌────────────────────────────────────┐
│ LeBron James              🔴 Tired │
│ LAL @ DEN • 7:30 PM               │
│ Line: 25.5                         │
│ → UNDER 72%                        │
│ Last 10: ●●○●○○●○○● (4-6)         │
└────────────────────────────────────┘
```

**Injury Card (Questionable)**
```
┌────────────────────────────────────┐
│ Anthony Davis       ⚠️ Questionable │
│ LAL @ DEN • 7:30 PM               │
│ Line: 22.5                         │
│ → OVER 68%                         │
│ Ankle - Monitor status             │
│ Last 10: ●●●●○●●○●● (7-3)         │
└────────────────────────────────────┘
```

**In-Progress Card**
```
┌────────────────────────────────────┐
│ LeBron James              🔴 Tired │
│ LAL @ DEN • 🔴 LIVE Q3 4:32       │
│ Line: 25.5                         │
│ Current: 18 pts                    │
│ Prediction was: UNDER 72%          │
└────────────────────────────────────┘
```

**Final Card**
```
┌────────────────────────────────────┐
│ LeBron James              🔴 Tired │
│ LAL @ DEN • FINAL                  │
│ Line: 25.5                         │
│ Final: 28 pts ✅ OVER              │
│ Prediction: UNDER 72% ❌           │
└────────────────────────────────────┘
```

### Card Elements (Picks Tab)

| Element | Source | Notes |
|---------|--------|-------|
| Player name | `player_full_name` | |
| Fatigue indicator | Calculated | 🟢 Fresh / 🟡 Normal / 🔴 Tired |
| Injury status | `injury_status` | Only if not healthy |
| Injury reason | `reason` | Brief, e.g., "Ankle" |
| Matchup | Schedule | Team @ Opponent |
| Game time/status | Schedule + live | Time, LIVE, or FINAL |
| Line | `current_points_line` | |
| Recommendation | `recommendation` | OVER / UNDER / PASS |
| Confidence | `confidence_score` | Percentage |
| Last 10 mini | Calculated | ● OVER / ○ UNDER pattern |
| Current pts | Live data | Only during game |
| Final pts | Post-game | Only after game |
| Result | Calculated | ✅ hit / ❌ miss |

### Filter Controls (Picks Tab)

**Filters:**
- Game: Dropdown of tonight's games (LAL @ DEN, etc.)
- Recommendation: All / OVER / UNDER / PASS
- Healthy only: Toggle to hide questionable players

**Sort Options:**
- **PPG (default)** - Season scoring average, highest first
- Confidence - Our confidence score, highest first
- Edge - Predicted margin vs line, highest first
- Game Time - Chronological by tipoff

---

## Tab 2: All Players

### Default State (No Selection)

Before selecting a game, show game matchup selector:

```
┌─────────────────────────────────────────────────┐
│                                                 │
│  Select a game to browse players                │
│                                                 │
│  ┌───────────────┐  ┌───────────────┐          │
│  │ LAL @ DEN     │  │ PHX @ GSW     │          │
│  │ 7:30 PM       │  │ 8:00 PM       │          │
│  └───────────────┘  └───────────────┘          │
│                                                 │
│  ┌───────────────┐  ┌───────────────┐          │
│  │ MIA @ BOS     │  │ NYK @ CHI     │          │
│  │ 8:30 PM       │  │ 9:00 PM       │          │
│  └───────────────┘  └───────────────┘          │
│                                                 │
│  Or search for any player by name               │
│                                                 │
└─────────────────────────────────────────────────┘
```

### After Game Selection

Shows all players from both teams, grouped by team.

### Inclusion Criteria

```
Show player if:
  has_game_today = true
  AND is_on_roster = true
```

Shows everyone playing tonight, regardless of spread availability.
**Includes OUT players** (grayed out, at bottom of team list).

### Player Card Design (All Players Tab)

**Card WITH Spread:**
```
┌────────────────────────────────────┐
│ LeBron James              🔴 Tired │
│ LAL @ DEN • 7:30 PM               │
│ Season: 24.8 pts • Last 5: 20.4   │
│ Line: 25.5 → UNDER 72%            │
│ Last 10: ●●○●○○●○○●               │
└────────────────────────────────────┘
```

**Card WITHOUT Spread:**
```
┌────────────────────────────────────┐
│ Austin Reaves                      │
│ LAL @ DEN • 7:30 PM               │
│ Season: 17.2 pts • Last 5: 19.1   │
│ Minutes: 28.4 avg                  │
│ Last 10: 18 22 15 19 21 17 20...  │
│ No spread available                │
└────────────────────────────────────┘
```

**OUT Player Card:**
```
┌────────────────────────────────────┐
│ Anthony Davis                 OUT  │  ← Grayed out styling
│ LAL @ DEN • 7:30 PM               │
│ Season: 24.2 pts                   │
│ Ankle - Out for game               │
│                                    │
└────────────────────────────────────┘
```

### Card Elements (All Players Tab)

| Element | Source | Notes |
|---------|--------|-------|
| Player name | `player_full_name` | |
| Fatigue indicator | Calculated | Only if playing (not OUT) |
| OUT badge | `injury_status` | When status = 'out' |
| Matchup | Schedule | Team @ Opponent |
| Game time | Schedule | Local time |
| Season avg | `player_game_summary` | Points average |
| Last 5 avg | Calculated | Recent form |
| Minutes avg | `player_game_summary` | Playing time (no spread only) |
| Line + Recommendation | Prediction | Only if spread exists |
| Last 10 mini | Calculated | ●/○ if spread, raw pts if not |
| "No spread" label | Conditional | When no betting line |

### Filter Controls (All Players Tab)

**Filters:**
- Game: Required selection (game matchup pills)
- Team: Filter to single team within game (optional)

**Default Sort:** Team groups, then by minutes played (starters first)

### OUT Player Treatment

Players confirmed OUT appear on All Players tab with:
- Grayed out card styling (reduced opacity)
- "OUT" badge with reason (e.g., "OUT - Ankle")
- Season averages shown (no recent form or fatigue)
- Positioned at bottom of team's player list

OUT players do NOT appear on Picks tab (no spread available).

---

## Shared Card Elements

### Fatigue Indicator Logic

| Level | Icon | Criteria |
|-------|------|----------|
| Fresh | 🟢 | 2+ days rest, normal minutes |
| Normal | 🟡 | 1 day rest, typical load |
| Tired | 🔴 | B2B, OR multiple B2Bs in last 14 days, OR elevated minutes |

### Injury Visual Treatment

| Status | Treatment |
|--------|-----------|
| Healthy | Normal card |
| Probable | Normal card (small badge optional) |
| Questionable | Yellow accent/border, ⚠️ badge, reason shown |
| Doubtful | Orange accent (rare - usually no line) |
| Out | Grayed out (All Players only), not shown on Picks |

### In-Progress Game Handling

| State | Card Shows |
|-------|------------|
| Pre-game | Normal card with line + prediction |
| In-progress | 🔴 LIVE badge, current points, prediction frozen |
| Final | FINAL badge, actual points, result (✅/❌) |

Cards update automatically. Full game details move to Results page next day.

### Last 10 Mini Grid (Colorblind Accessible)

| Result | Color | Icon |
|--------|-------|------|
| OVER (beat line) | Green | ● (filled) |
| UNDER (missed line) | Red | ○ (empty) |
| No line that game | Gray | - (dash) |

Icons provide accessibility for colorblind users (~8% of men).
No intensity shading in v1 (deferred to v1.5).

---

## Player Detail Panel

### Panel Behavior

**Desktop:**
- Slides in from right
- ~40% of viewport width
- Main grid remains visible (Airbnb pattern)
- Click outside or X to close

**Mobile:**
- Bottom sheet, swipe up to expand
- Nearly full screen when expanded
- Swipe down to close

### Two-Tab Structure

```
┌─────────────────────────────────────┐
│ [X]  LeBron James                   │
│                                     │
│ ┌──────────┬──────────┐            │
│ │ Tonight  │ Profile  │  ← tabs    │
│ └──────────┴──────────┘            │
│                                     │
│ [Selected tab content]              │
│                                     │
└─────────────────────────────────────┘
```

**When player has game today:** Both tabs available, "Tonight" is default

**When player has no game today:** Only "Profile" tab shown (or "Tonight" shows "No game today" message)

---

## Tonight Tab (Detail Panel)

### Purpose
Focused decision-support for tonight's bet. Shows only what's relevant to this game.

### Structure

```
┌─────────────────────────────────────┐
│ TONIGHT'S GAME                      │
│                                     │
│ LAL @ DEN • 7:30 PM ET             │
│ Line: 25.5 (opened 24.0, ↑1.5)     │
│ Rest: 1 day • Status: Available     │
├─────────────────────────────────────┤
│ QUICK NUMBERS                       │
│                                     │
│ Season    Last 10    Last 5         │
│  24.8      22.1 ↓     20.4          │
│                                     │
│ Minutes: 32.1 last 5 (↓ from 34.2) │
│ Fatigue: 🔴 Tired                   │
│   B2B, 3rd game in 4 days          │
│ Streak: UNDER last 3                │
├─────────────────────────────────────┤
│ TONIGHT'S FACTORS                   │
│                                     │
│ These factors apply to tonight:     │
│                                     │
│ • B2B: 19.8 avg (vs 24.8 overall)  │
│   12 games, -5.0 pts typical       │
│                                     │
│ • Away: 22.1 avg (vs 27.5 home)    │
│   35 games                          │
│                                     │
│ • vs DEN: 19.8 avg                 │
│   5 games                           │
│                                     │
│ • vs #3 Defense: 20.1 avg          │
│   18 games                          │
├─────────────────────────────────────┤
│ RECENT FORM                         │
│                                     │
│ Last 10: ●●○●○○●○○●                │
│ vs Line: 4-6 (40%)                 │
│                                     │
│ [tap any game for details]         │
├─────────────────────────────────────┤
│ OUR TAKE                            │
│                                     │
│ Prediction: 22.4 pts               │
│ Confidence: 74%                     │
│ Recommendation: UNDER               │
│                                     │
│ B2B games typically cost him ~5    │
│ points. Denver's elite defense     │
│ (ranked #3) limits scorers.        │
│ Minutes trending down suggests     │
│ reduced workload.                   │
│                                     │
│ Systems: 4 of 5 agree on UNDER     │
├─────────────────────────────────────┤
│ [View Full Profile →]               │
└─────────────────────────────────────┘
```

### Section Details

**Tonight's Game**
- Matchup, game time
- Current line with movement from open
- Days rest
- Injury status (if applicable)

**Quick Numbers**
- Season / Last 10 / Last 5 averages with trend arrows
- Minutes trend
- Fatigue level with explanation
- Current streak (if 3+ games)

**Tonight's Factors**
- **Only splits relevant to this specific game**
- Shows the factor, average, and comparison to baseline
- Sample size for context
- Examples: "B2B: 19.8 avg" only shows if tonight IS a B2B

**Recent Form**
- Last 10 games mini-grid (●/○)
- Win rate vs line
- Tappable for game details

**Our Take**
- Prediction, confidence, recommendation
- 2-3 sentence explanation of key factors
- System agreement

---

## Profile Tab (Detail Panel)

### Purpose
Complete historical view of the player. Used for deep research and for players without games today.

### Structure

```
┌─────────────────────────────────────┐
│ SEASON OVERVIEW                     │
│                                     │
│ 2024-25 Season                      │
│ 24.8 PPG • 7.2 RPG • 8.1 APG       │
│ 34.2 MPG • 52 games                │
├─────────────────────────────────────┤
│ GAME LOG                            │
│                                     │
│ Last 30 Games                       │
│                                     │
│ [28][22][19][31][24][25][18][29]..│
│ [26][30][17][23][28][25][22][19]..│
│ [27][24][21][26][30][17][23][28]..│
│                                     │
│ ● = OVER  ○ = UNDER  - = no line   │
│                                     │
│ vs Line: 17-13 (57%)               │
│ vs 25.5: 19 of 30 over             │
│                                     │
│ [Tap any game for full box score]  │
├─────────────────────────────────────┤
│ ALL SITUATIONAL SPLITS              │
│                                     │
│ Days Rest:                          │
│      B2B    1-day   2-day    3+    │
│ Pts  19.8   21.2    24.1    26.8   │
│      (12)   (28)    (22)    (18)   │
│                                     │
│ Location:                           │
│      Home    Away                   │
│ Pts  27.5    22.1                   │
│      (40)    (35)                   │
│                                     │
│ vs Division:                        │
│      Pacific  Northwest  Southwest │
│ Pts  25.2     23.1       24.8     │
│                                     │
│ vs Defense Tier:                    │
│      Top 10   Middle    Bottom 10  │
│ Pts  21.2     24.5      28.1      │
│      (18)     (22)      (12)      │
│                                     │
│ Opponent History:                   │
│ vs DEN: 19.8 (5)  vs PHX: 26.2 (4) │
│ vs GSW: 24.1 (6)  vs SAC: 22.8 (3) │
├─────────────────────────────────────┤
│ OUR TRACK RECORD                    │
│                                     │
│ Predictions on LeBron: 47 total    │
│ Overall: 62% (29-18)               │
│ OVER calls: 58% (14-10)            │
│ UNDER calls: 65% (15-8)            │
│ Avg error: 3.2 points              │
│ Bias: Slightly under-predicts      │
├─────────────────────────────────────┤
│ ADVANCED STATS                      │
│                                     │
│ [Expandable sections]              │
│ [+ Monthly Breakdown]              │
│ [+ Day of Week]                    │
│ [+ Shot Distribution]              │
│ [+ Teammate Impact]                │
└─────────────────────────────────────┘
```

### Section Details

**Season Overview**
- Key averages (PPG, RPG, APG, MPG)
- Games played
- Season context

**Game Log**
- GitHub-style grid showing last 30 games
- Color-coded: ● green OVER, ○ red UNDER, - gray no line
- Summary stats below
- Tappable cells for full game details

**All Situational Splits**
- Complete splits (not just relevant ones)
- Rest buckets (B2B, 1-day, 2-day, 3+)
- Home/Away
- Division or conference
- Defense tier (Top 10, Middle, Bottom 10)
- Opponent history (teams with 3+ games)

**Our Track Record**
- Total predictions on this player
- Win rate overall, by direction (OVER/UNDER)
- Average error
- Bias tendency

**Advanced Stats**
- Expandable sections for power users
- Monthly trends, day of week, shot distribution, etc.

---

## Player Profile Page (Standalone)

### When Used
- User searches for player not playing today
- Direct link to player profile

### Structure
Identical to Profile tab content, displayed as full page instead of panel.

### Additional Elements

**Banner (if upcoming game):**
```
┌─────────────────────────────────────┐
│ 📅 Next Game: Thu Dec 14 vs PHX    │
│ [View prediction when available]    │
└─────────────────────────────────────┘
```

**Banner (if no upcoming game soon):**
```
┌─────────────────────────────────────┐
│ No upcoming games scheduled         │
└─────────────────────────────────────┘
```

### Navigation
- Back button returns to previous page (search results, etc.)
- Can navigate to other players via search

---

## GitHub Grid Detail (Game Log)

### Visual Design

```
Last 30 Games

[28][22][19][31][24][25][18][29][24][21]
[26][30][17][23][28][25][22][19][27][24]
[27][24][21][26][30][17][23][28][25][22]
 ↑                                    ↑
Most recent                      Oldest
```

### Cell Specifications

| Attribute | Value |
|-----------|-------|
| Size | ~32x32px desktop, ~28x28px mobile |
| Gap | 4px |
| Border radius | 4px |
| Font | Small, centered number |

### Cell Styling (Colorblind Accessible)

| Result | Background | Text | Icon |
|--------|------------|------|------|
| OVER | Green (#22c55e) | White | ● |
| UNDER | Red (#ef4444) | White | ○ |
| No line | Gray (#9ca3af) | Dark gray | - |

**Mobile:** Numbers may be hidden, show only color + icon. Expand on tap.

### Hover/Tap Popover

```
┌─────────────────────────┐
│ Dec 8 vs PHX (W)        │
│                         │
│ 28 pts • 35 min         │
│ FG: 10/18 • 3PT: 2/5    │
│ Line: 25.5 → OVER +2.5  │
│                         │
│ [View full box score]   │
└─────────────────────────┘
```

### Summary Stats Below Grid

```
vs Line: 17-13 (57% OVER)
vs 25.5: 19 of 30 would hit OVER
```

- First line: actual results against each game's line
- Second line: how many games would beat current/tonight's line

---

## Results Page

### Purpose
Build trust by showing prediction outcomes transparently.

### Content

**Yesterday's Results:**
```
December 10, 2024 Results

Predictions: 42
Record: 26-16 (62%)

[Grid of yesterday's predictions with outcomes]
```

**Rolling Performance:**
```
System Performance

         7-day    30-day   Season
Record   18-12    84-62    312-248
Win %    60%      58%      56%
```

**Best/Worst Calls:**
- Highlight biggest wins (high confidence that hit)
- Acknowledge misses (high confidence that missed)
- Builds credibility through transparency

---

## Empty States

**No games today:**
```
No NBA games today.

Next games: Tomorrow, Dec 12
[View yesterday's results]
```

**Off-season:**
```
The NBA season has ended.

[View historical predictions]
[See 2024-25 season summary]
```

**All Players tab - No game selected:**
```
Select a game to browse players

[LAL @ DEN 7:30] [PHX @ GSW 8:00] [MIA @ BOS 8:30]

Or search for any player by name
```

**Search - No results:**
```
No players found for "xyz"

Try searching by:
• First name (e.g., "LeBron")
• Last name (e.g., "James")
• Full name (e.g., "LeBron James")
```

**Player Profile - No game scheduled:**
```
┌─────────────────────────────────────┐
│ No upcoming games scheduled         │
│                                     │
│ Check back closer to game day for   │
│ predictions and betting analysis.   │
└─────────────────────────────────────┘
```

---

## V1 vs V1.5 Scope

### V1 (Initial Launch)
- ✅ Two-tab homepage: Tonight's Picks + All Players
- ✅ Best Bets featured section
- ✅ Default sort by PPG with sort options
- ✅ Tabbed player detail panel (Tonight / Profile)
- ✅ Player Profile page (standalone for non-playing players)
- ✅ All Players requires game selection first
- ✅ OUT players shown on All Players tab
- ✅ GitHub-style game log grid (no intensity)
- ✅ Colorblind accessible (●/○ icons)
- ✅ In-progress and final game states
- ✅ Search by player name
- ✅ Results page (yesterday + rolling)
- ✅ Mobile-responsive with bottom nav

### V1.5 (Fast Follow)
- Full Players directory (all players, not just tonight's games)
- Additional filters (confidence threshold, line range, position)
- Game-centric view (browse by game, not player)
- Streaks page / hot players feature
- Line movement chart
- GitHub grid intensity shading
- Player comparison tool

### V2 (Future)
- User accounts
- Save favorite players
- Track your own picks
- Alerts/notifications
- Premium features
- Social/leaderboards

---

## Open Items for Wireframing

1. **Tab design in header** - Pills vs underline for Tonight's Picks / All Players
2. **Tab design in panel** - Pills vs underline for Tonight / Profile
3. **Best Bets section** - Horizontal scroll vs grid, card sizing
4. **Card layout refinement** - Spacing, typography, mobile sizing
5. **Detail panel width** - 40% vs 50% of viewport
6. **GitHub grid sizing** - Cell size, gap, rows on mobile
7. **Filter UI pattern** - Dropdowns vs pills vs toggles
8. **Game selector (All Players)** - Cards vs list vs pills
9. **Loading states** - Skeleton card designs
10. **Error states** - API failure messages
11. **Animations** - Panel slide, tab switch, card hover

---

*End of UI Specification v2*
