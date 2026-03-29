# Active Learning-First MLOps Platform — Core Philosophy Design

## Context

이 프로젝트는 현재 6-Layer CV MLOps 파이프라인 템플릿으로, 모든 계층이 구현되어 있다. 그러나 핵심 차별점이 부족하다: 대부분의 MLOps 템플릿이 "train → serve → monitor"에서 끝나는 것과 다르지 않다. 이 설계는 프로젝트의 **핵심 사상을 Active Learning-First Closed-Loop MLOps로 재정립**하고, 그에 맞는 아키텍처와 구현 우선순위를 확정한다.

**목적**: Production Template (실제 팀에서 사용할 on-prem MLOps 플랫폼)
**차별점**: Closed-Loop Active Learning + Dual-Path Data Flywheel
**확장 범위**: CV first, 향후 NLP/Tabular 등 도메인 무관하게 확장 가능

---

## 1. Core Identity — "Active Learning-First MLOps"

### 한 줄 정의

> 이 프로젝트는 Active Learning Loop을 중심으로 모든 MLOps 컴포넌트가 유기적으로 연결된 폐루프(closed-loop) ML 운영 플랫폼이다.

### 5대 원칙

**1. Closed-Loop by Design**
파이프라인은 순환형이다: train → serve → monitor → select → label → retrain → ...
"모니터링에서 끝나는 MLOps"가 아니라 "모니터링이 다음 학습의 시작점"이 되는 시스템.

**2. Dual-Path Data Flywheel**
서빙되는 **모든 데이터**는 학습 자산이다:
- **High confidence** → pseudo-label로 자동 축적되어 continuous learning에 활용
- **Low confidence** → human labeling queue로 전송되어 active learning에 활용

모델이 확신하는 데이터는 자동으로 학습하고, 불확실한 데이터만 사람이 검증한다. 서비스가 운영될수록 데이터 플라이휠이 돌아가며 모델이 자동으로 개선된다.

**3. Event-Driven Automation**
시간 기반(매주 월요일 재학습) 대신, **사건 기반**(drift 감지, 라벨링 완료, 품질 임계치 위반)으로 파이프라인이 작동한다. 필요할 때만 자원을 사용하되, 필요할 때는 즉시 반응한다.

**4. Domain-Agnostic Core, Domain-Specific Plugins**
Active Learning Loop의 흐름(uncertainty → select → label → retrain → evaluate → deploy)은 도메인에 무관하다. CV, NLP, Tabular 각각은 이 흐름의 구체적인 구현체(plugin)로 존재한다.

**5. Quality Gate at Every Transition**
모든 상태 전환(데이터 → 학습, 학습 → 배포, 배포 → 서빙)에 자동화된 품질 검증이 존재한다. 품질을 통과하지 못하면 파이프라인은 멈추고 알림을 보낸다.

### 시스템 시각화

```
┌──────────────────── Data Flywheel ─────────────────────────┐
│                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐      │
│  │  Serve   │───▶│ Monitor  │───▶│ Confidence Split │      │
│  │(FastAPI) │    │(Evidently│    │                  │      │
│  │          │    │Prometheus│    │ High ──▶ Auto    │      │
│  └────▲─────┘    └──────────┘    │ Low  ──▶ Human  │      │
│       │                          └───┬──────┬──────┘      │
│       │                              │      │              │
│       │         ┌────────────────────┘      │              │
│       │         ▼                           ▼              │
│       │    ┌──────────┐           ┌──────────────┐         │
│       │    │ Auto-    │           │   Label      │         │
│       │    │ Accumulate│          │   Studio     │         │
│       │    │(Pseudo-  │           │(Human HITL)  │         │
│       │    │ Label)   │           └──────┬───────┘         │
│       │    └────┬─────┘                  │                 │
│       │         │      ┌─────────────────┘                 │
│       │         ▼      ▼                                   │
│       │    ┌──────────────┐    ┌──────────┐                │
│       │    │   Retrain    │───▶│ Evaluate │                │
│       │    │  (Prefect)   │    │(Champion │                │
│       │    │              │    │ vs New)  │                │
│       │    └──────────────┘    └────┬─────┘                │
│       │                             │                      │
│       │    ┌──────────┐             │                      │
│       └────│  Deploy  │◀────────────┘                      │
│            │(Canary)  │  (if new > champion)               │
│            └──────────┘                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4대 축 연결 다이어그램

```
┌─────────────────────────────────────────────────────────┐
│                   Orchestration (Prefect)                │
│              Event-Driven Flow Coordination              │
│                                                          │
│   ┌─────────────┐  trigger  ┌─────────────────┐        │
│   │  Monitoring  │─────────▶│ Active Learning  │        │
│   │  & Trigger   │          │    Engine        │        │
│   │              │◀─────────│                  │        │
│   │  drift/conf  │ feedback │  uncertainty/    │        │
│   │  tracking    │          │  selection/      │        │
│   └──────┬───────┘          │  accumulation    │        │
│          │                  └────────┬─────────┘        │
│          │ metrics                   │ model             │
│          │                          │ registered         │
│          ▼                          ▼                    │
│   ┌──────────────────────────────────────────┐          │
│   │              CI/CD Pipeline              │          │
│   │  Code CI → ML CI → Quality Gate → CD    │          │
│   │         (Safety & Quality Guard)         │          │
│   └──────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Four Pillars Architecture — 4대 축

