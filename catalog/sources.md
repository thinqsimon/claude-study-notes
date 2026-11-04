# 기준 자료

사전의 **범위와 중요도를 대조**하는 데 쓴다. 문장은 옮기지 않고 사전에서 직접 쓴다. 항목별 공식 자료 링크는 각 항목의 `refs`에 있다.

## 범위 전체

| 자료 | 쓰는 법 |
|---|---|
| AX 서비스 풀스택 빌더 과정 교과내용 (고용24 훈련과정상세, 과정 ID AIG20260000581137), [과정 공고](https://linkareer.com/activity/328748) | AX 서비스 풀스택에 필요한 범위와 비중 확인. 진도를 따르지는 않는다 |
| [ACM/IEEE-CS/AAAI CS2023](https://csed.acm.org/) | 컴퓨터 과학 기초의 범위 대조 (지식 영역 17개) |
| [정보처리기사 출제기준 (큐넷)](https://www.q-net.or.kr/crf005.do?id=crf00503&jmCd=1320) | 교과서·시험에 나오는 기초 범위 대조 |
| [NCS 국가직무능력표준](https://www.ncs.go.kr/) | 직무별 능력 단위 대조 |
| [Stack Overflow Developer Survey 2025](https://survey.stackoverflow.co/2025/technology/) | 기술 사용률을 중요도 판단의 참고로 삼는다 |
| [roadmap.sh 풀스택](https://roadmap.sh/full-stack), [AI 엔지니어](https://roadmap.sh/ai-engineer) | 빠진 항목을 찾는 개인 참고로만 쓴다. [라이선스](https://github.com/kamranahmedse/developer-roadmap/blob/master/license)상 내용을 옮기지 않는다 |

## 분야별

| 분야 | 자료 |
|---|---|
| AX 프로덕트 기획·설계 | [Figma 학습 자료](https://help.figma.com/hc/en-us) |
| 개발 기초·협업 | [Pro Git](https://git-scm.com/book/en/v2), [Python 튜토리얼](https://docs.python.org/3/tutorial/) |
| 웹 프론트엔드 | [MDN Curriculum](https://developer.mozilla.org/en-US/curriculum/), [MDN 웹 개발 학습](https://developer.mozilla.org/en-US/docs/Learn_web_development), [React 학습](https://react.dev/learn), [Next.js 문서](https://nextjs.org/docs), [TypeScript 핸드북](https://www.typescriptlang.org/docs/handbook/intro.html) |
| 백엔드·API | [FastAPI 튜토리얼](https://fastapi.tiangolo.com/tutorial/), [MDN HTTP](https://developer.mozilla.org/en-US/docs/Web/HTTP), [OWASP Top 10](https://owasp.org/Top10/) |
| 데이터베이스·데이터 | [PostgreSQL 튜토리얼](https://www.postgresql.org/docs/current/tutorial.html), [SQLAlchemy 튜토리얼](https://docs.sqlalchemy.org/en/20/tutorial/) |
| 인프라·클라우드·DevOps | [Docker 시작하기](https://docs.docker.com/get-started/), [Kubernetes 개념](https://kubernetes.io/docs/concepts/), [GitHub Actions](https://docs.github.com/en/actions) |
| AI·머신러닝·딥러닝 기초 | [Google 머신러닝 단기 과정](https://developers.google.com/machine-learning/crash-course) |
| LLM·생성형 AI·프롬프트 | [Hugging Face LLM 과정](https://huggingface.co/learn/llm-course), [Microsoft 초보자를 위한 생성형 AI](https://github.com/microsoft/generative-ai-for-beginners), [Claude 프롬프트 가이드](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview), [OpenAI 텍스트 생성 가이드](https://platform.openai.com/docs/guides/text) |
| RAG·에이전트·오케스트레이션 | [LangChain 문서](https://docs.langchain.com/), [LangGraph 문서](https://langchain-ai.github.io/langgraph/), [MCP 문서](https://modelcontextprotocol.io/docs/getting-started/intro) |
| LLMOps·MLOps | [MLflow 문서](https://mlflow.org/docs/latest/), [Google 운영 ML 시스템](https://developers.google.com/machine-learning/crash-course/production-ml-systems), [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/) |
| AI 네이티브 개발·보안·윤리 | [NIST AI 위험 관리 프레임워크](https://www.nist.gov/itl/ai-risk-management-framework), [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/) |

## 과정 교과목과 분야의 연결

과정의 비중을 분야와 중요도 판단에 참고한다. 표에 없는 머신러닝 이론과 MLOps는 빼지 않되, 서비스 제작 경로에서 먼 항목의 중요도를 낮게 본다.

| 교과목 | 시간 | 주로 대응하는 분야 |
|---|---|---|
| AX 프로덕트 기획 & 서비스 설계 | 72 | AX 프로덕트 기획·설계 |
| AI-Augmented 백엔드 개발 | 40 | 백엔드·API, AI 네이티브 개발 |
| 서비스 도메인 모델링 & 데이터 아키텍처 | 40 | 데이터베이스·데이터 |
| API 아키텍처 & 인증 보안 설계 | 48 | 백엔드·API |
| AX UI 구현 & 프론트엔드 통합 | 56 | 웹 프론트엔드, AI 네이티브 개발 |
| AI Native 방법론 및 품질 자동화 | 48 | AI 네이티브 개발, 개발 기초(E2E 테스트), 인프라(배포 게이트) |
| LLM 서비스 엔지니어링 & RAG 파이프라인 | 56 | LLM·프롬프트, RAG·에이전트 |
| 세미 프로젝트: 시장 데이터 분석 대시보드 | 92 | 데이터 수집과 가공, RAG, 대시보드 시각화 |
| 기본 프로젝트: AI 서비스 스타터킷 | 92 | FastAPI·React·PostgreSQL·LangChain, CI/CD, 문서화 |
| 참여 기업 프로젝트 | 184 | LLM·RAG 기능, 방어 로직, 기획 문서, API 문서, 사용자 매뉴얼 |

과정 교안 같은 비공개 자료는 이 저장소에 올리지 않는다.
