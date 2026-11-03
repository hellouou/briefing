# 스케줄러 삭제 스크립트
$TaskName = "DailyEconomicBriefing"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "🗑️ [$TaskName] 스케줄러 작업이 삭제되었습니다." -ForegroundColor Yellow

