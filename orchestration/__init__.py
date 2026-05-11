"""
orchestration package

Orchestration system for NBA Props Platform.

Local Modules (Phase 1 workflow orchestration):
- config_loader: Load and validate workflows.yaml
- master_controller: Decision engine (evaluates all workflows)
- workflow_executor: Execution manager (runs scrapers)
- cleanup_processor: Self-healing (republish missed messages)
- schedule_locker: Daily schedule generation (Grafana monitoring)
- parameter_resolver: Resolve scraper params from workflow context

Cloud Functions (Phase transition orchestration):
- cloud_functions/phase2_to_phase3: Tracks Phase 2 completion, triggers Phase 3
- cloud_functions/phase3_to_phase4: Tracks Phase 3 completion, triggers Phase 4

IMPORTANT — keep this file empty of eager imports. Cloud Functions that only
need `orchestration.parameter_resolver` (e.g. backfill-pubsub-subscriber) ship
the package WITHOUT the master_controller/workflow_executor heavy deps. Eager
re-exports here would re-introduce the "No module named 'requests'/pandas/etc."
failure mode that the deploy-time empty-init shim was created to work around.
Every production caller already uses `from orchestration.<submodule> import …`
(verified 2026-05-11 — zero `from orchestration import …` call sites in
non-test code), so the re-exports were dead surface area anyway.
"""

# Intentionally no module-level imports. See note above.
