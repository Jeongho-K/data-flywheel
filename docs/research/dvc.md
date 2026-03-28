# DVC (Data Version Control)

## 1. 핵심 철학/설계 사상

DVC는 **"Git for Data"** 라는 슬로건 아래 설계된 데이터 버전 관리 도구다.
Git이 소스 코드의 변경 이력을 추적하듯, DVC는 대용량 데이터셋과 모델 파일의 변경 이력을 추적한다.

### 핵심 원리

- **포인터 파일 기반 추적**: 실제 데이터 파일은 Git에 커밋하지 않는다. 대신 `.dvc` 확장자의 경량 메타데이터 파일(해시, 크기 등)만 Git에 저장하고, 실제 데이터는 원격 저장소(S3, MinIO, GCS 등)에 보관한다.
- **재현 가능성(Reproducibility)**: `git checkout <commit>` + `dvc pull`만으로 특정 시점의 코드와 데이터를 동시에 복원할 수 있다. 이는 ML 실험의 재현성을 보장하는 핵심 메커니즘이다.
- **Git 워크플로우와의 자연스러운 통합**: 브랜치, 태그, 머지 등 기존 Git 워크플로우를 그대로 활용하면서 데이터 버전 관리를 추가할 수 있다.
- **저장소 독립성**: 원격 저장소로 S3, GCS, Azure Blob, SSH, HDFS, MinIO 등 다양한 백엔드를 지원하며, 설정 변경만으로 전환 가능하다.

### Git과의 역할 분담

| 구분 | Git | DVC |
|------|-----|-----|
| 추적 대상 | 소스 코드, 설정 파일, `.dvc` 파일 | 대용량 데이터셋, 모델 가중치 |
| 저장 위치 | Git 원격 저장소 (GitHub 등) | 객체 저장소 (S3, MinIO 등) |
| 변경 추적 | 텍스트 diff | 해시(MD5) 기반 |
| 파일 크기 | 수 KB ~ 수 MB | 수 MB ~ 수 TB |

---

## 2. 주요 기능 정리

### 2.1 `dvc init` — 프로젝트 초기화

Git 저장소 내에서 DVC를 초기화한다. `.dvc/` 디렉토리와 설정 파일이 생성된다.

```bash
# Git 저장소 내에서 실행
cd MLOps-Pipeline
dvc init

# 생성되는 파일 확인
git status
# new file: .dvc/.gitignore
# new file: .dvc/config
# new file: .dvcignore

# DVC 초기화를 git에 커밋
git add .dvc .dvcignore
git commit -m "data: initialize DVC"
```

### 2.2 `dvc add <path>` — 데이터 추적 시작

지정한 파일 또는 디렉토리를 DVC 추적 대상으로 등록한다. `.dvc` 포인터 파일이 생성되고, 원본 경로는 `.gitignore`에 자동 추가된다.

```bash
# 단일 파일 추적
dvc add data/raw/labels.csv

# 디렉토리 단위 추적 (이미지 데이터셋 등)
dvc add data/raw/cifar10-demo

# 생성된 파일 확인
ls data/raw/
# cifar10-demo/          <- 실제 데이터 (git 무시됨)
# cifar10-demo.dvc       <- 포인터 파일 (git에 커밋)
# .gitignore             <- 자동 생성/갱신
```

생성되는 `.dvc` 파일의 구조:

```yaml
outs:
  - md5: a304afb96060aad90176268345e10355
    size: 11490850
    hash: md5
    path: cifar10-demo
```

- `md5`: 데이터의 해시값으로, 데이터가 변경되면 이 값이 바뀐다.
- `size`: 바이트 단위의 파일/디렉토리 크기.
- `path`: 추적 대상의 상대 경로.

### 2.3 `dvc remote add` — 원격 저장소 설정

데이터를 저장할 원격 저장소를 설정한다. 본 프로젝트에서는 MinIO를 S3 호환 스토리지로 사용한다.

```bash
# MinIO를 기본(-d) 원격 저장소로 설정
dvc remote add -d minio-remote s3://dvc-storage

# MinIO 엔드포인트 및 인증 정보 설정
dvc remote modify minio-remote endpointurl http://localhost:9000
dvc remote modify minio-remote access_key_id minioadmin
dvc remote modify minio-remote secret_access_key minioadmin123

# 설정 확인
dvc remote list
# minio-remote    s3://dvc-storage

# 설정은 .dvc/config 파일에 저장됨
cat .dvc/config
# [core]
#     remote = minio-remote
# ['remote "minio-remote"']
#     url = s3://dvc-storage
#     endpointurl = http://localhost:9000
#     access_key_id = minioadmin
#     secret_access_key = minioadmin123
```

