# Prefect worker image that registers the continuous-training deployment
# on startup and then serves the work queue. Uses the same prefect base
# as the prefect-server service to guarantee protocol compatibility.

FROM prefecthq/prefect:3.6.23-python3.11

WORKDIR /app

# Install uv for fast dependency resolution, then add the runtime libs
# needed by the training flow + tasks. torch/torchvision are kept here
# because the flow performs real model training end-to-end.
RUN pip install --no-cache-dir --upgrade pip uv \
    && uv pip install --system --no-cache-dir \
        mlflow>=3.10 \
        torch>=2.6 \
        torchvision>=0.21 \
        boto3>=1.35 \
        pydantic-settings>=2.7 \
        Pillow>=11.0 \
        prometheus-client>=0.21 \
        httpx>=0.27 \
        numpy>=1.26

# Application source so ``python -m src.core.orchestration.flows...``
# resolves against an installed-style module layout.
COPY src/ ./src/

# ``.serve()`` is blocking — it registers the deployment on the Prefect
# server and then listens for triggers. The container therefore runs as
# a long-lived service, restarted by compose on failure.
ENTRYPOINT ["python", "-m", "src.core.orchestration.flows.continuous_training_serve"]
