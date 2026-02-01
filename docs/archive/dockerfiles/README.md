# Archived Dockerfiles

This directory contains Dockerfiles that have been removed from the repository but preserved for reference.

## Dockerfile.multi-service-legacy

**Original location:** `./Dockerfile` (repository root)

**Date archived:** 2026-01-31

**Reason for removal:** Violated Dockerfile organization conventions. Repository root should not contain Dockerfiles.

### What it was

A legacy multi-service Dockerfile that could deploy either:
- Phase 2 raw processors (via `SERVICE=phase2` env var)
- Phase 3 analytics processors (via `SERVICE=analytics` env var)

The service selection was controlled by a `SERVICE` environment variable at runtime.

### Why it was removed

1. **Violated organization conventions** - Service Dockerfiles should live with service code
2. **Error-prone** - Required runtime SERVICE env var, could deploy wrong service
3. **Duplicate functionality** - Service-specific Dockerfiles already existed
4. **Confusing** - Not clear what service would run without checking env vars

### What replaced it

Service-specific Dockerfiles following the standard pattern:

| Old (multi-service) | New (service-specific) |
|---------------------|------------------------|
| `./Dockerfile` with `SERVICE=phase2` | `data_processors/raw/Dockerfile` |
| `./Dockerfile` with `SERVICE=analytics` | `data_processors/analytics/Dockerfile` |

### Migration path

**Old deployment (bin/deploy_phase1_phase2.sh):**
```bash
gcloud run deploy nba-phase2-raw-processors \
  --source=. \
  --update-env-vars=SERVICE=phase2
```

**New deployment:**
```bash
./bin/deploy-service.sh nba-phase2-processors
# Uses data_processors/raw/Dockerfile explicitly
```

### Key differences

The old multi-service Dockerfile:
- Required `SERVICE` env var at runtime
- Had fallback logic and error messages
- Copied both raw and analytics code
- Used complex conditional CMD

The new service-specific Dockerfiles:
- No runtime SERVICE env var needed
- Single purpose, clear intent
- Copy only required code
- Simple CMD pointing to specific service

### Related files

- **Removed:** `./Dockerfile.mlb-worker` - Duplicate of `predictions/mlb/Dockerfile`
- **Moved:** `scripts/backup/Dockerfile.odds_api_*` - To `deployment/dockerfiles/nba/`

### References

- Dockerfile organization: `deployment/dockerfiles/README.md`
- Deployment patterns: `CLAUDE.md` - Deployment Patterns section
- Service-specific Dockerfiles pattern: All current service Dockerfiles follow this

## General Archival Policy

Dockerfiles are archived here when:
1. They violate current organization conventions
2. They duplicate existing functionality
3. They are replaced by better alternatives
4. They may be useful for reference but shouldn't be active

Archived Dockerfiles are:
- Preserved in git history
- Documented in this README
- Not used in any active deployment scripts
- Kept for historical reference only
