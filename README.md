# Adaptive System Evolution Lab (ASEL)

> **진행 중: M1~M5·EXP-003 완료, M6 통합 포트폴리오 진행 중** (M4 결과는 사용자 승인 전 잠정)  
> 언어: 한국어 · 시작: 2026-11-11 · 1차: 12주 포트폴리오(~2027-02-02) · 2차: 후속 5~12개월 연구

## 한 문장 소개

서로 다른 산업 현장(물류·조립·IT 서비스)을 **하나의 공통 언어로 조립해 표현**하고, 그 위에서 규칙 정책과 AI(Claude)가
작업 배정과 **시스템 구조 변경**을 판단하게 한 뒤, 그 판단이 만드는 이득·비용·새 병목을 **재현 가능한 실험**으로 검증하는 엔진.

## 왜 만드는가

업무 하나를 자동화하는 AX 를 넘어, 구성요소의 연결·제어 구조·권한·구조 변경 정책까지 다루는 공통 메커니즘의
가능성과 한계를 연구한다. 특정 현장의 생산량 증가만으로 범용성을 주장하지 않는다.

## 지금까지의 결과 (모두 가상 시나리오의 실제 측정값)

| 실험 | 질문 | 결과 | 보고서 |
|---|---|---|---|
| EXP-001 (270회) | Claude 배정 정책이 정답을 보지 않고 안전하게 판단하는가 | 안전 경계 위반·숨겨진 값 누출 0, 무효 제안 0%. 처리 시간은 FIFO 와 거의 같음 (가설 2개 지지, 2개 반증) | [M3](experiments/reports/M3-gate.md) |
| EXP-002 (810회) | 셀 역할 전환(구조 변경)은 언제 이득이고, 병목을 옮기는가 | 전환이 싸고 수요 급증이 클수록 이득, 전환이 비쌀수록 이득 감소(뒤집힘은 관측 안 됨), 구조 변경이 병목을 다른 곳으로 옮김 | [M4](experiments/reports/M4-gate.md) (잠정) |
| M5 이식성 | 다른 산업에도 엔진을 옮길 수 있는가 | 조립 라인: 코어 수정 0줄. 동결 뒤 설계한 IT 서비스: 코어 23줄(행동 1개 추가). 물류용 구조 정책은 IT 환경에서 시간 초과를 4~7배로 늘림(탐색적) | [M5](experiments/reports/M5-gate.md) |
| EXP-003 (415회) | AI 의 판단(배정·구조 제어)도 다른 산업으로 옮겨지는가 | Claude 구조 제어: 조립 라인에서 처리 시간 16% 단축(30/30 시드, 규칙 정책보다 좋음), IT 서비스에서 시간 초과 취소 약 7배(역할을 되돌리며 처리 공백을 만듦, 시간 제한은 관측에 없음). Claude 배정: 유효·안전하고 FIFO 대비 비열등이나 무료 규칙보다 낫지 않고 비쌈 (가설 5개 지지, 2개 반증, 1개 판정 불가) | [EXP-003](experiments/reports/EXP-003.md) |

실험마다 계획서를 실행 전에 커밋·푸시해 고정했고(사전 등록), 결과를 본 뒤 바꾼 분석은 '탐색적'으로 따로 표시한다.

## 빠르게 실행하기

