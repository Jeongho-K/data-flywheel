#!/bin/bash
# Initialize DVC and configure MinIO as remote storage.
# Run once after `pip install -r requirements.txt` and `make up`.

set -eu

echo "=== DVC Setup ==="

# Initialize DVC if not already initialized
if [ ! -d ".dvc" ]; then
    echo "[1/3] Initializing DVC..."
    dvc init
else
    echo "[1/3] DVC already initialized. Skipping."
fi

# Configure MinIO as the default remote
echo "[2/3] Configuring MinIO remote..."
dvc remote add -d minio-remote s3://dvc-storage 2>/dev/null || {
    echo "  Remote 'minio-remote' already exists. Updating configuration."
    dvc remote modify minio-remote url s3://dvc-storage
}

dvc remote modify minio-remote endpointurl http://localhost:${MINIO_API_PORT:-9000}
dvc remote modify minio-remote access_key_id ${MINIO_ROOT_USER:-minioadmin}
dvc remote modify minio-remote secret_access_key ${MINIO_ROOT_PASSWORD:-minioadmin123}
dvc remote modify minio-remote use_ssl false

echo "[3/3] DVC configuration complete."
echo ""
echo "  Remote: minio-remote → s3://dvc-storage"
echo "  Endpoint: http://localhost:${MINIO_API_PORT:-9000}"
echo ""
echo "Usage:"
echo "  dvc add data/raw/<dataset>     # Track dataset"
echo "  dvc push                        # Upload to MinIO"
echo "  dvc pull                        # Download from MinIO"
