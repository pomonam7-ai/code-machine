"""명령줄 실행:  python -m autocut 영상.mp4 [옵션]
옵션 없이 실행하면 GUI가 열립니다."""
import argparse
import sys


def main():
    if len(sys.argv) == 1:
        from .gui import main as gui_main
        return gui_main()
    from .config import Config
    from .pipeline import run, Logger

    ap = argparse.ArgumentParser(prog="autocut", description="오토컷 스튜디오 - 자동 컷편집 + 설명 일러스트 + 개인정보 모자이크")
    ap.add_argument("inputs", nargs="+", help="영상 파일(여러 개 가능)")
    ap.add_argument("-o", "--output", help="출력 파일 경로 (입력이 1개일 때)")
    ap.add_argument("--config", help="설정 JSON 파일")
    ap.add_argument("--model", help="whisper 모델 (small/medium/large-v3/large-v3-turbo)")
    ap.add_argument("--no-silence", action="store_true", help="무음 제거 끄기")
    ap.add_argument("--no-filler", action="store_true", help="필러워드 제거 끄기")
    ap.add_argument("--no-illu", action="store_true", help="일러스트 끄기")
    ap.add_argument("--no-mosaic", action="store_true", help="모자이크 끄기")
    ap.add_argument("--layout", choices=["auto", "left", "right", "full"])
    ap.add_argument("--keyword", action="append", default=[], help="추가로 가릴 단어 (여러 번 사용 가능)")
    ap.add_argument("--transcript", help="직접 만든 대본 JSON 사용")
    ap.add_argument("--fresh", action="store_true", help="이전 작업 결과를 재사용하지 않음")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    cfg = Config.from_json(a.config) if a.config else Config()
    if a.model: cfg.whisper_model = a.model
    if a.no_silence: cfg.remove_silence = False
    if a.no_filler: cfg.remove_fillers = False
    if a.no_illu: cfg.add_illustrations = False
    if a.no_mosaic: cfg.mosaic_pii = False
    if a.layout: cfg.illu_layout = a.layout
    cfg.custom_keywords += a.keyword

    def prog(stage, f):
        print(f"\r  {stage}: {f * 100:5.1f}%", end="", flush=True)
        if f >= 1:
            print()

    log = Logger(lambda m: print("\r" + m), prog, a.verbose)
    for inp in a.inputs:
        run(inp, a.output if len(a.inputs) == 1 else None, cfg, log, reuse=not a.fresh, transcript_override=a.transcript)


if __name__ == "__main__":
    main()
