"""1차 컷 편집: 무음 구간 + 필러워드 제거. '이해를 해치지 않게' 호흡과 문장 간 쉼은 남깁니다."""
import re
import numpy as np

_PUNCT = re.compile(r"[\s.,!?~…·\-\"'“”‘’()\[\]]+")
_SENT_END = re.compile(r"[.?!。]$|(다|요|죠|까|네|니다|세요)[.?!]?$")


def norm_word(w):
    return _PUNCT.sub("", w).lower()


def is_filler(word, cfg):
    t = norm_word(word["word"])
    if not t:
        return False
    hard = {norm_word(f) for f in cfg.fillers}
    if t in hard:
        return True
    # "어어어", "음음", "으으음" 같은 반복형
    if re.fullmatch(r"(어|음|으|엄|흠|에)+", t):
        return True
    soft = {norm_word(f) for f in cfg.soft_fillers}
    if t in soft and (word["end"] - word["start"]) >= cfg.soft_filler_min_dur:
        return True
    return False


def energy_db(audio16k, hop=0.01):
    n = int(16000 * hop)
    frames = len(audio16k) // n
    a = audio16k[: frames * n].reshape(frames, n).astype(np.float32)
    rms = np.sqrt((a ** 2).mean(axis=1) + 1e-10)
    return 20 * np.log10(rms + 1e-9), hop


def _merge(iv, gap=0.0):
    iv = sorted([list(x) for x in iv if x[1] > x[0]])
    out = []
    for s, e in iv:
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _subtract(keep, cuts):
    res = []
    for s, e in keep:
        pieces = [[s, e]]
        for cs, ce in cuts:
            nxt = []
            for ps, pe in pieces:
                if ce <= ps or cs >= pe:
                    nxt.append([ps, pe])
                else:
                    if cs > ps:
                        nxt.append([ps, cs])
                    if ce < pe:
                        nxt.append([ce, pe])
            pieces = nxt
        res.extend(pieces)
    return res


def compute_cuts(segments, audio16k, duration, cfg, fps=30.0):
    """원본 기준 남길 구간 리스트 [(s,e), ...]와 통계 반환."""
    words = [w for s in segments for w in s["words"]]
    # 문장 끝 단어 표시
    for s in segments:
        if s["words"]:
            s["words"][-1]["sent_end"] = True
    for w in words:
        if not w.get("sent_end") and _SENT_END.search(w["word"]):
            w["sent_end"] = True

    db, hop = energy_db(audio16k)
    speech_floor = np.percentile(db, 90) if len(db) else -20
    noise_floor = np.percentile(db, 15) if len(db) else -60
    thr = max(noise_floor + 0.35 * (speech_floor - noise_floor), -52)

    def voiced(t):
        i = int(t / hop)
        return 0 <= i < len(db) and db[i] > thr

    filler_idx = [i for i, w in enumerate(words) if cfg.remove_fillers and is_filler(w, cfg)]
    fset = set(filler_idx)
    content = [w for i, w in enumerate(words) if i not in fset]

    if not cfg.remove_silence:
        keep = [[0.0, duration]]
    else:
        keep = []
        for i, w in enumerate(content):
            s, e = w["start"], w["end"]
            # 위스퍼 경계가 부정확하므로 실제 소리 기준으로 0.25초까지 확장
            k = 0
            while k < 25 and voiced(s - 0.01):
                s -= 0.01; k += 1
            k = 0
            while k < 25 and voiced(e + 0.01):
                e += 0.01; k += 1
            pause = cfg.sentence_pause if w.get("sent_end") else cfg.keep_pause
            keep.append([s - cfg.pre_pad, e + max(cfg.post_pad, pause * 0.5)])
        # 짧은 쉼은 자연스러운 호흡이므로 이어 붙임
        keep = _merge(keep, gap=cfg.min_silence)
        # 단어 타임스탬프가 무음 위로 늘어난 경우: 내부의 긴 무음(에너지 기준)도 잘라냄
        long_sil = []
        run = None
        for i, v in enumerate(db > thr):
            t = i * hop
            if not v:
                run = t if run is None else run
            else:
                if run is not None and t - run >= max(1.0, cfg.min_silence * 1.8):
                    long_sil.append([run + cfg.keep_pause, t - cfg.keep_pause])
                run = None
        keep = _subtract(keep, long_sil)

    # 필러 제거: 이웃 단어 경계를 침범하지 않도록 범위를 좁힘
    cut_iv = []
    for idx in filler_idx:
        f = words[idx]
        prev_end = words[idx - 1]["end"] if idx > 0 else 0.0
        next_start = words[idx + 1]["start"] if idx + 1 < len(words) else duration
        cs = max(f["start"], prev_end + 0.02)
        ce = min(f["end"], next_start - 0.02)
        if ce - cs > 0.05:
            cut_iv.append([cs, ce])
    keep = _subtract(keep, cut_iv)

    # 정리: 범위 제한, 프레임 단위로 정렬(음성/영상 싱크 유지), 너무 짧은 조각 제거
    out = []
    for s, e in _merge(keep):
        s, e = max(0.0, s), min(duration, e)
        s, e = round(s * fps) / fps, round(e * fps) / fps
        if e - s >= cfg.min_keep:
            out.append((s, e))
    out = [tuple(x) for x in _merge(out)]
    kept = sum(e - s for s, e in out)
    stats = {"original": duration, "kept": kept, "removed": duration - kept,
             "fillers_cut": len(cut_iv), "segments": len(out)}
    return out, stats


class TimeMap:
    """원본 시간 ↔ 편집본 시간 변환."""

    def __init__(self, keep):
        self.keep = keep
        self.offsets = []
        acc = 0.0
        for s, e in keep:
            self.offsets.append(acc)
            acc += e - s
        self.total = acc

    def to_out(self, t):
        for (s, e), off in zip(self.keep, self.offsets):
            if t < s:
                return off
            if t <= e:
                return off + (t - s)
        return self.total

    def remap_segments(self, segments, cfg):
        out = []
        for seg in segments:
            words = [dict(w, start=self.to_out(w["start"]), end=self.to_out(w["end"]))
                     for w in seg["words"] if not (cfg.remove_fillers and is_filler(w, cfg))]
            words = [w for w in words if w["end"] - w["start"] > 0.01]
            if not words:
                continue
            text = " ".join(w["word"] for w in words)
            out.append({"start": words[0]["start"], "end": words[-1]["end"], "text": text, "words": words})
        return out


def build_audio_wav(audio16, sr, keep, path, crossfade_ms=12.0):
    """int16 오디오에서 남길 구간만 이어 붙여 WAV로 저장. 경계마다 짧은 페이드로 '틱' 소리 제거."""
    import wave
    fade = max(1, int(sr * crossfade_ms / 1000))
    ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
    with wave.open(path, "wb") as w:
        w.setnchannels(audio16.shape[1]); w.setsampwidth(2); w.setframerate(sr)
        for s, e in keep:
            a = audio16[int(round(s * sr)): int(round(e * sr))].astype(np.float32)
            if len(a) > 2 * fade:
                a[:fade] *= ramp
                a[-fade:] *= ramp[::-1]
            w.writeframes(np.clip(a, -32768, 32767).astype("<i2").tobytes())
