# NBA Platform Docker Strategy

## Overview

Our NBA analytics platform uses a **multi-service containerization strategy** with three main services:

- **Scrapers** - Data collection from APIs and websites
- **Processors** - ETL, data transformation, and validation  
- **Report Generators** - Analytics reports and dashboards

## Architecture Principles

### 🏗️ **Layered Build Strategy**
```
Base Image (nba-base)
├── Scrapers (nba-scrapers)
├── Processors (nba-processors)  
└── Report Gen (nba-reportgen)
```

### 📦 **Service Independence**
- Each service has its own `Dockerfile` and `requirements.txt`
- Services can be built, deployed, and scaled independently
- Shared utilities live in `shared/` directory

### 🔄 **Flexible Entry Points**
Each container can run different modules using command arguments:
```bash
# Same image, different services
docker run nba-scrapers events --serve
docker run nba-scrapers odds --serve  
docker run nba-scrapers bdl-games --serve
```

## Directory Structure

```
nba-stats-scraper/
├── docker/
│   ├── base.Dockerfile              # Foundation for all services
│   └── cloudbuild.yaml             # Multi-service CI/CD
├── shared/                          # Common code and utilities
│   ├── config/                     # Team mappings, constants
│   ├── utils/                      # Helper functions
│   └── requirements.txt            # Core dependencies
├── scrapers/
│   ├── Dockerfile                  # Scraper container
│   ├── requirements.txt            # Scraper-specific deps
│   ├── docker-entrypoint.sh        # Flexible startup script
│   └── ...                         # Scraper modules
├── processors/
│   ├── Dockerfile                  # Processor container
│   ├── requirements.txt            # Processing deps (pandas, etc.)
│   ├── docker-entrypoint.sh        # Processor startup
│   └── ...                         # Processing modules
└── reportgen/
    ├── Dockerfile                  # Report generator container
    ├── requirements.txt            # Visualization deps
    ├── docker-entrypoint.sh        # Report startup
    └── ...                         # Report modules
```

## Container Characteristics

### 🔍 **Base Image (nba-base)**
- **Purpose**: Common foundation for all services
- **Contains**: Python 3.11, basic system deps, shared utilities
- **Size**: ~200MB
- **Dependencies**: Core libraries (requests, google-cloud-*, logging)

### 🕷️ **Scrapers Container**
- **Purpose**: Data collection from external APIs
- **Special Features**: Playwright for browser automation, stealth capabilities
- **Typical Size**: ~400MB (includes browser)
- **Entry Points**: Events, odds, rosters, schedules
- **Scaling**: Horizontal, request-based

### ⚙️ **Processors Container** 
- **Purpose**: ETL and data transformation
- **Special Features**: pandas, numpy, BigQuery clients
- **Typical Size**: ~350MB  
- **Entry Points**: Event processing, data validation, ETL pipelines
- **Scaling**: Based on pub/sub queue depth

### 📊 **Report Generator Container**
- **Purpose**: Analytics and visualization
- **Special Features**: matplotlib, plotly, PDF generation
- **Typical Size**: ~300MB
- **Entry Points**: Player reports, daily summaries, dashboards
- **Scaling**: On-demand execution

## Build Process

### 🏗️ **Sequential Build Strategy**
1. **Build base image** (shared foundation)
2. **Build service images in parallel** (using base)  
3. **Push all images** to Container Registry
4. **Deploy to Cloud Run** (optional)

### ⚡ **Optimization Features**
- **Layer caching** - Base image rarely changes
- **Parallel builds** - Services build simultaneously  
- **Multi-stage builds** - Smaller production images
- **Health checks** - Built into every container

## Local Development

### 🚀 **Quick Start**
```bash
# Build all images
./bin/build_all_images.sh

# Run scrapers locally
docker run -p 8080:8080 nba-scrapers events --serve

# Test health endpoint
curl http://localhost:8080/health
```

### 🔧 **Development Workflow**
```bash
# Build specific service during development
docker build -f scrapers/Dockerfile -t nba-scrapers:dev .

# Mount code for live editing
docker run -v $(pwd):/app nba-scrapers:dev events --debug

# Use docker-compose for full stack
docker-compose up scrapers processors
```

## Production Deployment

### ☁️ **Cloud Run Deployment**
- **Auto-scaling** based on request volume
- **Regional deployment** for low latency
- **IAM integration** with service accounts
- **Secret management** via Secret Manager

### 📈 **Monitoring & Observability**
- **Structured logging** to Cloud Logging  
- **Custom metrics** via Cloud Monitoring
- **Health checks** for service discovery
- **Distributed tracing** across services

## Security Considerations

### 🔒 **Container Security**
- **Non-root user** in all containers
- **Minimal base image** (Python slim)
- **No secrets in images** (Secret Manager integration)
- **Read-only file system** where possible

### 🛡️ **Runtime Security**  
- **Service accounts** with minimal permissions
- **VPC integration** for network isolation
- **Binary authorization** for verified images
- **Vulnerability scanning** in CI/CD

## Cost Optimization

### 💰 **Image Size Management**
- **Multi-stage builds** to exclude build tools
- **Shared base layer** reduces total storage
- **Layer caching** speeds up builds
- **Unused dependency cleanup**

### ⚡ **Runtime Efficiency**
- **Right-sized containers** (CPU/memory)
- **Cold start optimization** with smaller images
- **Request batching** where appropriate
- **Auto-scaling policies** to minimize idle time

## Future Considerations

### 🔮 **Potential Optimizations**
- **Distroless images** for even smaller size
- **Multi-arch builds** (ARM64 for cost savings)
- **Service mesh** for advanced traffic management
- **GitOps deployment** with ArgoCD

### 📊 **Monitoring Metrics**
- Build time trends
- Image size over time  
- Container startup time
- Resource utilization patterns

---

**Next Steps:**
1. Read [Cloud Run Deployment Guide](cloud-run-deployment.md)
2. Check [Development Workflow](development-workflow.md)  
3. Review [Troubleshooting Guide](troubleshooting.md)

