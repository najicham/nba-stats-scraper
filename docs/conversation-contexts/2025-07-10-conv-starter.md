# NBA Analytics Platform - Conversation Context

## 🏀 Project Overview
**Goal:** NBA analytics platform providing data-driven insights for player prop bets  
**Status:** ✅ MVP Complete - Containerized microservices with working data pipeline  
**Budget:** ~$15/month target for production  

## 🏗️ Current Architecture
```
External APIs → Scrapers → GCS → Processors → BigQuery → ReportGen → Firestore → Frontend
                   ↓            ↓              ↓              ↓
              (Cloud Run)  (Raw JSON)   (SQL Analytics)  (Hot Data)
```

## ✅ What's Working Now
- **Containerized microservices**: 3 services (scrapers, processors, reportgen) running via Docker
- **Data collection**: Successfully pulling real NBA data from Odds API (16+ events per request)
- **Scrapers**: Events scraper + Player props scraper with Flask APIs
- **Local development**: Complete Docker environment with PostgreSQL, Redis, MinIO
- **Monitoring**: Sentry integration + comprehensive debugging tools
- **Shell workflow**: One-command environment setup (`nba-setup`)
- **Documentation**: Complete milestone summaries and monitoring guides

## 🛠️ Technology Stack
- **Containers**: Docker + docker-compose (local), Cloud Run (production)
- **Languages**: Python + Flask for microservices
- **Data Storage**: GCS (raw data), BigQuery (analytics), Firestore (serving)
- **Local Dev**: PostgreSQL, Redis, MinIO for development parity
- **Monitoring**: Sentry for error tracking and performance monitoring
- **APIs**: The Odds API (prop bets), Ball Don't Lie API (NBA stats)

## 📊 Real Data Examples
**Sample successful scraper response:**
```json
{
  "status": "success",
  "message": "Events scraping completed successfully", 
  "scraper": "odds_api_historical_events",
  "data_summary": {
    "rowCount": 16,
    "sport": "basketball_nba",
    "snapshot": "2025-01-08T23:55:38Z"
  }
}
```

## 📁 Key Project Files
- **Main containers**: `docker-compose.dev.yml` 
- **Scrapers**: `scrapers/oddsapi/oddsa_events_his.py`, `oddsa_player_props_his.py`
- **Monitoring**: `monitoring/scripts/system_status.sh`
- **Documentation**: `docs/summaries/2025-07-10-mvp-containerized-microservices.md`
- **Development tools**: Shell integration with `nba-setup`, `nba-status`, etc.

## 🚀 Development Workflow
```bash
nba-setup          # Complete environment activation
nba-up             # Start all Docker containers  
nba-test-events    # Test NBA data scraping
nba-status         # Check system health
nba-data           # View scraped data files
```

## 🎯 Current Development Phase
**Last Milestone:** MVP Containerized Microservices (July 10, 2025)
**Next Phase:** [UPDATE THIS - BigQuery Integration / Production Deployment / Frontend / etc.]

