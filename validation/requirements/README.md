# Validator Requirements Directory

This directory contains requirements documents for building data validators.

## Structure

```
requirements/
├── README.md                          # This file
├── in_progress/                       # Requirements currently being filled out
│   └── [processor]_requirements.md
└── completed/                         # Completed requirements (validators built)
    └── [processor]_requirements.md
```

## How to Create a New Validator

### 1. Copy the Template
```bash
cp ../VALIDATOR_REQUIREMENTS_TEMPLATE.md \
   in_progress/[your_processor]_requirements.md
```

### 2. Fill Out the Template
See `../HOW_TO_USE_VALIDATOR_TEMPLATE.md` for detailed instructions.

### 3. Submit to Validation Team
Once complete, share your file with the validation team.

### 4. Move to Completed
After validator is built and tested:
```bash
mv in_progress/[processor]_requirements.md \
   completed/[processor]_requirements.md
```

## Examples

See these completed examples:
- `completed/odds_game_lines_requirements.md` - API data with multiple bookmakers
- `completed/espn_scoreboard_requirements.md` - Scraper data with cross-validation

## Quick Start Commands

**Create new requirements file:**
```bash
./new_requirements.sh [processor_name]
```

**Check requirements status:**
```bash
ls in_progress/    # Being worked on
ls completed/      # Validators built
```

## Priority Sections

**Must fill (to start):**
1. BigQuery table name and schema
2. GCS paths and file patterns
3. Sample data (10 rows)

**Should fill (for complete validator):**
4. Expected coverage
5. Required fields and ranges
6. Cross-validation sources

**Nice to have:**
7. Known issues
8. Success criteria
9. Processor details

## Questions?

- See: `../HOW_TO_USE_VALIDATOR_TEMPLATE.md`
- Contact: Validation team
