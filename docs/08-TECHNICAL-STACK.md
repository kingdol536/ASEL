# 08. 기술 스택 및 구현 환경

> **문서 상태:** 개정안. **확정:** 핵심 시뮬레이션과 3D 렌더링의 분리, 2D 기능 검증→3D 물리 통합, headless 실험 및 시뮬레이션의 재현성. **잠정:** Python/SimPy 등 코어 후보. **미결정:** 주력 3D 렌더러·전문 물리 엔진·AI 실행 모델·최종 성능/평가 지표.  
> 관련 문서: `02-SYSTEM-ARCHITECTURE.md`, `04-AI-AGENT-SYSTEM.md`, `05-SIMULATION-AND-PHYSICS.md`, `07-EXPERIMENTAL-DESIGN.md`, `09-DEVELOPMENT-ROADMAP.md`.

## 1. 개발 환경과 하드웨어

| 항목 | 값·원칙 |
|---|---|
| GPU | NVIDIA GeForce **RTX 4070 Ti**, VRAM **12GB** |
| CPU | **AMD Ryzen 5 7600**, 6코어/12스레드 |
| RAM | **32GB** |
| 개발 에이전트 | **Claude Code** 중심으로 설계·코딩·테스트 보조 |
| 세계 내부 실행 AI | **미결정**: LLM API/규칙 정책/최적화 정책을 교체 가능한 어댑터로 연결 |
| OS | **Windows 11 Home** (2026-11-11 확인). Python 3.13.1, uv 0.7.19, git 2.50 설치됨 |
| 저장소 | GitHub `kingdol536/ASEL` (public), 기본 브랜치 `main` |
| 1차 일정 | **12주** 동안 독립적인 포트폴리오·제한된 3D 통합 검증 (2026-11-11 ~ 2027-02-02) |
| 후속 확장 | **추가 5~12개월**: 다중 물리·복원력·정밀도 조정·범용성 확장 |

**Claude Code를 개발에 사용하는 것과 가상 세계 내부에서 Claude 모델을 실행하는 것은 별개**다. API 권한·요금·응답 지연·호출 횟수는 별도로 검토한다. 하드웨어가 복잡한 3D 장면의 성능을 보장한다는 의미도 아니다.

## 2. 기술 선택의 우선순위

1. **연구 정합성:** 상태·작업·물리 모델의 의미와 검증 경계를 올바르게 표현하는가?
2. **독립성:** 렌더러·물리 솔버를 바꿔도 공통 세계 모델·정책/실험 기록을 재사용할 수 있는가?
3. **재현성:** Headless 반복 실행, 입력/시드/버전 고정, 로그·리플레이, 자동 테스트가 가능한가?
4. **통합 비용:** Ryzen 5 7600/32GB RAM/4070 Ti에서 구현·디버깅·시연이 감당 가능한가?
5. **확장성:** 3D 공간 제약·전문 물리·산업별 모델·다수 AI 역할을 인터페이스 뒤에 추가할 수 있는가?

**금지할 전제:** 게임 엔진을 물리 시뮬레이터의 유일한 원천으로 고정하지 않는다. 반대로 전문 물리 솔버가 3D 렌더링 UI까지 자동 제공한다고 가정하지 않는다.

## 3. 분야별 기술 후보와 상태