### Pillar 1: Active Learning Engine (심장)

어떤 데이터를 학습할지 결정하는 지능.

| 컴포넌트 | 기능 |
|---|---|
| Uncertainty Estimator | 서빙 시 모델 예측의 불확실성 측정 (entropy, margin, etc.) |
| Confidence Router | confidence threshold 기반으로 high/low 분류 |
| Sample Selector | 라벨링 queue에 넣을 샘플 선별 (query strategy) |
| Auto-Accumulator | high-confidence 예측을 pseudo-label로 자동 축적 |
| Labeling Bridge | Label Studio API와 연동하여 라벨링 작업 생성/완료 추적 |

확장 포인트: Uncertainty Estimator와 Sample Selector는 domain-specific. Strategy 인터페이스로 교체 가능.

### Pillar 2: Monitoring & Trigger System (눈과 귀)

시스템 상태를 감시하고 파이프라인 이벤트를 발생시키는 감시자.

| 컴포넌트 | 기능 |
|---|---|
| Real-time Metrics | Prometheus: 요청량, latency, confidence 분포 (기존) |
| Drift Detection | Evidently: data drift, prediction drift (기존) |
| Confidence Tracker | 시간에 따른 confidence 분포 변화 추적 (신규) |
| Alert & Trigger | drift/confidence 변화 감지 시 Prefect flow 트리거 |
| Feedback Monitor | pseudo-label 품질 추적, labeling 진행률 모니터링 |

핵심 연결: Monitoring이 Active Learning의 **trigger**.

### Pillar 3: CI/CD Pipeline (품질 보증)

코드와 모델 모두의 품질을 보증하는 자동화 장치.

| 영역 | 파이프라인 |
|---|---|
| Code CI | push → lint(Ruff) → unit test → type check → Docker build |
| ML CI | 모델 재학습 시 → CML 성능 리포트 → champion 대비 비교 |
| Data CI | DVC로 데이터 변경 추적 → 데이터 품질 검증 자동화 |
| CD | quality gate 통과 → MLflow champion 업데이트 → canary 배포 → 전체 전환 |

핵심 연결: CI/CD는 Active Learning loop의 **안전장치**.

### Pillar 4: Orchestration (접착제)

4대 축의 모든 동작을 event-driven으로 연결하는 중추신경계.

| Flow | Trigger | 동작 |
|---|---|---|
| `training_pipeline` | drift alert / labeling complete / manual | 데이터 검증 → 학습 → 평가 → 등록 |
| `monitoring_pipeline` | scheduled / manual | prediction log 분석 → drift 감지 → alert |
| `active_learning_flow` | confidence threshold / drift alert | uncertain 샘플 수집 → Label Studio 전송 → 라벨링 추적 |
| `deployment_flow` | model registered + gate passed | canary 배포 → 모니터링 → 전체 전환 or 롤백 |
| `data_accumulation_flow` | periodic / buffer full | high-confidence pseudo-labels 축적 → DVC 커밋 |

Event chain:
```
drift detected → active_learning_flow → labeling complete → training_pipeline
  → model registered → deployment_flow → monitoring confirms → done
```

---

## 3. Domain-Agnostic Architecture — CV 너머의 확장 설계

