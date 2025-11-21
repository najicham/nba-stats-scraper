# Pattern #13: Smart Caching

**Created:** 2025-11-20 8:14 AM PST
**Status:** 💡 Week 4-8 Situational - Wait for Query Performance Data
**Complexity:** Low (1-2 hours for simple version) to High (3-4 hours with Redis)
**Value:** High IF you have slow repeated queries (20-30% speedup)

---

## ⚠️ Prerequisites - Measure First!

**This pattern requires evidence of a "slow query" problem:**

1. **Multiple slow queries** - Same calculation repeated frequently
2. **Cacheable results** - Query results don't change between calls
3. **Significant time waste** - Queries take > 2 seconds and run > 10 times/day

**Don't implement unless:**
- Week 1-8 monitoring shows slow queries (run diagnostic queries below)
- You've already tried query optimization (indexes, partitioning, materialized views)
- The problem is costing > 2 hours of processing time per day

**Timeline:**
- Week 1-4: Monitor query performance
- Week 4: Run diagnostic queries, decide if caching needed
- Week 5-6: Implement simple in-memory caching IF needed
- Week 8+: Consider Redis IF multiple instances need shared cache

---

## Is This Needed?

**Run these queries during Week 1-8 monitoring to detect if you have a slow query problem:**

### Query 1: Find Repeated Expensive Queries
```sql
-- Detect if same queries are running repeatedly
-- Pattern needed if: > 50 queries taking > 5 seconds each

WITH query_patterns AS (
  SELECT
    processor_name,
    -- Extract query pattern (e.g., "SELECT AVG(points) FROM ... WHERE player_id = ?")
    REGEXP_REPLACE(query_text, r"'[^']*'", "'?'") as query_pattern,
    COUNT(*) as executions,
    AVG(duration_seconds) as avg_duration,
    SUM(duration_seconds) as total_duration_seconds,
    MIN(executed_at) as first_seen,
    MAX(executed_at) as last_seen
  FROM nba_orchestration.query_execution_log
  WHERE executed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    AND duration_seconds > 2  -- Only queries taking > 2 seconds
    AND status = 'completed'
  GROUP BY processor_name, query_pattern
  HAVING executions > 10  -- Repeated at least 10 times
)
SELECT
  processor_name,
  query_pattern,
  executions,
  ROUND(avg_duration, 2) as avg_seconds,
  ROUND(total_duration_seconds / 60, 1) as total_minutes,
  ROUND(total_duration_seconds * 0.8 / 60, 1) as potential_savings_minutes,  -- 80% cache hit rate
  DATE_DIFF(last_seen, first_seen, HOUR) as hours_span
FROM query_patterns
ORDER BY potential_savings_minutes DESC
LIMIT 20;

-- Pattern needed if: potential_savings_minutes > 20 for any processor
```

### Query 2: Detect Rolling Average Calculations
```sql
-- Find processors doing expensive rolling average calculations
-- Symptoms: Multiple queries with LIMIT N clauses for last N games

SELECT
  processor_name,
  COUNT(*) as rolling_avg_queries,
  AVG(duration_seconds) as avg_duration,
  SUM(duration_seconds) as total_duration_seconds,
  ROUND(SUM(duration_seconds) / 60, 1) as total_minutes
FROM nba_orchestration.query_execution_log
WHERE executed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND status = 'completed'
  AND (
    query_text LIKE '%ORDER BY game_date DESC LIMIT%'  -- Rolling window
    OR query_text LIKE '%AVG(%'  -- Average calculation
    OR query_text LIKE '%last % games%'
  )
  AND duration_seconds > 1
GROUP BY processor_name
ORDER BY total_minutes DESC;

-- Pattern needed if: total_minutes > 30 for any processor
```

