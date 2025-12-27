# Phase 6 Requirements

**Created:** 2025-12-02
**Status:** Draft

---

## User Stories

### Primary User: Sports Bettor

**As a bettor, I want to:**

1. See today's player points predictions before games start
2. Understand why the model recommends OVER or UNDER
3. Know the confidence level of each prediction
4. See the current Vegas line alongside the prediction
5. Get updated predictions when lines change

**Acceptance Criteria:**
- Predictions available by 10 AM PT on game days
- Show predicted points, line, margin, confidence
- Refresh when prop lines update
- Mobile-friendly interface

---

### Secondary User: Analyst

**As an analyst, I want to:**

1. Compare predictions across different models
2. Track historical accuracy by player and model
3. Understand feature importance (why this prediction?)
4. Export data for custom analysis

**Acceptance Criteria:**
- Show all 5 model predictions per player
- Historical accuracy stats (% correct, avg error)
- Model explanations where available
- JSON/CSV export option

---

### Tertiary User: Developer

**As a developer, I want to:**

1. Access predictions via API
2. Get real-time updates via webhooks/SSE
3. Query historical predictions
4. Integrate with my own systems

**Acceptance Criteria:**
- REST API with JSON responses
- Authentication via API keys
- Rate limiting (reasonable for hobby use)
- Documentation

---

## Functional Requirements

### F1: Daily Predictions Display

| Requirement | Priority | Notes |
|-------------|----------|-------|
| Show all players with predictions | Must Have | |
| Filter by game/team | Must Have | |
| Sort by confidence/margin | Should Have | |
| Show game time context | Must Have | |

### F2: Prediction Details

| Requirement | Priority | Notes |
|-------------|----------|-------|
| Predicted points | Must Have | |
| Vegas line | Must Have | |
| Margin (pred - line) | Must Have | |
| Confidence score | Must Have | |
| Recommendation (OVER/UNDER/PASS) | Must Have | |
| Individual model predictions | Should Have | |

### F3: Historical Accuracy

| Requirement | Priority | Notes |
|-------------|----------|-------|
| Track actual vs predicted | Should Have | Requires game results |
| Show model accuracy % | Should Have | |
| Show by player | Could Have | |
| Show by model | Should Have | |

### F4: Real-Time Updates

| Requirement | Priority | Notes |
|-------------|----------|-------|
| Update when lines change | Should Have | |
| Show "updated X min ago" | Must Have | |
| Push notifications | Could Have | Future |

---

## Non-Functional Requirements

### Performance

| Metric | Target |
|--------|--------|
| Page load time | < 2 seconds |
| API response time | < 500ms |
| Update latency | < 5 minutes |

### Availability

| Metric | Target |
|--------|--------|
| Uptime | 99% (hobby project) |
| Scheduled downtime | Announced 24h ahead |

### Scalability

| Metric | Target |
|--------|--------|
| Concurrent users | 100 |
| API requests/day | 10,000 |
| Data retention | 1 season |

### Security

| Requirement | Notes |
|-------------|-------|
| HTTPS only | Required |
| No PII stored | Predictions only |
| API authentication | For write operations |

---

## Out of Scope (v1)

- User accounts / personalization
- Betting platform integration
- Real-money transactions
- Mobile app (native)
- Push notifications
- Multi-sport support

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Predictions delivered on time | 95% of game days |
| Model accuracy (OVER/UNDER) | > 52% (better than coin flip) |
| Page load performance | < 2 seconds |
| API uptime | > 99% |

---

## Open Questions

1. **Authentication:** Do we need user accounts, or is it public?
2. **Historical data:** How far back do we show accuracy?
3. **Model explanations:** How much detail to expose?
4. **Update frequency:** How often do we refresh predictions?
5. **Monetization:** Is this a hobby or business?
