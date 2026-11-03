# agent.md

이 저장소에서 작업하는 모든 AI 코딩 에이전트(Claude, Codex, Cursor 등) 공통 규칙입니다. 구조와 불변 조건 상세는 `CLAUDE.md`를 보세요.

## 목표
유튜브 등 강의/설명 영상을 넣으면 사람 편집자 수준의 1차 편집본을 자동으로 만듭니다.
1. 무음 구간과 필러워드("어", "음")를 컷합니다. 이해를 해치지 않는 선에서만 자릅니다.
2. 이해를 돕는 설명 일러스트를 넣습니다. 플랫 벡터 + 핸드드로잉 카툰 스타일이고 글자는 최소로 씁니다.
3. 화면 속 개인정보를 모자이크합니다.
4. 결과는 완성 MP4와 SRT 자막입니다.

## 제약
- **무료·오프라인 우선**: 기본 경로에는 유료 API, 계정, 클라우드 호출이 없어야 합니다. 선택 기능(Ollama, Stable Diffusion)도 로컬에서만 돌아야 합니다.
- **Windows 일반 사용자 대상**: 더블클릭 설치(`install.bat`)와 실행(`run.bat`)이 항상 동작해야 합니다. 새 의존성은 `requirements.txt`에 넣고, Windows용 휠이 있는지 확인하세요.
- **Python 3.10~3.12**를 지원합니다.
- **UI, 로그, 메시지는 한국어**로 씁니다.
- 기능은 실패해도 **우아하게 폴백**해야 합니다:
  - GPU → CPU
  - EasyOCR → Tesseract
  - Ollama → 규칙
  - SD → 벡터

## 작업 규칙
- 변경한 뒤에는 합성 테스트 영상으로 `python -m autocut <test.mp4> --transcript <json> --fresh`를 실행하고 아래를 확인합니다:
  - 오류가 없는지
  - 영상과 오디오 길이가 같은지
  - 캡처한 프레임에 일러스트와 모자이크가 정상인지
- 개인정보 정규식을 바꾸면 오탐(일반 숫자, 날짜)과 미탐(하이픈/공백 변형, OCR 오인식 O↔0, l↔1)을 모두 점검합니다.
- 비밀값(API 키, 토큰)은 `.env`에만 두고 커밋하지 않습니다. `.env`는 `.gitignore`에 들어 있습니다.
- 대용량 산출물은 커밋하지 않습니다:
  - 영상
  - `*_autocut_work/`
  - 모델 캐시
  - `venv/`
- `.bat` 파일은 UTF-8, CRLF 줄바꿈을 유지합니다.

## 디렉터리
```
autocut/            파이썬 패키지 (python -m autocut)
assets/fonts/       손글씨 폰트 (install.bat이 Gaegu-Bold 다운로드, 커밋 안 함)
assets/illustration_styles.png  일러스트 33종 미리보기
install.bat / install_gpu.bat / run.bat
```
