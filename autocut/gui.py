"""간단한 실행 화면 (tkinter, 추가 설치 불필요)."""
import os
import queue
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .config import Config
from .pipeline import Logger
from .batch import collect_inputs, run_batch

APP = "오토컷 스튜디오"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        self.geometry("760x720")
        self.minsize(640, 600)
        self.q = queue.Queue()
        self.worker = None
        self.stop = False
        self.files = []      # 직접 고른 영상 또는 폴더
        self.out_dir = ""
        self.cfg = Config()

        pad = dict(padx=10, pady=4)
        top = ttk.Frame(self); top.pack(fill="x", **pad)
        ttk.Button(top, text="📂 영상 선택", command=self.pick).pack(side="left")
        ttk.Button(top, text="📁 폴더 선택 (일괄)", command=self.pick_dir).pack(side="left", padx=4)
        self.flabel = ttk.Label(top, text="선택된 영상 없음", foreground="#666")
        self.flabel.pack(side="left", padx=10)

        bat = ttk.LabelFrame(self, text="일괄 처리"); bat.pack(fill="x", **pad)
        self.recursive = tk.BooleanVar(value=False)
        ttk.Checkbutton(bat, text="하위 폴더 영상까지 포함", variable=self.recursive,
                        command=self.refresh_label).grid(row=0, column=0, sticky="w", padx=8)
        self.skip_done = tk.BooleanVar(value=True)
        ttk.Checkbutton(bat, text="이미 편집된 영상 건너뛰기", variable=self.skip_done).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(bat, text="결과 저장 폴더…", command=self.pick_out).grid(row=1, column=0, sticky="w", padx=8, pady=2)
        self.olabel = ttk.Label(bat, text="원본 영상 옆에 저장", foreground="#666")
        self.olabel.grid(row=1, column=1, columnspan=2, sticky="w")

        opt = ttk.LabelFrame(self, text="편집 옵션"); opt.pack(fill="x", **pad)
        self.v = {}
        for i, (key, text) in enumerate([("remove_silence", "무음 구간 제거"), ("remove_fillers", "필러워드 제거 (어, 음…)"),
                                         ("add_illustrations", "설명 일러스트 넣기"), ("mosaic_pii", "화면 속 개인정보 모자이크"),
                                         ("write_srt", "자막 파일(.srt)도 저장")]):
            self.v[key] = tk.BooleanVar(value=getattr(self.cfg, key))
            ttk.Checkbutton(opt, text=text, variable=self.v[key]).grid(row=i // 2, column=i % 2, sticky="w", padx=8, pady=2)

        adv = ttk.LabelFrame(self, text="세부 설정"); adv.pack(fill="x", **pad)
        ttk.Label(adv, text="음성인식 모델").grid(row=0, column=0, sticky="w", padx=8)
        self.model = ttk.Combobox(adv, values=["auto", "small", "medium", "large-v3-turbo", "large-v3"], width=16, state="readonly")
        self.model.set(self.cfg.whisper_model); self.model.grid(row=0, column=1, sticky="w")
        ttk.Label(adv, text="일러스트 위치").grid(row=0, column=2, sticky="w", padx=8)
        self.layout = ttk.Combobox(adv, values=["auto", "left", "right", "full"], width=10, state="readonly")
        self.layout.set(self.cfg.illu_layout); self.layout.grid(row=0, column=3, sticky="w")
        ttk.Label(adv, text="일러스트 모양").grid(row=0, column=4, sticky="w", padx=8)
        self.style = ttk.Combobox(adv, values=["sticker", "card"], width=8, state="readonly")
        self.style.set(self.cfg.illu_style); self.style.grid(row=0, column=5, sticky="w")
        ttk.Label(adv, text="컷 강도 (쉼 허용 초)").grid(row=1, column=0, sticky="w", padx=8)
        self.minsil = tk.DoubleVar(value=self.cfg.min_silence)
        ttk.Spinbox(adv, from_=0.3, to=2.0, increment=0.05, textvariable=self.minsil, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(adv, text="일러스트 간격(초)").grid(row=1, column=2, sticky="w", padx=8)
        self.gap = tk.DoubleVar(value=self.cfg.illu_min_gap)
        ttk.Spinbox(adv, from_=5, to=60, increment=1, textvariable=self.gap, width=8).grid(row=1, column=3, sticky="w")
        ttk.Label(adv, text="추가로 가릴 단어 (쉼표 구분, 예: 내 이름, 회사명)").grid(row=2, column=0, columnspan=2, sticky="w", padx=8)
        self.kw = ttk.Entry(adv, width=40); self.kw.grid(row=2, column=2, columnspan=2, sticky="we", pady=4)
        self.fresh = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv, text="처음부터 다시 (이전 대본/분석 재사용 안 함)", variable=self.fresh).grid(row=3, column=0, columnspan=3, sticky="w", padx=8)

        bar = ttk.Frame(self); bar.pack(fill="x", **pad)
        self.runbtn = ttk.Button(bar, text="▶ 편집 시작", command=self.start); self.runbtn.pack(side="left")
        self.stopbtn = ttk.Button(bar, text="■ 중지", command=self.request_stop, state="disabled"); self.stopbtn.pack(side="left", padx=6)
        self.openbtn = ttk.Button(bar, text="결과 폴더 열기", command=self.open_folder, state="disabled"); self.openbtn.pack(side="right")
        self.stage = ttk.Label(self, text="대기 중"); self.stage.pack(fill="x", padx=12)
        self.pb = ttk.Progressbar(self, maximum=1000); self.pb.pack(fill="x", padx=12, pady=2)

        self.txt = tk.Text(self, height=14, wrap="word", font=("Malgun Gothic", 9))
        self.txt.pack(fill="both", expand=True, padx=10, pady=8)
        self.after(100, self.poll)
        self.last_out = None
        self.file_pos = ""

    def pick(self):
        fs = filedialog.askopenfilenames(title="편집할 영상 선택",
                                         filetypes=[("영상", "*.mp4 *.mov *.mkv *.avi *.m4v *.webm"), ("모든 파일", "*.*")])
        if fs:
            self.files = list(fs)
            self.refresh_label()

    def pick_dir(self):
        d = filedialog.askdirectory(title="편집할 영상이 들어 있는 폴더 선택")
        if d:
            self.files = [d]
            self.refresh_label()

    def pick_out(self):
        d = filedialog.askdirectory(title="결과 영상을 저장할 폴더 (취소하면 원본 옆에 저장)")
        self.out_dir = d or ""
        self.olabel.config(text=d or "원본 영상 옆에 저장", foreground="#000" if d else "#666")

    def refresh_label(self):
        if not self.files:
            return
        items, _ = collect_inputs(self.files, self.recursive.get())
        if len(self.files) == 1 and os.path.isdir(self.files[0]):
            folder = os.path.basename(os.path.normpath(self.files[0]))
            text = f"📁 {folder} — 영상 {len(items)}개"
        else:
            names = ", ".join(os.path.basename(p) for p, _ in items)
            text = names if len(names) < 70 else f"{len(items)}개 영상"
        self.flabel.config(text=text, foreground="#000")

    def build_cfg(self):
        c = Config()
        for k, var in self.v.items():
            setattr(c, k, var.get())
        c.whisper_model = self.model.get()
        c.illu_layout = self.layout.get()
        c.illu_style = self.style.get()
        c.min_silence = float(self.minsil.get())
        c.illu_min_gap = float(self.gap.get())
        c.custom_keywords = [w.strip() for w in self.kw.get().split(",") if w.strip()]
        return c

    def start(self):
        if not self.files:
            messagebox.showinfo(APP, "먼저 영상이나 폴더를 선택해 주세요."); return
        items, _ = collect_inputs(self.files, self.recursive.get())
        if not items:
            messagebox.showinfo(APP, "선택한 곳에 편집할 영상이 없습니다."); return
        self.stop = False
        self.last_out = None
        cfg = self.build_cfg()
        self.runbtn.config(state="disabled"); self.stopbtn.config(state="normal")
        self.txt.delete("1.0", "end")
        log = Logger(lambda m: self.q.put(("log", m)), lambda s, f: self.q.put(("prog", (s, f))))

        fresh = self.fresh.get()
        # 1개만 골랐으면 항상 다시 만듦 (작업 폴더 JSON 수정 후 재렌더링 흐름)
        skip = self.skip_done.get() and not fresh and len(items) > 1
        out_dir = self.out_dir or None

        def work():
            try:
                results = run_batch(items, cfg, log, reuse=not fresh, skip_done=skip, out_dir=out_dir,
                                    stop_flag=lambda: self.stop,
                                    on_file=lambda i, n, p: self.q.put(("file", (i, n, p))))
                done = [r for r in results if r["status"] in ("완료", "건너뜀")]
                if done:
                    self.last_out = done[-1]["output"]
            except Exception as e:
                self.q.put(("log", f"✖ 오류: {e}"))
                self.q.put(("log", traceback.format_exc()))
            self.q.put(("done", None))

        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

    def request_stop(self):
        self.stop = True
        self.stage.config(text="중지하는 중…")

    def open_folder(self):
        if self.last_out:
            os.startfile(os.path.dirname(os.path.abspath(self.last_out)))  # Windows

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.txt.insert("end", val + "\n"); self.txt.see("end")
                    if val[:1] in "①②③④⑤":
                        self.stage.config(text=self.file_pos + val)
                elif kind == "file":
                    i, n, p = val
                    self.file_pos = f"[{i}/{n}] " if n > 1 else ""
                    self.title(f"{APP} {self.file_pos}".strip())
                elif kind == "prog":
                    s, f = val
                    self.pb["value"] = f * 1000
                elif kind == "done":
                    self.runbtn.config(state="normal"); self.stopbtn.config(state="disabled")
                    self.stage.config(text="완료" if not self.stop else "중지됨")
                    self.title(APP); self.file_pos = ""
                    if self.last_out:
                        self.openbtn.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self.poll)


def main():
    App().mainloop()
