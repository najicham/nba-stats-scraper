# Getting Started

Welcome to the NBA Props Platform! This guide will help you get set up and productive.

## Prerequisites

- Python 3.12+
- Docker
- gcloud CLI
- Access to GCP project: `nba-props-platform`

## Initial Setup

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd nba-stats-scraper
   ```

2. **Set up Python environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

3. **Configure GCP:**
   ```bash
   gcloud auth login
   gcloud config set project nba-props-platform
   gcloud auth application-default login
   ```

4. **Set up monitoring tools:**
   ```bash
   chmod +x monitoring/scripts/nba-monitor
   export PATH="$PATH:$(pwd)/monitoring/scripts"
   ```

5. **Test your setup:**
   ```bash
   nba-monitor status yesterday
   ```

## Project Structure

```
nba-stats-scraper/
├── scrapers/           # Scraping external APIs
├── data_processors/    # Processing data into BigQuery
├── workflows/          # Cloud Workflow definitions
├── monitoring/         # Monitoring tools and scripts
├── shared/             # Shared utilities
└── docs/              # Documentation (you are here!)
```

## Next Steps

1. Read [../architecture/system-overview.md](../architecture/system-overview.md)
2. Review [development-workflow.md](development-workflow.md)
3. Try [scraper-testing-guide.md](scraper-testing-guide.md)
4. Check out [../operations/README.md](../operations/README.md) for monitoring

## Getting Help

- Check [Wiki: Troubleshooting](https://your-wiki-url/troubleshooting)
- Review recent [../investigations/](../investigations/)
- Ask the team on Slack

**Last Updated:** $(date +%Y-%m-%d)
