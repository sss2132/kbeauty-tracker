# 텔레그램 채널 운영 가이드

텔레그램 플러그인 구조, 멀티봇 설정, 트러블슈팅을 다루는 문서.
세션 연결이 안 되거나 메시지 수신이 안 될 때 이 문서를 먼저 참조한다.

---

## 1. 전체 구조

```
Windows Task Scheduler (KBeauty-DailyCollect, 매일 19:00)
  │
  ▼
scheduled_daily_collect.ps1
  │
  ├─ 1) telegram-kbeauty/.env에서 봇 토큰 읽어 Bot API 알림 전송
  ├─ 2) _start_telegram.ps1 호출
  │       │
  │       ├─ 환경변수 설정:
  │       │     TELEGRAM_STATE_DIR = ~/.claude/channels/telegram-kbeauty/
  │       │     TELEGRAM_BOT_TOKEN = K-Beauty 전용 봇
  │       ├─ claude.exe --channels plugin:telegram@claude-plugins-official 실행
  │       │
  │       ▼
  │     플러그인(bun)이 환경변수를 상속받아 K-Beauty 봇으로 polling 시작
  │
  ▼
사용자가 텔레그램에서 "시작" 전송 → ORCHESTRATOR.md에 따라 파이프라인 실행
```

### 수동 실행
- 세션만: `powershell .\kbeauty-tracker\_start_telegram.ps1` (알림 없이 세션 시작)
- 스케줄러 트리거: `schtasks /run /tn KBeauty-DailyCollect`

---

## 2. 멀티봇 분리 구조

| 세션 | 봇 이름 | State Dir | 용도 |
|------|---------|-----------|------|
| K-Beauty | @kbeautytracker1_bot | `~/.claude/channels/telegram-kbeauty/` | 일일 수집 파이프라인 |
| Quant | (quant 전용 봇) | `~/.claude/channels/telegram-quant/` | 퀀트 세션 |
| 기본 (더미) | (더미 봇) | `~/.claude/channels/telegram/` | 플러그인 프로세스 유지용 |

### 핵심 원칙
- **1봇 = 1폴러**: 하나의 봇 토큰에 하나의 프로세스만 `getUpdates` 가능. 두 개가 붙으면 409 Conflict 또는 메시지 유실.
- **State Dir로 분리**: 각 세션의 시작 스크립트가 `TELEGRAM_STATE_DIR` 환경변수를 설정 → 플러그인(bun)이 상속 → 해당 디렉토리의 `.env`에서 봇 토큰을 읽음.
- **기본 디렉토리 변경 금지**: `~/.claude/channels/telegram/.env`는 더미 봇 토큰. 여기를 실제 봇 토큰으로 바꾸면 다른 세션의 플러그인이 해당 봇을 가로챈다.

### 각 State Dir 구조
```
~/.claude/channels/telegram-kbeauty/
  .env          # TELEGRAM_BOT_TOKEN=...
  access.json   # { dmPolicy: "allowlist", allowFrom: ["chat_id"] }
```

---

## 3. 환경변수 전달 흐름

```
PS1 스크립트 ($env:TELEGRAM_STATE_DIR, $env:TELEGRAM_BOT_TOKEN 설정)
  → claude.exe (환경변수 상속)
    → bun (플러그인 MCP 서버, 환경변수 상속)
      → server.ts:
          STATE_DIR = process.env.TELEGRAM_STATE_DIR ?? 기본 디렉토리
          .env 파일에서 토큰 로드 (process.env에 없을 때만)
```

**주의**: server.ts 주석에 "Plugin-spawned servers don't get an env block"이라고 되어 있으나, 이는 MCP config의 `env` 블록이 없다는 의미. 실제로는 부모 프로세스의 환경변수를 상속받는다.

---

## 4. Dos and Don'ts

### DO
- ✅ 각 세션 시작 스크립트에서 `TELEGRAM_STATE_DIR`와 `TELEGRAM_BOT_TOKEN`을 환경변수로 설정
- ✅ `--channels plugin:telegram@claude-plugins-official`로 양방향 채널 사용
- ✅ 새 봇 추가 시 전용 State Dir (`telegram-{이름}`) 생성
- ✅ `access.json`에 `dmPolicy: "allowlist"`로 잠금

### DON'T
- ❌ **프로젝트 안에 `_telegram_mcp.json` 같은 MCP config 파일 두지 않기** — Claude Code가 자동으로 `settings.local.json`에 `enabledMcpjsonServers`로 등록해서 플러그인과 MCP 서버가 동시에 같은 봇을 폴링 → 메시지 유실
- ❌ `--mcp-config`와 `--channels plugin:telegram`을 동시에 사용하지 않기 (중복 폴링)
- ❌ `~/.claude/channels/telegram/.env`(기본 디렉토리)를 실제 봇 토큰으로 바꾸지 않기 — 모든 세션의 플러그인이 기본값으로 이 파일을 읽음
- ❌ `settings.local.json`에 `enabledMcpjsonServers`나 `enableAllProjectMcpServers: true` 넣지 않기
- ❌ 다른 세션의 bun 프로세스를 일괄 종료하지 않기 — 각자 고유 봇이 있음

