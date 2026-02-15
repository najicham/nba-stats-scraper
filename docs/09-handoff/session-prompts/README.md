# Session Prompts

Ready-to-use prompts for starting new Claude Code sessions.

## Active Prompts

**COMPREHENSIVE-TESTING-SESSION-PROMPT.md** — Most comprehensive testing plan
- Run exhaustive validation across all dimensions (temporal, home/away, position, rest, etc.)
- 8-12 hours of testing (Tier 1-3)
- Goal: Achieve HIGH confidence (>80%) on all signal decisions
- **Use this for thorough validation before production deployment**

**NEW-SESSION-SIGNAL-ANALYSIS-PROMPT.md** — Original Session 256 prompt
- 4 parallel agents for intersection, segmentation, interaction matrix, zero-pick prototypes
- ~2-3 hours (already completed in Session 256)
- Historical reference

## Archived Files (Session 255)

- NEW-CHAT-PROMPT.md
- NEXT-SESSION-START-HERE.md
- QUICK-HANDOFF.md
- SESSION-255-FINAL-STATUS.txt
- WELCOME-BACK.txt

These were interim handoff files from Session 255-256 transition.

---

## Recommended Usage

### For Production Deployment

1. Start fresh session
2. Use **COMPREHENSIVE-TESTING-SESSION-PROMPT.md**
3. Run all Tier 1 tests (2-3 hours)
4. If Tier 1 passes, run Tier 2-3 (6-9 hours)
5. Document results
6. Deploy with HIGH confidence

### For Quick Iteration

1. Read Session 256 final handoff: `docs/09-handoff/2026-02-14-SESSION-256-FINAL-HANDOFF.md`
2. Pick specific test from Tier 1
3. Run targeted validation
4. Iterate on findings

---

**Created:** 2026-02-14 (Session 256)
