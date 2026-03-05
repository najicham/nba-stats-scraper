# Session 411 Handoff — Signal Experiments + Decay Monitoring

**Date:** 2026-03-05
**Type:** Signal infrastructure, monitoring, new shadow signals
**Key Insight:** Toxic window (Jan 30 - Feb 25) explains most "dead" signals — they're recovering post-ASB

---

## What This Session Did

### 1. Re-enabled `volatile_scoring_over`

**77.8% HR (7-2) post-toxic window.** Was disabled Session 391 at 50% (4-4) during toxic window. The signal was never broken — it was a casualty of trade deadline + ASB chaos.

- `ml/signals/registry.py` — re-registered
- `ml/signals/signal_health.py` — added back to ACTIVE_SIGNALS

### 2. Created Signal Decay Monitor (`bin/monitoring/signal_decay_monitor.py`)

Complements model decay detection (Session 389 CF) but for **signals**. Prevents the volatile_scoring_over situation from recurring — signals get disabled during toxic windows and nobody notices when they recover.

```bash
PYTHONPATH=. python bin/monitoring/signal_decay_monitor.py --dry-run
PYTHONPATH=. python bin/monitoring/signal_decay_monitor.py --date 2026-03-05
```

**Classification states:**
- HEALTHY: HR >= 50% (14d, N >= 10)
- WATCH: HR < 50% (14d)
- DEGRADING: HR < 45% (14d) — Slack alert + "consider disabling"
- RECOVERED: Disabled signal with HR >= 60% (14d) — Slack alert + "consider re-enabling"

Queries `signal_health_daily` table (already exists and populated daily).

### 3. Created 5 New Shadow Signals from Feature Store

All use raw feature values from `ml_feature_store_v2` via the `book_stats` CTE. 4 OVER + 1 UNDER (fills UNDER gap — only 6th UNDER signal).

| Signal | Direction | Feature | Threshold | Rationale |
|--------|-----------|---------|-----------|-----------|
| `usage_surge_over` | OVER | f48 usage_rate_l5 | >= 25% | Top quartile usage, more touches |
| `scoring_momentum_over` | OVER | f44 slope + f43 avg3 + f1 avg10 | slope > 1.0 + avg3 > avg10 | Upward trend confirmation |
| `career_matchup_over` | OVER | f29 avg_vs_opp + f30 games_vs_opp | avg > line + games >= 3 | Historical dominance |
| `minutes_load_over` | OVER | f40 minutes_load_7d | >= 100 min | Heavy engagement |
| `blowout_risk_under` | UNDER | f57 blowout_risk | >= 0.40 + line >= 15 | Gets benched in blowouts |

**Files created:**
- `ml/signals/usage_surge_over.py`
- `ml/signals/scoring_momentum_over.py`
- `ml/signals/career_matchup_over.py`
- `ml/signals/minutes_load_over.py`
- `ml/signals/blowout_risk_under.py`

**Files modified:**
- `ml/signals/supplemental_data.py` — added 7 features to book_stats CTE + SELECT + pred dict
- `ml/signals/registry.py` — registered all 5 as shadow + re-enabled volatile_scoring_over
- `ml/signals/signal_health.py` — added all to ACTIVE_SIGNALS
- `ml/experiments/signal_backtest.py` — added feature columns to BQ query + pred dict

### 4. Updated Documentation

- `CLAUDE.md` — signal counts 27 active + 20 shadow, added signal_decay_monitor.py to monitoring
- `SIGNAL-INVENTORY.md` — full Session 411 section with all 5 new shadow signals
- `MEMORY.md` — toxic window insight, new tool, signal counts

---

## Key Discovery: Toxic Window Explains Signal Disability

Analysis of signals across 3 periods (pre-toxic Dec-Jan 29, toxic Jan 30-Feb 25, post-toxic Feb 26+):

| Signal | Pre-Toxic | Toxic | Post-Toxic | Pattern |
|--------|-----------|-------|------------|---------|
| `combo_3way` | 85.7% | 53.3% | 50% | Collapsed during toxic |
| `bench_under` | 85.7% | 51.2% | 57.1% | Collapsed, recovering |
| `3pt_bounce` | 66.7% | 46.2% | 66.7% | Dipped, recovered |
| `volatile_scoring_over` | 81.5% | 50.0% | 77.8% | Dipped, recovered |

**Implication:** Don't manually disable signals during toxic windows — use the signal decay monitor to automate detection and re-enablement.

---

## Current Signal Counts

- **Active production signals:** 27 (was 26)
- **Shadow signals:** 20 (was 15)
- **Negative filters:** 17 (unchanged)
- **Total registered:** 47

---

## What's Next

### Immediate (post-push)
1. Signal backtest validates fire rates on historical data for all new signals
2. Push auto-deploys — new signals start firing in shadow mode

### 7-14 days (~Mar 12-19)
1. Run `signal_decay_monitor.py` to assess all signal states
2. Check `signal_health_daily` for new signal fire rates and HR
3. Promote any shadow signal with HR >= 60% + N >= 30

### ~30 days (~Apr 5)
1. `projection_delta` signal — once NumberFire has 30 days of data, evaluate projection vs line delta
2. `sharp_money` signals — once VSiN has 30 days of data, evaluate sharp money divergence
3. Consider tightening `blowout_risk_under` threshold from 0.40 to 0.50 if fire rate too high

---

## Files Changed

| File | Action |
|------|--------|
| `ml/signals/registry.py` | Re-enabled volatile_scoring_over, registered 5 new shadow signals |
| `ml/signals/supplemental_data.py` | Added 7 feature columns to book_stats CTE + SELECT + pred dict |
| `ml/signals/signal_health.py` | Added 9 signals to ACTIVE_SIGNALS (volatile + 3 session 410 + 5 new) |
| `ml/signals/usage_surge_over.py` | NEW |
| `ml/signals/scoring_momentum_over.py` | NEW |
| `ml/signals/career_matchup_over.py` | NEW |
| `ml/signals/minutes_load_over.py` | NEW |
| `ml/signals/blowout_risk_under.py` | NEW |
| `bin/monitoring/signal_decay_monitor.py` | NEW |
| `ml/experiments/signal_backtest.py` | Added Session 410+411 feature columns to BQ query + pred dict |
| `CLAUDE.md` | Signal counts, monitoring section |
| `docs/.../SIGNAL-INVENTORY.md` | Session 411 section, counts, volatile_scoring_over status |
