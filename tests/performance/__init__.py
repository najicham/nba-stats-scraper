# tests/performance/__init__.py
"""
Performance/Load Tests for Critical Paths

This package contains benchmarks and load tests for:
- Scraper throughput
- Processor batch sizes
- Prediction latency
- Export timing

Run with:
    pytest tests/performance/ -v --benchmark-only
    pytest tests/performance/ -v --benchmark-columns=min,max,mean,stddev

To save and compare benchmarks:
    pytest tests/performance/ --benchmark-save=baseline
    pytest tests/performance/ --benchmark-compare=baseline
"""
