@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo 먼저 install.bat 을 실행해 주세요.
  pause
  exit /b 1
)
rem 영상 폴더(또는 여러 영상)를 이 아이콘 위에 끌어다 놓으면 안의 영상을 모두 차례로 편집합니다.
rem 이미 편집된 영상은 건너뛰고, 끝나면 결과 요약 CSV를 만듭니다.
set "TARGET=%~1"
if "%TARGET%"=="" (
  echo 편집할 영상이 들어 있는 폴더 경로를 붙여 넣고 Enter를 누르세요.
  echo ^(탐색기 주소창에서 복사하거나, 폴더를 이 창에 끌어다 놓아도 됩니다^)
  set /p "TARGET=폴더: "
)
if "%TARGET%"=="" exit /b 1
if "%~1"=="" (
  venv\Scripts\python.exe -m autocut "%TARGET:"=%" -r
) else (
  venv\Scripts\python.exe -m autocut %* -r
)
echo.
pause
