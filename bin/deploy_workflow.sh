# bin/deploy_workflow.sh
PROJECT=${PROJECT:-nba-props-platform}
REGION=${REGION:-us-west2}
NAME=$1
FILE=$2   # path to yaml

gcloud workflows deploy "$NAME" \
  --source "$FILE" \
  --service-account workflow-sa@${PROJECT}.iam.gserviceaccount.com \
  --location ${REGION}
