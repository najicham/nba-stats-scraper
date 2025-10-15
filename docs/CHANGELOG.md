# Changelog

All notable changes to the NBA Props Platform documentation and monitoring.

## [2025-10-14] - Documentation & Monitoring Setup

### Added
- Complete documentation reorganization
- New monitoring tool: `nba-monitor`
- Daily status checking workflow
- Comprehensive troubleshooting guide
- System architecture documentation
- Documentation organization guide

### Fixed
- Late-night-recovery workflow GCS status writing bug

### Changed
- Renamed dated files from YY-MM-DD to YYYY-MM-DD format
- Reorganized docs into architecture/development/operations structure
- Paused all Cloud Scheduler jobs for debugging

### Documentation
- Created 7 new documentation files
- Created 5 monitoring Python scripts
- Added READMEs for shared/utils and monitoring/scripts

## [Future]

### To Do
- Fix remaining "No Data Found" errors in scrapers
- Investigate proxy exhaustion issues
- Re-enable paused schedulers after testing
- Set up automated daily summary emails
