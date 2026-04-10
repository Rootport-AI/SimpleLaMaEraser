@echo off
set PYTHONUTF8=1

REM Set base and application directories
set BASE_DIR=%~dp0
set APP_DIR=%BASE_DIR%appfiles\lama

REM Verify the application directory exists
if not exist "%APP_DIR%" (
    echo ERROR: Application directory not found: %APP_DIR%
    echo Please run setup.bat first.
    pause
    exit /b 1
)

REM Locate the venv Python executable.
REM Using venv\Scripts\python.exe directly avoids ambiguity about which Python
REM is active in the current shell, regardless of PATH or activate state.
set VENV_PYTHON=%APP_DIR%\venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo ERROR: venv Python not found: %VENV_PYTHON%
    echo Please run setup.bat first.
    pause
    exit /b 1
)

REM Set environment variables required by the app
set TORCH_HOME=%APP_DIR%
set PYTHONPATH=%APP_DIR%

REM Launch the application
echo Starting SimpleLaMaEraser...
echo Open your browser at http://localhost:7859
cd /d "%APP_DIR%"
"%VENV_PYTHON%" app.py
if errorlevel 1 (
    echo ERROR: Application exited with an error.
    pause
    exit /b 1
)

pause
