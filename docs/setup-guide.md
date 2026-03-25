# 설치 및 실행 가이드

## 사전 요구사항

| 도구 | 최소 버전 | 설치 확인 |
|------|----------|----------|
| Docker | 24.0+ | `docker --version` |
| Docker Compose | 2.20+ | `docker compose version` |
| Python | 3.11+ | `python --version` |
| Make | - | `make --version` |
| NVIDIA Container Toolkit | - | `nvidia-smi` (GPU 사용 시) |

## 빠른 시작

```bash
# 1. 저장소 클론
git clone https://github.com/Jeongho-K/MLOps-Pipeline.git
cd MLOps-Pipeline

# 2. 환경변수 설정
cp .env.example .env

# 3. 서비스 시작
make up

# 4. 초기 데이터 설정 (MinIO 버킷, MLflow 실험)
make seed

# 5. 상태 확인
make ps
```

## 서비스 접속

| 서비스 | URL | 기본 인증 |
|--------|-----|----------|
| MLflow UI | http://localhost:5000 | 없음 |
| Prefect UI | http://localhost:4200 | 없음 |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin123 |

## 환경변수 설정

`.env.example` 파일을 복사하여 `.env`를 생성하고, 필요에 따라 값을 수정합니다.

상세 환경변수 목록은 [설정 레퍼런스](configuration-reference.md)를 참조하세요.

## GPU 설정

GPU를 사용하려면 NVIDIA Container Toolkit이 설치되어 있어야 합니다.

```bash
# NVIDIA Container Toolkit 설치 확인
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.6.3-runtime-ubuntu22.04 nvidia-smi
```

GPU 서비스는 `docker-compose.override.yml`에서 설정합니다 (Phase 3/5에서 활성화).

## 유용한 명령어

```bash
make up              # 모든 서비스 시작
make down            # 모든 서비스 중지
make down-v          # 서비스 중지 + 볼륨 삭제 (데이터 초기화)
make ps              # 서비스 상태 확인
make logs SERVICE=mlflow  # 특정 서비스 로그 확인
make seed            # 초기 데이터 설정
make lint            # 코드 린트 검사
make format          # 코드 포맷팅
make test            # 단위 테스트 실행
```

## 문제 해결

자주 발생하는 문제와 해결 방법은 [트러블슈팅](troubleshooting.md)을 참조하세요.
