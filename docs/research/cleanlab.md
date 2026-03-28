# CleanLab

## 1. 핵심 철학/설계 사상

CleanLab은 **Data-Centric AI** 철학을 기반으로 한 데이터 품질 검증 라이브러리다.
모델 아키텍처를 바꾸는 대신, 데이터의 라벨 품질을 개선하여 성능을 향상시키는 접근법을 취한다.

### 핵심 원리

- **Confident Learning**: 모델의 예측 확률(predicted probabilities)을 활용하여 라벨 오류를 체계적으로 탐지한다. 모델이 "확신하는" 예측과 실제 라벨이 불일치하는 샘플을 찾아내는 원리다.
- **모델 독립적(Model-Agnostic)**: PyTorch, TensorFlow, scikit-learn 등 어떤 프레임워크의 모델이든 predicted probabilities만 제공하면 동작한다. 특정 모델에 종속되지 않는다.
- **입증된 실적**: ImageNet, MNIST 등 널리 사용되는 벤치마크 데이터셋에서도 수천 개의 라벨 오류를 발견한 바 있다. "잘 정제된" 데이터셋조차 라벨 품질 문제가 있을 수 있음을 보여준다.
- **자동화 가능**: API가 단순하여 ML 파이프라인에 자연스럽게 통합할 수 있다.

### 동작 메커니즘

CleanLab의 핵심 알고리즘인 Confident Learning은 다음 단계로 동작한다:

1. 모델의 out-of-sample 예측 확률을 수집한다 (cross-validation 또는 holdout 방식)
2. 각 클래스별 자신감 임계값(confidence threshold)을 계산한다
3. 임계값을 기준으로 라벨과 예측이 불일치하는 샘플을 식별한다
4. 노이즈 행렬(noise matrix)을 추정하여 라벨 오류 패턴을 분석한다

---

## 2. 주요 기능 정리

### 2.1 `find_label_issues` --- 라벨 오류 탐지

주어진 라벨과 예측 확률을 기반으로 라벨 오류가 의심되는 샘플의 인덱스를 반환한다.

```python
from cleanlab.filter import find_label_issues

# labels: 현재 라벨 (numpy array, shape: [N])
# pred_probs: 모델의 클래스별 예측 확률 (numpy array, shape: [N, K])
issue_mask = find_label_issues(
    labels=labels,
    pred_probs=pred_probs,
    filter_by="prune_by_noise_rate",  # 필터링 방법
)

# boolean mask -> 인덱스 변환
issue_indices = np.where(issue_mask)[0].tolist()
```

`filter_by` 파라미터 옵션:

| 옵션 | 설명 |
|------|------|
| `prune_by_class` | 클래스별로 가장 의심스러운 샘플 제거 |
| `prune_by_noise_rate` | 추정된 노이즈 비율 기반 제거 (기본값) |
| `both` | 위 두 방법의 교집합 |
| `confident_learning` | Confident Learning 알고리즘 직접 적용 |
| `predicted_neq_given` | 예측 라벨 != 주어진 라벨인 샘플 |

`return_indices_ranked_by` 파라미터로 인덱스를 직접 정렬하여 받을 수도 있다:

```python
issue_indices = find_label_issues(
    labels=labels,
    pred_probs=pred_probs,
    return_indices_ranked_by="self_confidence",  # 가장 의심스러운 순서로 정렬
)
```

### 2.2 `get_label_quality_scores` --- 라벨 품질 점수

각 샘플에 대해 0~1 사이의 라벨 품질 점수를 계산한다. 점수가 낮을수록 라벨 오류 가능성이 높다.

```python
from cleanlab.rank import get_label_quality_scores

quality_scores = get_label_quality_scores(
    labels=labels,
    pred_probs=pred_probs,
    method="self_confidence",
)
# quality_scores: numpy array, shape [N], 값 범위 [0, 1]
```

`method` 옵션:

| 옵션 | 설명 |
|------|------|
| `self_confidence` | 주어진 라벨에 해당하는 예측 확률 (기본값) |
| `normalized_margin` | 주어진 라벨 확률과 최대 확률의 정규화된 차이 |
| `confidence_weighted_entropy` | 엔트로피로 가중된 자신감 점수 |

