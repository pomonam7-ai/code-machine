"""전체 파이프라인: 대본 → 1차 컷 → 일러스트 계획/생성 → 개인정보 감지 → 최종 렌더링."""
import json
import math
import os
import time

import cv2
import numpy as np

from . import media
from .config import Config
from .cutter import compute_cuts, TimeMap, build_audio_wav
from .illustrate import render_card, find_font, SDEngine
from . import planner as planner_mod
from . import pii as pii_mod


class Logger:
    def __init__(self, fn=None, progress=None, verbose=False):
        self.fn = fn or print
        self.progress_fn = progress
        self.verbose = verbose

    def __call__(self, msg, level="info"):
        if level == "detail" and not self.verbose:
            return
        self.fn(msg)

    def progress(self, stage, frac):
        if self.progress_fn:
            self.progress_fn(stage, max(0.0, min(1.0, frac)))


def _save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(segments, path, max_chars=28):
    lines, n = [], 1
    for s in segments:
        words = s["words"]
        chunk = []
        for w in words + [None]:
            if w is not None and (not chunk or len(" ".join(x["word"] for x in chunk + [w])) <= max_chars):
                chunk.append(w)
                continue
            if chunk:
                lines.append(f"{n}\n{_srt_time(chunk[0]['start'])} --> {_srt_time(chunk[-1]['end'])}\n"
                             f"{' '.join(x['word'] for x in chunk)}\n")
                n += 1
            chunk = [w] if w is not None else []
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ------------------------------------------------------------------ 오버레이
def _ease_out_back(x):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _blend(frame, rgba, x, y, alpha=1.0):
    H, W = frame.shape[:2]
    h, w = rgba.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    src = rgba[y0 - y:y1 - y, x0 - x:x1 - x]
    a = (src[:, :, 3:4].astype(np.float32) / 255.0) * alpha
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (roi * (1 - a) + src[:, :, :3].astype(np.float32) * a).astype(np.uint8)


class FaceSide:
    def __init__(self):
        self.det = None
        try:
            p = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
            if os.path.exists(p):
                self.det = cv2.CascadeClassifier(p)
        except Exception:
            pass

    def choose(self, frame):
        """얼굴이 있는 반대쪽에 카드 배치."""
        if self.det is None:
            return "right"
        g = cv2.cvtColor(cv2.resize(frame, (480, int(480 * frame.shape[0] / frame.shape[1]))), cv2.COLOR_BGR2GRAY)
        faces = self.det.detectMultiScale(g, 1.15, 5, minSize=(30, 30))
        if len(faces) == 0:
            return "right"
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        return "left" if (x + w / 2) > 240 else "right"


