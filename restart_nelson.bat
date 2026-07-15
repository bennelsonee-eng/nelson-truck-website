@echo off
:: restart_nelson.bat - Kill orphan processes on Nelson-website dev ports and restart fresh.
:: Scoped to the Nelson website's ports (8002 + 5175) so it can coexist with the
:: Titan website (8001 + 5174) and Nelson ERP (8000 + 5173) without trampling them.
::
:: Usage:  restart_nelson.bat           (kills + restarts both backend and frontend)
::         restart_nelson.bat kill      (kills only, does not restart)
::         restart_nelson.bat backend   (kills + restarts backend only)
::         restart_nelson.bat frontend  (kills + restarts frontend only)

echo.
echo ============================================
echo   Nelson Truck Website - Restart
echo ============================================
echo.

:: Step 1: Kill backend supervisor tree on port 8002
echo [1/4] Killing Python processes on port 8002 (tree)...
powershell -NoProfile -Command "$l = Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($l) { $wpid = $l.OwningProcess; $proc = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $wpid) -EA SilentlyContinue; if ($proc) { $parent = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $proc.ParentProcessId) -EA SilentlyContinue; if ($parent -and $parent.Name -eq 'python.exe') { Write-Host ('      Killing supervisor tree PID ' + $proc.ParentProcessId); taskkill /F /T /PID $proc.ParentProcessId 2>$null | Out-Null } else { Write-Host ('      Killing worker tree PID ' + $wpid); taskkill /F /T /PID $wpid 2>$null | Out-Null } } else { Write-Host ('      Killing PID ' + $wpid + ' (no proc info)'); taskkill /F /T /PID $wpid 2>$null | Out-Null } } else { Write-Host '      Port 8002 already free' }"
timeout /t 2 /nobreak >nul

:: Step 2: Kill Node.js processes on port 5175 (Vite dev server)
echo [2/4] Killing Node processes on port 5175...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5175 " ^| findstr "LISTENING"') do (
    echo       Killing PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: Step 3: Verify ports are free
echo [3/4] Verifying ports are free...
netstat -aon | findstr ":8002 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (echo       WARNING: port 8002 still has a listener) else (echo       Port 8002 is free)
netstat -aon | findstr ":5175 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (echo       WARNING: port 5175 still has a listener) else (echo       Port 5175 is free)

if "%1" == "kill" (
    echo.
    echo Done -- ports cleared, no restart per kill arg.
    exit /b 0
)

:: Step 4: Restart backend + frontend per arg
echo [4/4] Starting services...

if "%1" == "frontend" goto :startfrontend

:startbackend
echo       Starting backend on port 8002...
start "Nelson Web Backend" cmd /c "cd /d %~dp0app\backend && set DATABASE_URL=postgresql+asyncpg://postgres:nelson2026@localhost:5432/nelson_web && .venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8002 --log-level warning"
timeout /t 3 /nobreak >nul

if "%1" == "backend" goto :done

:startfrontend
echo       Starting frontend on port 5175...
start "Nelson Web Vite" cmd /c "cd /d %~dp0app\frontend && node_modules\.bin\vite.cmd"

:done
echo.
echo ============================================
echo   Nelson services launched in new windows.
echo   Backend: http://127.0.0.1:8002
echo   Vite:    http://localhost:5175
echo ============================================
