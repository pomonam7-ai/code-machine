"""간단한 실행 화면 (tkinter, 추가 설치 불필요)."""
import os
import queue
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .config import Config
from .pipeline import run, Logger

APP = "오토컷 스튜디오"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        self.geometry("760x640")
        self.minsize(640, 520)
        self.q = queue.Queue()
        self.worker = None
        self.stop = False
        self.files = []
        self.cfg = Config()

        pad = dict(padx=10, pady=4)
        top = ttk.Frame(self); top.pack(fill="x", **pad)
        ttk.Button(top, text="📂 영상 선택", command=self.pick).pack(side="left")
        self.flabel = ttk.Label(top, text="선택된 영상 없음", foreground="#666")
        self.flabel.pack(side="left", padx=10)

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

    def pick(self):
        fs = filedialog.askopenfilenames(title="편집할 영상 선택",
                                         filetypes=[("영상", "*.mp4 *.mov *.mkv *.avi *.m4v *.webm"), ("모든 파일", "*.*")])
        if fs:
            self.files = list(fs)
            names = ", ".join(os.path.basename(f) for f in fs)
            self.flabel.config(text=names if len(names) < 70 else f"{len(fs)}개 영상", foreground="#000")

    def build_cfg(self):
        c = Config()
        for k, var in self.v.items():
            setattr(c, k, var.get())
        c.whisper_model = self.model.get()
        c.illu_layout = self.layout.get()
        c.min_silence = float(self.minsil.get())
        c.illu_min_gap = float(self.gap.get())
        c.custom_keywords = [w.strip() for w in self.kw.get().split(",") if w.strip()]
        return c

    def start(self):
        if not self.files:
            messagebox.showinfo(APP, "먼저 영상을 선택해 주세요."); return
        self.stop = False
        cfg = self.build_cfg()
        self.runbtn.config(state="disabled"); self.stopbtn.config(state="normal")
        self.txt.delete("1.0", "end")
        log = Logger(lambda m: self.q.put(("log", m)), lambda s, f: self.q.put(("prog", (s, f))))

        def work():
            for f in self.files:
                try:
                    r = run(f, None, cfg, log, reuse=not self.fresh.get(), stop_flag=lambda: self.stop)
                    self.last_out = r["output"]
                except Exception as e:
                    self.q.put(("log", f"✖ 오류: {e}"))
                    self.q.put(("log", traceback.format_exc()))
                if self.stop:
                    break
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
                        self.stage.config(text=val)
                elif kind == "prog":
                    s, f = val
                    self.pb["value"] = f * 1000
                elif kind == "done":
                    self.runbtn.config(state="normal"); self.stopbtn.config(state="disabled")
                    self.stage.config(text="완료" if not self.stop else "중지됨")
                    if self.last_out:
                        self.openbtn.config(state="normal")
        except queue.Empty:
            pass
        self.after(100, self.poll)


def main():
    App().mainloop()