| 계층 | 후보 | 용도 | 결정 상태·검증 사항 |
|---|---|---|---|
| 논리 시뮬레이션 | Python + **자체 이산 사건 루프** (SimPy 미채택) | 사건·대기열·자원 경합·재구성 상태 | **잠정**(2026-11-11). 근거·재검토 조건: `docs/decisions/0001-own-event-loop.md` |
| 공통 데이터 계약 | 코어는 dataclass, 시나리오 입력 경계는 Pydantic | `WorldState`, `Action`, `Event` 검증/직렬화 | 잠정. 런타임 비용 확인 |
| 관계 그래프 | NetworkX | 구조·의존성·관측 범위 분석 | 잠정. 큰 그래프는 대체 가능 |
| 최적화 | Google OR-Tools | 배치·할당·선후관계·제약 탐색 | 잠정. 실제 적용 문제부터 결정 |
| 데이터/통계 | NumPy, SciPy, pandas | 확률 실험·통계·검증 | 우선 검토 |
| 2D 기능 뷰 | 간단한 Python 뷰어 또는 웹 2D | 상태·관계·경로·오류 시각화 | **도구 미정**. 실험 코어와 분리 |
| 3D 실시간 엔진 | Godot 4, Unity | 장면 구성·카메라·상호작용·기본 물리 | **후보**. 게임 엔진 채택 의무 없음 |
| 웹 3D 렌더러 | Three.js | 가벼운 웹 기반 공간 시연·외부 평가 | **후보**. 별도 물리/상태 코어 필요 |
| 전문 역학 솔버 | MuJoCo | 로봇 관절·접촉·제어 검증 | **후속 후보**. 적용 조건이 있을 때 도입 |
| 로봇 통합 시뮬레이터 | Gazebo | 로봇·센서·물리·ROS 연동 | **후속 후보**. 구축 비용 평가 |
| 3D 데이터/산업 플랫폼 | OpenUSD, Omniverse, Isaac Sim | 3D 자산/산업·로봇 환경 확장 | **후속 후보**. HW 요구 및 라이선스·버전 확인 |
| 다중 물리 연결 | FMI/FMU, Modelica | 별도 물리 모델의 계약 및 공동 실행 | **후속 후보** |
| AI 모델 어댑터 | API 기반 LLM + mock/rule/optimization 정책 | 역할·권한·모델을 고정하지 않는 실행 | 구조 원칙 확정, 구체 모델 미정 |
| 테스트·CI | pytest, Git, GitHub Actions | 불변조건·회귀·빌드·공개 검증 | 우선 검토 |
| 실험 파일 | YAML + NDJSON + JSON/Parquet | 시나리오·사건·집계 결과·버전 | 잠정. 스키마 버전 필수 |

**MVP에서는 표에 나온 기술을 전부 설치하지 않는다.** 초기에는 논리 코어, 정책 계약, 실험 파일, 한 가지 단순한 뷰어로 출발하며 3D와 전문 물리 결합은 단계적으로 추가한다.

## 4. 권장 구조: 교체 가능한 렌더러 + 물리 어댑터

```text
src/core/        # WorldState, sim clock, logical transitions, invariants
src/domains/     # scenario/world adapters
src/policies/    # rules/optimizers; future LLM adapters
src/agents/      # optional role runtime, scoped observations
src/physics/     # PhysicsAdapter, units, stepping, result mapping
src/evaluation/  # independent metrics + private truth
src/io/          # scenarios, event protocol, snapshots, replay
experiments/     # seeds/configs/results/repro scripts
viewer-2d/      # small relationship/spatial viewer
viewer-3d/      # render/interaction adapter, engine TBD
tests/          # property/invariant/integration/replay tests
```

```text
                         [AI/Policy Adapter]
                               |
                      [Validated Proposals]
                               v
[Scenario Runner] --> [Logical World + Coordinator] <---> [PhysicsAdapter]
                           |             |
                           |        [World State Events]
                           |             |
                    [Independent Eval]   +--> 2D viewer
                                         +--> 3D viewer
                                         +--> saved replay
```

이 구조는 **논리적 모듈 분해 초안**이므로 실제 패키지 위치는 조정 가능하다. 정답 접근과 운영 AI 관측의 정보 경계는 `04-AI-AGENT-SYSTEM.md`에 따른다.

## 5. 시뮬레이션·물리·렌더러의 최소 계약

