"""faster-whisper로 단어 단위 타임스탬프 대본 생성 (완전 오프라인, 첫 실행 시 모델만 다운로드)."""

# 머뭇거림 소리도 받아 적도록 유도하는 프롬프트
FILLER_PROMPT = "음, 어, 그... 어어, 음... 네, 그러니까 이렇게 말하다가 머뭇거리는 소리도 그대로 적습니다."


def _add_nvidia_dlls():
    """Windows: pip로 설치한 nvidia-cublas/cudnn DLL 경로 등록 (GPU 가속용, 없으면 무시)."""
    import os, sys, glob
    if os.name != "nt":
        return
    for sp in sys.path:
        for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            try:
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            except Exception:
                pass


def _has_cuda():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def transcribe(wav_path, cfg, log=print):
    _add_nvidia_dlls()
    from faster_whisper import WhisperModel

    device = cfg.device
    if device == "auto":
        device = "cuda" if _has_cuda() else "cpu"
    model_name = cfg.whisper_model
    if model_name == "auto":
        model_name = "large-v3-turbo" if device == "cuda" else "medium"
    compute = "float16" if device == "cuda" else "int8"
    log(f"  음성 인식 모델: {model_name} ({device}, {compute}) - 첫 실행은 모델 다운로드로 오래 걸릴 수 있어요")
    def _run(dev, comp):
        model = WhisperModel(model_name, device=dev, compute_type=comp)
        seg_iter, info = model.transcribe(
            wav_path, language=cfg.language, word_timestamps=True, vad_filter=False,
            initial_prompt=FILLER_PROMPT, condition_on_previous_text=False, beam_size=5,
        )
        dur = max(1.0, info.duration)
        segments = []
        for s in seg_iter:
            words = [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
                     for w in (s.words or []) if w.word.strip()]
            segments.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(), "words": words})
            log(f"  [{s.start:7.1f}s] {s.text.strip()}", level="detail")
            if hasattr(log, "progress"):
                log.progress("음성 인식", s.end / dur)
        return segments

    try:
        return _run(device, compute)
    except Exception as e:
        if device != "cuda":
            raise
        log(f"  GPU 음성 인식 실패({str(e)[:120]}) → CPU로 다시 시도")
        return _run("cpu", "int8")
