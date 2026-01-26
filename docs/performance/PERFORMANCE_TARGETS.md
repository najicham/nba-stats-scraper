# Performance Targets and Baselines

This document defines Service Level Objectives (SLOs), Service Level Indicators (SLIs), and performance baselines for the NBA Stats Scraper system.

## Table of Contents

- [Overview](#overview)
- [Performance Targets](#performance-targets)
- [Service Level Objectives (SLOs)](#service-level-objectives-slos)
- [Service Level Indicators (SLIs)](#service-level-indicators-slis)
- [Regression Detection](#regression-detection)
- [Benchmarking](#benchmarking)
- [Monitoring Integration](#monitoring-integration)
- [Performance Optimization Guidelines](#performance-optimization-guidelines)

## Overview

Performance testing ensures the system meets latency, throughput, and resource usage requirements. This document establishes measurable targets and detection thresholds for performance regression.

**Key Principles:**
- Establish baselines through benchmarking
- Detect regressions early in CI/CD
- Monitor production performance continuously
- Optimize based on data, not intuition

## Performance Targets

### Scraper Performance

| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| Single scrape operation | <5s | <10s |
| HTTP request/response | <2s | <5s |
| JSON parsing (100KB) | <500ms | <1s |
| Proxy rotation overhead | <1s | <2s |
| Data validation | <100ms | <500ms |

**Rationale:**
- 5s per scrape allows 720 scrapes/hour
- With 30 games/day × 3 scrapers = 90 scrapes
- Provides 8x headroom for retries and delays

### Processor Performance

| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| Records processed/second | >1000 | >500 |
| 100 games full pipeline | <10 min | <15 min |
| BigQuery write (100 rows) | <5s | <10s |
| BigQuery write (1000 rows) | <30s | <60s |
| Transform time per record | <10ms | <50ms |

**Rationale:**
- 1000 records/sec allows processing full season (1,230 games × 10 players = 12,300 records) in ~12 seconds
- 10 minute target for 100 games ensures daily pipeline completes in <30 minutes

### Query Performance

| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| Simple SELECT query | <1s | <2s |
| Cached query | <500ms | <2s |
| Complex JOIN query | <5s | <10s |
| Analytical query (window functions) | <8s | <15s |
| Query cache hit rate | >80% | >60% |

**Rationale:**
- Cached queries power real-time dashboards
- Complex queries used in analytics pipelines (batch acceptable)
- 80% cache hit rate ensures cost efficiency

### End-to-End Pipeline

| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| Full daily pipeline | <30 min | <60 min |
| Phase 1 (Scrapers) | <10 min | <20 min |
| Phase 2 (Raw Processors) | <10 min | <20 min |
| Phase 3 (Analytics) | <5 min | <15 min |
| Phase 4 (Precompute) | <5 min | <10 min |

**Rationale:**
- 30 minute target ensures completion before game start times
- Phases can run in parallel where dependencies allow
- Critical threshold allows for retry overhead

## Service Level Objectives (SLOs)

### Availability SLOs

| Service | Target | Measurement Window |
|---------|--------|-------------------|
| Scraper success rate | 99.5% | 30 days |
| Processor completion rate | 99.9% | 30 days |
| API response availability | 99.9% | 30 days |
| Dashboard availability | 99.5% | 30 days |

### Latency SLOs

| Service | P50 | P95 | P99 |
|---------|-----|-----|-----|
| Scraper operations | <3s | <5s | <10s |
| Processor runs | <5min | <10min | <15min |
| API requests | <200ms | <500ms | <1s |
| Dashboard loads | <2s | <5s | <10s |

### Throughput SLOs

| Service | Target | Measurement |
|---------|--------|-------------|
| Scrapers (concurrent) | 10 req/s | Per scraper instance |
| Processors (batch) | 100 games/10min | Per processor type |
| BigQuery writes | 1000 rows/min | Per table |
| API requests | 100 req/s | Total system |

## Service Level Indicators (SLIs)

### Scraper SLIs

**SLI 1: Scraper Success Rate**
```
success_rate = successful_scrapes / total_scrape_attempts
Target: >99.5%
```

**SLI 2: Scraper Latency (P95)**
```
p95_latency = 95th percentile of scrape_duration
Target: <5s
```

**SLI 3: Proxy Health**
```
proxy_health = healthy_proxies / total_proxies
Target: >80%
```

### Processor SLIs

**SLI 1: Processor Completion Rate**
```
completion_rate = successful_runs / total_runs
Target: >99.9%
```

**SLI 2: Processing Throughput**
```
throughput = records_processed / processing_time_seconds
Target: >1000 records/sec
```

**SLI 3: BigQuery Write Efficiency**
```
write_efficiency = rows_written / write_time_seconds
Target: >100 rows/sec
```

### Query SLIs

**SLI 1: Query Latency (P95)**
```
p95_query_latency = 95th percentile of query_duration
Target: <5s for complex queries, <1s for simple
```

**SLI 2: Cache Hit Rate**
```
cache_hit_rate = cached_queries / total_queries
Target: >80%
```

**SLI 3: Bytes Processed Efficiency**
```
bytes_per_query = avg(bytes_processed / queries)
Target: <100MB per query
```

### Pipeline SLIs

**SLI 1: Pipeline Completion Time**
```
completion_time = pipeline_end_time - pipeline_start_time
Target: <30 minutes
```

**SLI 2: Phase Success Rate**
```
phase_success_rate = successful_phases / total_phases
Target: >99.5%
```

**SLI 3: Data Freshness**
```
data_freshness = current_time - last_update_time
Target: <1 hour during game day
```

## Regression Detection

### Detection Thresholds

Performance regression is detected when metrics exceed these thresholds:

| Metric Type | Warning | Critical | Action |
|-------------|---------|----------|--------|
| Latency increase | +20% | +50% | Block deployment |
| Throughput decrease | -10% | -25% | Block deployment |
| Memory increase | +25% | +50% | Investigate immediately |
| Error rate increase | +5% | +10% | Rollback |

### Regression Testing Strategy

**Pre-deployment:**
1. Run benchmark suite on feature branch
2. Compare against baseline (main branch)
3. Flag regressions exceeding warning threshold
4. Block merge if critical threshold exceeded

**Post-deployment:**
1. Monitor production metrics for 24 hours
2. Compare against pre-deployment baseline
3. Alert on regressions
4. Automatic rollback on critical regressions

### Benchmark Comparison

```bash
# Save baseline
pytest tests/performance/ --benchmark-save=baseline --benchmark-autosave

# Compare against baseline
pytest tests/performance/ --benchmark-compare=baseline --benchmark-compare-fail=mean:10%

# View historical benchmarks
pytest tests/performance/ --benchmark-histogram
```

## Benchmarking

### Running Benchmarks

**Full benchmark suite:**
```bash
pytest tests/performance/ -v --benchmark-only
```

**Specific test file:**
```bash
pytest tests/performance/test_scraper_benchmarks.py -v --benchmark-only
```

**With detailed statistics:**
```bash
pytest tests/performance/ -v --benchmark-only \
  --benchmark-columns=min,max,mean,stddev,median,iqr,outliers
```

**Save results:**
```bash
pytest tests/performance/ --benchmark-save=my-results --benchmark-autosave
```

**Compare with previous:**
```bash
pytest tests/performance/ --benchmark-compare=0001 --benchmark-compare-fail=mean:20%
```

### Benchmark Output

Example benchmark output:
```
test_scraper_benchmarks.py::TestHTTPRequestBenchmarks::test_benchmark_simple_http_request
  Mean: 0.0023s (2.3ms)
  Min:  0.0020s
  Max:  0.0035s
  StdDev: 0.0003s
  Iterations: 1000

Status: PASS (target: <5s)
```

### Continuous Benchmarking

Benchmarks run automatically in CI/CD:
- On every pull request (compare against main)
- Nightly on main branch (track trends)
- Before production deployment (gate deployment)

## Monitoring Integration

### Application Metrics

**Scrapers:**
- `scraper_duration_seconds` (histogram)
- `scraper_success_total` (counter)
- `scraper_error_total` (counter)
- `proxy_rotation_duration_seconds` (histogram)

**Processors:**
- `processor_duration_seconds` (histogram)
- `processor_records_processed_total` (counter)
- `processor_bigquery_write_duration_seconds` (histogram)
- `processor_memory_usage_bytes` (gauge)

**Queries:**
- `query_duration_seconds` (histogram)
- `query_bytes_processed` (histogram)
- `query_cache_hits_total` (counter)
- `query_cache_misses_total` (counter)

### Cloud Monitoring Dashboards

**Performance Dashboard:**
- Scraper latency (P50, P95, P99)
- Processor throughput
- BigQuery query performance
- Pipeline completion times

**Cost Dashboard:**
- BigQuery bytes processed
- Cloud Functions invocations
- Cloud Run instance hours
- Data transfer costs

### Alerting Rules

**Critical Alerts:**
```yaml
- alert: ScraperLatencyHigh
  expr: histogram_quantile(0.95, scraper_duration_seconds) > 10
  for: 5m
  severity: critical

- alert: ProcessorThroughputLow
  expr: rate(processor_records_processed_total[5m]) < 500
  for: 10m
  severity: critical

- alert: PipelineCompletionSlow
  expr: pipeline_duration_seconds > 3600
  severity: critical
```

**Warning Alerts:**
```yaml
- alert: ScraperLatencyWarning
  expr: histogram_quantile(0.95, scraper_duration_seconds) > 5
  for: 10m
  severity: warning

- alert: QueryCacheHitRateLow
  expr: query_cache_hits_total / (query_cache_hits_total + query_cache_misses_total) < 0.8
  for: 30m
  severity: warning
```

## Performance Optimization Guidelines

### Scraper Optimization

**HTTP Optimization:**
- Use connection pooling
- Enable HTTP/2 where supported
- Implement request batching
- Configure appropriate timeouts

**Parsing Optimization:**
- Stream large JSON responses
- Use orjson for fast JSON parsing
- Lazy load non-critical data
- Cache parsed schemas

**Proxy Optimization:**
- Monitor proxy health proactively
- Balance load across healthy proxies
- Implement sticky sessions for same source
- Remove failed proxies quickly

### Processor Optimization

**Data Loading:**
- Batch GCS reads where possible
- Use streaming for large files
- Implement connection pooling
- Cache frequently accessed data

**Transformation:**
- Use vectorized operations (pandas)
- Process in batches
- Parallelize independent transformations
- Minimize data copies

**BigQuery Writes:**
- Batch writes (100-1000 rows)
- Use load jobs for large batches
- Implement deduplication efficiently
- Partition and cluster tables appropriately

### Query Optimization

**Query Design:**
- Use partition pruning (filter on date)
- Filter on clustered columns
- Limit scanned bytes with WHERE clauses
- Use approximate aggregations where acceptable

**Caching:**
- Enable BigQuery query cache
- Use materialized views for common queries
- Implement application-level caching
- Set appropriate TTLs

**Schema Design:**
- Partition tables by date
- Cluster by frequently filtered columns
- Use appropriate data types
- Denormalize for read performance

### Pipeline Optimization

**Parallelization:**
- Run independent scrapers in parallel
- Process multiple dates concurrently
- Use async I/O where possible
- Implement work stealing

**Resource Management:**
- Right-size Cloud Run instances
- Use autoscaling appropriately
- Implement circuit breakers
- Set resource limits

**Dependency Management:**
- Minimize inter-phase dependencies
- Use Pub/Sub for loose coupling
- Implement smart retry logic
- Fail fast on unrecoverable errors

## Baseline Metrics (Established 2026-01-25)

### Current Baselines

**Scraper Baselines:**
- HTTP request: 1.2s (P95: 2.1s)
- JSON parsing (100KB): 250ms (P95: 450ms)
- Full scrape operation: 3.5s (P95: 4.8s)

**Processor Baselines:**
- Throughput: 1,500 records/sec
- Transform time: 5ms/record
- BigQuery write (100 rows): 2.5s
- BigQuery write (1000 rows): 18s

**Query Baselines:**
- Simple SELECT: 450ms (P95: 850ms)
- Cached query: 180ms (P95: 320ms)
- Complex JOIN: 3.2s (P95: 5.8s)
- Cache hit rate: 85%

**Pipeline Baselines:**
- Full pipeline: 22 minutes
- Phase 1: 8 minutes
- Phase 2: 7 minutes
- Phase 3: 4 minutes
- Phase 4: 3 minutes

### Tracking Changes

Baselines are reviewed and updated:
- Monthly during normal operations
- After major performance optimizations
- After infrastructure changes
- When targets are consistently exceeded

---

**Document Version:** 1.0
**Last Updated:** 2026-01-25
**Next Review:** 2026-02-25