---

## 5. 트러블슈팅

### 증상: 세션은 열리지만 메시지를 못 받음 ("Listening for channel messages" 표시됨)

**진단 순서:**

1. **봇이 폴링되고 있는지 확인**
   ```bash
   curl -s "https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
   ```
   - `pending_update_count > 0` → 아무도 폴링 안 하고 있음 (플러그인이 다른 토큰으로 붙었거나 시작 실패)
   - `pending_update_count == 0` → 누군가 폴링 중 (정상이거나 다른 프로세스가 가로챔)

2. **중복 폴링 확인** — 같은 봇 토큰을 쓰는 bun 프로세스가 여러 개인지
   ```cmd
   wmic process where "name='bun.exe'" get ProcessId,ParentProcessId,CommandLine
   ```
   ParentProcessId로 어떤 claude.exe 세션의 플러그인인지 확인.

3. **MCP 서버 중복 등록 확인**
   ```
   .claude/settings.local.json에 enabledMcpjsonServers 또는 enableAllProjectMcpServers가 있으면 제거
   프로젝트 안에 *mcp*.json 파일이 있으면 삭제 (플러그인과 중복 폴링 원인)
   ```

4. **환경변수 전달 확인**
   ```
   _start_telegram.ps1에서 $env:TELEGRAM_STATE_DIR가 올바른 디렉토리를 가리키는지 확인
   해당 디렉토리의 .env에 올바른 봇 토큰이 있는지 확인
   ```

### 증상: 양방향 채널 자체가 안 열림 (Listening 메시지 없음)

- `--channels plugin:telegram@claude-plugins-official` 플래그 확인
- 플러그인 설치 상태: `~/.claude/plugins/cache/claude-plugins-official/telegram/` 존재 여부
- bun 설치: `bun --version` 확인

### 증상: 알림은 오지만 세션이 안 열림

- `scheduled_daily_collect.ps1` → `_start_telegram.ps1` 호출 흐름 확인
- Windows Terminal(`wt.exe`) 설치 여부 확인
- 스케줄러 설정: `schtasks /query /tn KBeauty-DailyCollect /v /fo LIST`

---

## 6. 과거 이슈 기록

### 2026-04-01: bun 프로세스 alive but not polling
- **증상**: 세션 열림, "Listening" 표시, Bot API 알림 정상 도착, 하지만 사용자 메시지 수신 불가. `getWebhookInfo`에서 `pending_update_count: 4`.
- **원인**: 플러그인 `server.ts`가 MCP 연결(line 614)을 `bot.start()` **이전에** 완료함. 이전 세션의 long-poll이 Telegram 서버에 남아 409 Conflict → 비409 에러 전환 시 폴링 루프가 조용히 `return`으로 종료. MCP 연결은 유지되므로 프로세스는 살아있고 "Listening" 표시되지만 실제 `getUpdates` 호출은 안 됨.
- **해결**: `_start_telegram.ps1`에 선제적 좀비 정리 + Telegram API long-poll 끊기 로직 추가. `scheduled_daily_collect.ps1`에 시작 후 헬스체크(`getWebhookInfo` → `pending_update_count` 확인) + 자동 재시작 로직 추가.
- **교훈**: 플러그인 구조상 MCP 연결과 폴링이 독립적이므로, 시작 전 이전 세션 완전 정리 + 시작 후 폴링 확인이 반드시 필요

### 2026-03-31: MCP 서버 중복 등록으로 메시지 유실
- **증상**: 7시 세션이 열리고 "Listening" 표시되지만 "시작" 메시지가 세션에 안 들어감
- **원인**: 프로젝트에 `_telegram_mcp.json`이 있었고, Claude Code가 세션 시작 시 이를 MCP 서버로 자동 등록(`settings.local.json`에 `enabledMcpjsonServers: ["telegram"]` 추가). 플러그인과 MCP 서버가 동일 봇 토큰으로 동시 폴링 → MCP 서버가 메시지를 가져가고 플러그인(채널)에는 안 들어감.
- **해결**: `_telegram_mcp.json` 삭제 + `settings.local.json`에서 MCP 설정 제거 + `scheduled_daily_collect.ps1`이 `.env` 파일에서 직접 토큰을 읽도록 수정
- **교훈**: 프로젝트 안에 텔레그램 관련 MCP config JSON을 절대 두지 않는다

### 2026-03-30: 이전 경로 좀비 프로세스
- **증상**: 동일
- **원인**: `marketplaces/.../external_plugins/telegram/` 경로의 이전 버전 bun 프로세스가 종료되지 않고 K-Beauty 봇을 계속 폴링
- **해결**: 좀비 프로세스 종료 + 이전 경로 디렉토리 삭제
