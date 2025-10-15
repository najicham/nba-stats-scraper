# NBA Props Platform Documentation

**Quick Links:**
- 📖 **[Wiki](https://your-wiki-url)** - Operational guides, troubleshooting, daily procedures
- 💻 **[GitHub](.)** - Technical docs, architecture, development guides

## Documentation Structure

This repository contains **technical and development documentation**. For operational guides and how-tos, see the **[Wiki](https://your-wiki-url)**.

### 📁 What's Where

```
docs/
├── architecture/        → System design and architecture decisions
├── development/         → Development workflows and guides
├── operations/          → Links to wiki for operational guides
├── reference/           → Historical implementation notes
└── archive/             → Old/outdated documentation
```

---

## 🏗️ Architecture (`architecture/`)

**Technical system design and decisions**

- **[system-architecture.md](architecture/system-architecture.md)** - Complete system architecture
- **[service-architecture.md](architecture/service-architecture.md)** - Cloud Run services
- **[infrastructure-decisions.md](architecture/infrastructure-decisions.md)** - Infrastructure choices

**When to read:**
- Understanding how the system works
- Making architectural decisions
- Onboarding engineers

---

## 💻 Development (`development/`)

**Development workflows and practices**

- **[development-workflow.md](development/development-workflow.md)** - Development process
- **[dev-cheatsheet.md](development/dev-cheatsheet.md)** - Quick command reference
- **[docker-strategy.md](development/docker-strategy.md)** - Docker & containerization
- **[cloud-run-deployment.md](development/cloud-run-deployment.md)** - Deployment procedures
- **[scraper-testing-guide.md](development/scraper-testing-guide.md)** - Testing scrapers

**When to read:**
- Writing new scrapers/processors
- Deploying changes
- Setting up development environment

---

## ⚙️ Operations (`operations/`)

**For operational guides, see the [Wiki](https://your-wiki-url)**

The wiki contains:
- 📊 **Workflow Monitoring** - Daily monitoring and status checks
- 🔧 **Troubleshooting** - Common issues and fixes
- 🚨 **Alerts** - Understanding and managing alerts
- 📋 **Runbooks** - Step-by-step operational procedures

**Local operations docs:**
- **[monitoring.md](operations/monitoring.md)** → See [Wiki: Monitoring Guide](https://your-wiki-url/monitoring)
- **[troubleshooting.md](operations/troubleshooting.md)** → See [Wiki: Troubleshooting](https://your-wiki-url/troubleshooting)

**When to read:**
- Daily monitoring
- Investigating issues
- On-call procedures

---

## 📚 Reference (`reference/`)

**Historical implementation notes and detailed specs**

Organized by topic:
- **[backfill/](reference/backfill/)** - Backfill strategies and implementations
- **[scrapers/](reference/scrapers/)** - Scraper development history
- **[processors/](reference/processors/)** - Processor implementations
- **[workflows/](reference/workflows/)** - Workflow configurations
- **[schedule/](reference/schedule/)** - Scheduling strategies

**When to read:**
- Understanding why something was built a certain way
- Looking up historical context
- Learning from past implementations

---

## 📦 Archive (`archive/`)

**Old and outdated documentation**

Kept for historical reference but no longer actively maintained.

---

## Quick Start Guides

### For New Developers
1. Read [architecture/system-architecture.md](architecture/system-architecture.md)
2. Read [development/development-workflow.md](development/development-workflow.md)
3. Set up your environment using [development/dev-cheatsheet.md](development/dev-cheatsheet.md)
4. Review [Wiki: Monitoring Guide](https://your-wiki-url/monitoring) for daily operations

### For Operators/On-Call
1. Go to [Wiki](https://your-wiki-url) - this is your main resource
2. Bookmark [Wiki: Troubleshooting](https://your-wiki-url/troubleshooting)
3. Set up monitoring tools: [Wiki: Monitoring Setup](https://your-wiki-url/monitoring)
4. Review [Wiki: Runbooks](https://your-wiki-url/runbooks)

### For Product/Business
1. Read [architecture/system-architecture.md](architecture/system-architecture.md) - high-level overview
2. See [Wiki: System Overview](https://your-wiki-url/overview) for non-technical explanation
3. Review [Wiki: Data Flow](https://your-wiki-url/data-flow) to understand the pipeline

---

## 🔄 Documentation Maintenance

### Where to Add New Documentation

**Add to GitHub (`docs/`):**
- Architecture decisions and changes
- Development workflow changes
- New service documentation
- Technical specifications
- API schemas

**Add to Wiki:**
- Operational procedures
- Troubleshooting guides
- Monitoring dashboards
- Alert runbooks
- How-to guides

### Keeping Docs Current

**GitHub Docs:**
- Update when code architecture changes
- Review quarterly
- Keep focused on "how it works"

**Wiki:**
- Update when operations change
- Review monthly
- Keep focused on "how to use it"

---

## 🛠️ Reorganization

This documentation was recently reorganized (2025-10-14) to separate:
- **Technical docs** (in GitHub) - for developers
- **Operational docs** (in Wiki) - for operators/users

To run the reorganization script:
```bash
./docs/reorganize_docs.sh
```

---

## 📞 Need Help?

- **Development questions:** Check `development/` docs
- **Architecture questions:** Check `architecture/` docs
- **Operational issues:** Check [Wiki](https://your-wiki-url)
- **Can't find it:** Search both GitHub docs and Wiki

---

**Last Updated:** 2025-10-14
