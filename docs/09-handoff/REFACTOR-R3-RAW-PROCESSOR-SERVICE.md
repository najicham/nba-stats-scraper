# Refactor Session R3: Raw Processor Service

**Scope:** 1 file, 2 large functions (~1,125 lines of functions)
**Risk Level:** Medium (handles all Phase 2 processing)
**Estimated Effort:** 1.5-2 hours
**Model:** Sonnet recommended

---

## Overview

Refactor the two largest functions in the raw processor service: `process_pubsub()` (696 lines) and `extract_opts_from_path()` (429 lines).

---

## File to Refactor

### data_processors/raw/main_processor_service.py

**Current State:** Contains two massive functions that handle all Pub/Sub message processing and path-based option extraction.

---

## Function 1: process_pubsub() (696 lines)

**Lines:** 564-1259

**Current State:** Monolithic function handling:
- Message decoding and validation
- Format normalization (GCS vs Scraper formats)
- Batch processing detection
- ESPN roster batch mode
- Basketball Reference batch mode
- OddsAPI batch mode
- Standard file processing
- Error handling and notifications

**Target Structure:**
```
data_processors/raw/
├── main_processor_service.py    # Simplified process_pubsub() (~100 lines)
├── handlers/
│   ├── __init__.py
│   ├── message_handler.py       # Decode, validate, normalize messages
│   ├── batch_detector.py        # Detect and route batch triggers
│   ├── espn_batch_handler.py    # ESPN roster batch processing
│   ├── br_batch_handler.py      # Basketball Reference batch processing
│   ├── oddsapi_batch_handler.py # OddsAPI batch processing
│   └── file_processor.py        # Standard single-file processing
```

**Extraction Steps:**

1. **Create `handlers/message_handler.py`**
   ```python
   class MessageHandler:
       def decode_message(self, envelope):
           """Decode and validate Pub/Sub message."""

       def normalize_format(self, data):
           """Convert GCS/Scraper formats to standard format."""
   ```

2. **Create `handlers/batch_detector.py`**
   ```python
   class BatchDetector:
       def is_batch_trigger(self, data) -> bool:
           """Check if message is a batch trigger."""

       def get_batch_type(self, data) -> str:
           """Return batch type: 'espn', 'br', 'oddsapi', or None."""
   ```

3. **Create `handlers/espn_batch_handler.py`**
   ```python
   class ESPNBatchHandler:
       def process(self, data, firestore_client):
           """Process ESPN roster batch with Firestore locking."""
   ```

4. **Create `handlers/br_batch_handler.py`**
   ```python
   class BRBatchHandler:
       def process(self, data, firestore_client):
           """Process Basketball Reference roster batch."""
   ```

5. **Create `handlers/oddsapi_batch_handler.py`**
   ```python
   class OddsAPIBatchHandler:
       def process(self, data, firestore_client):
           """Process OddsAPI game lines and props batch."""
   ```

6. **Create `handlers/file_processor.py`**
   ```python
   class FileProcessor:
       def process(self, data, processor_map):
           """Route to appropriate processor and execute."""
   ```

7. **Simplify `process_pubsub()`**
   ```python
   def process_pubsub():
       handler = MessageHandler()
       data = handler.decode_message(request.get_json())
       data = handler.normalize_format(data)

       detector = BatchDetector()
       if detector.is_batch_trigger(data):
           batch_type = detector.get_batch_type(data)
           if batch_type == 'espn':
               return ESPNBatchHandler().process(data, firestore_client)
           elif batch_type == 'br':
               return BRBatchHandler().process(data, firestore_client)
           elif batch_type == 'oddsapi':
               return OddsAPIBatchHandler().process(data, firestore_client)

       return FileProcessor().process(data, PROCESSOR_MAP)
   ```

---

## Function 2: extract_opts_from_path() (429 lines)

**Lines:** 1260-1688

**Current State:** Giant if/elif chain matching 20+ path patterns and extracting metadata.