### Query 3: Measure Potential Cache Hit Rate
```sql
-- Estimate how often same calculation is repeated
-- (Same player_id + game_date + stat)

WITH repeated_calculations AS (
  SELECT
    processor_name,
    JSON_EXTRACT_SCALAR(metadata, '$.player_id') as player_id,
    JSON_EXTRACT_SCALAR(metadata, '$.game_date') as game_date,
    JSON_EXTRACT_SCALAR(metadata, '$.stat') as stat,
    COUNT(*) as repeat_count
  FROM nba_orchestration.pipeline_execution_log
  WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    AND status = 'completed'
    AND metadata IS NOT NULL
  GROUP BY processor_name, player_id, game_date, stat
  HAVING repeat_count > 1  -- Calculated multiple times
)
SELECT
  processor_name,
  COUNT(*) as unique_calculations,
  SUM(repeat_count) as total_calculations,
  SUM(repeat_count - 1) as redundant_calculations,
  ROUND(SUM(repeat_count - 1) / SUM(repeat_count) * 100, 1) as potential_hit_rate_pct
FROM repeated_calculations
GROUP BY processor_name
ORDER BY redundant_calculations DESC;

-- Pattern needed if: potential_hit_rate_pct > 50% and redundant_calculations > 100
```

**Decision criteria:**
- Query 1 shows potential_savings_minutes > 20: Strong signal
- Query 2 shows total_minutes > 30: Strong signal
- Query 3 shows potential_hit_rate_pct > 50%: Strong signal
- **ALL THREE combined:** Definitely implement
- **None of the above:** Don't implement, no problem to solve

---

## What Problem Does This Solve?

**Problem:** Repeated expensive calculations waste time and money.

**Example scenario:**
```
PlayerGameSummaryProcessor running for 2025-11-18 (450 players):

Without caching:
  For each player:
    - Query season average (2 seconds)
    - Query 10-game rolling average (2 seconds)
    - Query 5-game rolling average (2 seconds)
    - Query home/away splits (2 seconds)

  Total: 450 players × 8 seconds = 3,600 seconds (60 minutes)

  THEN, odds update triggers same processor 30 minutes later:
    - Same 450 players
    - Same calculations (data hasn't changed!)
    - Another 60 minutes wasted

Total wasted per day: 5-10 runs × 60 minutes = 5-10 hours
```

**With caching:**
```
First run:
  - 450 players × 8 seconds = 60 minutes (cache misses)

Second run (30 minutes later):
  - 450 players × 0.01 seconds = 4.5 seconds (cache hits!)
  - Savings: 60 minutes → 4.5 seconds (800x faster)

Subsequent runs: All cache hits (until data updates)
```

---

## How It Works

### Simple Version (In-Memory Only - Start Here)

```python
# shared/processors/patterns/smart_caching_mixin.py

from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
import logging

logger = logging.getLogger(__name__)


class CacheEntry:
    """A cached value with expiration."""

    def __init__(self, value: Any, ttl: timedelta):
        self.value = value
        self.cached_at = datetime.utcnow()
        self.expires_at = self.cached_at + ttl

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


class SmartCacheMixin:
    """
    Simple in-memory caching for expensive calculations.

    Usage:
        class YourProcessor(SmartCacheMixin, AnalyticsProcessorBase):
            def calculate_expensive_stat(self, player_id, game_date):
                return self.cached_query(
                    f"stat:{player_id}:{game_date}",
                    lambda: self._query_bigquery(player_id, game_date)
                )
    """

    # Override in subclass
    CACHE_TTL = timedelta(hours=1)
    CACHE_MAX_SIZE = 1000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache = {}  # {cache_key: CacheEntry}
        self._cache_hits = 0
        self._cache_misses = 0

    def cached_query(
        self,
        cache_key: str,
        expensive_function: Callable[[], Any],
        ttl: Optional[timedelta] = None
    ) -> Any:
        """
        Execute function with caching.

        Args:
            cache_key: Unique key (e.g., "season_avg:player_123:2025-11-18:points")
            expensive_function: Function to call on cache miss
            ttl: Time-to-live (default: 1 hour)

        Returns:
            Cached or computed value
        """
        ttl = ttl or self.CACHE_TTL

        # Check cache
        if cache_key in self._cache:
            entry = self._cache[cache_key]

            # Check expiration
            if not entry.is_expired():
                self._cache_hits += 1
                logger.debug(f"Cache hit: {cache_key[:50]}...")
                return entry.value
            else:
                # Expired - remove
                del self._cache[cache_key]

        # Cache miss - compute
        self._cache_misses += 1
        logger.debug(f"Cache miss: {cache_key[:50]}...")

        result = expensive_function()

        # Store in cache (check size limit)
        if len(self._cache) >= self.CACHE_MAX_SIZE:
            # Evict oldest entry
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].cached_at
            )
            del self._cache[oldest_key]

        self._cache[cache_key] = CacheEntry(result, ttl)

        return result

    def invalidate_cache(self, pattern: Optional[str] = None):
        """
        Invalidate cache entries.

        Args:
            pattern: Wildcard pattern (e.g., "*:player_123:*")
                     If None, clears entire cache
        """
        if pattern is None:
            self._cache.clear()
            logger.info("Cache fully invalidated")
            return

        # Pattern matching
        import fnmatch
        keys_to_delete = [
            key for key in self._cache.keys()
            if fnmatch.fnmatch(key, pattern)
        ]

        for key in keys_to_delete:
            del self._cache[key]

        logger.info(f"Cache invalidated: {len(keys_to_delete)} entries matching '{pattern}'")

    def get_cache_stats(self) -> Dict:
        """Get cache performance metrics."""
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total * 100) if total > 0 else 0.0

        return {
            'hits': self._cache_hits,
            'misses': self._cache_misses,
            'hit_rate_pct': round(hit_rate, 1),
            'cache_size': len(self._cache),
            'max_size': self.CACHE_MAX_SIZE
        }
```

