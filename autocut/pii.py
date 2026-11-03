"""화면 속 글자에서 개인정보(전화번호·이메일·주민번호·카드/계좌번호·주소 등)를 찾아 모자이크 구간을 만듭니다."""
import re
import cv2
import numpy as np

PATTERNS = {
    "주민등록번호": r"\d{6}\s?[-–~]\s?[1-4]\d{6}",
    "휴대폰번호": r"01[016789]\s?[-.)]?\s?\d{3,4}\s?[-.]?\s?\d{4}",
    "전화번호": r"0\d{1,2}\s?[-.)]\s?\d{3,4}\s?[-.]\s?\d{4}",
    "이메일": r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
    "카드번호": r"\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{3,4}",
    "계좌번호": r"\d{2,6}-\d{2,6}-\d{2,8}(-\d{1,3})?",
    "운전면허": r"\d{2}-\d{2}-\d{6}-\d{2}",
    "여권번호": r"\b[MSRODmsrod]\d{8}\b",
    "도로명주소": r"[가-힣]{1,10}(로|길)\s?\d{1,4}(번길)?(\s?\d{1,4})?(-\d{1,4})?",
    "지번주소": r"[가-힣]{1,8}(동|읍|면|리)\s?\d{1,5}(-\d{1,5})?(번지)?",
    "동호수": r"\d{1,4}\s?동\s?\d{1,5}\s?호",
    "IP주소": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
}
_COMPILED = {k: re.compile(v) for k, v in PATTERNS.items()}
# 이 단어가 함께 보이면 그 줄 전체를 개인정보 줄로 봄
LABEL_HINTS = re.compile(r"(주소|연락처|전화|휴대폰|핸드폰|이메일|e-?mail|계좌|주민|생년월일|성명|이름|카드번호|비밀번호|password|아이디|ID\s*:)", re.I)


def _digit_fix(t):
    """OCR이 숫자를 문자로 잘못 읽는 경우 보정 (숫자 많은 문자열만)."""
    digits = sum(c.isdigit() for c in t)
    if digits >= max(4, len(t) * 0.5):
        t = t.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8", "—": "-", "–": "-"}))
    return t


def find_pii(text, custom=()):
    t = _digit_fix(text)
    hits = [k for k, rx in _COMPILED.items() if rx.search(t)]
    if ("휴대폰번호" in hits or "전화번호" in hits) and "계좌번호" in hits:
        hits.remove("계좌번호")
    for kw in custom:
        if kw and kw in text:
            hits.append("사용자지정")
    return hits


class OCR:
    def __init__(self, engine="auto", log=None):
        self.engine = None
        self.log = log or (lambda *a, **k: None)
        if engine in ("auto", "easyocr"):
            try:
                import easyocr
                gpu = False
                try:
                    import torch
                    gpu = torch.cuda.is_available()
                except Exception:
                    pass
                self.reader = easyocr.Reader(["ko", "en"], gpu=gpu, verbose=False)
                self.engine = "easyocr"
            except Exception as e:
                if engine == "easyocr":
                    raise
                self.log(f"  EasyOCR 사용 불가({e}) → Tesseract 시도")
        if self.engine is None:
            import pytesseract
            langs = pytesseract.get_languages(config="")
            self.lang = "kor+eng" if "kor" in langs else "eng"
            self.tess = pytesseract
            self.engine = "tesseract"
        self.log(f"  OCR 엔진: {self.engine}")

    def read(self, img):
        """[(x1,y1,x2,y2,text,conf), ...]"""
        out = []
        if self.engine == "easyocr":
            for box, text, conf in self.reader.readtext(img, paragraph=False):
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                out.append((min(xs), min(ys), max(xs), max(ys), text, conf))
        else:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            d = self.tess.image_to_data(rgb, lang=self.lang, output_type=self.tess.Output.DICT)
            for i, text in enumerate(d["text"]):
                if text.strip() and float(d["conf"][i]) > 30:
                    x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
                    out.append((x, y, x + w, y + h, text, float(d["conf"][i]) / 100))
        return out


def _group_lines(boxes):
    """같은 줄에 있는 글자 상자를 묶어서, 번호가 여러 조각으로 쪼개져도 찾을 수 있게 함."""
    boxes = sorted(boxes, key=lambda b: ((b[1] + b[3]) / 2, b[0]))
    lines = []
    for b in boxes:
        cy, h = (b[1] + b[3]) / 2, b[3] - b[1]
        for ln in lines:
            lcy, lh = ln["cy"], ln["h"]
            last = ln["boxes"][-1]
            if abs(cy - lcy) < 0.6 * max(h, lh) and b[0] - last[2] < 2.5 * max(h, lh):
                ln["boxes"].append(b)
                break
        else:
            lines.append({"cy": cy, "h": h, "boxes": [b]})
    return [ln["boxes"] for ln in lines]


