#!/bin/bash
# Quick deployment script for DocFlow Backend to Google Cloud Run

echo "🚀 Deploying DocFlow Backend to Google Cloud Run..."
echo ""
echo "Region: europe-west1"
echo "Service: docflow-backend"
echo ""

gcloud run deploy docflow-backend \
  --source . \
  --region europe-west1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 4Gi \
  --cpu 4 \
  --timeout 300 \
  --max-instances 10 \
  --no-cpu-throttling \
  --set-env-vars "PORT=8080,GCS_PROJECT_ID=rocasoft,FIRESTORE_PROJECT_ID=rocasoft,GCS_BUCKET_NAME=voucher-bucket-1,USE_MOCK_SERVICES=false,SKIP_CLASSIFICATION=false" \
  --update-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Test your deployment:"
echo "curl https://docflow-backend-672967533609.europe-west1.run.app/health"