**Target Structure:**
```
data_processors/raw/
├── main_processor_service.py
├── path_extractors/
│   ├── __init__.py
│   ├── base.py                  # Base extractor class
│   ├── registry.py              # Extractor registry
│   ├── bdl_extractors.py        # Ball-Don't-Lie paths
│   ├── nba_extractors.py        # NBA.com paths
│   ├── espn_extractors.py       # ESPN paths
│   ├── odds_extractors.py       # OddsAPI, BettingPros paths
│   ├── bigdataball_extractors.py # BigDataBall paths
│   └── mlb_extractors.py        # MLB paths
```

**Extraction Pattern:**

1. **Create `path_extractors/base.py`**
   ```python
   from abc import ABC, abstractmethod
   import re

   class PathExtractor(ABC):
       @abstractmethod
       def matches(self, path: str) -> bool:
           """Check if this extractor handles the path."""

       @abstractmethod
       def extract(self, path: str) -> dict:
           """Extract options from the path."""
   ```

2. **Create `path_extractors/registry.py`**
   ```python
   class ExtractorRegistry:
       def __init__(self):
           self._extractors = []

       def register(self, extractor: PathExtractor):
           self._extractors.append(extractor)

       def extract_opts(self, path: str) -> dict:
           for extractor in self._extractors:
               if extractor.matches(path):
                   return extractor.extract(path)
           raise ValueError(f"No extractor for path: {path}")
   ```

3. **Create domain-specific extractors**
   ```python
   # path_extractors/bdl_extractors.py
   class BDLStandingsExtractor(PathExtractor):
       PATTERN = re.compile(r'bdl/standings/(\d{4}-\d{2}-\d{2})/')

       def matches(self, path: str) -> bool:
           return bool(self.PATTERN.search(path))

       def extract(self, path: str) -> dict:
           match = self.PATTERN.search(path)
           return {'date': match.group(1), 'type': 'standings'}
   ```

4. **Simplify `extract_opts_from_path()`**
   ```python
   from .path_extractors import create_registry

   _registry = create_registry()

   def extract_opts_from_path(path: str) -> dict:
       return _registry.extract_opts(path)
   ```

---

## Testing Strategy

```bash
# 1. Run existing processor tests
python -m pytest tests/unit/data_processors/raw/ -v

# 2. Test path extraction with known paths
python -c "
from data_processors.raw.main_processor_service import extract_opts_from_path
print(extract_opts_from_path('nba-stats-scraper/nba_raw/bdl/standings/2026-01-25/data.json'))
"

# 3. Verify service still starts
python -c "from data_processors.raw.main_processor_service import create_app; print('OK')"
```

---

## Success Criteria

- [ ] process_pubsub() reduced to <100 lines
- [ ] Each handler class <150 lines
- [ ] extract_opts_from_path() reduced to <20 lines
- [ ] Each extractor class <50 lines
- [ ] All existing tests pass
- [ ] Path extraction works for all 20+ path patterns

---

## Files to Create

| File | Purpose | Estimated Lines |
|------|---------|-----------------|
| `handlers/__init__.py` | Handler exports | ~20 |
| `handlers/message_handler.py` | Message decode/normalize | ~100 |
| `handlers/batch_detector.py` | Batch detection | ~50 |
| `handlers/espn_batch_handler.py` | ESPN batch | ~100 |
| `handlers/br_batch_handler.py` | BR batch | ~100 |
| `handlers/oddsapi_batch_handler.py` | OddsAPI batch | ~150 |
| `handlers/file_processor.py` | Single file processing | ~100 |
| `path_extractors/__init__.py` | Registry factory | ~30 |
| `path_extractors/base.py` | Base extractor | ~30 |
| `path_extractors/registry.py` | Extractor registry | ~40 |
| `path_extractors/bdl_extractors.py` | BDL paths | ~100 |
| `path_extractors/nba_extractors.py` | NBA.com paths | ~150 |
| `path_extractors/espn_extractors.py` | ESPN paths | ~80 |
| `path_extractors/odds_extractors.py` | Odds paths | ~100 |
| `path_extractors/bigdataball_extractors.py` | BigDataBall | ~80 |
| `path_extractors/mlb_extractors.py` | MLB paths | ~150 |

---

## Notes

- The Firestore locking in batch handlers is critical - preserve exactly
- Path patterns must match exactly as before - test all variants
- Message format normalization handles legacy formats - don't break compatibility
