# CleanVision

## 1. 핵심 철학/설계 사상

CleanVision은 **이미지 데이터셋의 품질 문제를 자동으로 탐지**하는 오픈소스 도구다.
CleanLab의 자매 프로젝트로, CleanLab이 **라벨 품질**을 다루는 반면 CleanVision은 **이미지 자체의 품질**을 다룬다.

### 핵심 원리

- **GPU 불필요**: CPU만으로 대규모 이미지 데이터셋을 효율적으로 분석한다. 별도의 모델 학습 없이 이미지 자체의 속성(밝기, 선명도, 해시값 등)만으로 품질을 평가한다.
- **라벨 독립적**: 이미지의 라벨이 없어도 동작한다. 이미지 파일만 존재하면 품질 문제를 탐지할 수 있다.
- **모든 CV 작업에 적용 가능**: 분류, 탐지, 세그멘테이션, 생성 모델 등 작업 유형에 관계없이 사용할 수 있다. 이미지 품질 문제는 모든 CV 작업의 성능에 영향을 미치기 때문이다.
- **CleanLab과의 보완 관계**: CleanVision(이미지 품질) + CleanLab(라벨 품질) = 종합적인 데이터 품질 평가. 두 도구를 함께 사용하면 데이터의 이미지와 라벨 양쪽 모두를 검증할 수 있다.

---

## 2. 주요 기능 정리

### 2.1 기본 사용법 --- Imagelab

`Imagelab`은 CleanVision의 핵심 클래스로, 이미지 데이터셋의 로딩, 분석, 결과 조회를 모두 담당한다.

```python
from cleanvision import Imagelab

# 이미지 디렉토리를 지정하여 Imagelab 인스턴스 생성
imagelab = Imagelab(data_path="path/to/images/")

# 모든 이슈 타입에 대해 검사 실행
imagelab.find_issues()

# 이슈 요약 보고서 출력
imagelab.report()
```

`Imagelab`은 HuggingFace Dataset 객체도 직접 받을 수 있다:

```python
from datasets import load_dataset

dataset = load_dataset("cifar10", split="train")
imagelab = Imagelab(hf_dataset=dataset, image_key="img")
imagelab.find_issues()
```

### 2.2 탐지 가능한 이슈 타입

| 이슈 타입 | 설명 | 탐지 방식 |
|-----------|------|----------|
| `blurry` | 흐린 이미지 (초점 맞지 않음) | 라플라시안 분산(Laplacian variance) 기반 |
| `dark` | 너무 어두운 이미지 | 평균 밝기값 기반 |
| `light` | 너무 밝은 이미지 (과다 노출) | 평균 밝기값 기반 |
| `odd_aspect_ratio` | 비정상적인 가로세로 비율 | 데이터셋 내 비율 분포 기반 |
| `odd_size` | 다른 이미지들과 크기가 크게 다른 이미지 | 데이터셋 내 크기 분포 기반 |
| `low_information` | 정보가 거의 없는 이미지 (단색, 거의 빈 이미지 등) | 엔트로피 기반 |
| `exact_duplicates` | 완전히 동일한 이미지 | 이미지 해시 비교 |
| `near_duplicates` | 거의 동일한 이미지 (약간의 차이) | perceptual hash 비교 |

### 2.3 특정 이슈만 검사

전체 검사가 불필요한 경우, 관심 있는 이슈 타입만 선택적으로 검사할 수 있다.

```python
# 특정 이슈 타입만 검사
imagelab.find_issues(issue_types={"dark": {}, "blurry": {}})
```

### 2.4 임계값 커스터마이즈

각 이슈 타입의 임계값을 조정하여 탐지 민감도를 제어할 수 있다. 임계값이 낮을수록 더 엄격하게 이슈를 탐지한다.

```python
imagelab.find_issues(
    issue_types={
        "blurry": {"threshold": 0.3},        # 기본값보다 엄격하게
        "dark": {"threshold": 0.2},
        "near_duplicates": {"hash_size": 8},  # 해시 크기 조정 (클수록 엄격)
    }
)
```

### 2.5 결과 접근

`find_issues()` 실행 후 두 가지 주요 속성으로 결과에 접근한다.

```python
# 이미지별 이슈 플래그 DataFrame (행: 이미지, 열: 이슈 타입별 플래그)
issues_df = imagelab.issues

# 이슈 타입별 요약 (탐지된 이미지 수 등)
summary = imagelab.issue_summary

# 특정 이슈 타입의 이미지만 필터링
blurry_images = issues_df[issues_df["is_blurry_issue"]]

# 점수 컬럼으로 심각도 확인 (0에 가까울수록 심각)
worst_blurry = issues_df.sort_values("blurry_score").head(10)
```

### 2.6 시각화

탐지된 이슈를 시각적으로 확인할 수 있다. Jupyter 노트북 환경에서 주로 사용한다.

```python
imagelab.visualize(issue_types=["blurry", "dark"])
```

---

