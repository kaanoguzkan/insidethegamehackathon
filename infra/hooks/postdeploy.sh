#!/bin/sh
# Runs after `azd deploy`: things that need the deployed code to exist.
#  1. The simulator job runs the Brain's image; Bicep only knows a placeholder, so point the job at the image just deployed.
#  2. Subscribe the `analyze` Function to the tracking chunks: Event Grid BlobCreated events in the `frames` container.
set -eu
RG="rg-${AZURE_ENV_NAME}"

az containerapp job update -g "$RG" -n "caj-${AZURE_ENV_NAME}-sim" --image "$SERVICE_BRAIN_IMAGE_NAME" -o none

FUNC=$(az functionapp list -g "$RG" --query "[0].name" -o tsv)
FUNC_ID=$(az functionapp show -g "$RG" -n "$FUNC" --query id -o tsv)
az eventgrid system-topic event-subscription create -g "$RG" --system-topic-name "evgt-${AZURE_ENV_NAME}-storage" -n analyze-chunks \
  --endpoint-type azurefunction --endpoint "$FUNC_ID/functions/analyze" \
  --included-event-types Microsoft.Storage.BlobCreated --subject-begins-with /blobServices/default/containers/frames/blobs/ -o none
echo "tracking chunks now trigger the analyze Function"
