@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo   오토컷 스튜디오 설치 (처음 한 번만)
echo ============================================

set PY=
py -3.11 --version >nul 2>&1 && set PY=py -3.11
if not defined PY py -3.12 --version >nul 2>&1 && set PY=py -3.12
if not defined PY py -3.10 --version >nul 2>&1 && set PY=py -3.10
if not defined PY python --version >nul 2>&1 && set PY=python
if not defined PY (
  echo [!] Python이 없습니다. 자동 설치를 시도합니다...
  winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
  echo.
  echo 설치가 끝나면 이 창을 닫고 install.bat 을 다시 실행해 주세요.
  echo 자동 설치가 안 되면 https://www.python.org/downloads/ 에서 3.11 설치 - "Add to PATH" 체크
  pause
  exit /b 1
)
echo 사용할 Python: %PY%

if not exist venv (
  %PY% -m venv venv || (echo 가상환경 생성 실패 & pause & exit /b 1)
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || (echo [!] 패키지 설치 실패. 인터넷 연결을 확인하세요. & pause & exit /b 1)

echo.
echo 손글씨 폰트(Gaegu, 무료 OFL) 다운로드...
if not exist assets\fonts mkdir assets\fonts
if not exist assets\fonts\Gaegu-Bold.ttf (
  powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing 'https://github.com/google/fonts/raw/main/ofl/gaegu/Gaegu-Bold.ttf' -OutFile 'assets\fonts\Gaegu-Bold.ttf' } catch { Write-Host '폰트 다운로드 실패 - 맑은 고딕을 사용합니다' }"
)

echo.
echo 모델 미리 받기 (음성인식 / 글자인식) - 몇 분 걸릴 수 있어요...
python -c "import easyocr; easyocr.Reader(['ko','en'], gpu=False, verbose=False)"
python -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8')"

echo.
echo ============================================
echo   설치 완료!  run.bat 을 더블클릭해서 실행하세요.
echo   (NVIDIA 그래픽카드가 있으면 install_gpu.bat 도 실행하면 훨씬 빨라집니다)
echo ============================================
pause
