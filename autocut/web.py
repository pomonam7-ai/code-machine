"""로컬 웹앱: 브라우저에서 버튼으로 모든 기능을 씁니다. (python -m autocut 또는 run.bat)

- 추가 설치 없이 파이썬 표준 라이브러리 http.server만 씁니다. 인터넷 연결이 필요 없습니다.
- 이 PC에서만 접속할 수 있습니다(127.0.0.1). 실행할 때마다 만든 토큰이 있어야 API를 호출할 수 있습니다.
"""
import base64
import io
import json
import mimetypes
import os
import re
import secrets
import string
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .config import Config
from .pipeline import Logger
from . import batch
from . import illustrate as ill

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "webui", "index.html")
TOKEN = secrets.token_urlsafe(24)
SERVE_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".png", ".jpg", ".jpeg", ".webp", ".csv", ".srt", ".json"}

# 웹에서 바꿀 수 있는 설정만 허용 (나머지는 config.py / settings.json)
WEB_OPTIONS = ["remove_silence", "remove_fillers", "add_illustrations", "use_logos", "mosaic_pii", "write_srt",
               "whisper_model", "illu_layout", "illu_style", "min_silence", "illu_min_gap", "custom_keywords",
               "planner", "video_codec"]


# ------------------------------------------------------------------ 작업 상태
class Job:
    """한 번에 하나의 편집 작업만 돌립니다. 브라우저는 /api/status로 상태를 가져갑니다."""

    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.reset()

    def reset(self):
        self.running = False
        self.stop = False
        self.logs = []
        self.stage = "대기 중"
        self.frac = 0.0
        self.file_i = self.file_n = 0
        self.file_name = ""
        self.results = []
        self.started = 0.0
        self.kind = ""

    def log(self, msg):
        with self.lock:
            self.logs.append(str(msg))
            if msg[:1] in "①②③④⑤":
                self.stage = msg.strip()

    def progress(self, stage, frac):
        with self.lock:
            self.frac = frac

    def on_file(self, i, n, path):
        with self.lock:
            self.file_i, self.file_n, self.file_name = i, n, os.path.basename(path)
            self.frac = 0.0

    def start(self, items, cfg, kind="batch", **kw):
        with self.lock:
            if self.running:
                raise RuntimeError("이미 편집 중입니다. 끝나거나 중지한 뒤 다시 시작하세요.")
            self.reset()
            self.running, self.kind, self.started = True, kind, time.time()
        log = Logger(self.log, self.progress)

        def work():
            try:
                self.results = batch.run_batch(items, cfg, log, stop_flag=lambda: self.stop, on_file=self.on_file, **kw)
            except Exception as e:
                self.log(f"✖ 오류: {e}")
                self.log(traceback.format_exc())
            finally:
                with self.lock:
                    self.running = False
                    self.stage = "중지됨" if self.stop else "완료"

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()

    def status(self, since=0):
        with self.lock:
            return {"running": self.running, "stage": self.stage, "frac": self.frac, "file_i": self.file_i,
                    "file_n": self.file_n, "file_name": self.file_name, "logs": self.logs[since:],
                    "next": len(self.logs), "results": self.results if not self.running else [],
                    "elapsed": time.time() - self.started if self.started else 0, "kind": self.kind}


JOB = Job()


# ------------------------------------------------------------------ 도우미
def build_cfg(opts):
    c = Config()
    for k in WEB_OPTIONS:
        if k not in (opts or {}):
            continue
        v, cur = opts[k], getattr(c, k)
        if isinstance(cur, bool):
            v = bool(v)
        elif isinstance(cur, float):
            v = float(v)
        elif isinstance(cur, int):
            v = int(v)
        elif isinstance(cur, list):
            v = [w.strip() for w in (v.split(",") if isinstance(v, str) else v) if str(w).strip()]
        else:
            v = str(v)
        setattr(c, k, v)
    return c


