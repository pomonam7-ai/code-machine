"""명령줄 실행:  python -m autocut 영상.mp4 [옵션]
폴더를 주면 안의 영상을 모두 일괄 편집합니다:  python -m autocut 영상폴더 [-r] [--out-dir 결과폴더]
옵션 없이 실행하면 웹앱(브라우저 화면)이 열립니다.  --gui: 예전 창 화면,  --web [--port N]: 웹앱"""
import argparse
import sys


def main():
    if len(sys.argv) == 1 or sys.argv[1] == "--web":
        from .web import main as web_main
        return web_main(sys.argv[2:])
    if sys.argv[1] == "--gui":
        from .gui import main as gui_main
        return gui_main()
    from .config import Config
    from .pipeline import Logger
    from .batch import collect_inputs, run_batch

    ap = argparse.ArgumentParser(prog="autocut", description="오토컷 스튜디오 - 자동 컷편집 + 설명 일러스트 + 개인정보 모자이크")
    ap.add_argument("inputs", nargs="+", help="영상 파일 또는 폴더 (여러 개 가능)")
    ap.add_argument("-o", "--output", help="출력 파일 경로 (입력이 1개일 때)")
    ap.add_argument("-r", "--recursive", action="store_true", help="폴더의 하위 폴더 영상까지 포함")
    ap.add_argument("--out-dir", help="결과 영상을 모아 둘 폴더 (기본: 원본 옆)")
    ap.add_argument("--redo", action="store_true", help="이미 편집된 영상도 다시 편집 (기본: 건너뜀)")
    ap.add_argument("--list", action="store_true", help="편집할 영상 목록만 보여 주고 끝냄")
    ap.add_argument("--config", help="설정 JSON 파일")
    ap.add_argument("--model", help="whisper 모델 (small/medium/large-v3/large-v3-turbo)")
    ap.add_argument("--no-silence", action="store_true", help="무음 제거 끄기")
    ap.add_argument("--no-filler", action="store_true", help="필러워드 제거 끄기")
    ap.add_argument("--no-illu", action="store_true", help="일러스트 끄기")
    ap.add_argument("--no-mosaic", action="store_true", help="모자이크 끄기")
    ap.add_argument("--layout", choices=["auto", "left", "right", "full"])
    ap.add_argument("--style", choices=["sticker", "card"], help="일러스트 모양: sticker(투명 배경, 기본) | card(종이 카드)")
    ap.add_argument("--no-logo", action="store_true", help="assets/logos 로고 자동 표시 끄기")
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
    if a.style: cfg.illu_style = a.style
    if a.no_logo: cfg.use_logos = False
    cfg.custom_keywords += a.keyword

    def prog(stage, f):
        print(f"\r  {stage}: {f * 100:5.1f}%", end="", flush=True)
        if f >= 1:
            print()

    items, missing = collect_inputs(a.inputs, a.recursive)
    for m in missing:
        print(f"✖ 찾을 수 없음: {m}")
    if not items:
        print("편집할 영상이 없습니다.")
        return 1
    if a.list:
        for i, (p, _) in enumerate(items, 1):
            print(f"{i:3d}. {p}")
        return 0
    if a.output and len(items) > 1:
        print("※ -o는 영상이 1개일 때만 쓸 수 있습니다. 여러 개는 --out-dir를 쓰세요.")
        return 2
    if len(items) > 1:
        print(f"영상 {len(items)}개를 차례로 편집합니다.")

    log = Logger(lambda m: print("\r" + m), prog, a.verbose)
    # 여러 개일 때만 이미 편집된 영상을 건너뜀. 1개를 직접 지정하면 항상 다시 만듦.
    # --fresh는 '처음부터 다시'이므로 건너뛰지 않음
    skip = len(items) > 1 and not (a.redo or a.fresh)
    results = run_batch(items, cfg, log, reuse=not a.fresh, skip_done=skip,
                        out_dir=a.out_dir, output=a.output, transcript_override=a.transcript)
    return 1 if any(r["status"] in ("실패", "중지") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
