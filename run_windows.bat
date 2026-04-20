@echo off
setlocal
cd /d "%~dp0"

echo ===========================================
echo    한성대 e-Class 영상 자동 다운로더 (Win)
echo ===========================================
echo.

:: Python 설치 여부 확인
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [에러] Python이 설치되어 있지 않거나 PATH가 설정되지 않았습니다.
    echo Python 3.x를 설치해주세요.
    pause
    exit /b
)

:: 프로그램 실행
python main.py

echo.
echo ===========================================
echo 작업이 완료되었습니다.
pause
