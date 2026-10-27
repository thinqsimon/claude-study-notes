# claude-study-notes

Claude Code용 `/study-notes` 스킬. AI와 개발하며 나눈 대화에서 **공부해야 할 개념과 문제해결 과정**을 골라
`~/StudyNotes/<프로젝트>/` 에 초보자용 학습장(Markdown)으로 정리합니다.

핵심 원칙은 **요약이 아니라 재강의**입니다. 대화를 발췌하는 게 아니라, 그 개념을 처음 배우는 사람에게
가르치듯 처음부터 다시 설명합니다. 여러 번 실행하면 **지난번 이후의 대화만** 새 파일로 정리됩니다(증분).

## 설치

### 방법 1. 플러그인으로 설치 (권장)
Claude Code 안에서:
```
/plugin marketplace add thinqsimon/claude-study-notes
/plugin install study-notes@thinqsimon
```

### 방법 2. 스킬 폴더에 직접 복사
```bash
git clone https://github.com/thinqsimon/claude-study-notes.git
mkdir -p ~/.claude/skills
cp -R claude-study-notes/skills/study-notes ~/.claude/skills/
```

설치 후 Claude Code를 재시작하면 `/study-notes` 가 보입니다. Python 3.10 이상이 필요하며 표준 라이브러리만 씁니다.

## 사용법
- 정리하고 싶을 때 채팅에 `/study-notes` 를 입력합니다.
- 결과: `~/StudyNotes/<프로젝트>/YYYY-MM-DD_NN.md` (주제별 `## N. 제목` 섹션), `~/StudyNotes/index.md` (주제 목록).
- 다시 입력하면 지난 정리 이후 대화만 `_02`, `_03` … 으로 이어서 정리됩니다.
- 처음부터 다시 정리하려면 `~/StudyNotes/.state/<세션id>.json` 을 지웁니다.

## 구성
```
skills/study-notes/
  SKILL.md                 절차와 작성 규칙
  scripts/study_notes.py   대화 기록 증분 추출(extract) · 체크포인트 확정(commit) · 상태(status)
  templates/note.md        노트 형식 (frontmatter + 목차 + 주제 섹션)
```

## 동작 원리
1. `extract`: `~/.claude/projects/<프로젝트>/<세션>.jsonl` 에서 지난 체크포인트 이후 메시지만 잘라 임시 파일로 만듭니다.
   macOS 한글 경로의 유니코드 정규화(NFD → NFC) 차이도 처리합니다.
2. Claude가 그 구간을 읽고 주제를 뽑아 템플릿 구조대로 노트를 씁니다.
3. `commit`: 체크포인트를 저장하고 `index.md` 에 주제 행을 추가합니다.

## 라이선스
MIT
