# F-001 예측 — AI 주도 구조 재편으로 가는 AX 문제 연쇄 (2026~2030)

- 상태: **사전 고정** — 2026-11-12 작성. 오탈자 외에는 고치지 않는다. 판단이 바뀌면 새 파일로 남긴다([규칙](README.md)).
- 성격: 전부 **예측(가설)** 이다. 시장 규모·도입 시점을 실증하지 않았다.
- 근거: 2026-11-12 웹 조사(검색 약 35건). 대부분 원문 전체가 아니라 검색 요약으로 읽었다. 수치는 §6 출처의 원문 대조가 남아 있다.
- 범위: 12주 필수 범위를 바꾸지 않는다. ASEL 비전 문서 §4(2028~2030 장기 가설)를 구체화한 것이다.

## 1. 궁극 목표 (2029년 이후)

AI가 현장의 운영뿐 아니라 **구조**(설비 역할, 라인 구성, 로봇 배치)까지 목표와 조건 변화에 맞춰 재편하고,
그 재편이 만드는 다음 문제를 발견하고 대응하는 현장. 사람은 목표와 권한의 경계를 정한다.

## 2. 전제 (가설)

- 2026년 업계는 "AI가 과업을 수행한다"(피지컬 AI)와 "AI가 결정을 돕는다"(에이전트) 단계다.
- 2027~28년은 파일럿에서 생산 확장으로 넘어가는 시기와 규제 적용(EU 기계 규정 2027-01, EU AI Act 제품 내장 고위험 2028-08 연기안,
  한국 AI 기본법 2026 시행)이 겹친다. 병목은 로봇·AI의 **능력**에서 **연결·권한·검증·확장**으로 옮겨간다.
- 로봇 형태(휴머노이드 여부)에 걸지 않는다. 휴머노이드의 생산 확장은 2028년까지 소수에 그친다는 예측(Gartner)과
  손재주·안전 비판(Brooks)이 있다. 아래 연쇄는 로봇이 AMR·다기능 로봇이어도 성립하도록 적는다.

## 3. 문제 연쇄 예측

