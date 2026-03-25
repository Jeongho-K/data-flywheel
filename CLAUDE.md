# MLOps Pipeline - Project Rules

## Overview

General-purpose CV MLOps pipeline template for on-premises deployment.
Supports image classification, detection, and segmentation workflows.

## Architecture (6 Layers)

```
Layer 6: Monitoring    — Evidently, Prometheus, Grafana
Layer 5: Serving       — Nginx, Gunicorn, Uvicorn, FastAPI
Layer 4: Orchestration — Prefect
Layer 3: Training      — PyTorch, MLflow
Layer 2: Data Pipeline — DVC, CleanLab, CleanVision
Layer 1: Infrastructure— Docker Compose, PostgreSQL, MinIO, Redis
```

**Layer dependency rule:** Upper layers may only reference lower layers. Never import upward.

## Tech Stack (Pinned Versions)

| Component | Version / Image |
|---|---|
| PostgreSQL | `postgres:16.6-alpine` |
| MinIO | `minio/minio:RELEASE.2025-09-07T16-13-09Z` |
| MLflow | `ghcr.io/mlflow/mlflow:v3.10.1` |
| Prefect | `prefecthq/prefect:3.6.23-python3.11` |
| Redis | `redis:7.4-alpine` |
| Nginx | `nginx:1.28.2-alpine` |
| Prometheus | `prom/prometheus:v3.10.0` |
| Grafana | `grafana/grafana-oss:12.4.1` |
| Python | 3.11.x |
| PyTorch | 2.6.x |
| CUDA | `nvidia/cuda:12.6.3-runtime-ubuntu22.04` |

## Coding Standards

- **Python**: 3.11+, type hints required on all function signatures
- **Linter/Formatter**: Ruff (config in `pyproject.toml`)
- **Config management**: Pydantic Settings (`.env` → typed dataclass)
- **Docstrings**: Google style, in English
- **Logging**: `logging` module only, never `print()`
- **No hardcoded credentials**: All secrets via environment variables

## Docker Rules

- Pin base image versions — never use `:latest`
- Multi-stage builds for all custom images
- Prefer official Docker images when available
- GPU support: `deploy.resources.reservations.devices` in compose
- Each service has its own Dockerfile in `docker/`

## Language Rules

- **Code** (variables, functions, classes, comments, docstrings): English
- **Documentation** (`docs/*.md`, `README.md`): Korean
- **Commit messages**: English, conventional commits (`feat:`, `fix:`, `docs:`, `infra:`, `test:`, `refactor:`)
- **Branches**: `feature/phase-{N}-{name}`, `fix/{description}`

## Git Workflow

- Phase-based branches → PR to main
- PR review cycle (모든 단계 통과 시 머지):
  1. **코드 리뷰** — code-reviewer, silent-failure-hunter, comment-analyzer, code-simplifier 병렬 실행
  2. 발견된 이슈 수정 → 재리뷰 (모든 리뷰어 통과할 때까지 반복)
  3. **QC 테스트** — 실제 서비스를 올리고 유저 입장에서 E2E 동작 검증 (서비스 기동, API 호출, UI 접속 등)
  4. QC 이슈 발견 시 수정 → 재 QC (통과할 때까지 반복)
  5. 모든 리뷰 + QC 통과 → 머지

## Testing

- **Runner**: pytest
- **Unit tests**: `tests/unit/` — no external dependencies
- **Integration tests**: `tests/integration/` — requires running Docker services
- **E2E tests**: `tests/e2e/` — full pipeline tests
- **Naming**: `test_<module>_<behavior>.py`

## Documentation

- Architecture diagrams: Mermaid syntax
- README.md: lightweight (intro + quickstart + docs links only)
- Detailed docs in `docs/` directory, one file per layer
- Update relevant docs when changing configuration

## Directory Structure

```
MLOps-Pipeline/
├── CLAUDE.md                 # This file
├── README.md                 # Project intro + docs links (Korean)
├── docker-compose.yml        # All services
├── docker-compose.override.yml # GPU/dev overrides
├── .env.example              # Environment variable template
├── Makefile                  # Common commands
├── pyproject.toml            # Python tooling config
├── docker/                   # Dockerfiles per service
├── src/                      # Source code (by layer)
│   ├── data/                 # Layer 2: DVC, validation, preprocessing
│   ├── training/             # Layer 3: models, trainers, configs
│   ├── serving/              # Layer 5: FastAPI, nginx, gunicorn
│   ├── orchestration/        # Layer 4: Prefect flows, tasks
│   └── monitoring/           # Layer 6: Evidently, Prometheus, Grafana
├── configs/                  # Service configuration files
├── tests/                    # unit, integration, e2e
├── scripts/                  # Setup and utility scripts
├── examples/                 # Example templates
└── docs/                     # Documentation (Korean)
```

## Make Commands

| Command | Description |
|---|---|
| `make up` | Start all services |
| `make down` | Stop all services |
| `make down-v` | Stop and destroy volumes |
| `make ps` | Show service status |
| `make logs SERVICE=mlflow` | Tail service logs |
| `make seed` | Initialize MinIO buckets and MLflow experiments |
| `make lint` | Run Ruff linter |
| `make format` | Run Ruff formatter |
| `make test` | Run unit tests |
| `make test-integration` | Run integration tests |
| `make test-e2e` | Run end-to-end tests |
| `make verify` | Run Phase verification checks |