---

## Implementation

### Step 1: Add Mixin to Processor (15 minutes)

```python
# data_processors/analytics/player_game_summary_processor.py

from shared.processors.patterns.smart_caching_mixin import SmartCacheMixin
from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from datetime import timedelta

class PlayerGameSummaryProcessor(SmartCacheMixin, AnalyticsProcessorBase):
    """Player game stats with caching for expensive calculations."""

    # Configure cache
    CACHE_TTL = timedelta(hours=2)  # Cache for 2 hours
    CACHE_MAX_SIZE = 1000  # Max 1000 entries

    def __init__(self):
        super().__init__()
        self.table_name = 'player_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'

    # Rest of implementation...
```

### Step 2: Wrap Expensive Calculations (30 minutes)

**Before (no caching):**
```python
def calculate_season_average(self, player_id: str, game_date: str, stat: str) -> float:
    """Calculate season average - SLOW (2 seconds per call)."""
    query = f"""
    SELECT AVG({stat}) as avg_value
    FROM nba_raw.nbac_gamebook_player_stats
    WHERE universal_player_id = '{player_id}'
      AND game_date < '{game_date}'
      AND game_date >= DATE_SUB('{game_date}', INTERVAL 120 DAY)
    """

    result = self.bq_client.query(query).to_dataframe()
    return float(result['avg_value'].iloc[0]) if not result.empty else 0.0
```

**After (with caching):**
```python
def calculate_season_average(self, player_id: str, game_date: str, stat: str) -> float:
    """Calculate season average - CACHED (first call: 2s, subsequent: 0.01s)."""
    cache_key = f"season_avg:{player_id}:{game_date}:{stat}"

    return self.cached_query(
        cache_key,
        lambda: self._query_season_average(player_id, game_date, stat),
        ttl=timedelta(hours=4)  # Season stats change slowly, use longer TTL
    )

def _query_season_average(self, player_id: str, game_date: str, stat: str) -> float:
    """Internal: Execute the actual query."""
    query = f"""
    SELECT AVG({stat}) as avg_value
    FROM nba_raw.nbac_gamebook_player_stats
    WHERE universal_player_id = '{player_id}'
      AND game_date < '{game_date}'
      AND game_date >= DATE_SUB('{game_date}', INTERVAL 120 DAY)
    """

    result = self.bq_client.query(query).to_dataframe()
    return float(result['avg_value'].iloc[0]) if not result.empty else 0.0
```

### Step 3: Add Common Cached Methods (30 minutes)

Create reusable cached calculation methods:

