# Infrastructure Documentation

**Last Updated:** 2025-11-15
**Purpose:** Cross-phase infrastructure documentation (Pub/Sub, shared services)
**Audience:** Engineers working with the event-driven integration layer

---

## 📖 Reading Order (Start Here!)

**New to the infrastructure? Read these in order:**

### 1. **01-pubsub-integration-verification.md** ⭐ START HERE
   - **Created:** 2025-11-14 17:44 PST
   - **Pub/Sub integration testing and verification**
   - **Why read this:** Learn how to verify Phase 1→2 Pub/Sub integration is working
   - **Status:** Phase 2 integration deployed and operational

### 2. **02-pubsub-schema-management.md**
   - **Created:** 2025-11-14 17:21 PST
   - **Pub/Sub message schema management and error prevention**
   - **Why read this:** Understand message schemas and prevent schema mismatch errors
   - **Status:** Current

---

## 🗂️ What Goes in This Directory

**Infrastructure** = Cross-phase shared systems used by 2+ phases

**Belongs here:**
- ✅ Pub/Sub topics and subscriptions
- ✅ Message schemas and formats
- ✅ Integration verification guides
- ✅ Shared authentication and service accounts
- ✅ Cloud Run service configuration (when cross-phase)

**Does NOT belong here:**
- ❌ Phase-specific operations (goes in `processors/`, `orchestration/`, etc.)
- ❌ Monitoring dashboards (goes in `monitoring/`)
- ❌ Business logic (goes in phase-specific directories)

**Rule of thumb:** If it connects multiple phases or is shared plumbing, it goes here.

---

## 📋 Current Topics

### Pub/Sub Integration
- Phase 1→2 integration (scrapers publish, processors subscribe)
- Message normalization (handling both scraper and GCS formats)
- Schema validation and error prevention
- Future: Phase 2→3, 3→4, 4→5 integrations

### Deployment & Configuration
- Cloud Run service accounts
- Pub/Sub topic/subscription setup
- IAM permissions across services

---

## 🔗 Related Documentation

**Phase-Specific Operations:**
- **Phase 1 Orchestration:** `docs/orchestration/` - Scheduler and workflows
- **Phase 2 Processors:** `docs/processors/` - Processor operations

**Cross-Phase Concerns:**
- **Monitoring:** `docs/monitoring/` - Grafana dashboards and health checks
- **Data Flow:** `docs/data-flow/` - How data transforms between phases
- **Architecture:** `docs/01-architecture/` - Overall system design

---

## 📝 Adding New Documentation

**To add infrastructure documentation:**

1. **Check if it's infrastructure** - Does it connect multiple phases?
2. **Find next number:** `ls *.md | tail -1` → Currently at 02, next is 03
3. **Create file:** `03-new-infrastructure-doc.md`
4. **Use standard metadata header**
5. **Update this README** with the new document

**See:** `docs/DOCUMENTATION_GUIDE.md` for file organization standards

---

## 🗄️ Archive Policy

**Move to `archive/` when:**
- Integration guides superseded by new approach
- Old Pub/Sub configurations no longer used
- Historical reference only (no longer operational)

**Archive structure:**
```
archive/
├── YYYY-MM-DD/     (session artifacts)
└── old/            (superseded configs)
```

---

**Directory Status:** Active
**File Organization:** Chronological numbering (01-99)
**Next Available Number:** 03
