# =====================================================================
# Windows Task Scheduler Setup for 24/7 Always-Running Monitor
# =====================================================================
# This script registers a Windows Scheduled Task that starts the Spice Nest
# Meesho Buyer Monitor at system boot, ensuring background 24-hour cycles
# run permanently without requiring an open browser tab.
#
# To register, run PowerShell as Administrator:
#   powershell -ExecutionPolicy Bypass -File .\setup_windows_service.ps1
# =====================================================================

$TaskName = "SpiceNestMeeshoBuyerMonitor"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ScriptDir "venv\Scripts\python.exe"
$AppPy = Join-Path $ScriptDir "app.py"

Write-Host "Registering Windows Task: $TaskName" -ForegroundColor Cyan
Write-Host "Directory: $ScriptDir"
Write-Host "Python: $PythonExe"

# Define the action: run python.exe app.py in working directory
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "app.py" -WorkingDirectory $ScriptDir

# Define the trigger: at system startup
$Trigger = New-ScheduledTaskTrigger -AtStartup

# Define principal: run with highest privileges
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Define settings: restart on failure, run indefinitely
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -ExecutionTimeLimit (New-TimeSpan -Days 365)

try {
    # Unregister existing task if present
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    
    # Register new task
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "24-Hour Autonomous Meesho Buyer-Side Price Monitoring Daemon for Spice Nest Impex"
    Write-Host "✓ Windows Task '$TaskName' registered successfully!" -ForegroundColor Green
    Write-Host "The 24-hour monitoring daemon will run automatically at PC boot." -ForegroundColor Green
} catch {
    Write-Warning "Could not register as SYSTEM service (requires Administrator privilege)."
    Write-Host "Alternative: Use start_buyer_monitor.bat or run under current user account." -ForegroundColor Yellow
}
