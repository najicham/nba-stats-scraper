# Data Quality Prevention - Architecture Patterns

This document describes the architectural patterns and design decisions behind the prevention system.

## Design Philosophy

### Prevention Over Detection

```
Traditional Approach:          Prevention Approach:
┌──────────────────┐          ┌──────────────────┐
│  Write Code      │          │  Write Code      │
│       ↓          │          │       ↓          │
│  Commit Code     │          │  Pre-commit Hook │ ← Catches schema issues
│       ↓          │          │       ↓          │
│  Deploy Code     │          │  Deploy Code     │
│       ↓          │          │       ↓          │
│  Process Data    │          │  Version Check   │ ← Tracks deployment
│       ↓          │          │       ↓          │
│  Write to BQ     │          │  Process Data    │
│       ↓          │          │       ↓          │
│  ERROR! ✗        │          │  Write to BQ ✓   │
│       ↓          │          │       ↓          │
│  Manual Fix      │          │  Success!        │
└──────────────────┘          └──────────────────┘
```

### Defense in Depth

Multiple layers of protection, each catching different issues:

1. **Commit Time**: Schema validation (catches field mismatches)
2. **Deploy Time**: Deployment tracking (identifies stale code)
3. **Process Time**: Freshness warnings (alerts on old deployments)
4. **Backfill Time**: Early exit bypass (allows historical processing)
5. **Post-Process**: Failure cleanup (removes false positives)

---

## Pattern 1: Mixin Composition

### Problem
Need to add version tracking and freshness checks to 55+ processors without modifying each one individually.

### Solution
Use Python mixins for composable functionality.

### Implementation

```python
# Mixin provides functionality
class ProcessorVersionMixin:
    def get_processor_metadata(self) -> Dict:
        return {
            'processor_version': self.PROCESSOR_VERSION,
            'schema_version': self.PROCESSOR_SCHEMA_VERSION,
            # ... more fields
        }

# Base class inherits mixin
class TransformProcessorBase(ProcessorVersionMixin, ABC):
    def __init__(self):
        self.add_version_to_stats()  # Automatic tracking

# All child processors inherit automatically
class PlayerGameSummaryProcessor(AnalyticsProcessorBase):
    pass  # Gets version tracking for free
```

### Benefits
- **Single implementation**: Write once, use everywhere
- **Automatic inheritance**: All processors get updates
- **Composable**: Multiple mixins can be combined
- **Backward compatible**: No breaking changes to existing processors

### Tradeoffs
- **Implicit behavior**: Mixins add behavior that's not obvious from child class
- **Method resolution order**: Multiple inheritance requires careful MRO management
- **Testing complexity**: Need to test both mixin and integration

---

## Pattern 2: Fail-Safe Defaults

### Problem
Prevention mechanisms shouldn't break processors if they fail.

### Solution
All checks are non-blocking with graceful degradation.

### Implementation

```python
class DeploymentFreshnessMixin:
    def check_deployment_freshness(self) -> None:
        """Check deployment age, but never fail."""
        try:
            # Attempt to check deployment info
            self._check_git_freshness()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Git not available - not critical
            pass  # Graceful degradation

    def _check_git_freshness(self) -> None:
        """Check git status, but never raise."""
        try:
            result = subprocess.run(..., timeout=2)  # Timeout to prevent hang
            if result.returncode == 0:
                # Process result
                pass
        except subprocess.TimeoutExpired:
            # Git too slow - skip check
            pass
```

### Principles
1. **Warnings only**: Log warnings, never raise exceptions
2. **Timeouts**: Subprocess calls have short timeouts (2 seconds)
3. **Catch broadly**: Catch all reasonable exception types
4. **Fail open**: If unsure, allow processing to continue
5. **Log everything**: Failures logged for debugging, but don't block

### Examples

```python
# Schema validation: Warn but allow commit if schema file missing
if not os.path.exists(schema_path):
    print("WARNING: Schema file not found, skipping validation")
    sys.exit(0)  # Allow commit

# Version tracking: Unknown deployment type is acceptable
deployment_info = self._get_deployment_info()
# Returns {'deployment_type': 'unknown'} instead of raising

# Freshness check: Missing git is not an error
try:
    commit_age = get_commit_age()
except FileNotFoundError:
    return  # Git not installed, skip check
```

---

## Pattern 3: Progressive Enhancement

### Problem
Can't rewrite entire codebase at once. Need gradual rollout.

### Solution
Add features to base classes, processors inherit automatically.

### Rollout Strategy

```
Phase 1: Core Infrastructure
├── Create mixins (version_tracking_mixin.py)
├── Integrate into base classes
└── All processors inherit automatically

Phase 2: Opt-In Features
├── Processors use default versions (1.0)
└── Teams update versions when making changes

Phase 3: Required Fields
├── Add processor_version to required schema fields
├── Pre-commit hook validates version bumps
└── Teams must update versions for all changes

Phase 4: Alerting & Automation
├── Alert on stale deployments (>48 hours)
├── Auto-trigger reprocessing for version mismatches
└── Dashboard shows version distribution
```

