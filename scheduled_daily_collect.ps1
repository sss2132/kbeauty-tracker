# K-Beauty 자동 수집 — 윈도우 스케줄러에서 호출

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# 기존 K-Beauty 세션 정리
Get-CimInstance Win32_Process -Filter "Name='claude.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'K-Beauty' -and $_.ProcessId -ne $PID } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

# 텔레그램 알림 전송
$envFile = Join-Path $env:USERPROFILE ".claude\channels\telegram-kbeauty\.env"
$botToken = (Get-Content -LiteralPath $envFile -Encoding UTF8 | Where-Object { $_ -match "^TELEGRAM_BOT_TOKEN=" }) -replace "^TELEGRAM_BOT_TOKEN=", ""
$chatId = "8553326130"
$uri = "https://api.telegram.org/bot$botToken/sendMessage"
try {
    $msgBody = @{ chat_id = $chatId; text = [char]0xC790 + [char]0xB8CC + [char]0xC218 + [char]0xC9D1 + " " + [char]0xC2DC + [char]0xAC04 + [char]0xC785 + [char]0xB2C8 + [char]0xB2E4 + "." } | ConvertTo-Json -Compress
    $msgBytes = [System.Text.Encoding]::UTF8.GetBytes($msgBody)
    Invoke-WebRequest -Uri $uri -Method POST -Body $msgBytes -ContentType "application/json; charset=utf-8" -ErrorAction Stop | Out-Null
} catch {}

# Claude Remote Control 세션 시작 (로컬+원격 양방향)
$scriptBlock = @'
Set-Location "C:\Users\Taejun Park\Desktop\K-Beauty"
& "C:\Users\Taejun Park\.local\bin\claude.exe" --remote-control "K-Beauty Daily"
'@
$encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($scriptBlock))
Start-Process wt.exe -ArgumentList "new-tab --title KBeauty-Remote powershell -NoExit -EncodedCommand $encoded"
