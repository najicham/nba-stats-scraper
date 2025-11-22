# Dependency Checking Documentation

**Created**: 2025-11-21 12:53:37 PST
**Last Updated**: 2025-11-21 13:25:00 PST

---

## 📚 Documentation Structure

This directory contains comprehensive dependency checking documentation for all phases of the NBA Props Platform data pipeline.

### Documents

- **[`00-overview.md`](./00-overview.md)** - System architecture and standardized patterns (MASTER DOCUMENT)
- **[`01-raw-processors.md`](./01-raw-processors.md)** - Phase 2: 22 raw data processors dependency checks
- **[`02-analytics-processors.md`](./02-analytics-processors.md)** - Phase 3: 5 analytics processors dependency checks
- **[`03-precompute-processors.md`](./03-precompute-processors.md)** - Phase 4: 5 precompute processors dependency checks
- **[`04-predictions-coordinator.md`](./04-predictions-coordinator.md)** - Phase 5: Prediction systems dependency checks
- **[`05-publishing-api.md`](./05-publishing-api.md)** - Phase 6: Publishing/API layer (future)

---

## 🎯 Quick Start

1. **Start with**: [`00-overview.md`](./00-overview.md) - Master reference document explaining dependency checking principles
2. **Then dive into**: Phase-specific documents for detailed processor specs
3. **Use as reference**: Copy examples when adding new processors

---

## 📖 How to Use This Documentation

### For Understanding the System
- **New to dependency checking?** Start with `00-overview.md` Section: "What is Dependency Checking?"
- **Want to see examples?** `01-raw-processors.md` has 3 fully detailed processor examples
- **Need to understand cascade effects?** See `00-overview.md` Section: "Cross-Phase Dependencies"

### For Implementation
- **Adding a new processor?**
  1. Find the relevant phase document (01-05)
  2. Copy the processor template
  3. Fill in all sections with actual code/data
- **Debugging dependency issues?**
  1. Check `00-overview.md` Section: "Monitoring & Alerting"
  2. Use sample monitoring queries
  3. Refer to phase-specific failure scenarios

### For Operations
- **Daily monitoring**: Use health check queries in each phase doc
- **Troubleshooting**: Each doc has "Failure Scenarios & Logging" sections
- **Alerting thresholds**: See `00-overview.md` Section: "Alerting Thresholds"

---

## 📊 Completion Status

| Document | Status | Completion | Notes |
|----------|--------|------------|-------|
| 00-overview.md | ✅ Complete | 100% | Master reference |
| 01-raw-processors.md | ✅ Detailed Examples | 14% (3/22) | 3 full examples as reference |
| 02-analytics-processors.md | 🚧 Template | 20% | Structure ready, needs details |
| 03-precompute-processors.md | ✅ Documented | 60% | Core concepts + ML feature store |
| 04-predictions-coordinator.md | 🚧 Template | 25% | Planning template |
| 05-publishing-api.md | 🎯 Future | 5% | Placeholder for future phase |

**Overall Pipeline Coverage**: ~45% detailed, 100% structured

---

## 🏗️ Pipeline Phase Overview

Quick reference for which phase does what:

| Phase | Name | Processors | Main Function | Output Dataset |
|-------|------|------------|---------------|----------------|
| **Phase 1** | Scrapers | 26+ scrapers | Scrape raw data from APIs | GCS files |
| **Phase 2** | Raw Processors | 22 processors | Transform JSON → BigQuery | `nba_raw.*` |
| **Phase 3** | Analytics | 5 processors | Aggregate into ML features | `nba_analytics.*` |
| **Phase 4** | Precompute | 5 processors | Cache features for speed | `nba_precompute.*` + `nba_predictions.ml_feature_store_v2` |
| **Phase 5** | Predictions | 6 systems | Generate ML predictions | `nba_predictions.*` |
| **Phase 6** | Publishing | Future | Publish to API/Firestore | User-facing |

---

## 🔧 How to Extend

### Adding a New Processor

1. **Find the relevant phase document** (01-05 based on phase number)
2. **Copy the processor template** from existing examples in that doc
3. **Fill in all required sections**:
   - Primary dependencies
   - Expected data volume
   - Dependency check logic (code)
   - Partial data handling
   - Failure scenarios with logging
   - Database fields
   - Historical requirements
4. **Update completion status** in this README
5. **Test your dependency checks** before deploying

### Updating Existing Content

1. Update the "Last Updated" timestamp at top of file
2. Make your changes
3. Update the version number if significant changes
4. Document what changed in git commit message
5. Update completion percentage in this README if applicable

---

## 🎓 Dependency Checking Principles (Quick Reference)

