# Infrastructure Decisions

## Container Registry: Google Artifact Registry

**Decision**: Use Google Artifact Registry instead of Google Container Registry (gcr.io)

**Date**: July 13, 2025

**Context**: Need a Docker registry to store base images and service images for the sophisticated deployment approach.

### Why Artifact Registry?

1. **Modern**: Google's current recommendation (gcr.io is being deprecated)
2. **Better security**: Advanced vulnerability scanning and IAM integration
3. **Regional**: Images stored in us-west2 (same region as Cloud Run)
4. **Multi-format**: Can store Docker, Maven, npm, Python packages
5. **Future-proof**: Won't need to migrate later

### Repository Structure

```
us-west2-docker.pkg.dev/nba-props-platform/pipeline/
├── nba-base:latest                    # Base image with shared dependencies
├── nba-scrapers:dev-143052           # Service images with timestamps
├── nba-scrapers:dev-144521           # Multiple versions for rollback
└── nba-scrapers:latest               # Latest stable version
```

### Setup Commands

```bash
# One-time repository creation
gcloud artifacts repositories create pipeline \
  --repository-format=docker \
  --location=us-west2 \
  --description="NBA Analytics Docker images"
```

### Integration

- **Cloud Build**: Automatically builds and pushes images
- **Cloud Run**: Pulls images for deployment
- **Terraform**: Infrastructure managed as code (see `infra/artifact_registry.tf`)

### Benefits Realized

- **Speed**: Base image cached, service builds ~2min instead of ~3min
- **Security**: Non-root containers, vulnerability scanning
- **Reliability**: Rollback to previous timestamped versions
- **DevOps**: Proper separation of infrastructure and application concerns
