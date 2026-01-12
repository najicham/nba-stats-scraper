# Default Procfile - use SERVICE env var to select which service to run
# Deploy with: gcloud run deploy SERVICE_NAME --source=. --set-env-vars="SERVICE=coordinator"

web: if [ "$SERVICE" = "coordinator" ]; then gunicorn --config predictions/coordinator/gunicorn_config.py predictions.coordinator.coordinator:app; elif [ "$SERVICE" = "worker" ]; then gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 300 predictions.worker.worker:app; else echo "Set SERVICE=coordinator or SERVICE=worker"; fi
