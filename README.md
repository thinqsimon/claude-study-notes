# claude-study-notes

Claude Code와 OpenAI Codex에서 쓰는 `study-notes` 스킬 (Claude Code: `/study-notes`, Codex: `$study-notes`). AI와 개발하며 나눈 대화에서 **공부해야 할 개념과 문제해결 과정**을 골라
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

### 방법 2. Claude Code 스킬 폴더에 직접 복사
```bash
git clone https://github.com/thinqsimon/claude-study-notes.git
mkdir -p ~/.claude/skills
cp -R claude-study-notes/skills/study-notes ~/.claude/skills/
```

### 방법 2-W. Windows (Claude Code)
PowerShell에서:
```powershell
git clone https://github.com/thinqsimon/claude-study-notes.git
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse claude-study-notes\skills\study-notes "$HOME\.claude\skills\"
```

### 방법 3. Codex (CLI · VS Code 확장 · 데스크톱 앱)
Codex 채팅에 아래처럼 말하면 내장 `skill-installer`가 설치합니다.
```
$skill-installer 로 thinqsimon/claude-study-notes 저장소의 skills/study-notes 를 설치해줘
```
또는 직접 복사합니다.
```bash
# macOS / Linux
git clone https://github.com/thinqsimon/claude-study-notes.git
mkdir -p ~/.codex/skills
cp -R claude-study-notes/skills/study-notes ~/.codex/skills/
```
```powershell
# Windows (PowerShell)
git clone https://github.com/thinqsimon/claude-study-notes.git
New-Item -ItemType Directory -Force "$HOME\.codex\skills" | Out-Null
Copy-Item -Recurse claude-study-notes\skills\study-notes "$HOME\.codex\skills\"
```

설치 후 도구를 재시작하면 Claude Code에서는 `/study-notes`, Codex에서는 `$study-notes` 가 보입니다. 같은 폴더가 두 도구에서 그대로 동작하며, Python 3.10 이상이 필요하고 표준 라이브러리만 씁니다.

## 지원 환경
| | macOS / Linux | Windows |
|---|---|---|
| 파이썬 명령 | `python3` | `python` 또는 `py -3` |
| 셸 | bash, zsh | Git Bash, PowerShell (cmd.exe 미지원) |
| 노트 위치 | `~/StudyNotes` | `%USERPROFILE%\StudyNotes` |
| 기록 위치 | `~/.claude/projects`, `~/.codex` | `%USERPROFILE%\.claude\projects`, `%USERPROFILE%\.codex` |

Windows에서는 Git Bash가 주는 `/c/Users/...` 경로, 드라이브 문자 대소문자, cp949 콘솔 인코딩을 스크립트가 처리합니다. Windows 실기 검증은 아직 하지 못했으니 문제가 있으면 이슈로 알려 주세요.

## 사용법
- 정리하고 싶을 때 채팅에 `/study-notes`(Claude Code) 또는 `$study-notes`(Codex) 를 입력합니다.
- 결과: `~/StudyNotes/<프로젝트>/YYYY-MM-DD_NN.md` (주제별 `## N. 제목` 섹션), `~/StudyNotes/index.md` (주제 목록).
- 다시 입력하면 지난 정리 이후 대화만 `_02`, `_03` … 으로 이어서 정리됩니다.
- 처음부터 다시 정리하려면 `~/StudyNotes/.state/<세션id>.json` (Windows: `%USERPROFILE%\StudyNotes\.state\`) 을 지웁니다.

## 구성
```
skills/study-notes/
  SKILL.md                 절차와 작성 규칙
  scripts/study_notes.py   대화 기록 증분 추출(extract) · 체크포인트 확정(commit) · 상태(status)
  templates/note.md        노트 형식 (frontmatter + 목차 + 주제 섹션)
```

## 동작 원리
1. `extract --agent claude|codex`: 지난 체크포인트 이후 메시지만 잘라 임시 파일로 만듭니다.
   - Claude Code: `~/.claude/projects/<프로젝트>/<세션>.jsonl`
   - Codex: `~/.codex/state_*.sqlite` 의 스레드 목록에서 현재 폴더의 최근 스레드를 찾아 `~/.codex/sessions/…/rollout-*.jsonl` 을 읽습니다. `exec` 도구 호출은 안의 셸 명령만 뽑아 보여 줍니다.
   - macOS 한글 경로의 유니코드 정규화(NFD → NFC) 차이도 처리합니다.
2. Claude가 그 구간을 읽고 주제를 뽑아 템플릿 구조대로 노트를 씁니다.
3. `commit`: 체크포인트를 저장하고 `index.md` 에 주제 행을 추가합니다.

## 라이선스
MIT