## 3. 현재 프로젝트 활용 상태

### 3.1 이미지 검증 모듈

`src/data/validation/image_validator.py`에서 CleanVision을 활용하고 있다.

- `validate_image_dataset()` 함수가 핵심 진입점
- `Imagelab`으로 이미지를 로딩하고 `find_issues()`로 검사 실행
- `is_*_issue` 컬럼에서 하나라도 True인 이미지를 카운트하여 `health_score` 산출
  - `health_score = 1.0 - (문제_이미지_수 / 전체_이미지_수)`
- `ValidationReport` dataclass로 결과 반환: `total_images`, `issues_found`, `issue_types`, `health_score`
- `issue_types` 파라미터로 검사할 이슈 타입을 선택할 수 있으나, 현재 호출 시 기본값(`None`, 전체 검사)으로 사용

### 3.2 Prefect 파이프라인 통합

- `src/orchestration/tasks/data_tasks.py`의 `validate_images` task에서 `validate_image_dataset()` 호출
- `src/orchestration/flows/training_pipeline.py`에서 품질 게이트로 활용:
  - `health_score >= min_health_score` (기본 0.5) 조건을 만족해야 학습 진행
  - 미달 시 `RuntimeError`를 발생시켜 파이프라인 중단

### 3.3 미활용 기능

현재 코드에서 CleanVision의 다음 기능들을 활용하지 않고 있다:

| 미활용 기능 | 설명 |
|------------|------|
| 임계값 커스터마이즈 | `find_issues()` 호출 시 빈 dict `{}`만 전달. 임계값 조정 미사용 |
| `near_duplicates` / `exact_duplicates` 검사 | 기본 전체 검사에 포함되나, task 호출부에서 이슈 타입을 특정하지 않음 |
| `low_information` 검사 | 동일하게 기본 전체 검사에 포함 |
| 시각화 기능 | `visualize()` 미사용 |
| 결과의 Prefect 아티팩트 기록 | `create_markdown_artifact()`로 검증 결과 기록 미구현 |
| MLflow 메트릭 로깅 | `ValidationReport.to_dict()`가 존재하지만 실제 MLflow 로깅 미구현 |

---

## 4. 미활용 기능 & 개선 포인트

### 4.1 이슈 타입 확장 + 임계값 커스터마이즈

현재는 `find_issues()`를 기본 파라미터로 호출한다. 이슈 타입별 임계값을 명시적으로 설정하면 프로젝트에 맞는 검증 기준을 수립할 수 있다.

```python
# Before: 기본 파라미터로 전체 검사
imagelab.find_issues()

# After: 8개 이슈 모두 검사 + 프로젝트에 맞는 임계값 설정
ISSUE_TYPES_WITH_THRESHOLDS = {
    "blurry": {"threshold": 0.3},
    "dark": {"threshold": 0.05},
    "light": {"threshold": 0.05},
    "odd_aspect_ratio": {"threshold": 3.0},
    "odd_size": {"threshold": 10.0},
    "low_information": {"threshold": 0.15},
    "exact_duplicates": {},
    "near_duplicates": {"hash_size": 8},
}

imagelab.find_issues(issue_types=ISSUE_TYPES_WITH_THRESHOLDS)
```

### 4.2 설정 기반 접근 (Pydantic Settings)

이슈 타입과 임계값을 환경변수로 설정 가능하게 만들면, 코드 변경 없이 검증 기준을 조정할 수 있다.

```python
from pydantic import Field
from pydantic_settings import BaseSettings


class ImageValidationSettings(BaseSettings):
    """CleanVision image validation configuration."""

    model_config = {"env_prefix": "CLEANVISION_"}

    blurry_threshold: float = Field(default=0.3, description="Blur detection threshold")
    dark_threshold: float = Field(default=0.05, description="Dark image threshold")
    light_threshold: float = Field(default=0.05, description="Light image threshold")
    odd_aspect_ratio_threshold: float = Field(default=3.0, description="Aspect ratio threshold")
    odd_size_threshold: float = Field(default=10.0, description="Odd size threshold")
    low_information_threshold: float = Field(default=0.15, description="Low info threshold")
    near_duplicates_hash_size: int = Field(default=8, description="Perceptual hash size")
    enable_duplicate_check: bool = Field(default=True, description="Enable duplicate detection")

    def to_issue_types(self) -> dict[str, dict]:
        """Convert settings to CleanVision issue_types dict."""
        issue_types: dict[str, dict] = {
            "blurry": {"threshold": self.blurry_threshold},
            "dark": {"threshold": self.dark_threshold},
            "light": {"threshold": self.light_threshold},
            "odd_aspect_ratio": {"threshold": self.odd_aspect_ratio_threshold},
            "odd_size": {"threshold": self.odd_size_threshold},
            "low_information": {"threshold": self.low_information_threshold},
        }
        if self.enable_duplicate_check:
            issue_types["exact_duplicates"] = {}
            issue_types["near_duplicates"] = {"hash_size": self.near_duplicates_hash_size}
        return issue_types
```

