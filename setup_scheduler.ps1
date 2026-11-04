# 매일 아침 06:00 스케줄러 등록 스크립트 (인코딩 무결성 보장)
$PythonExe = "$env:USERPROFILE\.local\bin\python3.15.exe"
$RegisterScript = Join-Path $PSScriptRoot "register_task.py"

if (Test-Path $PythonExe) {
    & $PythonExe $RegisterScript
} else {
    Write-Host "Python 경로를 찾을 수 없습니다: $PythonExe" -ForegroundColor Red
}