def _roots():
    out = []
    if os.name == "nt":
        out += [{"name": f"{d}:\\", "path": f"{d}:\\"} for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    else:
        out.append({"name": "/", "path": "/"})
    home = os.path.expanduser("~")
    for name, sub in (("홈", ""), ("바탕화면", "Desktop"), ("동영상", "Videos"), ("다운로드", "Downloads")):
        p = os.path.join(home, sub) if sub else home
        if os.path.isdir(p):
            out.append({"name": name, "path": p})
    return out


def browse(path):
    if not path:
        return {"path": "", "parent": None, "dirs": [], "files": [], "roots": _roots()}
    path = os.path.abspath(os.path.expanduser(path))
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"폴더를 찾을 수 없습니다: {path}")
    dirs, files = [], []
    try:
        names = os.listdir(path)
    except PermissionError:
        raise PermissionError(f"폴더를 열 권한이 없습니다: {path}")
    for n in sorted(names, key=batch._natural_key):
        if n.startswith(".") or n.startswith("$"):
            continue
        p = os.path.join(path, n)
        if os.path.isdir(p):
            if not n.endswith(batch.WORK_SUFFIX):
                dirs.append({"name": n, "path": p})
        elif batch.is_video(n):
            out = batch.output_path_for(p)
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
            files.append({"name": n, "path": p, "size": size, "done": batch.is_done(p, out),
                          "output": out if os.path.exists(out) else ""})
    parent = os.path.dirname(path)
    return {"path": path, "parent": parent if parent != path else "", "dirs": dirs, "files": files, "roots": _roots()}


def work_dir(video):
    return os.path.splitext(video)[0] + batch.WORK_SUFFIX


def _jload(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def project(video, output=""):
    """일러스트 편집용 정보: 계획(illustrations.json), 카드 미리보기, 편집본 기준 문장 목록."""
    video = os.path.abspath(video)
    w = work_dir(video)
    plan = _jload(os.path.join(w, "illustrations.json"))
    if plan is None:
        raise FileNotFoundError("아직 편집하지 않은 영상입니다. 먼저 '편집 시작'으로 한 번 편집해 주세요.")
    out = output or batch.output_path_for(video)
    items = plan.get("items", [])
    cards = [os.path.join(w, "cards", f"{i:03d}.png") for i in range(len(items))]
    sents = []
    segs, cuts = _jload(os.path.join(w, "transcript.json")), _jload(os.path.join(w, "cuts.json"))
    if segs and cuts:
        from .cutter import TimeMap
        from .planner import sentences_from
        tm = TimeMap(cuts["keep"])
        sents = [{"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"]}
                 for s in sentences_from(tm.remap_segments(segs, Config()))]
    st = _jload(os.path.join(w, "settings.json"), {}) or {}
    return {"video": video, "output": out if os.path.exists(out) else "", "items": items,
            "cards": [c if os.path.exists(c) else "" for c in cards], "sentences": sents,
            "settings": {k: st.get(k) for k in WEB_OPTIONS if k in st}}