```python
class PlayerGameSummaryProcessor(SmartCacheMixin, AnalyticsProcessorBase):
    # ... existing code ...

    def get_rolling_average(
        self,
        player_id: str,
        game_date: str,
        stat: str,
        window: int = 10
    ) -> float:
        """
        Get rolling average with caching.

        Cached for 2 hours. Subsequent calls return instantly.
        """
        cache_key = f"rolling_avg:{player_id}:{game_date}:{stat}:{window}"

        return self.cached_query(
            cache_key,
            lambda: self._query_rolling_average(player_id, game_date, stat, window)
        )

    def get_home_away_split(
        self,
        player_id: str,
        game_date: str,
        stat: str,
        is_home: bool
    ) -> float:
        """
        Get home/away split with caching.

        Cached for 3 hours (stable data).
        """
        location = 'home' if is_home else 'away'
        cache_key = f"split:{location}:{player_id}:{game_date}:{stat}"

        return self.cached_query(
            cache_key,
            lambda: self._query_home_away_split(player_id, game_date, stat, is_home),
            ttl=timedelta(hours=3)
        )

    def get_matchup_history(
        self,
        player_id: str,
        opponent_team_id: str,
        game_date: str,
        stat: str
    ) -> float:
        """
        Get historical performance vs opponent with caching.

        Cached for 6 hours (very stable).
        """
        cache_key = f"matchup:{player_id}:{opponent_team_id}:{game_date}:{stat}"

        return self.cached_query(
            cache_key,
            lambda: self._query_matchup_history(player_id, opponent_team_id, game_date, stat),
            ttl=timedelta(hours=6)
        )
```

### Step 4: Use in Transform (15 minutes)

```python
def transform_data(self, raw_data):
    """Transform with cached calculations."""
    results = []

    for _, row in raw_data.iterrows():
        player_id = row['universal_player_id']
        game_date = row['game_date']

        # All these are cached!
        result_row = {
            **row.to_dict(),
            'points_season_avg': self.calculate_season_average(player_id, game_date, 'points'),
            'points_l10': self.get_rolling_average(player_id, game_date, 'points', 10),
            'points_l5': self.get_rolling_average(player_id, game_date, 'points', 5),
            'rebounds_l10': self.get_rolling_average(player_id, game_date, 'rebounds', 10),
            'assists_l10': self.get_rolling_average(player_id, game_date, 'assists', 10),
        }

        results.append(result_row)

    # Log cache performance
    cache_stats = self.get_cache_stats()
    self.logger.info(
        f"Cache performance: {cache_stats['hit_rate_pct']}% hit rate, "
        f"{cache_stats['hits']} hits, {cache_stats['misses']} misses"
    )

    return results
```

### Step 5: Monitor Performance (15 minutes)

Add cache stats to processing metadata:

```python
def run(self, opts: Dict) -> bool:
    game_date = opts.get('game_date', self.default_game_date)

    # Processing...
    result = super().run(opts)

    # Include cache stats in metadata
    cache_stats = self.get_cache_stats()
    self.processing_metadata.update({
        'cache_hits': cache_stats['hits'],
        'cache_misses': cache_stats['misses'],
        'cache_hit_rate_pct': cache_stats['hit_rate_pct'],
        'cache_size': cache_stats['cache_size']
    })

    return result
```

---

## Expected Impact

### Performance Improvement

**Scenario: Processing 450 players, runs 10 times/day**

Without caching:
```
First run:  450 players × 8 seconds = 3,600s (60 min)
Second run: 450 players × 8 seconds = 3,600s (60 min)
Third run:  450 players × 8 seconds = 3,600s (60 min)
...
Daily total: 10 runs × 60 min = 600 minutes (10 hours)
```

With caching (80% hit rate after first run):
```
First run:  450 players × 8 seconds = 3,600s (60 min) - cache misses
Second run: 450 players × 0.4 seconds = 180s (3 min) - 80% cache hits
Third run:  450 players × 0.4 seconds = 180s (3 min)
...
Daily total: 60 + (9 × 3) = 87 minutes

Savings: 600 min → 87 min (86% reduction, 8.5 hours saved/day)
```

### Cost Reduction

**BigQuery queries:**
```
Without caching: 450 players × 5 queries × 10 runs = 22,500 queries/day
With caching (80% hit rate): 4,500 queries/day
Reduction: 80% fewer BigQuery queries
```

---

## Cache Invalidation Strategy

**When to invalidate cache:**

### 1. After New Data Arrives
```python
def run(self, opts: Dict) -> bool:
    game_date = opts.get('game_date')
    source_table = opts.get('source_table')

    # If new player stats arrived, invalidate season/rolling averages
    if source_table == 'nbac_gamebook_player_stats':
        self.invalidate_cache('season_avg:*')
        self.invalidate_cache('rolling_avg:*')
        self.logger.info("Cache invalidated: new player stats arrived")

    # Continue processing...
    return super().run(opts)
```

