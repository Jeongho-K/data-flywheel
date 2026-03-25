#!/bin/bash
# Initialize MLOps Pipeline with default MLflow experiments and verify service health.
# Run after `make up` when all services are healthy.

set -e

echo "=== MLOps Pipeline Seed Data ==="

# Check that required services are healthy
echo "[1/3] Checking services..."
for svc in postgres minio mlflow prefect-server redis; do
    if ! docker compose ps "$svc" --format "{{.Status}}" 2>/dev/null | grep -q "healthy"; then
        echo "Error: $svc is not healthy. Run 'make up' first and wait for services to start."
        exit 1
    fi
done
echo "  All required services are healthy."

# Create MLflow experiment
echo "[2/3] Creating MLflow experiment..."
docker compose exec mlflow mlflow experiments create --experiment-name "default-classification" 2>/dev/null || {
    echo "  MLflow experiment already exists or MLflow not ready. Skipping."
}

echo "[3/3] Verifying services..."
echo "  PostgreSQL: $(docker compose exec postgres psql -U ${POSTGRES_USER:-mlops} -lqt 2>/dev/null | grep -c 'mlflow\|prefect') databases found"
echo "  MinIO: $(curl -sf http://localhost:${MINIO_API_PORT:-9000}/minio/health/live && echo 'OK' || echo 'UNREACHABLE')"
echo "  MLflow: $(curl -sf http://localhost:${MLFLOW_PORT:-5000}/health && echo 'OK' || echo 'UNREACHABLE')"
echo "  Prefect: $(curl -sf http://localhost:${PREFECT_PORT:-4200}/api/health && echo 'OK' || echo 'UNREACHABLE')"
echo "  Redis: $(docker compose exec redis redis-cli ping 2>/dev/null || echo 'UNREACHABLE')"

echo ""
echo "=== Seed complete ==="