### "불변의 흐름 + 가변의 구현"

```
불변의 흐름 (Framework):
  Predict → Measure Uncertainty → Route → Label/Auto-Accumulate → Retrain → Evaluate → Deploy

가변의 구현 (Plugin):
  CV:  softmax entropy  │ Label Studio(image) │ CleanVision │ PyTorch CNN
  NLP: token probability │ Label Studio(text)  │ text quality │ Transformer
  Tab: ensemble variance │ Label Studio(table) │ Great Expect │ XGBoost/etc
```

### 핵심 인터페이스 (Protocol)

```python
class UncertaintyEstimator(Protocol):
    """모델 예측의 불확실성을 측정"""
    def estimate(self, predictions: Any) -> list[float]: ...

class DataValidator(Protocol):
    """도메인별 데이터 품질 검증"""
    def validate(self, dataset_path: Path) -> ValidationReport: ...

class ModelTrainer(Protocol):
    """도메인별 모델 학습"""
    def train(self, config: TrainConfig) -> TrainResult: ...

class SampleSelector(Protocol):
    """라벨링할 샘플 선별 전략"""
    def select(self, uncertainties: list[float], budget: int) -> list[int]: ...
```

### CV Plugin (첫 번째 구현체)

| 인터페이스 | CV 구현 | 현재 위치 |
|---|---|---|
| `UncertaintyEstimator` | Softmax Entropy + Margin Sampling | 신규 |
| `DataValidator` | CleanVision + CleanLab | `src/data/validation/` |
| `ModelTrainer` | PyTorch ClassificationTrainer | `src/training/trainers/` |
| `SampleSelector` | Top-K Uncertain + Diversity Sampling | 신규 |

### 디렉토리 구조 진화

```
src/
├── core/                    # Framework (도메인 무관)
│   ├── active_learning/     # uncertainty routing, sample selection interface
│   ├── orchestration/       # Prefect flows
│   ├── monitoring/          # metrics, drift detection
│   ├── serving/             # FastAPI app, model loading
│   └── ci/                  # quality gates, evaluation
│
├── plugins/                 # Domain-Specific Plugins
│   └── cv/                  # CV Plugin (첫 번째 구현체)
│       ├── uncertainty.py   # softmax entropy estimator
│       ├── validator.py     # CleanVision + CleanLab wrapper
│       ├── trainer.py       # PyTorch classification trainer
│       ├── selector.py      # uncertainty-based sample selector
│       ├── transforms.py    # 이미지 전처리
│       └── models/          # CNN architectures
│
└── common/                  # 공유 유틸리티
```

---

## 4. Quality Gates & Safety — 모든 전환점의 안전장치

### 5-Gate Map

```
[Data] ──G1──▶ [Train] ──G2──▶ [Register] ──G3──▶ [Deploy] ──G4──▶ [Serve]
                                                                       │
                                                            G5 ◀───────┘
```

| Gate | 위치 | 검증 | 실패 시 |
|---|---|---|---|
| G1: Data Quality | 학습 전 | health score > threshold, pseudo-label 비율, 최소 크기 | 학습 차단 |
| G2: Training Quality | 학습 후 | val_accuracy, val_loss, 과적합 여부 | 등록 차단 |
| G3: Champion Gate | 배포 전 | 새 모델 vs champion 성능 비교 | 배포 차단 |
| G4: Canary Gate | canary 후 | error rate, latency, confidence 분포 | 자동 롤백 |
| G5: Runtime Gate | 서빙 중 | drift score, confidence 이상, 에러율 | AL 트리거 or 롤백 |

### Canary Deployment

```
Phase 1: Canary (10%)  →  Phase 2: 30분 검증  →  Phase 3: Full (or 롤백)
Nginx weight 1:9          metrics 비교             weight 10:0 or 0:10
```

### Pseudo-Label 품질 보증

| 검증 | 방법 |
|---|---|
| Confidence Threshold | 기본 0.95 이상만 auto-accumulate |
| Distribution Check | 클래스 편중 검증 |
| Periodic Audit | random sampling → human 검증 |
| Contamination Limit | 전체 데이터 중 pseudo-label 비율 상한 (예: 30%) |

---

## 5. Architecture Evolution — 기존 6-Layer와의 관계

### 6-Layer(인프라) ↔ 4-Pillar(기능) 보완 관계