### 2. For Specific Players
```python
# After injury update for player_123
self.invalidate_cache('*:player_123:*')
```

### 3. Daily Cleanup
```python
# Clear entire cache at start of day
if datetime.utcnow().hour == 0:  # Midnight
    self.invalidate_cache()  # Clear all
```

---

## Testing

### Unit Test: Cache Behavior
```python
# tests/patterns/test_smart_caching.py

import pytest
from shared.processors.patterns.smart_caching_mixin import SmartCacheMixin
from data_processors.analytics.analytics_base import AnalyticsProcessorBase


class TestProcessor(SmartCacheMixin, AnalyticsProcessorBase):
    """Test processor with caching."""
    pass


def test_cache_hit():
    """Test cache returns same value on second call."""
    processor = TestProcessor()
    call_count = 0

    def expensive_function():
        nonlocal call_count
        call_count += 1
        return 42

    # First call - cache miss
    result1 = processor.cached_query('test_key', expensive_function)
    assert result1 == 42
    assert call_count == 1

    # Second call - cache hit (function not called again)
    result2 = processor.cached_query('test_key', expensive_function)
    assert result2 == 42
    assert call_count == 1  # Still 1, function not called

    # Verify stats
    stats = processor.get_cache_stats()
    assert stats['hits'] == 1
    assert stats['misses'] == 1
    assert stats['hit_rate_pct'] == 50.0


def test_cache_expiration():
    """Test cache expires after TTL."""
    import time
    from datetime import timedelta

    processor = TestProcessor()
    processor.CACHE_TTL = timedelta(seconds=1)

    call_count = 0
    def expensive_function():
        nonlocal call_count
        call_count += 1
        return 42

    # Cache value
    result1 = processor.cached_query('test_key', expensive_function)
    assert call_count == 1

    # Wait for expiration
    time.sleep(2)

    # Should recalculate
    result2 = processor.cached_query('test_key', expensive_function)
    assert call_count == 2  # Function called again

    stats = processor.get_cache_stats()
    assert stats['misses'] == 2  # Both calls were cache misses


def test_cache_invalidation():
    """Test cache invalidation."""
    processor = TestProcessor()

    # Cache multiple values
    processor.cached_query('player:123:stat_a', lambda: 10)
    processor.cached_query('player:123:stat_b', lambda: 20)
    processor.cached_query('player:456:stat_a', lambda: 30)

    assert len(processor._cache) == 3

    # Invalidate player 123
    processor.invalidate_cache('player:123:*')

    assert len(processor._cache) == 1  # Only player:456 remains
    assert 'player:456:stat_a' in processor._cache


def test_cache_size_limit():
    """Test cache evicts oldest when size limit reached."""
    processor = TestProcessor()
    processor.CACHE_MAX_SIZE = 2

    # Add 3 entries (exceeds limit)
    processor.cached_query('key1', lambda: 1)
    processor.cached_query('key2', lambda: 2)
    processor.cached_query('key3', lambda: 3)

    # Should have evicted oldest (key1)
    assert len(processor._cache) == 2
    assert 'key1' not in processor._cache
    assert 'key2' in processor._cache
    assert 'key3' in processor._cache
```

### Integration Test: Real Performance
```python
def test_caching_performance():
    """Test actual performance improvement."""
    import time
    from data_processors.analytics.player_game_summary_processor import PlayerGameSummaryProcessor

    processor = PlayerGameSummaryProcessor()

    # Simulate slow query
    def slow_query():
        time.sleep(2)  # Simulate 2s BigQuery query
        return 25.5

    # First call - cache miss (slow)
    start = time.time()
    result1 = processor.cached_query('test:slow', slow_query)
    uncached_time = time.time() - start

    # Second call - cache hit (fast)
    start = time.time()
    result2 = processor.cached_query('test:slow', slow_query)
    cached_time = time.time() - start

    assert result1 == result2
    assert cached_time < 0.1  # Should be instant
    assert uncached_time > 1.0  # Should be slow

    speedup = uncached_time / cached_time
    print(f"Cache speedup: {speedup:.0f}x")
    assert speedup > 10  # At least 10x faster
```

---

## Monitoring

