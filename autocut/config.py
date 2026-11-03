"""기본 설정값. GUI/CLI에서 덮어쓸 수 있습니다."""
from dataclasses import dataclass, field, asdict
import json


@dataclass
class Config:
    # ---------- 음성 인식 ----------
    whisper_model: str = "auto"          # auto | small | medium | large-v3 | large-v3-turbo
    device: str = "auto"                  # auto | cuda | cpu
    language: str = "ko"

    # ---------- 컷 편집 ----------
    remove_silence: bool = True
    remove_fillers: bool = True
    min_silence: float = 0.55             # 이 길이 이상 쉬면 잘라냄 (초)
    keep_pause: float = 0.18              # 자른 자리 앞뒤로 남기는 호흡 (초)
    sentence_pause: float = 0.32          # 문장 끝(. ? !) 뒤에는 조금 더 길게 남김
    pre_pad: float = 0.06                 # 말 시작 직전 여유
    post_pad: float = 0.10                # 말 끝난 직후 여유
    min_keep: float = 0.12                # 이보다 짧은 조각은 버림
    crossfade_ms: float = 12.0            # 컷 지점 '틱' 소리 방지
    # 단독으로 등장하면 무조건 컷하는 필러
    fillers: list = field(default_factory=lambda: [
        "어", "어어", "어어어", "음", "음음", "으음", "음…", "어…", "엄", "흠", "으", "에", "에에",
        "um", "uh", "umm", "uhm", "hmm",
    ])
    # 길게 끌 때만(머뭇거림) 컷하는 단어 - 문장 성분일 수도 있어서 보수적으로
    soft_fillers: list = field(default_factory=lambda: ["그", "저", "그니까", "막", "뭐", "아"])
    soft_filler_min_dur: float = 0.38

    # ---------- 설명 일러스트 ----------
    add_illustrations: bool = True
    illustration_engine: str = "auto"     # auto | vector | sd   (sd = 로컬 Stable Diffusion, GPU 권장)
    planner: str = "auto"                 # auto | rules | ollama
    ollama_model: str = "qwen2.5:7b"
    ollama_url: str = "http://localhost:11434"
    sd_model: str = "stabilityai/sdxl-turbo"
    illu_min_gap: float = 12.0            # 일러스트 사이 최소 간격 (초)
    illu_min_dur: float = 2.6
    illu_max_dur: float = 6.0
    illu_layout: str = "auto"             # auto(얼굴 반대편) | left | right | full
    illu_style: str = "sticker"           # sticker(투명 배경 + 흰 테두리) | card(종이 카드)
    use_logos: bool = True                # assets/logos의 로고 이름이 대본에 나오면 로고를 띄움
    logo_dir: str = ""                    # 비우면 assets/logos
    illu_scale: float = 0.42              # 화면 폭 대비 카드 크기
    max_label_chars: int = 7              # 글자는 최소한으로
    font_path: str = ""                   # 비우면 assets/fonts → 맑은 고딕 순으로 찾음

    # ---------- 개인정보 모자이크 ----------
    mosaic_pii: bool = True
    ocr_engine: str = "auto"              # auto | easyocr | tesseract
    ocr_interval: float = 0.5             # 몇 초마다 화면 글자 검사
    ocr_max_side: int = 1280              # OCR 시 축소 해상도 (속도)
    mosaic_hold: float = 0.6              # 감지 전후로 모자이크 유지 시간
    custom_keywords: list = field(default_factory=list)  # 이름 등 추가로 가릴 단어

    # ---------- 출력 ----------
    video_codec: str = "libx264"          # libx264 | h264_nvenc
    crf: int = 19
    preset: str = "medium"
    fps: float = 0                        # 0 = 원본 유지
    write_srt: bool = True

    def to_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        c = cls()
        for k, v in data.items():
            if hasattr(c, k):
                setattr(c, k, v)
        return c
