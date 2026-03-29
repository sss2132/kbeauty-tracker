chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

$env:Path = "$env:USERPROFILE\.bun\bin;$env:Path"

Set-Location "C:\Users\Taejun Park\Desktop\K-Beauty"

$env:TELEGRAM_STATE_DIR = "$env:USERPROFILE\.claude\channels\telegram-kbeauty"
$env:TELEGRAM_BOT_TOKEN = "8723850429:AAHAds6417Co8TEqi5muSO_asT_dq2yuNuE"

# 1. Telegram notification via Bot API
$botToken = $env:TELEGRAM_BOT_TOKEN
$chatId = "8553326130"
$uri = "https://api.telegram.org/bot$botToken/sendMessage"
try {
    $body = [System.Text.Encoding]::UTF8.GetBytes((@{ chat_id = $chatId; text = "자료 수집 시간입니다." } | ConvertTo-Json -Compress))
    Invoke-WebRequest -Uri $uri -Method POST -Body $body -ContentType "application/json; charset=utf-8" -ErrorAction Stop | Out-Null
} catch {
    Write-Host "Telegram notification failed: $_"
}

# 2. Interactive Claude Code session with Telegram channel + explicit MCP config
$mcpConfig = "C:\Users\Taejun Park\Desktop\K-Beauty\kbeauty-tracker\_telegram_mcp.json"
& "C:\Users\Taejun Park\.local\bin\claude.exe" --channels plugin:telegram@claude-plugins-official --mcp-config $mcpConfig