[uv](https://docs.astral.sh/uv/) 와 Python 3.13 이 필요하다. API 키는 **필요 없다** (Claude 실행은 녹화된 응답을 재생).

```bash
uv sync                                                    # 의존성 설치
uv run pytest                                              # 자동 테스트 (불변조건·재현성·정답 누출)
uv run asel run scenarios/assembly-line-b.yaml --structure p1   # 조립 라인 1회 실행 -> experiments/runs/
uv run asel view experiments/runs/assembly-line-b/<run_dir>     # 2D 화면(HTML): 공정 흐름·타임라인·대기열
uv run asel replay-check experiments/runs/assembly-line-b/<run_dir>   # 사건 로그만으로 상태 재구성 검사
```

### 기록된 실험 재현

```bash
uv run python experiments/configs/reproduce.py check --sample 30   # 실험마다 표본 재현 (몇 분)
uv run python experiments/configs/reproduce.py check               # 전체 1,495회 (EXP-001 270, EXP-002 810, EXP-003 415)
```

저장소에 커밋된 실행 목록(`runs_index.csv`)대로 다시 실행해, 사건 로그의 SHA-256 이 기록과 바이트 단위로 같은지 대조한다.
재현은 항상 녹화된 응답만 쓴다(API 키 불필요, 호출 0). 캐시가 없으면 Claude 실행은 건너뛰고 그 수를 따로 보고한다.

원자료와 Claude 응답 캐시는 GitHub Release [`data-v1`](https://github.com/kingdol536/ASEL/releases/tag/data-v1) 에 있다
(체크섬: [`SHA256SUMS.txt`](experiments/reports/assets/data-v1/SHA256SUMS.txt)).

```bash
# Claude 실행까지 재현: llm-cache.zip 을 빈 폴더에 풀면 그 안에 cache/ 가 생긴다. 그 폴더를 지정
ASEL_LLM_DIR=<푼 폴더> uv run python experiments/configs/reproduce.py check --sample 30
# 원자료(실행별 사건 로그·manifest·평가): batches-<실험>.zip 을 저장소 루트에 풀면 experiments/batches/ 로 복원
```

실행 폴더에는 `events.ndjson`(공개 사건 로그), `private_events.ndjson`(숨겨진 참값, 평가기 전용),
`final_state.json`, `scenario.json`, `manifest.json`(코드 커밋·설정 해시·시드·환경)이 남는다.

## 구성

| 위치 | 내용 |
|---|---|
| `src/asel/core` | 세계 상태, 행동 검증(`제안 → 검증 → 적용 → 사건`), 불변조건, 사건 기반 시뮬레이터 |
| `src/asel/domains` | 도메인 어댑터 — 범용 작업 흐름(`job_flow`) 하나로 물류·조립·IT 를 설정 파일로 표현 |
| `src/asel/policies`, `src/asel/agents` | 관측 투영·정책 규약, 규칙 정책(FIFO·P0/P1/P2 등), Claude 배정·구조 제어 정책 |
| `src/asel/evaluation` | 독립 평가기(공개 로그만), 병목 지표, 대응 부트스트랩 비교 |
| `scenarios/` | 시나리오(가상 값) — 환경 A 물류, B 조립 라인(+3D 높이 제약), C IT 서비스 |
| `experiments/plans`, `experiments/reports` | 사전 고정 계획서, 게이트 보고서와 원자료 요약 |

## 문서 안내

| 문서 | 읽는 이유 |
|---|---|
| **[한 장 요약](docs/SUMMARY.md)** | 연구 질문·환경·결과·결론·한계를 한 화면에 |
| [연구 비전](docs/00-PROJECT-VISION.md) · [범위와 요구사항](docs/01-SCOPE-AND-REQUIREMENTS.md) | 목적, 확정/미확정 |
| [아키텍처](docs/02-SYSTEM-ARCHITECTURE.md) · [세계 모델](docs/03-WORLD-MODEL.md) | 책임 경계·상태·인터페이스 |
| [공통 언어](docs/11-COMMON-LANGUAGE.md) | 엔진의 부품(개념·관계·행동·사건) — 코드에서 자동 생성 |
| [AI 시스템](docs/04-AI-AGENT-SYSTEM.md) · [AI 사용 기록](docs/12-AI-USAGE.md) | AI 역할 후보, 개발 도구 vs 실험 대상 AI, 사람이 내린 결정 |
| [시뮬레이션·물리](docs/05-SIMULATION-AND-PHYSICS.md) · [수학](docs/06-MATHEMATICAL-FOUNDATIONS.md) | 2D → 3D, 지표의 정의 |
| [실험 설계](docs/07-EXPERIMENTAL-DESIGN.md) · [로드맵](docs/09-DEVELOPMENT-ROADMAP.md) | 검증 방법, 단계와 통과 조건 |
| [결정 기록](docs/decisions/README.md) · [용어집](docs/10-GLOSSARY.md) | 기술 선택의 근거와 상태 |
| [Claude Code 지침](CLAUDE.md) | AI 코딩 협업 규칙 |

## 주의

- 모든 시나리오 수치는 기능 검증용 **가상 값**이며, 실험 결과는 현실 성능 주장이 아니다.
- 3D 는 정적 배치·천장 높이 제약을 엔진에서 검증하는 수준이다(그래픽 없음, [결정 0007](docs/decisions/0007-3d-graphics-deferred.md)).
- 3개 환경의 결과를 모든 산업의 범용성으로 해석하지 않는다. 산업별 적용성은 도메인별 검증이 필요하다.
- 시뮬레이션 안 AI 의 최종 역할·권한 구성과 최종 평가 지표는 아직 **미결정**이다.
