# 0002. Python 패키지 위치: `src/asel/`

- 상태: **확정** (2026-11-11)
- 관련: `docs/02` §7, `docs/08` §4

## 맥락

`docs/02` §7의 디렉터리 구조는 `src/core/`, `src/io/` 처럼 `src/` 바로 아래에 모듈을 둔다.
그대로 Python 최상위 패키지로 만들면 `io`가 표준 라이브러리 `io`와 이름이 충돌한다.

## 선택

모듈 구분은 문서 그대로 유지하되, 한 단계 아래 `src/asel/`에 둔다:
`src/asel/core`, `src/asel/io`, `src/asel/domains`, `src/asel/policies` 등.
`viewer-2d/`, `viewer-3d/`, `experiments/`, `tests/`는 저장소 최상위에 그대로 둔다.

## 대안 포기 비용

없음. 이름만 `asel.` 접두사가 붙는다.

## 재검토 조건

뷰어를 다른 언어(예: Godot/Three.js)로 만들 때 공유 스키마 위치를 다시 정한다.