### 2.3 `Datalab` --- 통합 데이터 품질 감사

개별 함수를 따로 호출하는 대신, `Datalab` 클래스를 사용하면 라벨 오류, 아웃라이어, 클래스 불균형, 중복 데이터 등을 한 번에 진단할 수 있다.

```python
from cleanlab import Datalab
import pandas as pd

data = pd.DataFrame({
    "image_path": image_paths,
    "label": labels,
})

lab = Datalab(data=data, label_name="label")
lab.find_issues(pred_probs=pred_probs)

# 종합 리포트 출력
lab.report()

# 특정 이슈 타입만 조회
label_issues = lab.get_issues("label")
outlier_issues = lab.get_issues("outlier")
```

`Datalab.report()`가 검사하는 항목:

- **Label Issues**: 라벨이 잘못된 것으로 의심되는 샘플
- **Outlier Issues**: 데이터 분포에서 극단적으로 벗어난 샘플
- **Near Duplicate Issues**: 거의 동일한 샘플 쌍
- **Class Imbalance Issues**: 클래스 간 심각한 불균형

### 2.4 Cross-Validation으로 pred_probs 생성

CleanLab의 핵심 입력인 `pred_probs`는 반드시 **out-of-sample** 예측이어야 한다.
학습 데이터에 대해 직접 추론한 확률을 사용하면 모델이 이미 해당 데이터를 외워버렸을 수 있으므로, 라벨 오류 탐지 정확도가 크게 떨어진다.

scikit-learn 모델의 경우 `cross_val_predict`로 간단하게 생성할 수 있다:

```python
from sklearn.model_selection import cross_val_predict

# 각 샘플이 학습에 포함되지 않은 fold에서의 예측을 얻음
pred_probs = cross_val_predict(
    clf, X, labels, cv=5, method="predict_proba"
)
```

PyTorch 모델의 경우 직접 K-Fold를 구현하거나, 학습 완료 후 학습 데이터에 대해 추론하는 **post-hoc 방식**을 사용할 수 있다. Post-hoc 방식은 정확도가 약간 떨어지지만 파이프라인 통합이 훨씬 간단하다:

```python
import torch
from torch.utils.data import DataLoader

def get_pred_probs(
    model: torch.nn.Module,
    loader: DataLoader,
    device: str = "cpu",
) -> tuple[np.ndarray, np.ndarray]:
    """Get predicted probabilities from a trained model."""
    model.eval()
    all_probs = []
    all_labels = []
    with torch.no_grad():
        for images, targets in loader:
            outputs = model(images.to(device))
            probs = torch.softmax(outputs, dim=1)
            all_probs.append(probs.cpu().numpy())
            all_labels.extend(targets.numpy())
    return np.concatenate(all_probs), np.array(all_labels)
```

---

## 3. 현재 프로젝트 활용 상태

### 구현된 부분

- `src/data/validation/label_validator.py`:
  - `validate_labels()` 함수가 구현되어 있음
  - `find_label_issues()` + `get_label_quality_scores()` 사용
  - `LabelReport` dataclass로 결과를 반환하며, `to_dict()` 메서드로 MLflow 로깅 가능
  - `filter_by` 파라미터로 필터링 방법을 설정할 수 있음

### 치명적 문제: 파이프라인 미연결

현재 `validate_labels()` 함수는 **파이프라인 어디에서도 호출되지 않는다**.

- `src/orchestration/tasks/data_tasks.py`에 `validate_labels` task가 존재하지 않음
- `src/orchestration/flows/training_pipeline.py`에서 `validate_images`(CleanVision)만 호출하고, `validate_labels`(CleanLab)는 호출하지 않음
- 결과적으로 CleanLab의 핵심 가치인 라벨 품질 검증이 전혀 활용되지 않고 있음

이미지 품질 검사(CleanVision)만으로는 데이터 품질을 충분히 보장할 수 없다.
라벨 오류는 모델 성능에 직접적인 영향을 미치므로, 반드시 파이프라인에 통합해야 한다.

