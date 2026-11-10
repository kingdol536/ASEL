# Adaptive System Evolution Lab (ASEL)

> **진행 중: M1~M4 구현·실험 완료 (M4 결과는 사용자 승인 전 잠정) / 다음: M5 복수 조건 실험, 3D 시험**  
> 언어: 한국어 · 시작: 2026-11-11 · 1차: 12주 포트폴리오(~2027-02-02) · 2차: 후속 5~12개월 연구

## 한 문장 소개

목표·환경·제약이 변화하는 가상 산업 환경에서, AI와 알고리즘이 **운영 방식과 시스템 구조를 재구성**하고 그로 인해 생기는 후속 병목까지 관찰·검증하는 적응형 시스템 실험 플랫폼.

## 왜 만드는가

기존 업무 하나를 자동화하는 AX를 넘어 **구성요소의 연결, 정보·제어 구조, 권한·계약, 구조 변경 정책**까지 다룰 수 있는 공통 메커니즘의 가능성과 한계를 연구한다. 특정 물류센터의 생산량 증가만으로 범용성을 주장하지 않는다.

## 연구 질문

1. 서로 다른 산업 구조를 공통 모델과 환경별 어댑터로 표현할 수 있는가?
2. AI를 포함한 여러 제어 주체가 제한된 관측·권한으로 협력해 목표 변화를 다룰 수 있는가?
3. 시스템의 구조를 재구성했을 때 새로운 병목과 통제 비용이 어떻게 발생하는가?
4. 단위 기능의 2D 실험을 3D 공간·물리 통합 환경으로 옮길 때 무엇이 유지되고 무엇이 깨지는가?
5. 실험의 가정·한계·비용을 포함해 외부에서 재현할 수 있는 증거를 만들 수 있는가?

## 구현 계획

- **12주:** 최소 공통 모델, 2D/headless 단위 시험, 설정 가능한 AI/정책 인터페이스, 구조 변경, 독립 검증, 제한된 3D 통합 데모, 반복 실험 보고서.
- **후속 5~12개월:** 다중 산업 확장, 다중 물리 결합, 목적 전환·위기 대응, 선택적 정밀도, 통제 및 평가 메커니즘의 공진화.

**중요:** 3D 통합은 목표이나 첫 12주의 범위는 작은 공간·물리 사례로 제한한다. 역할별 AI와 평가지표의 최종 구성은 미확정이다.

## 문서 안내

| 문서 | 읽는 이유 |
|---|---|
| [연구 비전](docs/00-PROJECT-VISION.md) | 목적·핵심 개념·장기 비전 |
| [범위와 요구사항](docs/01-SCOPE-AND-REQUIREMENTS.md) | 확정/미확정, 단계별 범위 |
| [아키텍처](docs/02-SYSTEM-ARCHITECTURE.md) | 책임 경계·상태·인터페이스 |
| [세계 모델](docs/03-WORLD-MODEL.md) | 공통 표현과 시나리오 |
| [AI 시스템](docs/04-AI-AGENT-SYSTEM.md) | AI 후보 역할과 권한 격리 |
| [시뮬레이션·물리](docs/05-SIMULATION-AND-PHYSICS.md) | 2D → 3D, 물리·시간 동기화 |
| [수학](docs/06-MATHEMATICAL-FOUNDATIONS.md) | 이론·수식·적용 조건 |
| [실험](docs/07-EXPERIMENTAL-DESIGN.md) | 검증 방법·비교·공진화 |
| [기술 스택](docs/08-TECHNICAL-STACK.md) | 하드웨어·도구·결정 후보 |
| [로드맵](docs/09-DEVELOPMENT-ROADMAP.md) | 12주 + 확장·완료 게이트 |
| [용어집](docs/10-GLOSSARY.md) | 정의·혼동 방지 |
| [Claude Code 지침](CLAUDE.md) | AI 코딩 협업 규칙 |

## 실행 방법

[uv](https://docs.astral.sh/uv/)가 필요하다.

```bash
uv sync                                              # 의존성 설치
uv run pytest                                        # 불변조건·재현성 테스트
uv run asel run scenarios/warehouse-small-a.yaml     # headless 실행 -> experiments/runs/
uv run asel replay-check experiments/runs/warehouse-small-a/<run_dir>   # 이벤트 로그 재생 검증
```

실행 결과 폴더에는 `events.ndjson`(이벤트 로그), `final_state.json`, `scenario.json`, `manifest.json`(코드 커밋·설정 해시·시드·환경)이 남는다.
시나리오의 수치는 기능 검증용 **가상 값**이다.

## 나중에 공개할 증거물(현재 예정)

재실행 가능한 설정·시드, 코드와 자동 테스트, 환경별 비교 기록, 실패·악화 사례, 2D 상태 시각화, 3D 통합 영상/데모, 검증 보고서, 기여·AI 사용 범위 기록.

## 주의

현재 구현은 논리 세계 코어, 공개/비공개 로그 분리, 정책 규약과 Claude 정책 어댑터, 독립 평가기, 셀 재구성과 구조 정책까지다(M1~M4). 3D 는 아직 없다. 실험 결과는 가상 시나리오의 측정값이며 현실 성능 주장이 아니다 — [M2](experiments/reports/M2-gate.md) · [M3](experiments/reports/M3-gate.md) · [M4](experiments/reports/M4-gate.md) 보고서 참고. 특정 산업에의 적용성은 도메인별 검증이 필요하다.
