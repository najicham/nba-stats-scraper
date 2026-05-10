# Demo Script — Pre-Presentation Walkthrough

To be filled in toward the end of Phase L. Will cover:

1. Architecture story (start with old vs new, walk through halt_state + expected_outputs).
2. Live demo path:
   - Show `nba-pipeline-health` Cloud Monitoring dashboard with NBA halt visible + MLB healthy.
   - Show the halt envelope in `gs://nba-props-platform-api/v1/best-bets/all.json` (halt_active=true with reason, freshly written today).
   - Show the frontend rendering an explicit halt banner instead of stuck-loading skeleton.
   - Show `expected_outputs` with green-status rows for the 109-day backfill window.
   - Trigger a synthetic gap (delete one expected_outputs row's actual data) → watch gap_detector fire → watch backfill complete in <5 min.
   - Show alert routing into Slack.
3. Failure mode walkthrough — for each historical incident (Apr 2026 /mlb, May 2026 best-bets stuck, Dec 2025-Jan 2026 26-day gap, Oct 2025-Feb 2026 109-day gap), what would the new system catch and how fast.
4. Off-season → season transition: how does the system come back automatically on Oct 22, 2026?
5. Rollback plan: every phase is independently rolled back via feature flag or Cloud Function disable.
6. On-call cheatsheet: 3 alert types, what to do for each, runbook links.

---

## Open items to populate before demo

- [ ] Final dashboard URL.
- [ ] Slack alert channel + sample payloads.
- [ ] `nba-pipeline-health` screenshot.
- [ ] Backfill final summary (X/Y dates recovered, Z lost).
- [ ] Failover demo recording (in case live demo fails).
