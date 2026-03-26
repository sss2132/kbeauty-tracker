Set-Location "C:\Users\Taejun Park\Desktop\K-Beauty"

# K-Beauty 전용 텔레그램 state dir (다른 세션과 봇 토큰 충돌 방지)
$env:TELEGRAM_STATE_DIR = "$env:USERPROFILE\.claude\channels\telegram-kbeauty"
$env:TELEGRAM_BOT_TOKEN = "8723850429:AAHAds6417Co8TEqi5muSO_asT_dq2yuNuE"

# 1. Telegram notification via Bot API (direct, no Claude needed)
$botToken = "8723850429:AAHAds6417Co8TEqi5muSO_asT_dq2yuNuE"
$chatId = "8553326130"
$message = "자료 수집 시간입니다."
$uri = "https://api.telegram.org/bot$botToken/sendMessage"
try {
    $body = @{ chat_id = $chatId; text = $message } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri $uri -Method POST -Body $body -ContentType "application/json; charset=utf-8" -ErrorAction Stop | Out-Null
} catch {
    Write-Host "Telegram notification failed: $_"
}

# 2. Interactive Claude Code session with Telegram channels
& "C:\Users\Taejun Park\.local\bin\claude.exe" --channels plugin:telegram@claude-plugins-official
