# Performance and Load Testing Suite

This directory contains performance benchmarks and load tests for the NBA Stats Scraper system.

## Overview

Performance tests measure:
- **Scraper performance**: HTTP request/response, parsing, proxy rotation
- **Processor throughput**: Records processed per second, BigQuery write performance
- **Query performance**: BigQuery query latency, cache hit rates
- **End-to-end pipeline**: Phase transition times, full pipeline completion

## Test Files

### `test_scraper_benchmarks.py`
Benchmarks for scraper operations:
- HTTP request/response timing
- JSON parsing performance
- Proxy rotation overhead
- Data validation speed
- Memory footprint

**Target:** <5s per scrape operation

### `test_processor_throughput.py`
Benchmarks for data processor operations:
- Records processed per second
- BigQuery write performance
- Transform efficiency
- Memory usage profiling

**Target:** Process 100+ games in <10 minutes

### `test_query_performance.py`
Benchmarks for BigQuery query performance:
- Simple SELECT queries
- Complex JOINs
- Aggregations and window functions
- Query cache effectiveness

**Targets:**
- <2s for cached queries
- <10s for complex queries

### `test_pipeline_e2e_performance.py`
End-to-end pipeline benchmarks:
- Phase transition timing
- Full pipeline completion
- Bottleneck identification
- Resource usage tracking

**Target:** <30 minutes for full pipeline

## Running Tests

### Basic Usage

Run all performance tests:
```bash
pytest tests/performance/ -v
```

Run only benchmarks (skip non-benchmark tests):
```bash
pytest tests/performance/ -v --benchmark-only
```

Run specific test file:
```bash
pytest tests/performance/test_scraper_benchmarks.py -v --benchmark-only
```

### Advanced Options

Show detailed statistics:
```bash
pytest tests/performance/ -v --benchmark-only \
  --benchmark-columns=min,max,mean,stddev,median,iqr,outliers
```

Save benchmark results:
```bash
pytest tests/performance/ --benchmark-save=baseline --benchmark-autosave
```

Compare with previous results:
```bash
pytest tests/performance/ --benchmark-compare=baseline
```

Fail if performance regresses:
```bash
pytest tests/performance/ --benchmark-compare=baseline --benchmark-compare-fail=mean:20%
```

Generate histogram:
```bash
pytest tests/performance/ --benchmark-histogram
```

### Filtering Tests

Run only scraper benchmarks:
```bash
pytest tests/performance/test_scraper_benchmarks.py::TestHTTPRequestBenchmarks -v --benchmark-only
```

Run only specific benchmark:
```bash
pytest tests/performance/test_scraper_benchmarks.py::TestHTTPRequestBenchmarks::test_benchmark_simple_http_request -v --benchmark-only
```

## Benchmark Output

### Understanding Results

Example output:
```
test_scraper_benchmarks.py::TestHTTPRequestBenchmarks::test_benchmark_simple_http_request

Name                                          Min      Max     Mean   StdDev   Median    IQR
test_benchmark_simple_http_request       0.0020s  0.0035s  0.0023s  0.0003s  0.0022s  0.0001s

2 passed in 5.23s
```

**Columns:**
- **Min**: Fastest execution time
- **Max**: Slowest execution time
- **Mean**: Average execution time
- **StdDev**: Standard deviation (consistency)
- **Median**: Middle value (50th percentile)
- **IQR**: Interquartile range (spread)

### Performance Targets

Each test includes assertions against performance targets:
```python
# Verify performance target
stats = benchmark.stats
mean_time = stats['mean']
assert mean_time < 5.0, f"Scraper run took {mean_time:.2f}s, target is <5s"
```

Tests will fail if performance degrades beyond acceptable thresholds.

## Continuous Integration

### CI/CD Integration

Performance tests run automatically:
1. **Pull Requests**: Compare against main branch baseline
2. **Main Branch**: Track performance trends over time
3. **Pre-deployment**: Gate deployments on performance regression

### Regression Detection

Performance regressions are detected using thresholds:
- **Warning**: +20% latency increase or -10% throughput decrease
- **Critical**: +50% latency increase or -25% throughput decrease

Critical regressions block deployment.

## Baseline Management

### Establishing Baselines

Create initial baseline:
```bash
# Run benchmarks and save as baseline
pytest tests/performance/ --benchmark-save=baseline --benchmark-autosave

# Baseline saved to: .benchmarks/<timestamp>_baseline.json
```

