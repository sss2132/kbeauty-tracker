@echo off
chcp 65001 >nul

cd /d "C:\Users\Taejun Park\Desktop\K-Beauty"

:: Set K-Beauty bot token (overrides shared .env)
set TELEGRAM_BOT_TOKEN=8723850429:AAHAds6417Co8TEqi5muSO_asT_dq2yuNuE

:: 1. Send Telegram notification via one-shot -p mode
"C:\Users\Taejun Park\.local\bin\claude.exe" --channels plugin:telegram@claude-plugins-official -p "텔레그램 chat_id 8553326130 으로 '오후 7시 자료 수집 시간입니다. 텔레그램으로 자료 수집 시작 이라고 보내주세요.' 라고 메시지를 보내줘." >nul 2>&1

:: 2. Open interactive Claude Code session with Telegram channels
"C:\Users\Taejun Park\.local\bin\claude.exe" --channels plugin:telegram@claude-plugins-official
