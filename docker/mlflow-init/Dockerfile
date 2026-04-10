# One-shot image that seeds the MLflow Model Registry with a baseline
# ``cv-classifier`` model so the serving API can load a model on first
# startup of a fresh environment. The seed script is idempotent — if a
# registered model already exists it is left untouched.

# --- Stage 1: Builder (install dependencies) ---
FROM python:3.11.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip uv

# Runtime dependencies: the seed script imports ``src.plugins.cv.models``
# which pulls in torch/torchvision, and MLflow client + boto3 for S3.
RUN uv pip install --system --no-cache-dir \
    mlflow>=3.10 \
    torch>=2.6 \
    torchvision>=0.21 \
    boto3>=1.35 \
    pydantic-settings>=2.7

# --- Stage 2: Runtime ---
FROM python:3.11.12-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Application source + seed script. The script imports
# ``src.plugins.cv.models.classifier.create_classifier`` so ``src`` must
# be importable from the working directory.
COPY src/ ./src/
COPY scripts/seed_registry_model.py ./seed_registry_model.py

# Non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser \
    && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["python", "seed_registry_model.py"]