> **보안 참고**: 인증 정보는 `dvc remote modify --local`을 사용하면 `.dvc/config.local`에 저장되어 Git에 커밋되지 않는다. 프로덕션 환경에서는 반드시 `--local` 옵션을 사용할 것.

```bash
# 인증 정보를 로컬 전용 설정으로 분리
dvc remote modify --local minio-remote access_key_id minioadmin
dvc remote modify --local minio-remote secret_access_key minioadmin123
```

### 2.4 `dvc push` / `dvc pull` — 원격 저장소와 동기화

`push`는 로컬 캐시의 데이터를 원격 저장소로 업로드하고, `pull`은 원격에서 로컬로 다운로드한다.

```bash
# 추적 중인 모든 데이터를 원격 저장소로 업로드
dvc push

# 원격 저장소에서 데이터 다운로드
dvc pull

# 특정 .dvc 파일만 대상으로 push/pull
dvc push data/raw/cifar10-demo.dvc
dvc pull data/raw/cifar10-demo.dvc
```

일반적인 협업 워크플로우:

```bash
# 팀원 A: 데이터 추가 후 공유
dvc add data/raw/new-dataset
git add data/raw/new-dataset.dvc data/raw/.gitignore
git commit -m "data: add new-dataset"
git push
dvc push

# 팀원 B: 데이터 가져오기
git pull
dvc pull
```

### 2.5 `dvc diff` — 데이터 변경사항 확인

두 커밋 사이의 데이터 변경사항을 확인한다. `git diff`의 데이터 버전이라고 볼 수 있다.

```bash
# 마지막 커밋 대비 변경사항
dvc diff

# 특정 커밋/태그 간 비교
dvc diff v1.0 v2.0

# 출력 예시:
# Modified:
#   data/raw/cifar10-demo:
#     modified: 157 files
#     added: 43 files
#     deleted: 12 files
```

### 2.6 `dvc gc` — 사용하지 않는 캐시 정리

DVC 캐시(`.dvc/cache/`)에 누적된 오래된 데이터를 정리하여 디스크 공간을 확보한다.

```bash
# 현재 워크스페이스에서 사용하지 않는 캐시 제거
dvc gc --workspace

# 모든 Git 브랜치와 태그에서 참조하지 않는 캐시 제거
dvc gc --all-branches --all-tags

# 원격 저장소의 불필요한 데이터도 함께 정리
dvc gc --cloud --all-branches --all-tags
```

> **주의**: `dvc gc`는 되돌릴 수 없다. 실행 전 `--dry` 옵션으로 삭제 대상을 먼저 확인하는 것을 권장한다.

```bash
dvc gc --workspace --dry
```

### 2.7 `.dvcignore` — 추적 제외 설정

`.gitignore`와 동일한 문법으로, DVC가 특정 파일이나 디렉토리를 무시하도록 설정한다. `dvc add`로 디렉토리를 추적할 때 불필요한 파일을 제외하는 데 유용하다.

```bash
# .dvcignore 예시
# 임시 파일 제외
*.tmp
*.log

# 시스템 파일 제외
.DS_Store
__pycache__/
*.pyc

# 특정 디렉토리 제외
data/raw/scratch/
```

---

## 3. 현재 프로젝트 활용 상태

본 프로젝트(MLOps-Pipeline)에서 DVC 관련 인프라는 **부분적으로 준비**되어 있으나, 실제 데이터 추적은 아직 시작되지 않은 상태다.

### 준비된 항목

| 항목 | 상태 | 위치 |
|------|------|------|
| DVC 의존성 | `dvc[s3]>=3.55` 등록됨 | `pyproject.toml` |
| MinIO 원격 저장소 | `dvc-storage` 버킷 자동 생성 | `docker-compose.yml` |
| 설정 스크립트 | MinIO 리모트 설정 자동화 | `scripts/setup_dvc.sh` |

### 미완료 항목

| 항목 | 현재 상태 | 필요 작업 |
|------|-----------|-----------|
| DVC 초기화 | `.dvc/` 디렉토리 없음 | `dvc init` 실행 |
| 데이터 추적 | `.dvc` 파일 없음 | `dvc add data/...` 실행 |
| 원격 저장소 연결 | 설정 미적용 | `scripts/setup_dvc.sh` 실행 또는 수동 설정 |
| 파이프라인 통합 | Prefect 태스크에 DVC 연동 없음 | `dvc pull` 태스크 추가 |

