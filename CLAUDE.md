# CLAUDE.md

이 저장소에서 작업하는 Claude Code용 안내입니다. 다른 에이전트 공통 규칙은 `agent.md`를 함께 보세요.

## 프로젝트 한 줄 요약
**오토컷 스튜디오**: 영상 → (음성인식 대본) → 무음·필러워드 1차 컷 → 설명 일러스트(플랫 벡터 + 핸드드로잉 카툰) 오버레이 → 화면 속 개인정보 모자이크 → 완성 MP4.
대상 환경은 **Windows PC, 무료·오프라인**입니다. 유료 API나 클라우드 서비스를 추가하지 마세요.

## 실행
```bash
# 웹앱 (인자 없이, 브라우저 자동 열림). 예전 tkinter 창은 --gui
python -m autocut [--web --port 8765 --no-browser]
python -m autocut --gui
# CLI
python -m autocut 영상.mp4 [-o out.mp4] [--no-illu] [--no-mosaic] [--layout auto|left|right|full] [--style sticker|card] [--no-logo] [--keyword 이름] [--fresh] [-v]
# 일괄 처리 (폴더/여러 파일). 여러 개일 때 이미 편집된 영상은 건너뜀
python -m autocut 폴더 [-r] [--out-dir 결과폴더] [--redo] [--list]
# 음성인식 없이 테스트 (대본 JSON 직접 주입)
python -m autocut test.mp4 --transcript transcript.json --fresh
```
Windows 사용자는 `install.bat` → `run.bat`을 씁니다. 폴더 일괄 처리는 `batch.bat`(폴더를 끌어다 놓기)입니다. GPU 선택 설치는 `install_gpu.bat`입니다.

## 구조 (`autocut/`)
| 파일 | 역할 |
|---|---|
| `config.py` | 모든 튜닝 값(`Config` dataclass). 새 옵션은 여기 추가하고 GUI/CLI에 연결합니다. |
| `media.py` | ffmpeg 래퍼. ffprobe 없이 `ffmpeg -i`로 파싱합니다. CFR 디코딩 파이프(`FrameReader`)와 인코딩(`FrameWriter`)이 있습니다. |
| `transcribe.py` | faster-whisper로 단어 타임스탬프를 만듭니다. 필러가 받아 적히도록 `initial_prompt`를 씁니다. CUDA 실패 시 CPU로 폴백합니다. |
| `cutter.py` | `compute_cuts`(남길 구간 계산), `TimeMap`(원본↔편집본 시간), `build_audio_wav` |
| `planner.py` | 일러스트 넣을 문장 선택. `rules`(키워드+신호어)와 `ollama`(로컬 LLM, 선택)가 있습니다. |
| `illustrate.py` | PIL 절차적 일러스트 엔진(`Pen`, `ICONS` 33종). `render_overlay`가 `render_sticker`(투명 배경 + 흰 테두리, 기본)와 `render_card`(종이 카드)를 고릅니다. 로고 라이브러리(`list_logos`/`load_logo`, `assets/logos`)와 `remove_background`(테두리와 이어진 단색 배경만 투명화). 선택적으로 `SDEngine`(diffusers). |
| `pii.py` | OCR(EasyOCR→Tesseract 폴백), 한국형 개인정보 정규식, 같은 줄 상자 묶기, 모자이크 이벤트 병합 |
| `pipeline.py` | 전체 오케스트레이션, 오버레이 애니메이션, 작업 폴더 캐시, SRT 저장 |
| `batch.py` | 일괄 처리. `collect_inputs`(폴더 펼치기, `_편집본`/작업 폴더 제외), `is_done`(건너뛰기 판정), `run_batch`(영상별 오류 격리, 중지, CSV 요약). CLI와 GUI 모두 이걸 거칩니다. |
| `web.py` | 로컬 웹앱 서버(표준 라이브러리 `http.server`, 추가 의존성 없음). 작업 1개씩(`Job`), 폴더 탐색, 일러스트 편집 저장/재렌더, 미리보기 PNG, 로고 업로드, Range 지원 파일 전송. |
| `webui/index.html` | 웹앱 화면 한 파일(인라인 CSS/JS, 외부 CDN 없음). `__TOKEN__`을 서버가 채웁니다. |
| `gui.py` | 예전 tkinter GUI(`--gui`). 작업 스레드와 큐로 로그/진행률을 전달합니다. |

