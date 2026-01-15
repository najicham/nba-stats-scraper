# Default Procfile - use SERVICE env var to select which service to run
# Deploy with: gcloud run deploy SERVICE_NAME --source=. --set-env-vars="SERVICE=coordinator"
# For analytics: gcloud run deploy nba-phase3-analytics-processors --source=. --set-env-vars="SERVICE=analytics"
# For precompute: gcloud run deploy nba-phase4-precompute-processors --source=. --set-env-vars="SERVICE=precompute"

web: if [ "$SERVICE" = "coordinator" ]; then gunicorn --config predictions/coordinator/gunicorn_config.py predictions.coordinator.coordinator:app; elif [ "$SERVICE" = "worker" ]; then gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 300 predictions.worker.worker:app; elif [ "$SERVICE" = "analytics" ]; then gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 600 data_processors.analytics.main_analytics_service:app; elif [ "$SERVICE" = "precompute" ]; then gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 600 data_processors.precompute.main_precompute_service:app; else echo "Set SERVICE=coordinator, worker, analytics, or precompute"; fi
