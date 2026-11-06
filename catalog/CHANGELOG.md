# 개념사전 변경 내역

## 0.15.0

- dic-maker로 3단계에 주제 18개, 용어 40개를 더했다
- 분야별: plan 13개, db 11개, llm 9개, rag 12개, mlops 13개

## 0.14.0

- dic-maker로 3단계에 주제 18개, 용어 42개를 더했다
- 분야별: dev 13개, fe 12개, ax 11개, ops 13개, ml 11개

## 0.13.0

- dic-maker로 3단계에 주제 18개, 용어 41개를 더했다
- 분야별: plan 11개, db 13개, llm 13개, rag 12개, mlops 10개

## 0.12.0

- dic-maker로 3단계에 주제 18개, 용어 42개를 더 넣었다
- 분야별: dev 11개, fe 12개, ax 13개, ops 11개, ml 13개

## 0.11.0

- dic-maker로 3단계에 주제 18개, 용어 42개를 더했다
- 분야별: plan 13개, db 11개, llm 11개, rag 12개, mlops 13개

## 0.10.1

- 기존 항목을 정리했다. 새 입문 주제를 선수로 이어 사다리를 잇고(`fe.next.server-data-fetching`, `fe.next.streaming-suspense`, `ops.deploy.zero-downtime`, `ops.container.isolation`, `db.internals.online-schema-change`, `mlops.eval.first-eval`, `dev.robust.atomic-replace`, `dev.robust.resumable-batch`), `ops.deploy.rolling-update`에 부모를 달았다.
- 겹치거나 넓은 별칭을 옮기거나 뺐다(`nginx`, `few-shot`, `Alembic 자동 생성`, `롤링 배포`, `SLO`, `span`, `학습률`, `와이어프레임`, `미세 조정`). `벡터 검색`을 `rag.vector-db.basics`에 더했다.
- 옮겨 간 자료 링크 2개를 고쳤고(`be.error.health-check`, `llm.api.first-call`), `ml.supervised.linear-regression`의 목표에 하이퍼파라미터를 넣었다.

## 0.10.0

- dic-maker로 3단계에 주제 8개, 용어 17개를 더했다
- 분야별: dev 6개, fe 5개, ax 4개, ops 6개, ml 4개

## 0.9.0

- dic-maker로 3단계에 주제 4개, 용어 11개를 더했다
- 분야별: plan 3개, db 4개, llm 3개, rag 3개, mlops 2개

## 0.8.0

- dic-maker로 모든 단계에 주제 14개, 용어 35개를 더했다
- 분야별: dev 5개, plan 7개, db 4개, fe 6개, llm 6개, rag 1개, ax 2개, ops 9개, ml 6개, mlops 3개

## 0.7.0

- dic-maker로 모든 단계에 주제 14개, 용어 35개를 더했다
- 분야별: dev 5개, plan 11개, db 3개, fe 7개, llm 1개, rag 3개, ax 6개, ops 4개, ml 6개, mlops 3개

## 0.6.1

- 강의 자료 Made With ML을 쓰던 항목 3개(`mlops.observe.drift`, `mlops.serve.model-serving`, `mlops.track.data-versioning`)의 자료 링크를 공식 문서로 바꿨다. `sources.md`의 LLMOps·MLOps 기준 자료도 MLflow 문서와 Google 운영 ML 시스템으로 바꿨다.

## 0.6.0

- dic-maker로 모든 단계에 주제 42개, 용어 97개를 더했다(1단계 26개, 2단계 31개, 3단계 26개, 4단계 35개, 5단계 21개).
- 분야별: dev 15개, plan 6개, db 20개, fe 6개, llm 18개, rag 17개, ax 18개, ops 4개, ml 12개, mlops 23개

## 0.5.0

- 2단계 입문에 신경망 첫 모델·정확도 평가·MLflow 평가와 트레이싱 입문·Figma 프레임과 컴포넌트·AI 멘탈 모델 온보딩·CLAUDE.md와 권한 규칙·셸 스크립트 첫걸음 등 주제 9개와 용어 21개 추가
- 분야별: plan 6개, ax 6개, ops 5개, ml 7개, mlops 6개

## 0.4.0

- 4단계 실전에 AI UX·Figma 핸드오프·서버/클라이언트 경계·React 메모이제이션·신경망 구조·데이터 분할·LLM 트레이싱·프롬프트 레지스트리·하위 에이전트 권한·모델 출력 방어 등 주제 10개와 용어 18개 추가
- 분야별: plan 6개, fe 6개, ax 5개, ml 6개, mlops 5개

## 0.3.0

- 주제를 단계마다 50개 이상으로 늘렸다(1단계 +38, 2단계 +19, 5단계 +32). 비어 있던 웹 프론트엔드, 기획, 머신러닝, MLOps, AX 분야를 중요도 순으로 채웠다.
- 독립 검토를 반영했다. 사실 오류와 겹치는 목표를 고치고, 설계·운영 중심 항목 7개를 4단계로 내렸으며, 내부 동작을 다루는 5단계 주제 7개와 Kubernetes 입문을 더했다.
- 공식 문서 링크가 없던 1단계 주제 7개에 링크를 넣고, 모든 주제에 링크를 요구한다. 노트 검사가 링크를 요구해 AI가 기억으로 주소를 적게 되던 문제다.
- 흔한 낱말이라 잘못 잡히던 별칭을 지우거나 구체적인 이름으로 바꾸고, 넓은 말 목록을 늘렸다.
- 후보함에 쌓인 개념(WAF, 실행 계획, VACUUM, 준비된 문장, 프로세스와 신호)을 사전에 넣었다.

## 0.2.1

- 뜻이 넓은 이름을 `broad_names.json`에 모아 후보 찾기에서 세지 않는다. "세션"이 Claude 세션인데 로그인 세션 후보로 잡히던 오탐을 막는다.
- 그 대신 항목에 구체적인 이름(세션 쿠키, 입력 검증, 토큰 수 등)을 더했다.

## 0.2.0

- 과정 교과목을 대조해 AX 프로덕트 기획·설계를 독립 분야로 뺐다.
- 백엔드·API 5단계를 채웠다. FastAPI 문서, OWASP Top 10:2025, OWASP API Top 10과 대조했다.
- 시범 노트에 필요한 LLM 기초와 Function Calling 항목을 넣었다.
- 독립 검토를 반영했다. 사실 오류를 고치고 단계·중요도를 다시 매겼으며, 분야 경계를 정해 테스트 일반·관측·캐시 항목을 해당 분야로 옮겼다.

## 0.1.0

- 분야 11개, 5단계 기준, 중요도 기준을 정했다.
- 항목 형식과 검사·생성 도구를 만들었다.
- 기준 확인용 샘플 항목 18개(HTTP, 임베딩)를 넣었다.
