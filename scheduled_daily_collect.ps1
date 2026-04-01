# K-Beauty 자동 수집 — 윈도우 스케줄러에서 호출
# 알림 전송 후 텔레그램 연결된 Claude Code 세션 시작

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# 텔레그램 알림 전송
$envFile = Join-Path $env:USERPROFILE ".claude\channels\telegram-kbeauty\.env"
$botToken = (Get-Content -LiteralPath $envFile -Encoding UTF8 | Where-Object { $_ -match "^TELEGRAM_BOT_TOKEN=" }) -replace "^TELEGRAM_BOT_TOKEN=", ""
$chatId = "8553326130"
$uri = "https://api.telegram.org/bot$botToken/sendMessage"
try {
    $body = [System.Text.Encoding]::UTF8.GetBytes((@{ chat_id = $chatId; text = $([char]0xC790 + [char]0xB8CC + " " + [char]0xC218 + [char]0xC9D1 + " " + [char]0xC2DC + [char]0xAC04 + [char]0xC785 + [char]0xB2C8 + [char]0xB2E4 + ".") } | ConvertTo-Json -Compress))
    Invoke-WebRequest -Uri $uri -Method POST -Body $body -ContentType "application/json; charset=utf-8" -ErrorAction Stop | Out-Null
} catch {}

# Claude Code 세션 시작 (별도 터미널에서)
$wtArgs = "-w new-window", "--title", "K-Beauty Telegram", "powershell", "-ExecutionPolicy", "Bypass", "-File", "$PSScriptRoot\_start_telegram.ps1"
Start-Process wt.exe -ArgumentList $wtArgs -ErrorAction SilentlyContinue

# 헬스체크: 20초 후 봇이 실제로 폴링 중인지 확인
Start-Sleep -Seconds 20

$maxRetries = 2
for ($attempt = 1; $attempt -le $maxRetries; $attempt++) {
    try {
        $webhookInfo = Invoke-RestMethod -Uri "https://api.telegram.org/bot$botToken/getWebhookInfo" -TimeoutSec 10
        $pending = $webhookInfo.result.pending_update_count
        if ($pending -eq 0) {
            Write-Host "[HEALTHCHECK] OK - 봇이 정상 폴링 중"
            break
        } else {
            Write-Host "[HEALTHCHECK] WARNING - pending_update_count=$pending (시도 $attempt/$maxRetries)"
            if ($attempt -lt $maxRetries) {
                # 알림
                $warnBody = [System.Text.Encoding]::UTF8.GetBytes((@{ chat_id = $chatId; text = "경고: 봇 폴링 실패 감지. 세션을 재시작합니다. (시도 $attempt)" } | ConvertTo-Json -Compress))
                Invoke-WebRequest -Uri $uri -Method POST -Body $warnBody -ContentType "application/json; charset=utf-8" -ErrorAction SilentlyContinue | Out-Null

                # 재시작
                Start-Sleep -Seconds 5
                Start-Process wt.exe -ArgumentList $wtArgs -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 20
            } else {
                $failBody = [System.Text.Encoding]::UTF8.GetBytes((@{ chat_id = $chatId; text = "경고: 봇 폴링 $maxRetries 회 실패. 수동 확인 필요." } | ConvertTo-Json -Compress))
                Invoke-WebRequest -Uri $uri -Method POST -Body $failBody -ContentType "application/json; charset=utf-8" -ErrorAction SilentlyContinue | Out-Null
            }
        }
    } catch {
        Write-Host "[HEALTHCHECK] 확인 실패: $_"
    }
}
