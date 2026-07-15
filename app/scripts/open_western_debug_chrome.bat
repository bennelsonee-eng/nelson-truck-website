@echo off
REM Launch Chrome with remote debugging enabled, in a dedicated profile.
REM After Chrome opens, navigate to:
REM   https://resources.westernplows.com/quick-match/plow/step1
REM Solve the hCaptcha. Leave the window open. Then run:
REM   python -m app.scripts.warm_western_session_cdp

set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
set PROFILE=%TEMP%\western-debug-profile

if not exist %CHROME% (
    echo Chrome not found at %CHROME%
    exit /b 1
)

echo Launching Chrome with --remote-debugging-port=9222
echo Profile dir: %PROFILE%
start "" %CHROME% --remote-debugging-port=9222 --user-data-dir="%PROFILE%" "https://resources.westernplows.com/quick-match/plow/step1"
