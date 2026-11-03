@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo 먼저 install.bat 을 실행해 주세요.
  pause
  exit /b 1
)
rem 영상 파일을 이 아이콘 위에 끌어다 놓으면 바로 편집, 그냥 실행하면 브라우저에서 웹앱이 열립니다.
rem 예전 창 화면을 쓰려면: venv\Scripts\python.exe -m autocut --gui
if "%~1"=="" (
  title 오토컷 스튜디오
  echo 브라우저에서 오토컷 스튜디오가 열립니다.
  echo 이 창은 닫지 마세요 ^(닫으면 프로그램이 꺼집니다^). 최소화해 두면 됩니다.
  venv\Scripts\python.exe -m autocut
) else (
  venv\Scripts\python.exe -m autocut %*
  echo.
  pause
)