From the master document (`00-overview.md`):

### The Four Pillars

1. **Fail Gracefully, Not Silently** - Always log and notify
2. **Track Completeness, Not Just Existence** - Know *how much* data, not just *if* it exists
3. **Store Dependency Metadata** - Track source quality for confidence scoring
4. **Use Standardized Thresholds** - Consistent quality tiers across phases

### Standard Thresholds

| Threshold Type | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
|----------------|---------|---------|---------|---------|
| **Critical** (abort) | < 30% | < 50% | < 60% | < 70% |
| **Warning** (continue with flag) | 30-70% | 50-80% | 60-85% | 70-90% |
| **Healthy** | > 70% | > 80% | > 85% | > 90% |

*Thresholds increase by phase because user-facing predictions require highest quality.*

---

## 📞 Questions & Support

### Common Questions

**Q: Which document should I read first?**
A: [`00-overview.md`](./00-overview.md) - It's the master reference with all core concepts.

**Q: I want to see a complete example of dependency checking.**
A: See [`01-raw-processors.md`](./01-raw-processors.md) - Processors 1-3 have full implementations.

**Q: How do I check if my processor's dependencies are healthy?**
A: Each phase doc has a "Health Check Query" section. Copy and modify for your processor.

**Q: What's the difference between Phase 3 and Phase 4?**
A: Phase 3 aggregates raw data into analytics features. Phase 4 pre-computes and caches those features for fast ML lookups.

**Q: Why does ML Feature Store write to `nba_predictions` instead of `nba_precompute`?**
A: See [`03-precompute-processors.md`](./03-precompute-processors.md) Section: "Cross-Dataset Dependencies"

### Getting Help

- **General patterns**: See [`00-overview.md`](./00-overview.md) Section: "Standardized Patterns"
- **Phase-specific help**: See individual phase documents (01-05)
- **Code examples**: Each phase doc includes Python code snippets
- **Monitoring**: See [`00-overview.md`](./00-overview.md) Section: "Monitoring & Alerting"

---

## 🔗 Related Documentation

### Architecture & Design
- [`docs/architecture/00-quick-reference.md`](../architecture/00-quick-reference.md) - Pipeline overview
- [`docs/architecture/04-event-driven-pipeline-architecture.md`](../architecture/04-event-driven-pipeline-architecture.md) - Pub/Sub architecture
- [`docs/data-flow/`](../data-flow/) - Detailed data transformations by phase

### Processor-Specific
- [`docs/processor-cards/`](../processor-cards/) - Quick reference cards for each processor
- [`docs/processors/`](../processors/) - Operations guides by phase

### Implementation
- [`docs/implementation/`](../implementation/) - Smart idempotency and other patterns

---

## 📅 Maintenance

### Ownership

- **Master Document (00-overview.md)**: Data Engineering Team
- **Phase 2 (01-raw-processors.md)**: Raw Processing Team
- **Phase 3 (02-analytics-processors.md)**: Analytics Team
- **Phase 4 (03-precompute-processors.md)**: ML Engineering Team
- **Phase 5 (04-predictions-coordinator.md)**: Predictions Team
- **Phase 6 (05-publishing-api.md)**: Platform Team (future)

### Update Triggers

Update this documentation when:
- ✅ New processor added to any phase
- ✅ New dependency added/removed from existing processor
- ✅ Threshold values changed
- ✅ Fallback logic changed
- ✅ Monitoring query updated
- ✅ Major bug discovered in dependency checking logic

### Review Cadence

- **Weekly**: Review critical dependency failures from monitoring
- **Monthly**: Review completeness trends and threshold effectiveness
- **Quarterly**: Full documentation audit and updates
- **Next Review**: 2025-12-21

---

## 📈 Documentation Roadmap

### Completed ✅
- Master overview document with all core patterns
- Phase 2 detailed examples (3 processors)
- Phase 4 core structure and ML feature store docs
- Cross-phase dependency documentation
- Monitoring and alerting guidelines

### In Progress 🚧
- Phase 2: Complete remaining 19 processors (currently 3/22)
- Phase 3: Add detailed specs for all 5 processors
- Phase 4: Expand remaining 4 processor details
- Phase 5: Document all 6 prediction systems

### Future 🎯
- Phase 6: Create structure when publishing layer designed
- Add Mermaid diagrams for dependency graphs
- Create troubleshooting decision trees
- Add performance benchmarks per processor

---

**Maintained By**: Data Engineering Team
**Last Full Review**: 2025-11-21
**Next Scheduled Review**: 2025-12-21
**Version**: 2.0 (major restructuring)