---

## 4. 미활용 기능 & 개선 포인트

### 4.1 DVC 초기화 및 데이터 추적

현재 프로젝트에 DVC를 완전히 적용하기 위한 단계별 가이드:

```bash
# 1. DVC 초기화
dvc init

# 2. MinIO 리모트 설정
dvc remote add -d minio-remote s3://dvc-storage
dvc remote modify minio-remote endpointurl http://localhost:9000
dvc remote modify --local minio-remote access_key_id minioadmin
dvc remote modify --local minio-remote secret_access_key minioadmin123

# 3. 데이터셋 추적
dvc add data/raw/cifar10-demo

# 4. git 커밋 (.dvc 파일 + .gitignore)
git add .dvc .dvcignore data/raw/cifar10-demo.dvc data/raw/.gitignore
git commit -m "data: track cifar10-demo dataset with DVC"

# 5. 데이터 업로드
dvc push
```

### 4.2 데이터 버전 관리 워크플로우

Active Learning 라운드마다 데이터셋이 변경되는 상황에서, DVC와 Git 태그를 조합하면 각 라운드의 데이터 상태를 명확하게 추적할 수 있다.

```bash
# === Round 1: 초기 데이터셋 ===
dvc add data/raw/cifar10-demo
git add data/raw/cifar10-demo.dvc data/raw/.gitignore
git commit -m "data: initial dataset for round 1"
git tag -a data-v1.0 -m "Round 1: 10,000 samples"
dvc push

# === Round 2: Active Learning으로 라벨링 데이터 추가 ===
# (새로운 이미지가 data/raw/cifar10-demo에 추가된 상태)
dvc add data/raw/cifar10-demo
git add data/raw/cifar10-demo.dvc
git commit -m "data: add 2,000 samples from active learning round 2"
git tag -a data-v2.0 -m "Round 2: 12,000 samples (+2,000 AL)"
dvc push

# === 이전 라운드 데이터로 복원 ===
git checkout data-v1.0 -- data/raw/cifar10-demo.dvc
dvc checkout data/raw/cifar10-demo.dvc
# -> data/raw/cifar10-demo가 Round 1 상태로 복원됨

# === 다시 최신 데이터로 복귀 ===
git checkout main -- data/raw/cifar10-demo.dvc
dvc checkout data/raw/cifar10-demo.dvc
```

이 워크플로우의 장점:

- **데이터 이력 추적**: `git log --oneline data/raw/cifar10-demo.dvc`로 데이터 변경 이력을 한눈에 확인할 수 있다.
- **실험 재현**: 특정 라운드의 모델을 재학습하려면, 해당 태그로 체크아웃하고 `dvc pull`만 실행하면 된다.
- **비교 분석**: `dvc diff data-v1.0 data-v2.0`으로 라운드 간 데이터 변경량을 파악할 수 있다.

### 4.3 Prefect 파이프라인 통합

Prefect 파이프라인의 시작 단계에서 DVC를 통해 데이터를 확보하는 태스크를 추가할 수 있다.

```python
import logging
import subprocess
from pathlib import Path

from prefect import task

logger = logging.getLogger(__name__)


@task(name="ensure-data-available", retries=2, retry_delay_seconds=30)
def ensure_data_available(data_dir: str) -> Path:
    """Pull dataset from DVC remote if not present locally.

    Args:
        data_dir: Path to the data directory tracked by DVC.

    Returns:
        Path to the verified data directory.

    Raises:
        subprocess.CalledProcessError: If dvc pull fails after retries.
    """
    path = Path(data_dir)
    if not path.exists():
        logger.info("Data not found at %s, pulling from DVC remote...", data_dir)
        result = subprocess.run(
            ["dvc", "pull", f"{data_dir}.dvc"],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("DVC pull completed: %s", result.stdout)
    else:
        logger.info("Data already available at %s", data_dir)
    return path


@task(name="version-data-after-round")
def version_data_after_round(data_dir: str, round_num: int) -> str:
    """Track updated dataset after an Active Learning round.

    Args:
        data_dir: Path to the updated data directory.
        round_num: The current Active Learning round number.

    Returns:
        The git commit hash for the data version.
    """
    # DVC add로 변경사항 추적
    subprocess.run(["dvc", "add", data_dir], check=True)

    # Git 커밋
    dvc_file = f"{data_dir}.dvc"
    subprocess.run(["git", "add", dvc_file], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"data: update dataset after AL round {round_num}"],
        check=True,
    )

    # DVC push로 원격 저장소에 업로드
    subprocess.run(["dvc", "push"], check=True)

    # 커밋 해시 반환
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit_hash = result.stdout.strip()
    logger.info("Data versioned at commit %s (round %d)", commit_hash, round_num)
    return commit_hash
```