## 꼭 지켜야 할 불변 조건
- **A/V 싱크**: 남길 구간은 `compute_cuts`에서 **프레임 경계로 반올림**됩니다. 영상(프레임 선택)과 오디오(샘플 슬라이스)가 같은 구간을 써야 합니다. 이 반올림을 깨지 마세요.
- **시간 기준**: 일러스트와 모자이크 이벤트는 **편집본 타임라인** 기준입니다(`TimeMap.to_out`). 원본 시간과 섞지 마세요.
- **메모리**: 오디오는 int16으로 읽고 구간별로 WAV에 스트리밍합니다. 전체 영상을 메모리에 올리지 마세요.
- **"이해를 해치지 않는 선"**: 컷은 보수적으로 합니다. 문장 끝 쉼(`sentence_pause`)과 호흡(`keep_pause`)을 남기고, 애매한 필러(`soft_fillers`)는 길게 끌 때만 자릅니다.
- **일러스트 글자 최소화**: 라벨은 키워드 1개, `max_label_chars`(기본 7) 이하입니다.
- **Windows 호환**: 서브프로세스에 `creationflags=_NOWIN`, 경로에 한글 허용, `.bat` 파일은 UTF-8 + CRLF + `chcp 65001`. `.bat`의 `( )` 블록 안 echo에서 괄호는 `^(` `^)`로 이스케이프합니다.

## 웹앱 규칙
- **오프라인**: 외부 CDN·폰트·스크립트를 쓰지 않습니다. 모든 CSS/JS는 `webui/index.html` 안에 둡니다.
- **보안**: `127.0.0.1`에만 바인딩합니다. 모든 `/api/*`는 실행마다 새로 만드는 토큰(`X-Token` 헤더 또는 `t` 쿼리)과 `Host`가 `127.0.0.1`/`localhost`인지 확인합니다(DNS 리바인딩 방지). `/api/file`은 `SERVE_EXTS` 확장자만 보냅니다. 이 검사를 빼지 마세요.
- 웹에서 바꿀 수 있는 설정은 `web.WEB_OPTIONS`에만 둡니다. 새 옵션을 웹에 노출하려면 여기와 화면 버튼을 같이 추가합니다.
- 편집기의 시간은 **편집본 타임라인** 기준이고, 저장은 기존 `keep_hash`를 유지한 채 `illustrations.json`만 바꿉니다(재렌더 시 대본·분석 재사용).
- 확인: 서버를 띄우고 Playwright로 추가 → 시작 → 결과 → 일러스트 편집 → 다시 만들기 흐름을 눌러 보고, 390px 폭에서 가로 스크롤이 없는지 봅니다.

## 일괄 처리 규칙
- 렌더링은 `<결과>.part.mp4`에 쓰고 끝나면 이름을 바꿉니다. 실패/중지 시 임시 파일은 지웁니다. 중간에 멈춘 파일을 완성본으로 착각해 건너뛰지 않기 위한 것이니 유지하세요.
- 건너뛰기는 **영상이 여러 개일 때만** 기본으로 켭니다. 1개를 지정하면 항상 다시 만듭니다(JSON 수정 후 재렌더링 흐름 보호).
- `is_done`은 결과가 원본보다 새롭고, 작업 폴더의 `transcript.json`/`illustrations.json`/`pii.json`보다도 새로울 때만 참입니다.

## 작업 폴더 캐시
`<영상>_autocut_work/`에 `transcript.json`, `cuts.json`, `illustrations.json`, `pii.json`, `cards/`, `settings.json`이 저장됩니다. 재실행하면 재사용합니다(`keep_hash` 일치 시). `--fresh`를 주면 무시합니다. 사용자가 JSON을 손으로 고쳐 재렌더링하는 흐름을 깨지 마세요.

## 테스트 방법
음성인식/OCR 모델 없이도 컷·렌더·일러스트를 검증할 수 있습니다.
1. 합성 영상(말소리 대신 톤 버스트 + 무음)과 그에 맞춘 `transcript.json`을 만듭니다.
2. `--transcript`로 실행합니다.
3. 아래를 확인합니다:
   - `ffprobe`로 영상·오디오 길이가 같은지
   - `cuts.json`의 구간
   - 프레임 캡처로 일러스트와 모자이크
- 일러스트를 추가하거나 수정하면 `render_card`로 전체 갤러리를 렌더링해서 눈으로 확인합니다.

## 새 일러스트 아이콘 추가
`illustrate.py`에 `def i_xxx(p, F)`를 작성합니다. 단위 좌표 -1~1을 쓰고 `p.poly/ellipse/rrect/line/arrow/face/sparkle`을 사용합니다. 그다음 `ICONS["xxx"] = (i_xxx, "기본라벨", ["한국어 키워드", "동사어간*"])`에 등록합니다. `*`로 끝나는 키워드는 동사 어간이라 기본 라벨을 씁니다.
