
## Creating New Validators

Need a validator for a new data source? Follow these steps:

### 1. Create Requirements Document
```bash
cd validation/requirements
./new_requirements.sh [processor_name]
```

### 2. Fill Out Template
```bash
nano in_progress/[processor_name]_requirements.md
```

See `HOW_TO_USE_VALIDATOR_TEMPLATE.md` for detailed instructions.

### 3. Share with Validation Team
Once complete, validator will be built in ~1-2 hours.

### 4. Test Your Validator
```bash
python -m validation.validators.[layer].[processor_name]_validator \
  --last-days 7 --no-notify
```

---

**Template Location:** `VALIDATOR_REQUIREMENTS_TEMPLATE.md`  
**Usage Guide:** `HOW_TO_USE_VALIDATOR_TEMPLATE.md`  
**Examples:** `requirements/completed/`