### Updating Baselines

After performance improvements:
```bash
# Save new baseline
pytest tests/performance/ --benchmark-save=optimized --benchmark-autosave

# Compare with previous
pytest tests/performance/ --benchmark-compare=baseline --benchmark-compare=optimized
```

### Viewing Historical Data

List saved benchmarks:
```bash
ls .benchmarks/
```

Compare specific benchmarks:
```bash
pytest tests/performance/ --benchmark-compare=0001 --benchmark-compare=0002
```

## Performance Profiling

### Memory Profiling

Tests include memory profiling:
```python
def test_memory_usage(self):
    import sys
    data_size = sys.getsizeof(self.data)
    assert data_size < 10000000, f"Using {data_size / 1e6:.1f}MB"
```

### Identifying Bottlenecks

Bottleneck identification tests:
```python
def test_identify_slowest_phase(self):
    # Measure Phase 1
    start = time.time()
    phase1()
    phase1_time = time.time() - start

    # Measure Phase 2
    start = time.time()
    phase2()
    phase2_time = time.time() - start

    # Report bottleneck
    print(f"Phase 1: {phase1_time:.3f}s")
    print(f"Phase 2: {phase2_time:.3f}s")
```

## Optimization Guidelines

### Scraper Optimization

If scraper benchmarks fail:
1. Check HTTP connection pooling configuration
2. Review JSON parsing (consider orjson)
3. Verify proxy rotation efficiency
4. Profile download vs decode time

### Processor Optimization

If processor benchmarks fail:
1. Check batch size configuration
2. Review transformation logic (vectorize with pandas)
3. Verify BigQuery write batching
4. Profile transform vs save time

### Query Optimization

If query benchmarks fail:
1. Check partition pruning (filter on date)
2. Verify clustering columns usage
3. Review query cache settings
4. Analyze bytes processed

### Pipeline Optimization

If pipeline benchmarks fail:
1. Identify slowest phase
2. Check for sequential operations that could be parallel
3. Review resource allocation (Cloud Run instances)
4. Verify Pub/Sub message processing

## Tools and Dependencies

### Required Packages

Performance tests require:
```
pytest>=7.0.0
pytest-benchmark>=4.0.0
memory_profiler>=0.61.0  # For memory profiling
```

Install with:
```bash
pip install pytest pytest-benchmark memory_profiler
```

### Optional Tools

**pytest-benchmark extensions:**
- `pytest-benchmark[histogram]`: Generate histograms
- `pytest-benchmark[aspect]`: Aspect-based profiling

**Profiling tools:**
- `py-spy`: Statistical profiler
- `line_profiler`: Line-by-line profiling
- `memray`: Memory profiler

## Troubleshooting

### Tests Run Too Slowly

Reduce iterations:
```bash
pytest tests/performance/ --benchmark-min-rounds=5
```

### Inconsistent Results

Increase rounds for stability:
```bash
pytest tests/performance/ --benchmark-min-rounds=100
```

### Benchmark Comparison Fails

Reset baseline:
```bash
rm -rf .benchmarks/
pytest tests/performance/ --benchmark-save=baseline --benchmark-autosave
```

### Memory Tests Fail

Check system memory:
```bash
free -h  # Linux
vm_stat  # macOS
```

## Best Practices

### Writing Performance Tests

1. **Use fixtures** for consistent test data
2. **Mock external services** (BigQuery, GCS, HTTP)
3. **Include assertions** against performance targets
4. **Test at multiple scales** (small, medium, large datasets)
5. **Profile memory** alongside timing

### Running Tests

1. **Run on consistent hardware** for comparable results
2. **Close unnecessary applications** before benchmarking
3. **Run multiple times** to ensure consistency
4. **Compare against baselines** regularly
5. **Track trends** over time

### Interpreting Results

1. **Focus on P95/P99** for SLO compliance
2. **Check standard deviation** for consistency
3. **Investigate outliers** for root causes
4. **Compare across branches** for regression detection
5. **Document baselines** for reference

## References

- [Performance Targets Documentation](../../docs/performance/PERFORMANCE_TARGETS.md)
- [pytest-benchmark Documentation](https://pytest-benchmark.readthedocs.io/)
- [Testing Guide](../../docs/TESTING-GUIDE.md)
- [BigQuery Performance Best Practices](https://cloud.google.com/bigquery/docs/best-practices-performance-overview)

---

**Last Updated:** 2026-01-25
