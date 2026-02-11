# Session 203: Execute Feature 4 Fix Deployment

**Copy-paste this into your next Claude session:**

---

Hi! I need you to execute the deployment plan from Session 202.

**Context:** Session 202 found and fixed a bug where Feature 4 (games_in_last_7_days) was defaulting for 49.6% of players. The code fix is complete but not yet committed/deployed.

**Your task:**
1. Read the handoff: `docs/09-handoff/2026-02-11-SESSION-202-HANDOFF.md`
2. Execute the deployment checklist (Steps 1-5)
3. Verify success criteria
4. Report results

**Time estimate:** ~30 minutes

**Priority:** P1 HIGH - Deploy today

Start by reading the handoff document and confirming you understand the plan before executing.

---

**Quick Summary for you:**
- Fix is in working directory (uncommitted)
- Need to: commit → push → verify deploy → regenerate Feb 6-10 → verify
- Low risk, high impact fix
- Auto-deploy should handle the deployment after push

