import os
import sys
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# C:\Users\김영신\.local\bin\python3.15.exe
PYTHON_PATH = os.path.expandvars(r"%USERPROFILE%\.local\bin\python3.15.exe")
SCRIPT_PATH = os.path.join(BASE_DIR, "briefing.py")

xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>매일 아침 06:00 경제 및 증시 데이터 자동 수집</Description>
    <URI>\\DailyEconomicBriefing</URI>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <IdleSettings>
      <Duration>PT10M</Duration>
      <WaitTimeout>PT1H</WaitTimeout>
      <StopOnIdleEnd>true</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
  </Settings>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-11-05T06:00:00+09:00</StartBoundary>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>{PYTHON_PATH}</Command>
      <Arguments>"{SCRIPT_PATH}"</Arguments>
      <WorkingDirectory>{BASE_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

temp_xml = os.path.join(BASE_DIR, "_task_temp.xml")
with open(temp_xml, "w", encoding="utf-16") as f:
    f.write(xml_content)

print(f"Registering task with:")
print(f"  Python: {PYTHON_PATH}")
print(f"  Script: {SCRIPT_PATH}")
print(f"  WorkDir: {BASE_DIR}")

cmd = ["schtasks.exe", "/create", "/xml", temp_xml, "/tn", "DailyEconomicBriefing", "/f"]
res = subprocess.run(cmd, capture_output=True)

try:
    os.remove(temp_xml)
except Exception:
    pass

output = res.stdout.decode("cp949", errors="replace") if res.stdout else ""
err = res.stderr.decode("cp949", errors="replace") if res.stderr else ""

if res.returncode == 0:
    print("SUCCESS:", output.strip())
else:
    print("ERROR:", err.strip())