기존 6-Layer 아키텍처는 인프라 관점의 계층 분리. 4-Pillar는 기능 관점의 역할 분리. 대체가 아니라 보완.

### 핵심 변경 사항

| 영역 | 현재 | 목표 |
|---|---|---|
| 프로젝트 정체성 | CV MLOps 파이프라인 템플릿 | Active Learning-First MLOps Platform |
| 디렉토리 구조 | `src/{data,training,serving,...}` | `src/{core,plugins/cv,...}` |
| 데이터 흐름 | 일방향 (train→serve→monitor) | 순환형 (Data Flywheel) |
| 재학습 트리거 | 수동 / 스케줄 | Event-driven |
| 배포 | 수동 `make up` | Canary 자동 배포 + 롤백 |
| CI/CD | 없음 | GitHub Actions + CML + DVC |
| Active Learning | Demo script만 | Production-grade closed-loop |
| 라벨링 | 없음 | Label Studio 연동 |
| Task 확장성 | Classification only | Plugin 아키텍처 |

### 신규 인프라

| 컴포넌트 | 용도 |
|---|---|
| Label Studio | HITL 라벨링 UI + API (Docker Compose 추가) |
| GitHub Actions | Code CI / ML CI |
| CML | ML 실험 리포팅 |

---

## 6. Implementation Phases — 구현 우선순위

**Phase A: Active Learning Core** (핵심 차별점)
- [ ] Uncertainty Estimator 구현 (softmax entropy for CV)
- [ ] Confidence Router (high/low 분류 로직)
- [ ] Label Studio Docker 연동 + Labeling Bridge API
- [ ] Auto-Accumulator (pseudo-label 축적)
- [ ] `active_learning_flow` Prefect flow
- [ ] `data_accumulation_flow` Prefect flow

**Phase B: Continuous Training Loop** (AL ↔ 재학습 연결)
- [ ] Event-driven retrain trigger (drift → train, labeling complete → train)
- [ ] Champion Gate (새 모델 vs 기존 모델 자동 비교)
- [ ] Training pipeline에 pseudo-label + human-labeled 데이터 통합
- [ ] DVC 데이터셋 버전 관리 자동화

**Phase C: CI/CD & Deployment** (품질 보증 + 자동 배포)
- [ ] GitHub Actions: code CI (lint, test, Docker build)
- [ ] CML: 재학습 시 성능 리포트 자동 생성
- [ ] Canary 배포 (Nginx upstream weight 조절)
- [ ] 자동 롤백 메커니즘

**Phase D: Architecture Refactoring** (확장성)
- [ ] `src/` 디렉토리를 `core/` + `plugins/cv/` 구조로 재편
- [ ] Protocol 인터페이스 정의
- [ ] 기존 코드를 CV Plugin으로 이동
- [ ] 문서 및 테스트 업데이트

---

## Verification

- Phase A 검증: Label Studio에 uncertain 샘플이 자동 전송되는지, pseudo-label이 축적되는지 확인
- Phase B 검증: drift 감지 → 재학습 → champion 비교까지 자동으로 동작하는지 E2E 테스트
- Phase C 검증: PR 생성 시 CI가 돌고, 모델 배포 시 canary가 동작하는지 확인
- Phase D 검증: 기존 모든 테스트가 새 디렉토리 구조에서 통과하는지 확인

---

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-03-29 | Active Learning-First 핵심 사상 확정 | 대부분 MLOps 템플릿에 없는 차별점. closed-loop이 핵심 가치 |
| 2026-03-29 | Dual-Path Data Flywheel 채택 | high confidence → auto, low confidence → human. 모든 데이터가 학습 자산 |
| 2026-03-29 | Label Studio 연동 | On-premises + CV 전용 UI + API 연동 가능. Docker Compose 추가 |
| 2026-03-29 | Event-Driven CT | 스케줄 기반 대신 drift/labeling 완료 기반 재학습 |
| 2026-03-29 | Full ML CI/CD | GitHub Actions + CML + DVC 조합 |
| 2026-03-29 | Domain-Agnostic Plugin 구조 | CV first, NLP/Tabular 향후 확장. Phase D에서 리팩토링 |
| 2026-03-29 | 구현 순서 A→B→C→D | AL Core 먼저 (핵심), 리팩토링 마지막 (YAGNI) |
