@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (echo 먼저 install.bat 을 실행하세요 & pause & exit /b 1)
call venv\Scripts\activate.bat
echo NVIDIA GPU 가속 설치 (음성인식·글자인식·이미지모델이 빨라집니다)
nvidia-smi >nul 2>&1 || (echo [!] NVIDIA 그래픽카드/드라이버를 찾지 못했습니다. & pause & exit /b 1)

python -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu124
python -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"

echo.
set /p SD="로컬 AI 이미지 모델(Stable Diffusion)도 설치할까요? 그래픽 메모리 8GB 이상 권장 (y/n): "
if /i "%SD%"=="y" (
  python -m pip install diffusers transformers accelerate safetensors
  echo 설치 완료 - 첫 실행 때 이미지 모델 ^(약 7GB^)을 내려받습니다.
)
echo.
echo GPU 설정 완료!
pause