class Overlay:
    def __init__(self, item, card_bgra, layout):
        self.item = item
        self.card = card_bgra
        self.layout = layout
        self.side = None

    def draw(self, frame, t, faces, cfg):
        s, e = self.item["start"], self.item["end"]
        if not (s <= t <= e):
            return
        H, W = frame.shape[:2]
        tin, tout = t - s, e - t
        k_in = min(1.0, tin / 0.35)
        k_out = min(1.0, tout / 0.25)
        scale = _ease_out_back(k_in) * (0.85 + 0.15 * k_out)
        alpha = min(k_in * 2, 1.0) * k_out
        if self.layout == "full":
            dim = min(1.0, tin / 0.3) * k_out * 0.55
            frame[:] = (frame.astype(np.float32) * (1 - dim) + np.array([240, 245, 250]) * dim).astype(np.uint8)
        if self.side is None:
            self.side = self.layout if self.layout in ("left", "right", "full") else faces.choose(frame)
        cw = self.card.shape[1]
        sw = max(8, int(cw * scale))
        sh = max(8, int(self.card.shape[0] * scale))
        img = self.card if sw == cw else cv2.resize(self.card, (sw, sh), interpolation=cv2.INTER_AREA)
        bob = int(math.sin(tin * 2.2) * H * 0.004)
        margin = int(W * 0.03)
        if self.side == "full":
            cx = W // 2
        elif self.side == "left":
            cx = margin + cw // 2
        else:
            cx = W - margin - cw // 2
        cy = H // 2 + bob
        _blend(frame, img, cx - sw // 2, cy - sh // 2, alpha)


# ------------------------------------------------------------------ 메인
def run(input_path, output_path=None, cfg=None, log=None, reuse=True, transcript_override=None, stop_flag=None):
    cfg = cfg or Config()
    log = log or Logger()
    t_start = time.time()
    base = os.path.splitext(input_path)[0]
    output_path = output_path or base + "_편집본.mp4"
    work = base + "_autocut_work"
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cfg.to_json(os.path.join(work, "settings.json"))

    info = media.probe(input_path)
    fps = cfg.fps or info["fps"]
    fps = round(fps, 3)
    W, H = info["width"], info["height"]
    log(f"▶ 입력: {os.path.basename(input_path)}  {W}x{H}  {fps}fps  {info['duration']:.1f}초")
    if not info["has_audio"]:
        raise RuntimeError("오디오가 없는 영상입니다.")

    def check_stop():
        if stop_flag and stop_flag():
            raise RuntimeError("사용자가 중지했습니다.")

    # 1) 대본
    log("① 대본 추출 (음성 인식)")
    wav16 = os.path.join(work, "audio16k.wav")
    media.extract_audio(input_path, wav16)
    tpath = os.path.join(work, "transcript.json")
    if transcript_override:
        segments = _load(transcript_override)
    elif reuse and os.path.exists(tpath):
        log("  이전 대본 재사용 (다시 하려면 작업 폴더의 transcript.json 삭제)")
        segments = _load(tpath)
    else:
        from .transcribe import transcribe
        log.progress("음성 인식", 0)
        segments = transcribe(wav16, cfg, log)
    _save(tpath, segments)
    log(f"  문장 {len(segments)}개 인식")
    check_stop()

    # 2) 컷 편집
    log("② 1차 컷 편집 (무음·필러워드 제거)")
    a16 = media.load_audio(wav16, sr=16000, channels=1, int16=True)[:, 0].astype(np.float32) / 32768.0
    keep, stats = compute_cuts(segments, a16, info["duration"], cfg, fps)
    _save(os.path.join(work, "cuts.json"), {"keep": keep, "stats": stats})
    tm = TimeMap(keep)
    khash = f"{len(keep)}-{stats['kept']:.2f}"
    out_segments = tm.remap_segments(segments, cfg)
    log(f"  {stats['original']:.1f}초 → {stats['kept']:.1f}초 (−{stats['removed']:.1f}초, 필러 {stats['fillers_cut']}개 제거)")
    check_stop()

    # 3) 일러스트
    overlays = []
    if cfg.add_illustrations:
        log("③ 설명 일러스트 계획·생성")
        ppath = os.path.join(work, "illustrations.json")
        if reuse and os.path.exists(ppath) and _load(ppath).get("keep_hash") == khash:
            items = _load(ppath)["items"]
            log("  이전 일러스트 계획 재사용 (illustrations.json을 고쳐서 재실행하면 반영됨)")
        else:
            items = planner_mod.plan(out_segments, tm.total, cfg, log)
            _save(ppath, {"keep_hash": khash, "items": items})
        font = find_font(cfg.font_path)
        sd = None
        if cfg.illustration_engine in ("sd", "auto"):
            try:
                import diffusers  # noqa
                sd = SDEngine(cfg.sd_model, log)
            except Exception as e:
                if cfg.illustration_engine == "sd":
                    log(f"  로컬 이미지 모델 사용 불가({e}) → 벡터 일러스트로 대체")
        layout = cfg.illu_layout
        card_w = int(W * (0.62 if layout == "full" else cfg.illu_scale))
        card_w -= card_w % 2
        card_h = int(card_w * 0.75)
        if card_h > H * 0.9:
            card_h = int(H * 0.9); card_w = int(card_h / 0.75)
        cdir = os.path.join(work, "cards"); os.makedirs(cdir, exist_ok=True)
        for i, it in enumerate(items):
            sd_img = None
            if sd is not None:
                subj = it.get("subject_en") or " and ".join(it["concepts"])
                try:
                    sd_img = sd.generate(subj, seed=i)
                except Exception as e:
                    log(f"  이미지 생성 실패({e}) → 벡터 사용")
            card = render_card(it["concepts"], it.get("label", ""), seed=i * 7 + 1, size=(card_w, card_h), font=font, sd_image=sd_img)
            card.save(os.path.join(cdir, f"{i:03d}.png"))
            arr = np.array(card)
            bgra = arr[:, :, [2, 1, 0, 3]].copy()
            overlays.append(Overlay(it, bgra, layout))
            log(f"  [{it['start']:6.1f}s] {'+'.join(it['concepts'])} '{it.get('label', '')}' ← {it['text'][:30]}")
        log(f"  일러스트 {len(overlays)}개")
    check_stop()

    # 4) 개인정보
    events = []
    if cfg.mosaic_pii:
        log("④ 화면 속 개인정보 감지")
        epath = os.path.join(work, "pii.json")
        if reuse and os.path.exists(epath) and _load(epath).get("keep_hash") == khash:
            events = _load(epath)["events"]
            log("  이전 감지 결과 재사용")
        else:
            events = pii_mod.scan_video(lambda: media.FrameReader(input_path, W, H, fps), keep, fps, cfg, log,
                                        progress=lambda f: log.progress("개인정보 감지", f))
            _save(epath, {"keep_hash": khash, "events": events})
        kinds = sorted({k for e in events for k in e["types"]})
        log(f"  모자이크 {len(events)}건 {('(' + ', '.join(kinds) + ')') if kinds else ''}")
    check_stop()

    # 5) 렌더링
    log("⑤ 최종 렌더링")
    audio = media.load_audio(input_path, sr=48000, channels=2, int16=True)
    wav_out = os.path.join(work, "audio_cut.wav")
    build_audio_wav(audio, 48000, keep, wav_out, cfg.crossfade_ms)
    del audio

    # 렌더링 중에는 임시 파일에 쓰고, 끝나면 이름을 바꿈 (중간에 멈춘 파일을 완성본으로 착각하지 않도록)
    part_path = os.path.splitext(output_path)[0] + ".part.mp4"
    reader = media.FrameReader(input_path, W, H, fps)
    writer = media.FrameWriter(part_path, W, H, fps, wav_out, cfg.video_codec, cfg.crf, cfg.preset)
    faces = FaceSide()
    keep_frames = [(int(round(s * fps)), int(round(e * fps))) for s, e in keep]
    total_out = sum(e - s for s, e in keep_frames)
    src_idx = out_idx = k = 0
    last_frame = None
    ok = False
    try:
        while k < len(keep_frames):
            frame = reader.read()
            if frame is None:
                break
            s, e = keep_frames[k]
            if src_idx >= e:
                k += 1
                if k >= len(keep_frames):
                    break
                s, e = keep_frames[k]
            if s <= src_idx < e:
                t = out_idx / fps
                if events:
                    pii_mod.apply_mosaic(frame, events, t)
                for ov in overlays:
                    ov.draw(frame, t, faces, cfg)
                writer.write(frame)
                last_frame = frame
                out_idx += 1
                if out_idx % 60 == 0:
                    log.progress("렌더링", out_idx / max(1, total_out))
                    check_stop()
            src_idx += 1
        # 디코더가 마지막 몇 프레임을 덜 준 경우 오디오 길이에 맞춰 채움
        while last_frame is not None and out_idx < total_out:
            writer.write(last_frame); out_idx += 1
        ok = True
    finally:
        reader.close()
        try:
            writer.close()
        except Exception:
            ok = False
            raise
        finally:
            if ok:
                os.replace(part_path, output_path)
            elif os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
    log.progress("완료", 1.0)

    if cfg.write_srt:
        write_srt(out_segments, os.path.splitext(output_path)[0] + ".srt")
    took = time.time() - t_start
    log(f"✔ 완료: {output_path}  (소요 {took / 60:.1f}분)")
    return {"output": output_path, "stats": stats, "illustrations": len(overlays), "mosaics": len(events)}