### Query: Cache Performance
```sql
-- Track cache hit rates across processors
SELECT
  processor_name,
  DATE(started_at) as process_date,
  AVG(SAFE_CAST(JSON_EXTRACT_SCALAR(processing_metadata, '$.cache_hit_rate_pct') AS FLOAT64)) as avg_hit_rate,
  AVG(SAFE_CAST(JSON_EXTRACT_SCALAR(processing_metadata, '$.cache_hits') AS INT64)) as avg_hits,
  AVG(SAFE_CAST(JSON_EXTRACT_SCALAR(processing_metadata, '$.cache_misses') AS INT64)) as avg_misses
FROM analytics_processing_metadata
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND processing_metadata LIKE '%cache_hit_rate_pct%'
GROUP BY processor_name, process_date
ORDER BY process_date DESC, processor_name;

-- Expect: 50-80% hit rate after initial warmup
```

### Query: Estimate Time Saved
```sql
-- Estimate time saved by caching (assuming 2s per cache hit)
SELECT
  processor_name,
  SUM(SAFE_CAST(JSON_EXTRACT_SCALAR(processing_metadata, '$.cache_hits') AS INT64)) as total_cache_hits,
  ROUND(SUM(SAFE_CAST(JSON_EXTRACT_SCALAR(processing_metadata, '$.cache_hits') AS INT64)) * 2 / 60, 1) as minutes_saved
FROM analytics_processing_metadata
WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND processing_metadata LIKE '%cache_hits%'
GROUP BY processor_name
ORDER BY minutes_saved DESC;
```

---

## Advanced: Redis for Shared Caching (Week 8+ Optional)

**Only implement Redis if:**
- You're running multiple Cloud Run instances
- In-memory cache hit rate is low (< 40%) due to different instances
- Worth the infrastructure complexity (deploy Memorystore, manage connections)

### Deploy Redis
```bash
# GCP Memorystore (smallest instance: $50/month)
gcloud redis instances create nba-props-cache \
    --size=1 \
    --region=us-central1 \
    --redis-version=redis_6_x
```

### Add Redis Support to Mixin
```python
# Add to SmartCacheMixin (optional upgrade)

try:
    import redis
    import pickle
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

class SmartCacheMixin:
    # Add configuration
    CACHE_ENABLE_REDIS = False  # Enable manually
    CACHE_REDIS_HOST = 'localhost'
    CACHE_REDIS_PORT = 6379

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache = {}
        self._cache_hits = 0
        self._cache_misses = 0

        # Initialize Redis if enabled
        self._redis = None
        if self.CACHE_ENABLE_REDIS and REDIS_AVAILABLE:
            try:
                self._redis = redis.Redis(
                    host=self.CACHE_REDIS_HOST,
                    port=self.CACHE_REDIS_PORT,
                    decode_responses=False
                )
                self._redis.ping()
                logger.info("Redis cache connected")
            except Exception as e:
                logger.warning(f"Redis unavailable: {e}, using in-memory only")
                self._redis = None

    def cached_query(self, cache_key, expensive_function, ttl=None):
        ttl = ttl or self.CACHE_TTL

        # Try in-memory first (L1)
        if cache_key in self._cache:
            entry = self._cache[cache_key]
            if not entry.is_expired():
                self._cache_hits += 1
                return entry.value
            else:
                del self._cache[cache_key]

        # Try Redis (L2)
        if self._redis:
            try:
                pickled = self._redis.get(cache_key)
                if pickled:
                    value = pickle.loads(pickled)
                    # Promote to L1
                    self._cache[cache_key] = CacheEntry(value, ttl)
                    self._cache_hits += 1
                    return value
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")

        # Cache miss - compute
        self._cache_misses += 1
        result = expensive_function()

        # Store in L1
        if len(self._cache) >= self.CACHE_MAX_SIZE:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].cached_at)
            del self._cache[oldest_key]
        self._cache[cache_key] = CacheEntry(result, ttl)

        # Store in Redis (L2)
        if self._redis:
            try:
                self._redis.setex(
                    cache_key,
                    int(ttl.total_seconds()),
                    pickle.dumps(result)
                )
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")

        return result
```

### Enable Redis in Processor
```python
class PlayerGameSummaryProcessor(SmartCacheMixin, AnalyticsProcessorBase):
    CACHE_ENABLE_REDIS = True
    CACHE_REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    CACHE_REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
```

---

## Best Practices

