@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo   VeriText - First-Time Windows Setup
echo ========================================
echo Developed By: Mohammad Omar Salameh
where py >nul 2>nul
if errorlevel 1 (
    echo Python Launcher not found. Install Python 3.11+ and run this script again.
    pause
    exit /b 1
)
py -m venv .venv
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail
if not exist .env copy .env.example .env >nul
echo.
echo IMPORTANT: Edit .env and set a unique APP_SECRET before public deployment.
echo.
set /p ADMIN_EMAIL="Administrator email: "
.venv\Scripts\python.exe -m app.cli create-admin --email "%ADMIN_EMAIL%"
if errorlevel 1 goto :fail
echo.
echo Setup complete. Run launch_windows.bat to start VeriText.
pause
exit /b 0
:fail
echo Setup failed. Check the messages above.
pause
exit /b 1
