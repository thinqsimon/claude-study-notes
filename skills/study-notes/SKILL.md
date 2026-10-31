---
name: study-notes
description: AI와의 개발 대화에서 공부해야 할 개념·문제해결 과정을 골라 ~/StudyNotes/<프로젝트>/ 에 초보자용 학습장 md로 증분 정리할 때 사용. 지난 실행 이후의 대화만 정리하며, 요약이 아니라 개념을 처음부터 다시 가르치듯 쓴다.
---
# 배움노트 정리 (study-notes)

Claude Code와 OpenAI Codex 어디서나 같은 방식으로 동작한다. Claude Code에서는 `/study-notes`, Codex에서는 `$study-notes`로 부른다.

## 가장 중요한 원칙: 요약이 아니라 "재강의"

- 대화는 **주제를 찾는 계기**일 뿐이다. 노트 본문은 대화 문장을 발췌·축약하지 않는다. 그 개념을 **처음 배우는 학생에게 가르치듯 처음부터 다시 설명**한다.
- 독자는 부트캠프 수강생 같은 초보 개발자다. 바이브 코딩 중 AI가 빠르게 지나간 개념을 나중에 혼자 읽고 이해하는 것이 목적이다.
- 대화에서 AI가 설명 없이 쓴 전문 용어(마이그레이션, 의존성 주입, 스트리밍, 체크포인트, 레이어 규칙 등)는 **대화에 설명이 없었더라도 노트에서는 반드시 풀어서** 설명한다.
- 주제 하나의 분량은 A4 반 쪽~한 쪽. 짧은 메모가 아니라 읽고 이해할 수 있는 교재 분량으로 쓴다.
- 쓰고 나서 스스로 확인: "이 노트만 읽은 학생이 같은 상황을 혼자 재현하거나 남에게 설명할 수 있는가?" 아니면 더 쓴다.

## 준비: 세 변수를 먼저 정한다

아래 명령의 `$PY`, `$SKILL_DIR`, `$AGENT`는 실행 전 실제 값으로 바꾼다.

- `$PY` = 파이썬 실행 명령. macOS/Linux는 `python3 -I`, Windows는 `python -I` (없으면 `py -3 -I`). 3.10 이상.
- `$SKILL_DIR` = **이 SKILL.md가 들어 있는 폴더**. 홈 디렉터리는 `~` 대신 `$HOME`으로 쓴다 (bash와 PowerShell 모두에서 풀리고, PowerShell은 외부 프로그램 인자의 `~`를 풀지 않는다).
  - Claude Code 플러그인: `${CLAUDE_PLUGIN_ROOT}/skills/study-notes`
  - Claude Code 직접 복사: `$HOME/.claude/skills/study-notes`
  - Codex: `$HOME/.codex/skills/study-notes` (`CODEX_HOME`을 바꿨다면 `$CODEX_HOME/skills/study-notes`)
- `$AGENT` = 지금 실행 중인 도구. Claude Code면 `claude`, Codex면 `codex`. 스크립트가 이 값으로 어느 쪽 대화 기록을 읽을지 정한다.

Windows 주의: 명령은 Git Bash 또는 PowerShell에서 실행한다 (cmd.exe는 `$HOME`, `$PWD`를 모른다). 경로 구분자는 `/`를 써도 된다.
Git Bash의 `$PWD`가 `/c/Users/...` 형태여도 스크립트가 `C:\Users\...`로 바꿔 처리한다. 노트는 `%USERPROFILE%\StudyNotes`에 생긴다.

Codex 주의: 노트 폴더 `$HOME/StudyNotes`는 작업 폴더 밖이다. 노트를 쓰거나 `commit`을 실행할 때 샌드박스가 막으면 쓰기 승인(escalation)을 요청한다. 기록 읽기(`~/.codex/sessions`, `~/.codex/state_*.sqlite`)는 읽기 전용이다.

## 절차

1. **세션 id 확인**
   - Claude Code: 시스템 프롬프트의 Scratchpad directory 경로 마지막 디렉터리명이 현재 세션 id다 (예: `b4a801d7-…`). 찾을 수 없으면 `--session`을 생략한다.
   - Codex: 스레드 id가 프롬프트에 없으므로 `--session`을 **생략**한다. 스크립트가 스레드 목록 DB에서 "이 작업 폴더에서 사용자가 연 가장 최근 스레드"를 고른다. 이후 `commit`에는 extract 출력의 `session` 값을 그대로 넘긴다.
2. **증분 추출**:
   ```bash
   $PY "$SKILL_DIR/scripts/study_notes.py" extract --agent $AGENT --cwd "$PWD" --session <세션id>
   ```
   stdout JSON의 `new_messages`가 0이면 "정리할 새 대화가 없습니다"라고 알리고 끝낸다.
   `delta_path`의 파일을 읽는다. 길면 나눠 읽는다. `suggested_file`이 이번에 쓸 노트 경로, `run_no`가 노트 번호다.
