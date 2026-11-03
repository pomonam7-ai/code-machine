@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo 먼저 install.bat 을 실행해 주세요.
  pause
  exit /b 1
)
rem 영상 파일을 이 아이콘 위에 끌어다 놓으면 바로 편집, 그냥 실행하면 프로그램 창이 열립니다.
if "%~1"=="" (
  start "" venv\Scripts\pythonw.exe -m autocut
) else (
  venv\Scripts\python.exe -m autocut %*
  echo.
  pause
)