### Current State: Phase 1 Complete

All processors now have version tracking, but most use default "1.0". Teams can gradually adopt custom versions as they make changes.

---

## Pattern 4: Configuration Over Code

### Problem
Different processors have different requirements (threshold times, enabled checks, etc.).

### Solution
Use class attributes for configuration.

### Implementation

```python
class DeploymentFreshnessMixin:
    FRESHNESS_THRESHOLD_HOURS: int = 24  # Default

class MyProcessor(ProcessorBase, DeploymentFreshnessMixin):
    FRESHNESS_THRESHOLD_HOURS = 48  # Override for this processor

class EarlyExitMixin:
    ENABLE_GAMES_FINISHED_CHECK: bool = False  # Default: disabled
    ENABLE_OFFSEASON_CHECK: bool = True

class PlayerGameSummaryProcessor(EarlyExitMixin, AnalyticsProcessorBase):
    ENABLE_GAMES_FINISHED_CHECK = True  # Enable for this processor
```

### Benefits
- **Per-processor customization**: Each processor can configure thresholds
- **Readable**: Configuration visible in class definition
- **Type-safe**: Type hints document expected types
- **Backward compatible**: Defaults ensure existing processors work

---

## Pattern 5: Idempotent Operations

### Problem
Scripts may run multiple times (cron jobs, manual runs, retries).

### Solution
All operations are idempotent - safe to run multiple times.

### Examples

**Scraper Cleanup:**
```python
def mark_as_backfilled(scraper_name, game_date):
    """Idempotent UPDATE - safe to run multiple times."""
    UPDATE scraper_failures
    SET backfilled = TRUE, backfilled_at = CURRENT_TIMESTAMP()
    WHERE scraper_name = @scraper_name
      AND game_date = @game_date
    # Running twice: first marks as TRUE, second is no-op
```

**Version Tracking:**
```python
def add_version_to_stats(self):
    """Idempotent update - safe to call multiple times."""
    if hasattr(self, 'stats'):
        self.stats.update(self.get_processor_metadata())
    # Dict update is idempotent - same result if called twice
```

**Schema Validation:**
```bash
# Pre-commit hook runs on every commit
# Same schema + same code = same result (deterministic)
```

### Principles
1. **No side effects**: Operations don't accumulate state
2. **UPDATE not INSERT**: Use UPDATE or MERGE, not INSERT
3. **Deterministic**: Same inputs always produce same outputs
4. **Stateless**: No persistent state between runs

---

## Pattern 6: Separation of Concerns

### Problem
Prevention mechanisms shouldn't be tightly coupled to business logic.

### Solution
Each mechanism is independent and self-contained.

### Architecture

```
┌─────────────────────────────────────────────────┐
│              Processor Business Logic           │
│  (Extract → Validate → Transform → Save)        │
└─────────────────────────────────────────────────┘
                      ↓ uses
┌─────────────────────────────────────────────────┐
│           Base Classes & Mixins                 │
│  ┌──────────────────────────────────────────┐  │
│  │  ProcessorVersionMixin                   │  │
│  │  - get_processor_metadata()              │  │
│  │  - add_version_to_stats()                │  │
│  └──────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────┐  │
│  │  DeploymentFreshnessMixin                │  │
│  │  - check_deployment_freshness()          │  │
│  │  - _check_git_freshness()                │  │
│  └──────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────┐  │
│  │  EarlyExitMixin                          │  │
│  │  - should_exit_early()                   │  │
│  └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
                      ↓ uses
┌─────────────────────────────────────────────────┐
│         Independent Tools & Scripts              │
│  ┌──────────────────────────────────────────┐  │
│  │  Schema Validation Hook                  │  │
│  │  (runs at commit time)                   │  │
│  └──────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────┐  │
│  │  Scraper Cleanup Script                  │  │
│  │  (runs periodically)                     │  │
│  └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

### Benefits
- **Independent testing**: Each component can be tested in isolation
- **Easier maintenance**: Changes to one component don't affect others
- **Reusable**: Mixins can be used by different processor types
- **Clear responsibilities**: Each component has a single purpose

---

## Pattern 7: Observable Operations

### Problem
Prevention mechanisms need visibility when they trigger.

### Solution
Structured logging with rich context.

### Implementation

```python
# Version tracking logs deployment info
logger.info(
    f"Processing with deployment: {revision}",
    extra={
        'revision': revision,
        'service': service_name,
        'processor_version': self.PROCESSOR_VERSION,
    }
)

# Freshness warnings include context
logger.warning(
    f"Last commit is {age_hours:.1f} hours old",
    extra={
        'last_commit_age_hours': age_hours,
        'threshold_hours': self.FRESHNESS_THRESHOLD_HOURS,
    }
)