3. **주제 뽑기** (델타 전체를 읽은 뒤):
   - 포함: 처음 등장한 기술 개념, 오류·막힘과 해결 과정, 실행한 핵심 명령어·코드, 설계 결정과 그 이유, 워크플로·도구 사용법(스킬, 에이전트, 훅 등)
   - 제외: 인사, 단순 진행 보고, 같은 내용의 반복, 비밀값(`.env` 내용, 토큰, 키, 이메일)
   - 중복 방지: index.md 전체를 읽지 말고 아래 순서로 후보만 좁힌다 (토큰 절약).
     1. **찾기**: 주제마다 키워드 2~3개(한글 용어, 영문 용어, 동의어)를 한 번에 검색한다.
        `grep -iE "체크포인트|checkpoint|증분" "$HOME/StudyNotes/index.md"`
        (PowerShell은 `Select-String -Path "$HOME/StudyNotes/index.md" -Pattern "체크포인트|checkpoint|증분"`)
     2. **판단**: 걸린 행의 제목·태그·요약 열을 보고 이번 주제와 같은 내용인지 정한다. 대부분 여기서 끝낸다.
     3. **확인 (드물게)**: 요약만으로 애매할 때만, 링크된 노트에서 그 `## N.` 섹션 하나만 읽는다. 파일 전체는 읽지 않는다.
        `awk '/^## 3\. /{p=1;print;next} p&&/^## [0-9]+\. /{exit} p' "<노트 경로>"`
     - 겹치면 새로 배운 부분만 "심화" 성격으로 쓰고 첫 줄에 기존 노트 링크를 건다. 새로 배운 게 없으면 그 주제는 뺀다.
   - 주제 수에 제한은 없다. 수십 개여도 한 파일에 모두 넣는다. 다만 억지로 쪼개지 말고 "학생이 한 번에 공부할 단위"로 묶는다.
4. **노트 작성**: `$SKILL_DIR/templates/note.md` 구조를 그대로 따라 `suggested_file`에 쓴다. 폴더가 없으면 만든다.
   - frontmatter의 `covers`는 extract 출력의 `from ~ to`, `session`은 앞 8자
   - 목차 표를 먼저 채우고, `## N. 제목` 섹션을 순서대로 쓴다
   - 각 섹션은 제목 바로 아래에 `> 한 줄 요약: …`, 그다음 메타 줄을 정확히 이 형식으로 쓴다: `` `유형` 개념 | `태그` fastapi, alembic | `난이도` ★★☆ `` (index.md가 두 줄을 파싱한다)
   - 한 줄 요약은 index.md의 요약 열로 들어가 다음 실행의 중복 판단에 쓰인다. 제목을 되풀이하지 말고 **핵심 내용을 한 문장으로** 쓴다. 검색에 걸리도록 핵심 용어를 넣는다
   - 유형은 `개념` / `문제해결` / `도구·명령어` / `설계결정` / `워크플로` 중 하나
   - 해당 없는 소제목(예: 개념 유형의 "문제 → 원인 → 해결")은 생략해도 된다. 그 외 소제목은 모두 채운다
5. **등록**:
   ```bash
   $PY "$SKILL_DIR/scripts/study_notes.py" commit --agent $AGENT --session <extract 출력의 session> --file <쓴 노트 경로>
   ```
   체크포인트가 저장되고 `$HOME/StudyNotes/index.md`에 주제 행이 추가된다. 처음이면 `README.md`도 생긴다.
6. **보고**: 노트의 절대 경로, 주제 수, 주제 제목 목록을 사용자에게 3~6줄로 알린다. 노트 내용을 채팅에 다시 붙이지 않는다.

## 작성 규칙

- 한국어. 용어 첫 등장 시 괄호로 한 줄 정의. 모든 설명에 "왜"를 포함한다.
- 순서: 상황 → 왜 필요한가(없으면 생기는 문제, 비유) → 핵심 개념(정의·원리) → 이 프로젝트에서 쓴 모습 → 흔한 실수 → 자가 점검 → 더 공부할 것
- 문제해결 유형은 **증상 → 원인 → 해결 → 재발 방지** 4단을 고정으로 쓴다. 오류 메시지는 원문 그대로 코드 블록에 넣는다.
- 코드·명령은 펜스 블록에 언어를 지정하고, 블록 위에 한 줄 설명을 쓴다. 옵션(`-I`, `--delete` 등)의 뜻을 풀이한다.
- 자가 점검 질문은 2~3개, 답을 바로 아래에 적는다. 더 공부할 것은 키워드 2~3개와 "왜 다음에 배워야 하는지".
- 일반 md 편집기 호환: HTML 태그, Obsidian 전용 문법(`[[링크]]`, callout) 금지. 표는 GFM. 수식·이모지 남용 금지.
- 프로젝트 파일을 언급할 때는 저장소 기준 상대 경로를 백틱으로 쓴다.

## 문제가 생기면

- `세션 기록을 찾을 수 없습니다`: `--session`을 빼고 다시 실행한다.
- `이 폴더에서 연 Codex 스레드 기록이 없습니다`: Codex에서 다른 폴더를 열었거나 `--agent`가 틀렸다. `--cwd`에 Codex가 연 작업 폴더를 넣는다.
- 체크포인트를 되돌리고 싶으면 `$HOME/StudyNotes/.state/<세션id>.json`을 지운다. 그 세션은 처음부터 다시 정리된다.
- 상태 확인: `$PY "$SKILL_DIR/scripts/study_notes.py" status --agent $AGENT --cwd "$PWD"`
