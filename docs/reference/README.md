# Reference Documentation

**Created:** 2025-11-21 18:20:00 PST
**Last Updated:** 2025-11-21 18:20:00 PST

Quick reference documentation for NBA platform components. These docs provide scannable, concise information for developers who need to understand system components quickly.

---

## Available References

### 1. [Scrapers Reference](01-scrapers-reference.md)
**25 scrapers across 7 data sources**

Quick reference for all NBA data scrapers organized by API source (Odds API, NBA.com, ESPN, BallDontLie, Basketball Reference, BigDataBall, BettingPros). Includes endpoint details, update frequency, and output formats.

**Use this when:** You need to understand what data we scrape and from where.

---

### 2. [Processors Reference](02-processors-reference.md)
**25 Phase 2 processors (GCS → BigQuery)**

Reference for all raw data processors that transform scraped data into BigQuery tables. Documents processing strategies (APPEND_ALWAYS, MERGE_UPDATE, INSERT_NEW_ONLY) and smart idempotency implementation.

**Use this when:** You need to understand how raw data gets processed into BigQuery.

---

### 3. [Analytics Processors Reference](03-analytics-processors-reference.md)
**5 Phase 3 analytics processors**

Reference for analytics processors that aggregate raw data into game summaries. Documents dependency tracking (v4.0 pattern with data_hash), smart reprocessing, and batch insert patterns.

**Use this when:** You need to understand Phase 3 analytics aggregations.

---

### 4. [Player Registry Reference](04-player-registry-reference.md)
**Universal player ID system**

Reference for the NBA Player Registry that provides universal player identification across all data sources. Documents fuzzy matching, cache strategies, and error handling.

**Use this when:** You need to implement player ID lookups in any processor.

---

### 5. [Notification System Reference](05-notification-system-reference.md)
**Multi-channel alerting (Email + Slack)**

Reference for the notification system that sends alerts via Email (Brevo) and Slack webhooks. Documents severity levels, routing rules, and extensibility patterns.

**Use this when:** You need to add alerting to a processor or service.

---

### 6. [Shared Utilities Reference](06-shared-utilities-reference.md)
**Common utilities across all phases**

Reference for shared utility services including NBA team mapper (fuzzy matching), travel/timezone calculations, and common helper functions.

**Use this when:** You need team mapping, travel distance, or timezone conversions.

---

## How to Use These References

**For quick lookups:**
- Scan the table of contents in each reference
- Jump to the specific section you need
- Copy-paste code examples directly

**For comprehensive understanding:**
- Start with the relevant reference doc
- Follow links to processor cards for detailed implementations
- Refer to guides for step-by-step implementation

---

## Related Documentation

### Detailed Implementation
- **[Processor Cards](../processor-cards/README.md)** - 1-2 page quick references for each processor
- **[Guides](../guides/00-overview.md)** - Step-by-step implementation guides
- **[Processor Patterns](../guides/processor-patterns/)** - Reusable implementation patterns

### Architecture & Design
- **[Architecture](../architecture/)** - System architecture documentation
- **[Data Flow](../data-flow/)** - How data flows through the system
- **[Predictions](../predictions/)** - ML prediction system documentation

### Operations
- **[Operations](../operations/)** - Deployment and maintenance guides
- **[Monitoring](../monitoring/)** - System monitoring and alerting
- **[Troubleshooting](../TROUBLESHOOTING.md)** - Common issues and fixes

---

## Documentation Standards

All reference docs follow these conventions:

**Format:**
- Scannable tables and lists
- Working code examples (not pseudocode)
- Copy-pasteable commands
- Real data examples

**Metadata:**
- Created timestamp (PST)
- Last updated timestamp (PST)
- Verified against actual code

**Content:**
- Document what IS (not what's planned)
- Honest about status and limitations
- Include all edge cases and error handling
- Show actual implementation patterns

---

## Contributing

When creating new reference documentation:

1. **Follow the template** - Use existing references as examples
2. **Verify against code** - All examples must match actual implementation
3. **Keep it concise** - Reference docs should be scannable (not comprehensive)
4. **Use real examples** - No placeholder code or hypothetical scenarios
5. **Update timestamps** - Mark when created and last updated

See [Processor Documentation Guide](../guides/05-processor-documentation-guide.md) for detailed standards.

---

**Last Verified:** 2025-11-21
**Maintained By:** NBA Platform Team