# Scraper cleanup logs all actions
logger.info(
    f"✅ Marked {scraper_name}/{game_date} as backfilled",
    extra={
        'scraper_name': scraper_name,
        'game_date': str(game_date),
        'records_found': record_count,
    }
)
```

### Benefits
- **Debugging**: Rich context helps investigate issues
- **Monitoring**: Can create alerts based on structured fields
- **Auditing**: Complete trail of what happened when
- **Metrics**: Can aggregate statistics from logs

---

## Pattern 8: Test First, Deploy Later

### Problem
Prevention mechanisms must be reliable - bugs in prevention are worse than no prevention.

### Solution
Comprehensive testing before production deployment.

### Testing Pyramid

```
                   ┌──────────┐
                   │   E2E    │  (1 test: Full backfill run)
                   └──────────┘
              ┌─────────────────┐
              │  Integration    │  (5 tests: Base class integration)
              └─────────────────┘
         ┌──────────────────────────┐
         │      Unit Tests          │  (36 tests: Individual components)
         └──────────────────────────┘
    ┌──────────────────────────────────┐
    │     Manual Validation            │  (Dry-run, spot checks)
    └──────────────────────────────────┘
```

### Testing Coverage

| Component | Unit Tests | Integration Tests | Manual Tests |
|-----------|-----------|------------------|--------------|
| Schema Validation | ✓ (implicit) | ✓ (pre-commit) | ✓ (test mismatches) |
| Version Tracking | ✓ (3 tests) | ✓ (base class) | ✓ (metadata check) |
| Freshness Warnings | ✓ (3 tests) | ✓ (base class) | ✓ (log inspection) |
| Early Exit Backfill | ✓ (3 new tests) | ✓ (existing 33) | ✓ (backfill run) |
| Scraper Cleanup | ✓ (logic tested) | N/A | ✓ (dry-run validated) |

---

## Anti-Patterns Avoided

### ❌ Anti-Pattern: Tightly Coupled Validation
```python
# BAD: Validation logic embedded in processor
class MyProcessor(ProcessorBase):
    def process(self, data):
        # Validation mixed with business logic
        if not self._validate_schema(data):
            raise ValueError("Schema mismatch")
        # Hard to reuse, hard to test
```

### ✅ Pattern: Separated Validation
```python
# GOOD: Validation as pre-commit hook
# Runs before commit, separate from processor logic
# Reusable across all processors
```

---

### ❌ Anti-Pattern: Blocking Checks
```python
# BAD: Check fails processor
def check_freshness(self):
    if deployment_age > 24:
        raise DeploymentTooOldError()  # Blocks processing!
```

### ✅ Pattern: Non-Blocking Warnings
```python
# GOOD: Warning doesn't block processing
def check_freshness(self):
    if deployment_age > 24:
        logger.warning("Deployment is old")  # Logs but continues
```

---

### ❌ Anti-Pattern: Hardcoded Configuration
```python
# BAD: Threshold hardcoded in method
def check_freshness(self):
    if age > 24:  # Magic number
        logger.warning("Old deployment")
```

### ✅ Pattern: Configurable Thresholds
```python
# GOOD: Configuration at class level
class MyMixin:
    FRESHNESS_THRESHOLD_HOURS = 24  # Overridable

def check_freshness(self):
    if age > self.FRESHNESS_THRESHOLD_HOURS:
        logger.warning("Old deployment")
```

---

## Future Patterns to Consider

### 1. Circuit Breaker for Prevention
If prevention checks fail consistently, automatically disable them to prevent blocking all processing.

### 2. Feature Flags
Allow enabling/disabling prevention mechanisms without code changes:
```python
if feature_flags.is_enabled('version_tracking'):
    self.add_version_to_stats()
```

### 3. Metrics Collection
Track prevention mechanism effectiveness:
- Schema validation catch rate
- Deployment freshness distribution
- Backfill success rate after cleanup

### 4. Automated Remediation
When stale code is detected:
- Auto-trigger reprocessing
- Auto-deploy latest code
- Auto-alert on-call engineer

---

## Lessons Learned

1. **Start with base classes**: Mixin pattern scales to 55+ processors with minimal changes
2. **Fail-safe is critical**: Non-blocking checks prevent prevention from becoming a problem
3. **Test incrementally**: Unit tests → integration tests → dry-run → production
4. **Log everything**: Structured logging enables debugging and monitoring
5. **Configuration over code**: Class attributes make customization easy

---

## Related Patterns

- **Mixin Pattern**: [Python Mixins](https://en.wikipedia.org/wiki/Mixin)
- **Fail-Safe Defaults**: [Fail-Safe Design](https://en.wikipedia.org/wiki/Fail-safe)
- **Defense in Depth**: [Security Principle](https://en.wikipedia.org/wiki/Defense_in_depth_(computing))
- **Progressive Enhancement**: [Web Development Pattern](https://en.wikipedia.org/wiki/Progressive_enhancement)
- **Separation of Concerns**: [Software Design Principle](https://en.wikipedia.org/wiki/Separation_of_concerns)