### ✅ DO: Use Deterministic Cache Keys
```python
# Good - includes all relevant parameters
cache_key = f"season_avg:{player_id}:{game_date}:{stat}"

# Bad - includes timestamp (never hits cache)
cache_key = f"season_avg:{player_id}:{datetime.now()}"
```

### ✅ DO: Use Longer TTL for Stable Data
```python
# Historical data - rarely changes
self.cached_query(key, func, ttl=timedelta(hours=6))

# Recent data - updates frequently
self.cached_query(key, func, ttl=timedelta(minutes=30))
```

### ✅ DO: Invalidate After Updates
```python
# After new game stats loaded
if source_table == 'nbac_gamebook_player_stats':
    self.invalidate_cache('season_avg:*')
    self.invalidate_cache('rolling_avg:*')
```

### ✅ DO: Log Cache Stats
```python
cache_stats = self.get_cache_stats()
logger.info(f"Cache: {cache_stats['hit_rate_pct']}% hit rate")
```

### ❌ DON'T: Cache Everything
```python
# Don't cache fast queries (< 0.5s)
# Overhead of caching > query time

# Bad - caching adds overhead for fast query
result = self.cached_query('simple', lambda: bq_client.query("SELECT 1").result())
```

### ❌ DON'T: Use Extremely Long TTL
```python
# Bad - data becomes stale
self.cached_query(key, func, ttl=timedelta(days=7))

# Good - reasonable TTL with invalidation
self.cached_query(key, func, ttl=timedelta(hours=4))
```

---

## Troubleshooting

### Issue: Low Hit Rate (< 40%)

**Diagnosis:**
```python
stats = processor.get_cache_stats()
print(f"Hit rate: {stats['hit_rate_pct']}%")
print(f"Cache size: {stats['cache_size']}/{stats['max_size']}")
```

**Common causes:**
1. Cache keys include timestamps → Fix: Use static keys
2. Cache too small (hitting size limit) → Fix: Increase `CACHE_MAX_SIZE`
3. TTL too short → Fix: Increase `CACHE_TTL`
4. Multiple instances (no shared cache) → Fix: Enable Redis

### Issue: Stale Data

**Diagnosis:**
```python
# Check cache entry age
entry = processor._cache.get(cache_key)
if entry:
    age = (datetime.utcnow() - entry.cached_at).total_seconds()
    print(f"Cache age: {age}s")
```

**Solution:**
```python
# Reduce TTL or invalidate more aggressively
processor.CACHE_TTL = timedelta(hours=1)  # Shorter TTL

# Or invalidate after data updates
processor.invalidate_cache('season_avg:*')
```

### Issue: Memory Usage High

**Diagnosis:**
```python
import sys
cache_size_bytes = sys.getsizeof(processor._cache)
print(f"Cache memory: {cache_size_bytes / 1024 / 1024:.1f} MB")
```

**Solution:**
1. Reduce `CACHE_MAX_SIZE`
2. Use shorter TTL
3. Enable Redis (offload to external cache)

---

## When NOT to Use This Pattern

❌ **Don't use if:**
- Queries are fast (< 1 second)
- Queries are infrequent (< 10 times/day)
- Results change constantly (low hit rate)
- Week 1-8 monitoring shows no slow query problem

✅ **Use if:**
- Week 1-8 shows slow repeated queries (> 2s each, > 50 times/day)
- Potential time savings > 20 minutes/day
- Query results are stable for 1+ hours
- You've already optimized the queries themselves

---

## Summary

**Pattern #13 helps avoid repeated expensive calculations by caching results.**

**Key points:**
- ⚠️ Measure first! Run diagnostic queries to detect if you have a slow query problem
- Only implement if Week 1-8 monitoring shows > 20 minutes/day wasted
- Start with simple in-memory caching (1-2 hours implementation)
- Add Redis later IF needed for multi-instance deployment
- Don't cache everything - only expensive calculations (> 2s)

**Timeline:**
- Week 1-4: Monitor query performance
- Week 4: Run "Is This Needed?" queries, decide
- Week 5-6: Implement simple version IF needed
- Week 8+: Consider Redis IF multi-instance coordination needed

**Expected impact:**
- 20-30% reduction in processing time (if you have the problem)
- 80% reduction in BigQuery costs for repeated queries
- 10-100x speedup for cached lookups (2s → 0.01s)

**This is a "wait and see" optimization - measure first, implement second.**
