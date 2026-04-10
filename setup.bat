@echo off
set PYTHONUTF8=1
echo Starting setup...

REM 1. Set base and app directories
set BASE_DIR=%~dp0
set APP_DIR=%BASE_DIR%appfiles
echo Setting up in: %APP_DIR%

if not exist "%APP_DIR%" mkdir "%APP_DIR%"
cd /d "%APP_DIR%"

REM 2. Clone the Rootport-AI LaMa fork
echo Cloning Rootport-AI LaMa repository (GPU-enhanced fork)...
git clone https://github.com/Rootport-AI/lama.git
if errorlevel 1 (
    echo Failed to clone repository.
    pause
    exit /b 1
)

REM 3. Create directories for Flask app
cd lama
echo Creating directories for Flask app...
if not exist "templates" mkdir templates
if not exist "static\js" mkdir static\js
if not exist "static\css" mkdir static\css

REM 4. Copy custom application files
echo Copying custom files...
copy /Y "%BASE_DIR%app.py" .
copy /Y "%BASE_DIR%index.html" "templates\index.html"
copy /Y "%BASE_DIR%main.js" "static\js\main.js"
copy /Y "%BASE_DIR%style.css" "static\css\style.css"

REM 5. Verify that Python 3.10 is available via the py launcher.
REM    Multiple Python versions may be installed on Windows; py -3.10 ensures
REM    we create the venv with exactly 3.10.
echo Checking for Python 3.10...
py -3.10 --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.10 was not found. Please install Python 3.10 and try again.
    echo Download: https://www.python.org/downloads/release/python-31011/
    pause
    exit /b 1
)
echo Python 3.10 found.

REM 6. Create virtual environment with Python 3.10 explicitly
echo Creating virtual environment with Python 3.10...
py -3.10 -m venv venv
if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
)

REM 7. Pin pip to 23.0.1 (newer pip versions have metadata compatibility issues
REM    with some packages in require.txt, such as pytorch-lightning).
echo Installing pip 23.0.1...
venv\Scripts\python.exe -m pip install pip==23.0.1
if errorlevel 1 (
    echo Failed to install pip 23.0.1.
    pause
    exit /b 1
)

REM 8. Install all Python dependencies
echo Installing requirements from require.txt...
venv\Scripts\python.exe -m pip install -r "%BASE_DIR%require.txt"
if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
)

REM 9. Download the big-lama model from Hugging Face
echo Downloading big-lama model from Hugging Face...
curl -L -o big-lama.zip https://huggingface.co/smartywu/big-lama/resolve/main/big-lama.zip
if errorlevel 1 (
    echo Failed to download big-lama model. Check your internet connection.
    pause
    exit /b 1
)

REM 10. Extract the model archive
echo Extracting big-lama model...
mkdir temp
powershell -Command "Expand-Archive -Path big-lama.zip -DestinationPath temp -Force"
if errorlevel 1 (
    echo Failed to extract big-lama model.
    pause
    exit /b 1
)

if exist big-lama rmdir /s /q big-lama
move temp\big-lama big-lama
if errorlevel 1 (
    echo Failed to move model files.
    pause
    exit /b 1
)

rmdir /s /q temp
del big-lama.zip

REM 11. Done
echo.
echo Setup completed successfully.
echo Application installed in: %APP_DIR%
pause