| 계약 | 필수 내용 | 첫 검증 |
|---|---|---|
| `WorldAdapter` | 도메인 개체·작업·관계·제약을 공통 스키마로 변환 | 도메인 환경 추가 시 코어 변경량 |
| `SimulationCore` | `reset`, `step`, `apply`, 시각·버전·이벤트 발행 | 같은 입력/시드로 논리 결과 재현 |
| `PolicyAdapter` | 허가된 관측→행동 제안 | 무효 행동 거부, 숨겨진 정보 누출 방지 |
| `PhysicsAdapter` | 물리 입력 설정, `step(dt)`, 상태/접촉 결과, 오류 리포트 | 기하학·충돌 제약이 실제 실행 가능성에 반영 |
| `RenderAdapter` | 스냅샷/이벤트→2D/3D 장면, 조작은 요청으로만 반환 | 화면 FPS 변화가 논리 이벤트를 바꾸지 않음 |
| `EvaluationAdapter` | 비공개 참값·공개된 성능 결과 분리 | 결과 신뢰성·누출 테스트 |

구현에 앞서 `02-SYSTEM-ARCHITECTURE.md`의 **상태 변수별 권위**를 준수해야 한다. Python과 3D 엔진이 같은 물체의 위치를 동시에 독립 계산하면 안 된다. 물리 상태를 솔버가 소유하는 경우 그 결과를 코디네이터가 검증·동기화하고 이후 논리 사건과 관측을 생성한다.

## 6. 2D/3D 엔진 선정 실험(Technology Spike)

브랜드 선호가 아니라 **작은 동일 시나리오**로 비교한다. 비교 대상은 최소한 다음과 같은 구성안이다.

- **대안 A:** Python 논리 코어 + Godot 또는 Unity 3D 클라이언트(내장 충돌은 제한된 시험용).
- **대안 B:** Python 논리 코어 + Three.js 3D 클라이언트(물리 검증은 독립 모듈).
- **대안 C(후속 필요 시):** Python 논리 코어 + MuJoCo/Gazebo 물리 어댑터 + 교체 가능한 3D 뷰어.

**프로토타입 장면:** 정적 설비 20~100개, 이동체 수십 개(측정용 예시), 한 가지 구조 변경, 높이가 다른 경로 교차 또는 3D 충돌/점유 제약 하나. 저장된 동일한 사건/상태를 재생하고 장면 로딩, 구현 시간, 실험 일치성, CPU·GPU·메모리 부담을 측정한다.

**선정 기준:** ① 핵심 상태 모델과 독립성, ② 3D 물리 제약의 실제 검증 가능성, ③ 개발·디버깅 시간, ④ RTX 4070 Ti/32GB에서의 시연 성능, ⑤ 향후 전문 물리 어댑터 교체 용이성. 주력 엔진 선정은 결과를 기록한 후 결정하며 현재는 미확정이다.

## 7. 실행 모드 및 데이터 교환

1. **기본:** `scenario + seed → headless run → event log/snapshots → 2D/3D replay`.
2. **확장:** 제어 AI가 관측을 받고 행동을 제안하면 검증기가 검사한 뒤 시뮬레이터가 적용한다.
3. **3D 물리 결합:** 필요한 객체와 시간 구간에 물리 `step(dt)` 호출 후 결과를 세계 상태로 동기화한다.
4. **실시간 협력:** 결과·정책 제어에 실제 요구가 생기면 파일 재생에서 소켓/IPC로 확장한다. 처음부터 분산 서비스/메시지 브로커를 구축하지 않는다.

이벤트 예시 필드: `schema_version`, `run_id`, `seq`, `sim_time`, `world_version`, `source`, `event_type`, `entity_id`, `payload`. `PhysicsAdapter` 결과에는 물리 모델 ID/버전, 단위, `step_id`를 추가한다.

## 8. 성능 예산과 계측

성능은 목적에 맞춰 **독립적으로** 기록한다.

| 구분 | 지표 예시 | 판단 내용 |
|---|---|---|
| 논리 실험 | `runs_per_min`, 이벤트/초, CPU 사용량 | 반복 검증 가능성 |
| 물리 솔버 | `physics_step_ms`, 안정적인 `dt`, 오류/불일치 | 정확도와 계산 비용의 균형 |
| 렌더러 | `render_cpu_ms`, `render_gpu_ms`, FPS, VRAM | 3D 장면 표현 성능 |
| AI 실행 | 호출/실험, 지연·토큰·비용, 실패율 | 정책 실행 비용·안정성 |
| 시스템 결합 | 메시지 지연, 상태 동기화 불일치, 재생 차이 | 계층 간 일관성 |