def detect_frame(ocr, frame, cfg):
    h, w = frame.shape[:2]
    scale = min(1.0, cfg.ocr_max_side / max(h, w))
    small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1 else frame
    boxes = ocr.read(small)
    found = []
    for line in _group_lines(boxes):
        joined = " ".join(b[4] for b in line)
        nospace = "".join(b[4] for b in line)
        hits = set(find_pii(joined, cfg.custom_keywords)) | set(find_pii(nospace, cfg.custom_keywords))
        if not hits:
            # 개별 상자 단위 검사
            for b in line:
                if find_pii(b[4], cfg.custom_keywords):
                    found.append((b, find_pii(b[4], cfg.custom_keywords)))
            continue
        targets = line
        if LABEL_HINTS.search(joined):
            # "주소: 서울시 ..." → 라벨 상자는 남기고 값만 가림
            targets = [b for b in line if not LABEL_HINTS.fullmatch(b[4].strip(" :："))] or line
        else:
            # 개인정보가 들어있는 상자(숫자/@/주소 포함)만 가림
            sel = [b for b in line if re.search(r"\d|@|(로|길|동|호)$", b[4])]
            targets = sel or line
        for b in targets:
            found.append((b, sorted(hits)))
    res = []
    for b, hits in found:
        x1, y1, x2, y2 = [v / scale for v in b[:4]]
        pw, ph = (x2 - x1) * 0.12 + 4, (y2 - y1) * 0.25 + 4
        res.append({"box": [max(0, int(x1 - pw)), max(0, int(y1 - ph)), min(w, int(x2 + pw)), min(h, int(y2 + ph))],
                    "types": hits, "text": b[4]})
    return res


def scan_video(reader_factory, keep, fps, cfg, log, progress=None):
    """편집본 타임라인 기준 모자이크 이벤트 [{t0,t1,box,types}] 반환.
    reader_factory()는 원본 FrameReader를 돌려줌 (남길 구간만 검사)."""
    ocr = OCR(cfg.ocr_engine, log)
    events = []
    reader = reader_factory()
    step = max(1, int(round(cfg.ocr_interval * fps)))
    keep_frames = [(int(round(s * fps)), int(round(e * fps))) for s, e in keep]
    total = sum(e - s for s, e in keep_frames)
    out_idx = 0
    src_idx = 0
    k = 0
    last_small, last_res = None, []
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
            if out_idx % step == 0:
                thumb = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90))
                if last_small is not None and np.abs(thumb.astype(int) - last_small).mean() < 1.5:
                    res = last_res  # 화면 변화 거의 없음 → 재사용 (속도)
                else:
                    res = detect_frame(ocr, frame, cfg)
                    last_small, last_res = thumb.astype(int), res
                t = out_idx / fps
                for r in res:
                    events.append({"t0": max(0, t - cfg.mosaic_hold), "t1": t + cfg.ocr_interval + cfg.mosaic_hold,
                                   "box": r["box"], "types": r["types"]})
                if progress and out_idx % (step * 10) == 0:
                    progress(out_idx / max(1, total))
            out_idx += 1
        src_idx += 1
    reader.close()
    return _merge_events(events)


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u else 0


def _merge_events(events):
    events.sort(key=lambda e: e["t0"])
    merged = []
    for ev in events:
        for m in merged[-30:]:
            if ev["t0"] <= m["t1"] and _iou(ev["box"], m["box"]) > 0.3:
                m["t1"] = max(m["t1"], ev["t1"])
                m["box"] = [min(m["box"][0], ev["box"][0]), min(m["box"][1], ev["box"][1]),
                            max(m["box"][2], ev["box"][2]), max(m["box"][3], ev["box"][3])]
                m["types"] = sorted(set(m["types"]) | set(ev["types"]))
                break
        else:
            merged.append(dict(ev))
    return merged


def apply_mosaic(frame, events, t):
    for ev in events:
        if ev["t0"] <= t <= ev["t1"]:
            x1, y1, x2, y2 = ev["box"]
            roi = frame[y1:y2, x1:x2]
            if roi.size == 0:
                continue
            bh, bw = roi.shape[:2]
            block = max(8, min(bw, bh) // 3)
            small = cv2.resize(roi, (max(1, bw // block), max(1, bh // block)), interpolation=cv2.INTER_LINEAR)
            frame[y1:y2, x1:x2] = cv2.resize(small, (bw, bh), interpolation=cv2.INTER_NEAREST)
    return frame
