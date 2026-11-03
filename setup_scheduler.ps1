# 매일 아침 06:00 스케줄러 등록 스크립트
$TaskName = "DailyEconomicBriefing"
$PythonPath = "C:\Users\김영신\.local\bin\python3.15.exe"
$ScriptPath = "$PSScriptRoot\briefing.py"

$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`"" -WorkingDirectory $PSScriptRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At 6:00AM
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "매일 아침 06:00 경제 및 증시 데이터 자동 수집" -Force
Write-Host "✅ [$TaskName] 매일 오전 06:00 스케줄러가 성공적으로 등록되었습니다." -ForegroundColor Green