환경변수 설정 예시:

```bash
# .env
CLEANVISION_BLURRY_THRESHOLD=0.25
CLEANVISION_DARK_THRESHOLD=0.1
CLEANVISION_ENABLE_DUPLICATE_CHECK=true
```

### 4.3 Prefect 아티팩트로 결과 기록

검증 결과를 Prefect 아티팩트로 기록하면 UI에서 이력을 추적할 수 있다.

```python
from prefect.artifacts import create_markdown_artifact


def format_validation_report(report: dict[str, Any]) -> str:
    """Format validation report as Markdown for Prefect artifact."""
    lines = [
        "# Image Quality Validation Report",
        "",
        f"- **Total images**: {report['total_images']}",
        f"- **Issues found**: {report['issues_found']}",
        f"- **Health score**: {report['health_score']:.2f}",
        "",
        "## Issue Breakdown",
        "",
        "| Issue Type | Count |",
        "|------------|-------|",
    ]
    for key, value in report.items():
        if key.startswith("issue_"):
            issue_name = key.replace("issue_", "")
            lines.append(f"| {issue_name} | {value} |")
    return "\n".join(lines)


@task(name="validate-images", retries=1, retry_delay_seconds=10)
def validate_images(data_dir: str) -> dict[str, Any]:
    from src.data.validation import validate_image_dataset

    train_dir = Path(data_dir) / "train"
    report = validate_image_dataset(train_dir)
    result = report.to_dict()

    # Prefect artifact로 결과 기록
    create_markdown_artifact(
        key="image-validation-report",
        markdown=format_validation_report(result),
        description="CleanVision image quality validation results",
    )

    return result
```

### 4.4 MLflow 메트릭 로깅

`ValidationReport.to_dict()`가 이미 MLflow 로깅에 적합한 형태를 반환한다. 학습 파이프라인에서 이를 실제로 로깅하면 실험 간 데이터 품질 변화를 추적할 수 있다.

```python
import mlflow


def log_validation_metrics(report_dict: dict[str, Any]) -> None:
    """Log validation metrics to MLflow."""
    mlflow.log_metrics({
        "data/total_images": report_dict["total_images"],
        "data/issues_found": report_dict["issues_found"],
        "data/health_score": report_dict["health_score"],
    })
    # 이슈 타입별 카운트도 개별 메트릭으로 로깅
    for key, value in report_dict.items():
        if key.startswith("issue_"):
            mlflow.log_metric(f"data/{key}", value)
```

### 4.5 Active Learning 연동

Active Learning 라운드에서 CleanVision을 활용하면, 새로 수집된 이미지의 품질 문제를 자동으로 탐지하고 제거할 수 있다.

```python
import os
from cleanvision import Imagelab


ISSUE_TYPES_WITH_THRESHOLDS = {
    "blurry": {"threshold": 0.3},
    "dark": {"threshold": 0.05},
    "light": {"threshold": 0.05},
    "low_information": {"threshold": 0.15},
    "exact_duplicates": {},
    "near_duplicates": {"hash_size": 8},
}


def clean_images(data_dir: str, round_num: int) -> tuple[int, list[str]]:
    """Detect and remove problematic images in an active learning round.

    Args:
        data_dir: Path to newly collected images.
        round_num: Current active learning round number.

    Returns:
        Tuple of (removed count, list of removed image paths).
    """
    imagelab = Imagelab(data_path=data_dir)
    imagelab.find_issues(issue_types=ISSUE_TYPES_WITH_THRESHOLDS)

    issues_df = imagelab.issues
    issue_columns = [
        col for col in issues_df.columns
        if col.startswith("is_") and col.endswith("_issue")
    ]
    has_any_issue = issues_df[issue_columns].any(axis=1)
    problematic_images = issues_df[has_any_issue].index.tolist()

    for img_path in problematic_images:
        os.remove(img_path)

    return len(problematic_images), problematic_images
```

---

## 5. 다른 도구와의 연결점

| 연결 도구 | 관계 | 활용 방식 |
|-----------|------|----------|
| **CleanLab** | 보완 관계 | CleanVision(이미지 품질) + CleanLab(라벨 품질) = 종합 데이터 품질 평가. 파이프라인에서 두 검증을 순차 실행 |
| **Prefect** | 오케스트레이션 | 검증 결과를 `create_markdown_artifact`로 기록. `health_score` 기반 품질 게이트로 학습 진행 여부 결정 |
| **MLflow** | 실험 추적 | `health_score`, 이슈 타입별 count를 메트릭으로 로깅하여 데이터 품질 변화 추적 |
| **DVC** | 데이터 버전 관리 | DVC로 관리되는 데이터셋에 CleanVision 검증을 적용. 버전별 품질 이력 추적 가능 |
| **Active Learning** | 데이터 수집 루프 | 매 라운드마다 새 이미지의 품질 이슈 탐지 후 제거, 정제된 데이터로 재학습 |
