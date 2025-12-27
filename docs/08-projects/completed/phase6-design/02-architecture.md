# Phase 6 Architecture

**Created:** 2025-12-02
**Status:** Draft

---

## Architecture Options

### Option A: Firestore + Static Site (Recommended)

```
┌─────────────────────────────────────────────────────────────────┐
│                        GCP Project                               │
│                                                                   │
│  BigQuery                 Firestore              Firebase Hosting │
│  ┌─────────────┐   pub    ┌─────────────┐   read   ┌───────────┐ │
│  │ player_prop │ ──────→  │ predictions │ ───────→ │ React App │ │
│  │ predictions │          │ (by date)   │          │ (static)  │ │
│  └─────────────┘          └─────────────┘          └───────────┘ │
│         ↑                       ↑                        ↑       │
│         │                       │                        │       │
│  Cloud Function          Cloud Function            Users/API     │
│  (publisher)             (on-write trigger)                      │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Pros:**
- Low cost (Firestore free tier + static hosting)
- Real-time updates built into Firestore
- Simple deployment
- Works well for hobby project scale

**Cons:**
- Firestore query limitations
- Need to denormalize data

---

### Option B: Cloud Run API + Database

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                   │
│  BigQuery          Cloud Run API           Web UI                 │
│  ┌───────────┐     ┌───────────────┐     ┌───────────┐           │
│  │predictions│ ←── │ /api/predict  │ ←── │ React App │           │
│  └───────────┘     │ /api/history  │     └───────────┘           │
│                    │ /api/accuracy │                              │
│                    └───────────────┘                              │
│                           ↑                                       │
│                      Cloud SQL                                    │
│                    (cache/history)                                │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Pros:**
- Full SQL query capability
- Standard REST API
- Easy to add features

**Cons:**
- Higher cost (Cloud SQL + Cloud Run always-on)
- More infrastructure to manage
- Overkill for current scale

---

### Option C: Direct BigQuery (Simplest)

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                   │
│  BigQuery                              Web UI                     │
│  ┌───────────────┐    direct query    ┌───────────────┐          │
│  │ predictions   │ ←───────────────── │ React App     │          │
│  │ (authorized)  │                    │ + BQ Client   │          │
│  └───────────────┘                    └───────────────┘          │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

**Pros:**
- Simplest architecture
- No additional services
- Data always fresh

**Cons:**
- BigQuery costs per query (could add up)
- Cold start latency
- Limited real-time capability
- Need to handle auth carefully

---

## Recommendation: Option A (Firestore + Static)

**Why:**

1. **Cost effective** - Free tier covers hobby use
2. **Real-time built-in** - Firestore listeners update UI automatically
3. **Simple** - Two services (publisher + static site)
4. **Scales down** - No always-on costs when not in use
5. **GCP native** - Integrates with existing infrastructure

---

## Detailed Architecture (Option A)

### Components

#### 1. Publisher (Cloud Function)

```python
# Triggered by Phase 5 completion or schedule
def publish_predictions(event):
    # 1. Query BigQuery for today's predictions
    predictions = query_predictions(today)

    # 2. Transform to Firestore format
    docs = transform_to_firestore(predictions)

    # 3. Write to Firestore
    batch_write(docs)

    # 4. Update metadata
    update_last_published()
```

**Triggers:**
- Pub/Sub `nba-phase5-predictions-complete`
- Cloud Scheduler (backup, every 30 min during game hours)

#### 2. Firestore Schema

```
/predictions
  /{game_date}              # e.g., "2024-01-15"
    /players
      /{player_lookup}      # e.g., "stephen_curry"
        - game_id
        - game_time
        - team_abbr
        - opponent_abbr
        - predictions: {
            ensemble: {
              predicted_points: 29.0,
              confidence: 72.5,
              recommendation: "OVER"
            },
            moving_average: {...},
            zone_matchup: {...},
            ...
          }
        - current_line: 25.5
        - line_margin: 3.5
        - updated_at

/metadata
  /status
    - last_published: timestamp
    - prediction_date: "2024-01-15"
    - player_count: 45
    - games_count: 5
```

#### 3. Static Web App

**Tech Stack:**
- React or Vue.js
- Firebase SDK for Firestore
- Tailwind CSS for styling
- Firebase Hosting

**Key Pages:**
- `/` - Today's predictions
- `/game/{game_id}` - Single game view
- `/player/{player}` - Player history
- `/accuracy` - Model performance

---

## Data Flow

```
1. Phase 5 completes
   ↓
2. Pub/Sub message → Cloud Function
   ↓
3. Cloud Function queries BigQuery
   ↓
4. Cloud Function writes to Firestore
   ↓
5. Firestore updates trigger UI refresh
   ↓
6. User sees new predictions (< 30 seconds)
```

---

## Cost Estimate (Monthly)

| Component | Usage | Cost |
|-----------|-------|------|
| Cloud Function | ~100 invocations/day | Free tier |
| Firestore | ~5K reads/day, 500 writes | Free tier |
| Firebase Hosting | Static site | Free tier |
| BigQuery (queries) | ~5 queries/day | ~$0.02 |
| **Total** | | **~$1/month** |

---

## Security

### Firestore Rules

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Public read for predictions
    match /predictions/{date}/players/{player} {
      allow read: if true;
      allow write: if false; // Only Cloud Function writes
    }

    // Public read for metadata
    match /metadata/{doc} {
      allow read: if true;
      allow write: if false;
    }
  }
}
```

### API Access (Future)

- Read-only API keys for developers
- Rate limiting via Firebase App Check
- No sensitive data exposed

---

## Open Decisions

1. **Domain:** Use Firebase subdomain or custom domain?
2. **Caching:** How long to cache predictions?
3. **Historical:** Store how many days in Firestore?
4. **Accuracy:** Calculate in real-time or batch?