def save_project(video, items):
    video = os.path.abspath(video)
    p = os.path.join(work_dir(video), "illustrations.json")
    plan = _jload(p)
    if plan is None:
        raise FileNotFoundError("작업 폴더의 illustrations.json이 없습니다.")
    max_chars = Config().max_label_chars
    logos = ill.list_logos()
    clean = []
    for it in items:
        s, e = float(it["start"]), float(it["end"])
        if e <= s:
            raise ValueError(f"끝 시간이 시작보다 빨라요: {s:.1f}초")
        c = {"start": round(s, 2), "end": round(e, 2),
             "concepts": [x for x in it.get("concepts", []) if x in ill.ICONS][:2],
             "label": str(it.get("label", ""))[:max_chars], "text": str(it.get("text", "")),
             "subject_en": str(it.get("subject_en", ""))}
        if it.get("logo") and it["logo"] in logos:
            c["logo"] = it["logo"]
        if not c["concepts"] and "logo" not in c:
            c["concepts"] = ["idea"]
        clean.append(c)
    clean.sort(key=lambda x: x["start"])
    plan["items"] = clean
    with open(p, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    return {"saved": len(clean)}


_PREVIEW = {}
_FONT = None


def preview_png(concepts, label="", logo="", style="sticker", size=(480, 360), seed=1):
    global _FONT
    if _FONT is None:
        _FONT = ill.find_font() or ""
    key = (tuple(concepts), label, logo, style, size, seed, _logo_mtime(logo))
    if key not in _PREVIEW:
        lg = ill.load_logo(logo) if logo else None
        img = ill.render_overlay(concepts, label, seed=seed, size=size, font=_FONT or None, logo=lg, style=style)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        if len(_PREVIEW) > 400:
            _PREVIEW.clear()
        _PREVIEW[key] = buf.getvalue()
    return _PREVIEW[key]


def _logo_mtime(name):
    info = ill.list_logos().get(name) if name else None
    return os.path.getmtime(info["path"]) if info else 0


_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def add_logo(name, data_b64):
    from PIL import Image
    name = _BAD.sub("", name or "").strip().strip(".")
    name = os.path.splitext(name)[0] if os.path.splitext(name)[1].lower() in ill.LOGO_EXTS else name
    if not name:
        raise ValueError("로고 이름이 비어 있어요.")
    raw = base64.b64decode(data_b64.split(",", 1)[-1])
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("로고 파일이 너무 커요 (20MB 이하).")
    img = Image.open(io.BytesIO(raw))
    img.load()
    img = ill.remove_background(img)
    if max(img.size) > 1600:
        img.thumbnail((1600, 1600))
    os.makedirs(ill.LOGO_DIR, exist_ok=True)
    for old in ill.list_logos().values():          # 같은 이름의 다른 확장자 정리
        if os.path.splitext(os.path.basename(old["path"]))[0] == name:
            os.remove(old["path"])
    path = os.path.join(ill.LOGO_DIR, name + ".png")
    img.save(path, "PNG")
    return {"name": name, "keywords": [k.strip() for k in name.split(",") if k.strip()]}


def delete_logo(name):
    info = ill.list_logos().get(name)
    if not info:
        raise FileNotFoundError("그 로고가 없어요.")
    os.remove(info["path"])
    return {"deleted": name}


def open_in_explorer(path):
    path = os.path.abspath(path)
    if os.name == "nt":
        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", path])
        else:
            os.startfile(path if os.path.isdir(path) else os.path.dirname(path))
    else:
        target = path if os.path.isdir(path) else os.path.dirname(path)
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def info():
    logos = ill.list_logos()
    return {"icons": [{"key": k, "label": v[1], "keywords": [x.rstrip("*") for x in v[2]]} for k, v in ill.ICONS.items()],
            "logos": [{"name": n, "keywords": v["keywords"]} for n, v in logos.items()],
            "defaults": {k: getattr(Config(), k) for k in WEB_OPTIONS},
            "max_label_chars": Config().max_label_chars, "font": bool(ill.find_font()),
            "logo_dir": ill.LOGO_DIR, "os": os.name}


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "AutoCutStudio"

    def log_message(self, fmt, *args):  # 콘솔을 조용하게
        pass

    # --- 보안: 이 PC의 이 주소로 들어온 요청 + 토큰만 허용
    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _token_ok(self, q):
        t = self.headers.get("X-Token") or (q.get("t") or [""])[0]
        return secrets.compare_digest(t, TOKEN)

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _err(self, code, msg):
        self._send(code, {"error": msg})

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 40 * 1024 * 1024:
            raise ValueError("요청이 너무 커요.")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._err(403, "허용되지 않은 주소")
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            with open(INDEX, encoding="utf-8") as f:
                html = f.read().replace("__TOKEN__", TOKEN)
            return self._send(200, html, "text/html; charset=utf-8",
                              {"Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; media-src 'self'; "
                                                          "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"})
        if u.path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if not u.path.startswith("/api/"):
            return self._err(404, "없는 주소")
        if not self._token_ok(q):
            return self._err(403, "토큰이 맞지 않아요. 프로그램 창의 주소로 다시 열어 주세요.")
        g = lambda k, d="": (q.get(k) or [d])[0]
        try:
            if u.path == "/api/info":
                return self._send(200, info())
            if u.path == "/api/browse":
                return self._send(200, browse(g("path")))
            if u.path == "/api/status":
                return self._send(200, JOB.status(int(g("since", "0") or 0)))
            if u.path == "/api/project":
                return self._send(200, project(g("video"), g("output")))
            if u.path == "/api/preview":
                concepts = [c for c in g("concepts").split(",") if c]
                size = (320, 240) if g("small") else (480, 360)
                png = preview_png(concepts, g("label"), g("logo"), g("style", "sticker"), size, int(g("seed", "1") or 1))
                return self._send(200, png, "image/png", {"Cache-Control": "max-age=60"})
            if u.path == "/api/file":
                return self._file(g("path"))
            return self._err(404, "없는 API")
        except (FileNotFoundError, PermissionError, ValueError) as e:
            return self._err(400, str(e))
        except Exception as e:
            traceback.print_exc()
            return self._err(500, f"처리 중 오류: {e}")

    def do_POST(self):
        if not self._host_ok():
            return self._err(403, "허용되지 않은 주소")
        u = urlparse(self.path)
        if not self._token_ok(parse_qs(u.query)):
            return self._err(403, "토큰이 맞지 않아요.")
        try:
            b = self._body()
            if u.path == "/api/scan":
                items, missing = batch.collect_inputs(b.get("paths", []), bool(b.get("recursive")))
                return self._send(200, {"items": [{"path": p, "rel": r, "name": os.path.basename(p),
                                                   "done": batch.is_done(p, batch.output_path_for(p, r, b.get("out_dir") or None))}
                                                  for p, r in items], "missing": missing})
            if u.path == "/api/start":
                items, missing = batch.collect_inputs(b.get("paths", []), bool(b.get("recursive")))
                if not items:
                    raise ValueError("편집할 영상이 없어요. 영상이나 폴더를 먼저 추가해 주세요.")
                fresh = bool(b.get("fresh"))
                skip = bool(b.get("skip_done", True)) and not fresh and len(items) > 1
                JOB.start(items, build_cfg(b.get("options")), "batch", reuse=not fresh, skip_done=skip,
                          out_dir=b.get("out_dir") or None)
                return self._send(200, {"started": len(items), "missing": missing})
            if u.path == "/api/rerender":
                video = os.path.abspath(b["video"])
                out = b.get("output") or batch.output_path_for(video)
                cfg = build_cfg(b.get("options") or project(video).get("settings"))
                JOB.start([(video, "")], cfg, "rerender", reuse=True, skip_done=False, output=out)
                return self._send(200, {"started": 1})
            if u.path == "/api/stop":
                JOB.stop = True
                return self._send(200, {"stopping": JOB.running})
            if u.path == "/api/project/save":
                return self._send(200, save_project(b["video"], b.get("items", [])))
            if u.path == "/api/logos":
                return self._send(200, add_logo(b.get("name", ""), b.get("data", "")))
            if u.path == "/api/logos/delete":
                return self._send(200, delete_logo(b.get("name", "")))
            if u.path == "/api/open":
                open_in_explorer(b["path"])
                return self._send(200, {"ok": True})
            if u.path == "/api/quit":
                self._send(200, {"bye": True})
                JOB.stop = True
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            return self._err(404, "없는 API")
        except RuntimeError as e:
            return self._err(409, str(e))
        except (FileNotFoundError, PermissionError, ValueError, KeyError) as e:
            return self._err(400, str(e))
        except Exception as e:
            traceback.print_exc()
            return self._err(500, f"처리 중 오류: {e}")

    def _file(self, path):
        """영상·이미지·결과 파일 보내기. 영상 탐색(건너뛰기)을 위해 Range 요청을 지원합니다."""
        path = os.path.abspath(path)
        if os.path.splitext(path)[1].lower() not in SERVE_EXTS or not os.path.isfile(path):
            return self._err(404, "파일이 없어요.")
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.lower().endswith((".srt", ".csv")):
            ctype += "; charset=utf-8"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # 브라우저가 영상 탐색 중 연결을 끊는 건 정상


def serve(port=8765, open_browser=True):
    srv = None
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    if srv is None:
        raise RuntimeError(f"{port}~{port + 19}번 포트를 모두 쓸 수 없습니다.")
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print("=" * 56)
    print(" 오토컷 스튜디오가 실행 중입니다.")
    print(f" 브라우저 주소: {url}")
    print(" 이 창을 닫거나 웹 화면의 [종료] 버튼을 누르면 꺼집니다.")
    print("=" * 56, flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        JOB.stop = True
        srv.server_close()
    return url


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="autocut", description="오토컷 스튜디오 웹앱")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    a = ap.parse_args(argv)
    serve(a.port, not a.no_browser)


if __name__ == "__main__":
    main()