---

## 4. 미활용 기능 & 개선 포인트

### 4.1 파이프라인 연결 (최우선 과제)

학습 완료 후 모델의 예측 확률을 활용하여 라벨을 검증하는 **post-hoc validation** 방식을 채택한다.
이 방식은 별도의 cross-validation 없이도 기존 학습 파이프라인에 자연스럽게 통합할 수 있다.

#### Prefect Task 구현

```python
# src/orchestration/tasks/data_tasks.py에 추가

@task(name="validate-labels", retries=1, retry_delay_seconds=10)
def validate_labels_task(
    model: torch.nn.Module,
    data_dir: str,
    device: str,
    num_classes: int,
) -> dict:
    """Validate labels using trained model predictions."""
    from torchvision.datasets import ImageFolder
    from torch.utils.data import DataLoader
    import numpy as np

    # 1. 학습 데이터에 대한 예측 확률 생성
    dataset = ImageFolder(data_dir, transform=get_eval_transforms())
    loader = DataLoader(dataset, batch_size=64, num_workers=0)

    labels = []
    pred_probs_list = []
    model.eval()
    with torch.no_grad():
        for images, targets in loader:
            outputs = model(images.to(device))
            probs = torch.softmax(outputs, dim=1)
            pred_probs_list.append(probs.cpu().numpy())
            labels.extend(targets.numpy())

    labels_arr = np.array(labels)
    pred_probs = np.concatenate(pred_probs_list)

    # 2. CleanLab 라벨 검증
    from src.data.validation.label_validator import validate_labels
    report = validate_labels(labels_arr, pred_probs)
    return report.to_dict()
```

#### 학습 파이프라인에 연결

```python
# src/orchestration/flows/training_pipeline.py에 추가

@flow(name="training-pipeline")
def training_pipeline(config: TrainingConfig) -> dict:
    # ... 기존 학습 단계 ...

    # 학습 완료 후 라벨 검증
    label_report = validate_labels_task(
        model=trained_model,
        data_dir=config.data_dir,
        device=config.device,
        num_classes=config.num_classes,
    )

    # MLflow에 라벨 품질 메트릭 로깅
    mlflow.log_metrics({
        "label_issues_found": label_report["label_issues_found"],
        "label_issue_rate": label_report["label_issue_rate"],
        "avg_label_quality": label_report["avg_label_quality"],
    })

    return {**training_result, **label_report}
```

### 4.2 Datalab 통합 인터페이스 활용

현재 `validate_labels()`는 `find_label_issues()`와 `get_label_quality_scores()`를 개별적으로 호출한다.
`Datalab`을 사용하면 라벨 오류뿐 아니라 아웃라이어, 중복, 클래스 불균형까지 한 번에 감사할 수 있다.

```python
from cleanlab import Datalab
import pandas as pd

def comprehensive_data_audit(
    labels: np.ndarray,
    pred_probs: np.ndarray,
    image_paths: list[str],
) -> dict:
    """Run comprehensive data quality audit using Datalab."""
    data = pd.DataFrame({
        "image_path": image_paths,
        "label": labels,
    })

    lab = Datalab(data=data, label_name="label")
    lab.find_issues(pred_probs=pred_probs)

    # 이슈 유형별 요약
    label_issues = lab.get_issues("label")
    outlier_issues = lab.get_issues("outlier")

    return {
        "label_issues_count": label_issues["is_label_issue"].sum(),
        "outlier_count": outlier_issues["is_outlier_issue"].sum(),
        "overall_quality": lab.get_info("overall"),
    }
```

### 4.3 라벨 오류 리포트를 Prefect Artifact로 생성

탐지된 라벨 오류를 Prefect의 markdown artifact로 저장하면, UI에서 바로 확인할 수 있다.