파이프라인 플로우에서의 사용 예시:

```python
from prefect import flow


@flow(name="training-pipeline")
def training_pipeline(data_dir: str = "data/raw/cifar10-demo") -> None:
    """Full training pipeline with DVC data management."""
    # Step 1: 데이터 확보
    data_path = ensure_data_available(data_dir)

    # Step 2: 데이터 검증
    validate_data(data_path)

    # Step 3: 학습 실행
    model = train_model(data_path)

    # Step 4: 모델 평가 및 등록
    register_model(model)
```

### 4.4 Makefile 통합

DVC 관련 명령어를 Makefile에 추가하면 팀 전체의 워크플로우를 통일할 수 있다.

```makefile
## DVC 초기화 및 원격 저장소 설정
dvc-init:
	dvc init
	dvc remote add -d minio-remote s3://dvc-storage
	dvc remote modify minio-remote endpointurl http://localhost:9000
	dvc remote modify --local minio-remote access_key_id minioadmin
	dvc remote modify --local minio-remote secret_access_key minioadmin123

## 원격 저장소에서 데이터 다운로드
dvc-pull:
	dvc pull

## 로컬 데이터를 원격 저장소에 업로드
dvc-push:
	dvc push

## 데이터 변경사항 확인
dvc-diff:
	dvc diff

## DVC 캐시 정리 (현재 워크스페이스 기준)
dvc-gc:
	dvc gc --workspace
```

---

## 5. 다른 도구와의 연결점

DVC는 단독으로 사용하기보다 ML 파이프라인의 다른 구성 요소들과 함께 사용할 때 가치가 극대화된다.

### Prefect (Layer 4: 오케스트레이션)

- **파이프라인 시작 시**: `dvc pull`로 학습에 필요한 데이터를 확보한다. 데이터가 이미 로컬에 있으면 건너뛴다.
- **Active Learning 라운드 종료 시**: `dvc add` + `dvc push`로 갱신된 데이터셋을 버전 관리하고 원격 저장소에 저장한다.
- **스케줄링**: Prefect의 주기적 실행과 DVC의 데이터 동기화를 결합하면, 자동화된 데이터 파이프라인을 구축할 수 있다.

### MLflow (Layer 3: 학습)

- **자동 git 커밋 기록**: MLflow는 학습 실행(run) 시 현재 git 커밋 해시를 자동으로 기록한다. 이 커밋에 `.dvc` 파일이 포함되어 있으므로, MLflow run → git commit → `.dvc` 파일 → 실제 데이터 경로를 역추적할 수 있다.
- **데이터 버전 태깅**: MLflow run의 태그에 데이터 버전(예: `data-v2.0`)을 명시적으로 기록하면, 어떤 데이터로 학습한 모델인지 즉시 파악할 수 있다.

```python
import mlflow

with mlflow.start_run():
    mlflow.set_tag("data.version", "data-v2.0")
    mlflow.set_tag("data.samples", "12000")
    # ... 학습 코드 ...
```

### Git

- `.dvc` 파일을 Git 태그와 함께 관리하면 **모델 버전 <-> 데이터 버전** 매핑이 가능하다.
- `git log --oneline -- "*.dvc"` 명령으로 데이터 변경 이력만 필터링하여 확인할 수 있다.
- 브랜치별로 다른 데이터셋 구성을 유지할 수 있어, 실험 브랜치에서 데이터 서브셋으로 빠르게 테스트하는 워크플로우가 가능하다.

### MinIO (Layer 1: 인프라)

- DVC의 원격 저장소 백엔드로 MinIO를 사용한다. S3 호환 API를 제공하므로 DVC의 `dvc[s3]` 플러그인으로 바로 연동된다.
- `dvc-storage` 버킷은 `docker-compose.yml`에서 MinIO 초기화 시 자동 생성된다.
- 로컬 개발 환경에서는 `http://localhost:9000`, Docker 네트워크 내부에서는 `http://minio:9000`으로 접근한다.

---

## 참고 자료

- [DVC 공식 문서](https://dvc.org/doc)
- [DVC S3 Remote 설정 가이드](https://dvc.org/doc/user-guide/data-management/remote-storage/amazon-s3)
- [DVC + MinIO 연동 가이드](https://dvc.org/doc/user-guide/data-management/remote-storage/amazon-s3#s3-compatible-servers-non-amazon)
