# Default Procfile - use SERVICE env var to select which service to run
# Deploy with: gcloud run deploy SERVICE_NAME --source=. --set-env-vars="SERVICE=coordinator"
# For analytics: gcloud run deploy nba-phase3-analytics-processors --source=. --set-env-vars="SERVICE=analytics"

web: if [ "$SERVICE" = "coordinator" ]; then gunicorn --config predictions/coordinator/gunicorn_config.py predictions.coordinator.coordinator:app; elif [ "$SERVICE" = "worker" ]; then gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 300 predictions.worker.worker:app; elif [ "$SERVICE" = "analytics" ]; then gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 600 data_processors.analytics.main_analytics_service:app; else echo "Set SERVICE=coordinator, worker, or analytics"; fi