| 단계 | 예측 증상 | 예상 시기 | 근거 수준 | ASEL 현재 기반 |
|---|---|---|---|---|
| ① 위임 | AI가 배정·스케줄을 사람 확인 없이 직접 실행한다. 잘못된 지시가 바로 반영되고 책임 소재가 불분명하다 | 2026~28 (진행 중) | 강함 | 제안→검증→적용→사건 계약, 정답 격리 (EXP-001 안전 위반 0) |
| ② 확장 | 한 현장에서 된 AI를 다른 현장·벤더로 복제하면 결과가 뒤집히는데, 투입한 뒤에야 안다 | 2027~29 | 강함 | 3개 환경 이식, EXP-003 (같은 구조 제어가 B 에서 −16%, C 에서 시간 초과 약 7배) |
| ③ 구조 재편 | AI가 설비 역할·라인 구성·로봇 배치를 바꾼다. 언제 바꿀지, 전환 비용과 중단을 감수할 가치가 있는지가 쟁점이 된다 | 2028~30 | 중간 | 셀 역할 전환, EXP-002 (이득 조건의 경계), 3D 천장 제약 |
| ④ 2차 효과 | 재편이 병목을 다른 곳으로 옮긴다. 재편이 잦으면 전환 비용과 혼란으로 현장이 진동한다 | 2029~ | 약함 | EXP-002 병목 이동, EXP-003 C 에서 역할을 바꿨다 되돌리며 만든 처리 공백 |
| ⑤ 다중 주체 | 여러 벤더 관제·AI가 총괄자 없이 각자 재편해 충돌한다. 목표가 엇갈리고 자원을 다툰다 | 2029~30 이후 | 중간~약함 | 없음 (구조 제어 주체 분리 #21 이 출발점) |
| ⑥ 자기 대응 | AI가 자기 재편의 결과를 감지해 재조정하고, 한계를 넘으면 멈추고 사람에게 넘긴다 | 2030 이후 | 약함 | 독립 평가기·병목 지표 (AI 바깥에서만 감지) |

판단 비용(어느 결정에 AI를 부르고 어느 결정을 규칙에 맡길지)은 ①~⑥ 전체에 걸쳐 나타난다.
ASEL 기반: EXP-001(사건마다 부르는 배정은 비용 대비 이득 없음), EXP-003(빈도를 제한한 구조 제어는 비용 1~20% 수준).

### 단계 사이의 연결 (원인 → 다음 문제)

- ①→②: 한 현장에서 권한·검증 체계가 잡히면 같은 AI를 다른 현장으로 복제한다.
  원인 가설: 현장마다 관측 항목·제약·지표 정의가 다르고, AI가 모르는 제약이 있다(EXP-003: 관측에 시간 제한이 없음).
- ②→③: 운영 수준 최적화의 이득은 금방 바닥나고, 남은 수단은 구조다.
  ASEL 관측: Claude 배정은 FIFO 와 1% 미만 차이(EXP-001), 이득은 구조 제어에서 나왔다(EXP-003 B −16%).
- ③→④: 재편은 국소 최적화이고 전환 비용·지연 효과가 있다. 한 병목을 풀면 다음 제약이 드러난다.
- ④→⑤: 여러 주체가 각자 2차 효과에 대응하면 대응끼리 충돌한다.
- ⑤→⑥: 재편 빈도가 사람이 검토할 수 있는 한도를 넘는다.

## 4. 선행 연구와의 관계 (2026-11-12 조사 기준)

| 단계 | 이미 있는 연구 줄기 | 조사에서 찾지 못한 것 |
|---|---|---|
| ③ | 재구성형 제조 시스템(RMS, Koren 등 1999~), 강화학습 재구성 계획(2024~2026), **LLM 에이전트 재구성(2025~2026 활발)**: 요구-능력 정합 후 AAS 생성, 모듈별 LLM 에이전트 제어, 레이아웃 생성 | 재편을 **언제 시작할지**(트리거)를 다룬 리뷰 |
| ④ | 이동 병목 탐지(Roser 2002~2021, 예측 2018), 스케줄 불안정(nervousness)과 안정성-비용 균형, 디지털 트윈 재구성 계획이 새 병목 공정을 만든 사례(2025), LLM 결정 진동(2026) | AI 재편 결정의 2차 효과(병목 이동·진동)를 **투입 전 검증 대상**으로 다루는 체계 |
| ⑤ | 홀로닉 제조(PROSA, ADACOR), 다중 에이전트 제조 제어. 산업 채택이 약하고 레거시 연동이 미해결 | — |
| ⑥ | 자기 적응 시스템 MAPE-K 루프, 생성형 AI 기반 자기 적응 시스템 서베이(2025, 논문 219편) | 물리 현장의 구조 재편에 적용한 사례 |
| 기반 | 능력·스킬 모델과 AAS (plug and produce), OPC UA·ISA-95·VDA 5050·ISO 21423 | 통신 표준 위의 구조·제약·권한 의미 계층을 여러 산업에 걸쳐 시험한 사례 |

**선점 지점 (가설):** "AI가 구조를 재편한다" 자체는 이미 경쟁이 있다. 비어 있는 것은
**AI의 재편 결정이 만드는 2차 효과를 투입 전에 드러내고 판정하는 검증 — 정답을 보지 않는 AI를 대상으로, 이질적 현장에 걸쳐** 다.
못 찾았다는 것이 없다는 뜻은 아니다. 검색 약 35건 기준이다.

## 5. 나중에 대조할 관측

| 단계 | 지지 관측 (기한) | 반증 관측 |
|---|---|---|
| ① | 2028 말까지 AI 실행 권한 경계·실행 전 검증이 주요 제품·표준·규제 지침에서 독립 항목으로 다뤄진다 | 2028 말에도 AI 실행이 사람 승인 단계 밖으로 거의 나가지 않는다 |
| ② | 2028 말까지 "여러 현장으로의 확장 실패"가 산업 AI 도입 장애 상위 3개 안에 남는다 | 2027~28 설문에서 다중 현장 확장이 주요 장애에서 빠진다 |
| ③ | 2029 말까지 상용 MES·오케스트레이션 제품이 설비 역할·라인 구성 변경을 AI가 제안하는 기능을 출시한다 | 2030 까지 구조 변경이 사람 엔지니어링 작업으로만 남는다 (③ 이후 연쇄 전체 약화) |
| ④ | 2030 까지 재편 후 병목 이동이나 재편 진동이 실무 보고·논문에서 AI 운영 문제로 명명된다 | ③ 이 실현됐는데도 2차 효과가 문제로 보고되지 않는다 |
| ⑤ | 2030 까지 다중 벤더 관제 간 재편·과업 충돌 조정이 표준(ISO 21423 후속 등)이나 제품 기능으로 다뤄진다 | 단일 플랫폼 독점으로 총괄자 없는 공존이 드물어진다 |
| ⑥ | 2030 이후 AI 재편 루프에 자동 정지·권한 강등·사람 이관 장치가 요구 사항으로 등장한다 | — (기한이 길어 이 문서에서는 판정 기준만 남긴다) |

## 6. 출처

예측·전망
- Gartner, 에이전틱 AI 프로젝트 40% 이상 취소 예측 (2025-06): https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027
- Gartner, 휴머노이드 생산 확장 20곳 미만 예측 (2026-01): https://www.gartner.com/en/newsroom/press-releases/2026-01-21-gartner-predicts-fewer-than-20-companies-will-scale-humanoid-robots-for-manufacturing-and-supply-chain-to-production-stage-by-2028
- IDC, AI 주도 제조의 미래 (2029 소프트웨어 정의 자동화 30%): https://www.idc.com/resource-center/blog/charting-the-ai-driven-future-of-manufacturing/
- Deloitte Tech Trends 2026, AI goes physical: https://www.deloitte.com/us/en/insights/topics/technology-management/tech-trends/2026/physical-ai-humanoid-robots.html
- WEF, Physical AI: Powering the New Age of Industrial Operations (2025-09): https://www.weforum.org/publications/physical-ai-powering-the-new-age-of-industrial-operations/
- IFR World Robotics 2025: https://ifr.org/ifr-press-releases/news/global-robot-demand-in-factories-doubles-over-10-years

현장·설문·제품
- TCS, Physical AI in Manufacturing: https://www.tcs.com/content/dam/global-tcs/en/pdfs/what-we-do/industries/manufacturing/physical-ai-in-manufacturing.pdf
- SAP Physical AI (2026-10): https://news.sap.com/2026/10/sap-unveils-physical-ai-extends-autonomous-enterprise-real-world-sap-teched/
- NVIDIA Mega Omniverse Blueprint: https://blogs.nvidia.com/blog/mega-omniverse-blueprint
- Boston Dynamics Atlas, 현대차 투입 계획: https://bostondynamics.com/blog/boston-dynamics-unveils-new-atlas-robot-to-revolutionize-industry/
- ISO 21423 다중 벤더 이동 로봇 공존: https://www.marketscale.com/industries/industrial-iot/a-373-iso-standard-lets-mobile-robots-from-different-vendors-share-a-floor

규제
- EU 기계 규정 2023/1230 해설 (UL): https://www.ul.com/resources/navigating-new-eu-machinery-regulation-eu-20231230
- EU AI Act 디지털 옴니버스 일정 (2차 보도): https://secureprivacy.ai/blog/eu-ai-act-digital-omnibus-the-new-high-risk-ai-deadlines-after-council-approval

선행 연구
- LLM 에이전트 재구성: CRAFT-AI (arXiv 2611.12092) https://arxiv.org/html/2611.12092 · LLM-Driven Multi-Agent Control for Skill-Based Smart Manufacturing (arXiv 2610.01364) https://arxiv.org/abs/2610.01364 · LLM agents-driven layout generation for RMS https://www.sciencedirect.com/science/article/pii/S0007850626000144 · Pretrained LLMs as Real-Time Controllers (arXiv 2503.03889) https://arxiv.org/html/2503.03889
- 강화학습 재구성 계획: https://dspace.lib.cranfield.ac.uk/handle/1826/24084 · https://www.engineering.org.cn/engi/EN/10.1016/j.eng.2026.05.019
- RMS 원칙과 전망 (Koren 등 2018): https://journal.hep.com.cn/fme/EN/Y2018/V13/I2/121
- 이동 병목 탐지 (Roser 등 2002): https://www.informs-sim.org/wsc02papers/145.pdf · 병목 예측: https://research.chalmers.se/publication/505673
- 디지털 트윈 기반 동적 라인 재구성 (arXiv 2506.07332): https://arxiv.org/pdf/2506.07332
- 홀로닉 제어 아키텍처와 과제 (arXiv 2002.04525): https://arxiv.org/pdf/2002.04525
- 생성형 AI 기반 자기 적응 시스템 서베이 (arXiv 2512.04680): https://arxiv.org/pdf/2512.04680
- 능력·스킬 모델과 AAS (arXiv 2307.00827): https://arxiv.org/abs/2307.00827v2
- 다중 에이전트 LLM 실패 분류 (arXiv 2503.13657): https://arxiv.org/abs/2503.13657v2
- LLM 집단 결정의 불안정 (alphaXiv 2603.09127): https://www.alphaxiv.org/abs/2603.09127

비판적 의견
- Rodney Brooks, 휴머노이드 손재주·안전 비판 (2025-09): https://techcrunch.com/2025/09/26/famed-roboticist-says-humanoid-robot-bubble-is-doomed-to-burst
