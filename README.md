# claude-study-notes

Claude Code와 OpenAI Codex에서 쓰는 `study-notes` 스킬 (Claude Code: `/study-notes`, Codex: `$study-notes`). AI와 개발하며 나눈 대화에서 **공부해야 할 개념과 문제해결 과정**을 골라
`~/StudyNotes/<프로젝트>/` 에 초보자용 학습장(Markdown)으로 정리합니다.

핵심 원칙은 **요약이 아니라 재강의**입니다. 대화를 발췌하는 게 아니라, 그 개념을 처음 배우는 사람에게
가르치듯 처음부터 다시 설명합니다. 여러 번 실행하면 **지난번 이후의 대화만** 새 파일로 정리됩니다(증분).

> **🪟 Windows 사용자는 아래 [Windows 사용자 안내](#-windows-사용자-안내-꼭-읽어-주세요)를 먼저 읽어 주세요.**
> 맥과 다른 점(파이썬 명령, 셸, 경로)이 있고, 그 부분만 맞추면 똑같이 동작합니다.

## 설치 (macOS / Linux)

### 방법 1. Claude Code 플러그인으로 설치 (권장)
Claude Code 안에서:
```
/plugin marketplace add thinqsimon/claude-study-notes
/plugin install study-notes@thinqsimon
```
이 방법은 Windows에서도 똑같이 됩니다.

### 방법 2. Claude Code 스킬 폴더에 직접 복사
```bash
git clone https://github.com/thinqsimon/claude-study-notes.git
mkdir -p ~/.claude/skills
cp -R claude-study-notes/skills/study-notes ~/.claude/skills/
```

### 방법 3. Codex (CLI · VS Code 확장 · 데스크톱 앱)
Codex 채팅에 아래처럼 말하면 내장 `skill-installer`가 설치합니다. (Windows도 동일)
```
$skill-installer 로 thinqsimon/claude-study-notes 저장소의 skills/study-notes 를 설치해줘
```
또는 직접 복사합니다.
```bash
git clone https://github.com/thinqsimon/claude-study-notes.git
mkdir -p ~/.codex/skills
cp -R claude-study-notes/skills/study-notes ~/.codex/skills/
```

설치 후 도구를 재시작하면 Claude Code에서는 `/study-notes`, Codex에서는 `$study-notes` 가 보입니다. 같은 폴더가 두 도구에서 그대로 동작하며, Python 3.10 이상이 필요하고 표준 라이브러리만 씁니다.

---

## 🪟 Windows 사용자 안내 (꼭 읽어 주세요)

이 스킬은 Windows 10/11에서도 동작하도록 만들어졌습니다. 다만 **맥 기준으로 쓰인 설명을 그대로 따라 하면 막히는 지점이 세 군데** 있습니다.

| 막히는 지점 | 맥 / 리눅스 | **Windows에서는 이렇게** |
|---|---|---|
| 파이썬 실행 명령 | `python3` | **`python`** (안 되면 `py -3`) |
| 터미널(셸) | bash, zsh | **PowerShell 또는 Git Bash**. `cmd.exe`(검은 명령 프롬프트)는 **지원하지 않습니다** |
| 홈 폴더 표기 | `~/StudyNotes` | **`$HOME\StudyNotes`** 또는 `%USERPROFILE%\StudyNotes` (보통 `C:\Users\<이름>\StudyNotes`) |

### 1단계. 준비물 확인
PowerShell(시작 메뉴에서 "PowerShell" 검색)을 열고 아래 두 줄을 실행합니다.
```powershell
python --version      # Python 3.10.0 이상이 나와야 합니다
git --version         # git version ... 이 나와야 합니다
```
- `python`을 입력했는데 **Microsoft Store가 열리면** 파이썬이 없는 것입니다. https://www.python.org/downloads/windows/ 에서 설치하되, 설치 첫 화면의 **"Add python.exe to PATH" 체크박스를 반드시 켜세요.** 설치 후 PowerShell을 닫았다 다시 엽니다.
- `git`이 없으면 https://git-scm.com/download/win 에서 **Git for Windows**를 설치합니다. 기본 옵션 그대로 설치하면 Git Bash도 같이 설치되고, Claude Code가 이 Git Bash를 사용합니다.

### 2단계. 설치
**Claude Code 플러그인(가장 쉬움)**: Claude Code 안에서 맥과 같은 두 줄을 입력합니다.
```
/plugin marketplace add thinqsimon/claude-study-notes
/plugin install study-notes@thinqsimon
```

**직접 복사(PowerShell)**: Claude Code용, Codex용 중 쓰는 쪽만 실행합니다. 둘 다 써도 됩니다.
```powershell
git clone https://github.com/thinqsimon/claude-study-notes.git

# Claude Code 용
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse -Force claude-study-notes\skills\study-notes "$HOME\.claude\skills\"

# Codex 용
New-Item -ItemType Directory -Force "$HOME\.codex\skills" | Out-Null
Copy-Item -Recurse -Force claude-study-notes\skills\study-notes "$HOME\.codex\skills\"
```
설치 뒤 Claude Code나 Codex를 **완전히 종료했다가 다시 실행**해야 스킬이 보입니다.

### 3단계. 설치 확인
PowerShell에서 아래 한 줄을 실행해 JSON이 출력되면 정상입니다. (`--cwd` 뒤에는 AI와 대화한 프로젝트 폴더를 넣습니다.)
```powershell
python -I "$HOME\.claude\skills\study-notes\scripts\study_notes.py" status --agent claude --cwd "C:\Users\<이름>\<프로젝트 폴더>"
```
Codex를 쓰면 경로의 `.claude`를 `.codex`로, `--agent claude`를 `--agent codex`로 바꿉니다.

### 4단계. 사용
맥과 같습니다. 채팅에 `/study-notes`(Claude Code) 또는 `$study-notes`(Codex)를 입력합니다.
노트는 **`C:\Users\<이름>\StudyNotes\<프로젝트>\`** 에 생기고, 주제 목록은 같은 폴더의 `index.md`에 쌓입니다. 탐색기 주소창에 `%USERPROFILE%\StudyNotes`를 붙여 넣으면 바로 열립니다.

### Windows에서 자주 나는 오류
| 증상 | 원인 | 해결 |
|---|---|---|
| `python3 : 용어가 ... 인식되지 않습니다` | Windows에는 `python3` 명령이 없음 | `python` 또는 `py -3`로 바꿔 실행 |
| `python`을 치면 Microsoft Store가 열림 | 파이썬 미설치 또는 PATH 미등록 | 1단계대로 설치하고 "Add to PATH" 체크. 이미 설치했다면 설정 > 앱 > 앱 실행 별칭에서 `python.exe` 별칭 끄기 |
| 경로에 `~`를 썼는데 파일을 못 찾음 | PowerShell은 프로그램에 넘기는 `~`를 풀지 않음 | `~` 대신 `$HOME` 또는 `%USERPROFILE%` 사용 |
| `$HOME`, `$PWD`가 빈 값으로 나옴 | cmd.exe에서 실행함 | PowerShell 또는 Git Bash에서 실행 |
| 출력의 한글이 `?`나 깨진 글자로 보임 | 콘솔 인코딩(cp949) | 스크립트가 UTF-8로 출력하도록 되어 있음. 그래도 깨지면 PowerShell에서 `chcp 65001` 실행 후 재시도 |
| `세션 기록을 찾을 수 없습니다` | `--cwd`가 AI와 대화한 폴더와 다름 | 대화한 프로젝트 폴더 경로를 정확히 넣기. Git Bash의 `/c/Users/...` 형태도 스크립트가 알아서 변환함 |
| `이 폴더에서 연 Codex 스레드 기록이 없습니다` | Codex가 다른 폴더를 열고 있거나 `--agent`가 틀림 | Codex에서 연 작업 폴더를 `--cwd`에 넣고 `--agent codex` 확인 |
| PowerShell에서 `.ps1 ... 실행할 수 없습니다` | 스크립트 실행 정책 | 이 스킬은 `.ps1`을 쓰지 않으므로 해당 없음. 위 명령을 한 줄씩 직접 입력하면 됨 |

### Windows 내부 처리 (알아 두면 좋은 것)
- Claude Code는 Windows에서 Git Bash를 쓰기 때문에 현재 폴더가 `/c/Users/...` 형태로 넘어옵니다. 스크립트가 이를 `C:\Users\...`로 바꾼 뒤 대화 기록 폴더(`%USERPROFILE%\.claude\projects\C--Users-...`)를 찾습니다.
- 드라이브 문자나 폴더명의 대소문자가 달라도 기록 폴더를 대소문자 무시로 한 번 더 찾습니다.
- Codex의 스레드 목록 DB(`%USERPROFILE%\.codex\state_*.sqlite`)는 읽기 전용으로만 엽니다. Codex가 켜져 있어도 안전합니다.
- 노트와 목록 파일은 모두 UTF-8로 저장됩니다. 메모장, VS Code, Obsidian 어디서나 열립니다.

> Windows 실기 검증은 아직 제한적입니다. 문제가 생기면 **오류 메시지 전체**와 `python --version` 결과를 이슈로 올려 주세요.

---

## 사용법
- 정리하고 싶을 때 채팅에 `/study-notes`(Claude Code) 또는 `$study-notes`(Codex) 를 입력합니다.
- 결과: `~/StudyNotes/<프로젝트>/<프로젝트>_YYYY-MM-DD_NN.md` (주제별 `## N. 제목` 섹션), `~/StudyNotes/index.md` (주제 목록).
- 다시 입력하면 지난 정리 이후 대화만 `_02`, `_03` … 으로 이어서 정리됩니다.
- 처음부터 다시 정리하려면 `~/StudyNotes/.state/<세션id>.json` (Windows: `%USERPROFILE%\StudyNotes\.state\`) 을 지웁니다.

## 지원 환경 요약
| | macOS / Linux | Windows |
|---|---|---|
| 파이썬 명령 | `python3` | `python` 또는 `py -3` |
| 셸 | bash, zsh | PowerShell, Git Bash (cmd.exe 미지원) |
| 노트 위치 | `~/StudyNotes` | `%USERPROFILE%\StudyNotes` |
| 기록 위치 | `~/.claude/projects`, `~/.codex` | `%USERPROFILE%\.claude\projects`, `%USERPROFILE%\.codex` |

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
   - macOS 한글 경로의 유니코드 정규화(NFD → NFC) 차이와 Windows 경로 표기 차이도 처리합니다.
2. AI가 그 구간을 읽고 주제를 뽑아 템플릿 구조대로 노트를 씁니다.
3. `commit`: 체크포인트를 저장하고 `index.md` 에 주제 행을 추가합니다.

## 라이선스
MIT
