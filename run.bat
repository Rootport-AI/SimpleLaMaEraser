@echo off

REM --- �x�[�X�f�B���N�g���ƃA�v���P�[�V�����f�B���N�g����ݒ� ---
set BASE_DIR=%~dp0
set APP_DIR=%BASE_DIR%appfiles\lama

REM --- �A�v���P�[�V�����f�B���N�g�������݂��邩�m�F ---
if not exist "%APP_DIR%" (
    echo �G���[: �A�v���P�[�V������������܂���B%APP_DIR% �����݂��܂���B
    echo �Z�b�g�A�b�v���Ɏ��s���Ă��������B
    pause
    exit /b 1
)

REM --- ��ƃf�B���N�g�����A�v���P�[�V�����f�B���N�g���Ɉړ� ---
cd /d "%APP_DIR%"

REM --- ���z����L���� ---
echo ���z����L�������Ă��܂�...
call venv\Scripts\activate
if errorlevel 1 (
    echo �G���[: ���z���̗L�����Ɏ��s���܂����B
    pause
    exit /b 1
)

REM --- ���ϐ���ݒ� ---
set TORCH_HOME=%CD%
set PYTHONPATH=%CD%

REM --- �A�v���P�[�V�������N�� ---
echo LaMa AI�����c�[�����N�����Ă��܂�...
echo �u���E�U�� http://localhost:7859 ���J���Ă��������B
python app.py
if errorlevel 1 (
    echo �G���[: �A�v���P�[�V�����̋N���Ɏ��s���܂����B
    pause
    exit /b 1
)

pause