1080p·60FPS는 **벤치마크 후보**로만 사용한다. GPU 부하가 낮다고 물리적 정확도가 높다는 뜻은 아니며, 높은 FPS가 대량 반복 실험의 처리량을 보장하지도 않는다.

## 9. 12주 도입 순서와 장기 후보

| 단계 | 우선 기술 | 구현 원칙 |
|---|---|---|
| W1–4 | Python/SimPy 후보 + 최소 스키마 + headless + 2D 관계 뷰, W3–4부터 소형 3D 엔진 시험 병행 | 세계 상태·이벤트·불변조건을 먼저 정확하게 구현하고 렌더러 연결 가능성 확인 |
| W5–8 | 정책 어댑터, 규칙/최적화 기준선, 독립 검증, 구조 재구성 | 정책 효과와 부작용을 데이터로 기록 |
| W9–10 | 앞서 시작한 3D 기술 시제품의 본격 통합, 모델/상태 교환 시험, 다른 환경/목표 시나리오 | 초기 기술 시험 결과에 따라 렌더러를 선택하고 3D 고유 제약을 검증 |
| W11–12 | 선택한 뷰어에서 최소 3D 통합 및 제약 검증, 공개 데모 | 예쁜 장면보다 2D 가정과 3D 물리 제약의 차이를 증명 |
| 이후 5~12개월 | MuJoCo/Gazebo, OpenUSD/Omniverse, FMI/Modelica 등 | 실제 연구 필요와 하드웨어 검증 결과에 따라 선택적 채택 |

이 표의 구현 기간은 `09-DEVELOPMENT-ROADMAP.md`를 **대체하지 않으며**, 기술 도입 흐름만 구체화한다. 물리 계산이 중요한 3D 기능은 W11–12 이전에 작은 시험을 병행할 수 있다.

## 10. 자동화·보안·도입 제한

- API 키 및 비공개 데이터는 버전 관리에서 제외한다. 민감 산업 자료 없이 합성 데이터를 기본으로 사용한다.
- AI 생성 코드는 상태 전이, 데이터 권한, 시뮬레이터 검증 등 핵심 동작을 자동 테스트로 확인한다.
- 모든 실험에 스키마 버전·설정·시드·코드 버전·엔진 버전·모델 버전을 기록한다.
- 초기에는 대규모 Kubernetes, 별도 벡터 DB, 대형 로봇 모델 학습, 고충실도 센서 시뮬레이션, 복잡한 멀티 에이전트 프레임워크를 필수로 넣지 않는다.
- 엔진/솔버 추가는 **필요 조건·비교 기준·간단한 대안의 한계**가 기록됐을 때만 승인한다.

## 11. 공식 참고 자료(버전·라이선스·시스템 요구사항은 도입 시 재검토)

- Python: https://docs.python.org/3/
- SimPy: https://simpy.readthedocs.io/
- NetworkX: https://networkx.org/documentation/stable/
- Google OR-Tools: https://developers.google.com/optimization
- Godot: https://docs.godotengine.org/
- Unity: https://docs.unity3d.com/
- Three.js: https://threejs.org/docs/
- MuJoCo: https://mujoco.readthedocs.io/
- Gazebo: https://gazebosim.org/docs
- OpenUSD: https://openusd.org/release/index.html
- NVIDIA Omniverse: https://docs.omniverse.nvidia.com/
- NVIDIA Isaac Sim: https://docs.isaacsim.omniverse.nvidia.com/
- FMI: https://fmi-standard.org/
- Modelica: https://modelica.org/
- pytest: https://docs.pytest.org/

**공식 문서 링크는 선택 후보의 출발점이다.** 확정된 소프트웨어 버전·라이선스·하드웨어 호환성을 의미하지 않는다.