```python
from prefect.artifacts import create_markdown_artifact

async def create_label_report_artifact(
    report: dict,
    issue_indices: list[int],
    image_paths: list[str],
) -> None:
    """Create a Prefect artifact with label validation results."""
    lines = [
        "# Label Validation Report",
        f"- Total samples: {report['total_samples']}",
        f"- Issues found: {report['label_issues_found']}",
        f"- Issue rate: {report['label_issue_rate']:.2%}",
        f"- Avg quality: {report['avg_label_quality']:.4f}",
        "",
        "## Top Suspicious Samples",
        "| Index | Image Path |",
        "|-------|-----------|",
    ]
    for idx in issue_indices[:20]:  # 상위 20개만 표시
        lines.append(f"| {idx} | {image_paths[idx]} |")

    await create_markdown_artifact(
        key="label-validation-report",
        markdown="\n".join(lines),
    )
```

### 4.4 데이터 품질 게이트

라벨 이슈 비율이 임계값을 초과하면 파이프라인을 중단하거나 경고하는 게이트를 추가한다.

```python
LABEL_ISSUE_THRESHOLD = 0.05  # 5% 이상이면 경고

def check_label_quality_gate(report: dict) -> bool:
    """Check if label quality meets the threshold."""
    issue_rate = report["label_issue_rate"]
    if issue_rate > LABEL_ISSUE_THRESHOLD:
        logger.warning(
            "Label issue rate %.2f%% exceeds threshold %.2f%%. "
            "Consider reviewing and cleaning the dataset.",
            issue_rate * 100,
            LABEL_ISSUE_THRESHOLD * 100,
        )
        return False
    return True
```

### 4.5 Active Learning 연동

매 학습 라운드마다 CleanLab으로 라벨 오류를 탐지하고, 이를 제거한 뒤 재학습하는 반복적 품질 개선이 가능하다.

```
Round 1: 전체 데이터로 학습 -> CleanLab으로 라벨 오류 100건 탐지
Round 2: 100건 제거 후 재학습 -> 새로운 오류 30건 탐지
Round 3: 30건 추가 제거 후 재학습 -> 오류 5건 이하 -> 완료
```

이 과정에서 각 라운드의 `label_issues_found`, `avg_label_quality` 메트릭을 MLflow에 기록하면 데이터 정제 효과를 정량적으로 추적할 수 있다.

---

## 5. 다른 도구와의 연결점

| 도구 | 연결 방식 |
|------|-----------|
| **MLflow** | `label_issues_found`, `label_issue_rate`, `avg_label_quality` 메트릭 로깅. 라운드별 추이를 대시보드에서 추적 |
| **Prefect** | `validate_labels` task 구현 + markdown artifact로 리포트 생성. 학습 파이프라인에 자연스럽게 통합 |
| **CleanVision** | 이미지 품질(CleanVision) + 라벨 품질(CleanLab)을 함께 검사하여 종합 데이터 품질 게이트 구성 |
| **Evidently** | 라벨 분포 변화를 데이터 드리프트로 모니터링. CleanLab의 라벨 이슈 비율 변화도 커스텀 메트릭으로 추적 가능 |
| **Prometheus/Grafana** | label quality 메트릭을 Pushgateway로 전송하여 시계열 모니터링 및 알림 설정 |
| **DVC** | 라벨 정제 전/후 데이터셋을 별도 버전으로 관리. `dvc diff`로 정제 효과 비교 가능 |

### 데이터 품질 파이프라인 전체 흐름

```
데이터 수집
  -> DVC로 버전 관리
  -> CleanVision으로 이미지 품질 검사 (깨진 이미지, 중복, 밝기 이상 등)
  -> 모델 학습
  -> CleanLab으로 라벨 품질 검사 (라벨 오류, 아웃라이어 등)
  -> 품질 게이트 통과 여부 판단
  -> MLflow에 메트릭 기록
  -> 문제 샘플 제거 후 재학습 (필요 시)
```

---

## 6. 참고 자료

- [CleanLab 공식 문서](https://docs.cleanlab.ai/)
- [Confident Learning 논문](https://arxiv.org/abs/1911.00068) --- Curtis G. Northcutt et al., 2021
- [CleanLab GitHub](https://github.com/cleanlab/cleanlab)
- [Label Errors in ML Benchmarks](https://labelerrors.com/) --- 유명 데이터셋의 라벨 오류 시각화
