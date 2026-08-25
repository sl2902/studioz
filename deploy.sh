#!/usr/bin/env bash
# deploy.sh — Build and deploy StudioZ backend to Cloud Run
#
# Prerequisites:
#   - gcloud CLI authenticated (gcloud auth login)
#   - Project set (gcloud config set project <PROJECT>)
#   - APIs enabled: Cloud Run, Artifact Registry, Cloud Storage
#
# Usage:
#   ./deploy.sh                     # Full deploy (bucket setup + build + deploy)
#   ./deploy.sh --bucket-only       # Only configure the GCS bucket
#   ./deploy.sh --skip-bucket       # Skip bucket setup (already done)

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────
# Configuration — update these for your environment
# ─────────────────────────────────────────────────────────────────────

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE_NAME="studioz-backend"
GCS_BUCKET="${GCS_BUCKET:-studioz-assets}"
FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-https://studioz.vercel.app}"

# Cloud Run service account (default compute SA unless overridden)
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-}"

# Parallel API key (must be set in env or will fail)
PARALLEL_API_KEY="${PARALLEL_WEB_API_KEY:?Set PARALLEL_WEB_API_KEY environment variable}"

# ─────────────────────────────────────────────────────────────────────
# Parse flags
# ─────────────────────────────────────────────────────────────────────

SKIP_BUCKET=false
BUCKET_ONLY=false

for arg in "$@"; do
  case $arg in
    --skip-bucket) SKIP_BUCKET=true ;;
    --bucket-only) BUCKET_ONLY=true ;;
    *) echo "Unknown flag: $arg"; exit 1 ;;
  esac
done

echo "╔══════════════════════════════════════════════════╗"
echo "║  StudioZ Deployment                             ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Project:  $PROJECT_ID"
echo "║  Region:   $REGION"
echo "║  Service:  $SERVICE_NAME"
echo "║  Bucket:   $GCS_BUCKET"
echo "║  Frontend: $FRONTEND_ORIGIN"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ─────────────────────────────────────────────────────────────────────
# 1. GCS Bucket Setup (public read + CORS for direct browser access)
# ─────────────────────────────────────────────────────────────────────

setup_bucket() {
  echo "── Setting up GCS bucket: gs://$GCS_BUCKET ──"

  # Create bucket if it doesn't exist
  if ! gcloud storage buckets describe "gs://$GCS_BUCKET" &>/dev/null; then
    echo "   Creating bucket..."
    gcloud storage buckets create "gs://$GCS_BUCKET" \
      --location="$REGION" \
      --uniform-bucket-level-access
  else
    echo "   Bucket already exists."
  fi

  # Grant public read access (objectViewer to allUsers)
  # This allows direct browser fetches of storyboard images, audio, and video
  echo "   Setting public read access (allUsers: objectViewer)..."
  gcloud storage buckets add-iam-policy-binding "gs://$GCS_BUCKET" \
    --member=allUsers \
    --role=roles/storage.objectViewer \
    --quiet 2>/dev/null || true

  # Set CORS policy for cross-origin browser requests (video seeking, audio fetch)
  echo "   Configuring CORS policy..."
  CORS_CONFIG=$(mktemp)
  cat > "$CORS_CONFIG" << 'EOF'
[
  {
    "origin": ["https://studioz-seven.vercel.app"],
    "method": ["GET", "HEAD"],
    "responseHeader": [
      "Content-Type",
      "Content-Length",
      "Content-Range",
      "Accept-Ranges",
      "Cache-Control"
    ],
    "maxAgeSeconds": 3600
  }
]
EOF
  gcloud storage buckets update "gs://$GCS_BUCKET" --cors-file="$CORS_CONFIG"
  rm -f "$CORS_CONFIG"

  echo "   ✓ Bucket configured for direct public access with CORS."
  echo ""
}

if [ "$SKIP_BUCKET" = false ]; then
  setup_bucket
fi

if [ "$BUCKET_ONLY" = true ]; then
  echo "Done (bucket-only mode)."
  exit 0
fi

# ─────────────────────────────────────────────────────────────────────
# 2. Build container image via Cloud Build
# ─────────────────────────────────────────────────────────────────────

IMAGE="gcr.io/$PROJECT_ID/$SERVICE_NAME"

echo "── Building container image: $IMAGE ──"
gcloud builds submit . \
  --tag "$IMAGE" \
  --quiet
echo "   ✓ Image built and pushed."
echo ""

# ─────────────────────────────────────────────────────────────────────
# 3. Deploy to Cloud Run
# ─────────────────────────────────────────────────────────────────────

echo "── Deploying to Cloud Run: $SERVICE_NAME ──"

DEPLOY_ARGS=(
  --image "$IMAGE"
  --region "$REGION"
  --platform managed
  --allow-unauthenticated
  --memory 1Gi
  --cpu 1
  --min-instances 1
  --max-instances 3
  --timeout 600
  --set-env-vars "GCP_PROJECT=$PROJECT_ID,GCP_LOCATION=$REGION,GCS_BUCKET=$GCS_BUCKET,STORAGE_BACKEND=gcs,PARALLEL_WEB_API_KEY=$PARALLEL_API_KEY,FRONTEND_ORIGIN=$FRONTEND_ORIGIN"
)

if [ -n "$SERVICE_ACCOUNT" ]; then
  DEPLOY_ARGS+=(--service-account "$SERVICE_ACCOUNT")
fi

gcloud run deploy "$SERVICE_NAME" "${DEPLOY_ARGS[@]}" --quiet

# Get the service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --format="value(status.url)")

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Deployed successfully!"
echo ""
echo "  Backend URL:  $SERVICE_URL"
echo "  API docs:     $SERVICE_URL/docs"
echo "  Bucket:       https://storage.googleapis.com/$GCS_BUCKET/"
echo ""
echo "  Frontend env var to set:"
echo "    VITE_API_BASE_URL=$SERVICE_URL"
echo "═══════════════════════════════════════════════════"
