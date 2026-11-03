"""ffmpeg 래퍼: 정보 읽기, 오디오 추출, 프레임 디코딩/인코딩 파이프."""
import os
import re
import shutil
import subprocess
import numpy as np

_FFMPEG = None
_NOWIN = 0x08000000 if os.name == "nt" else 0  # Windows에서 콘솔창 깜빡임 방지


def ffmpeg_exe():
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    exe = shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            raise RuntimeError("ffmpeg를 찾을 수 없습니다. install.bat을 다시 실행해 주세요.")
    _FFMPEG = exe
    return exe


def probe(path):
    """ffprobe 없이 ffmpeg -i 출력으로 크기/fps/길이/오디오 유무 파악 (자동 회전 반영)."""
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True,
                       text=True, encoding="utf-8", errors="ignore", creationflags=_NOWIN)
    err = p.stderr
    dur = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    if not dur:
        raise RuntimeError(f"영상 정보를 읽을 수 없습니다: {path}")
    duration = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
    vline = next((l for l in err.splitlines() if "Video:" in l), "")
    m = re.search(r",\s*(\d{2,5})x(\d{2,5})", vline)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1920, 1080)
    fm = re.search(r"([\d.]+)\s*fps", vline) or re.search(r"([\d.]+)\s*tbr", vline)
    fps = float(fm.group(1)) if fm else 30.0
    rot = re.search(r"rotation of\s*(-?[\d.]+)", err) or re.search(r"rotate\s*:\s*(-?\d+)", err)
    if rot and abs(round(float(rot.group(1)))) % 180 == 90:
        w, h = h, w
    has_audio = "Audio:" in err
    return {"width": w - w % 2, "height": h - h % 2, "fps": fps, "duration": duration, "has_audio": has_audio}


def extract_audio(path, out_wav, sr=16000, channels=1):
    subprocess.run([ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-vn",
                    "-ac", str(channels), "-ar", str(sr), "-c:a", "pcm_s16le", out_wav],
                   check=True, creationflags=_NOWIN)
    return out_wav


def load_audio(path, sr=48000, channels=2, int16=False):
    """(N, ch) 배열. int16=True면 메모리 절약용 정수 배열(읽기 전용)."""
    fmt, dt = ("s16le", np.int16) if int16 else ("f32le", np.float32)
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", path, "-vn",
                        "-ac", str(channels), "-ar", str(sr), "-f", fmt, "-"],
                       capture_output=True, check=True, creationflags=_NOWIN)
    return np.frombuffer(p.stdout, dtype=dt).reshape(-1, channels)


def write_wav(path, audio, sr):
    import wave
    a = np.clip(audio, -1, 1)
    a = (a * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(a.shape[1] if a.ndim > 1 else 1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())


class FrameReader:
    """CFR로 변환해 BGR 프레임을 순서대로 읽음 (가변 프레임레이트 폰 영상 대응)."""

    def __init__(self, path, width, height, fps, start=0.0):
        self.w, self.h = width, height
        self.size = width * height * 3
        cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error"]
        if start > 0:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", path, "-an", "-vf", f"fps={fps},scale={width}:{height}",
                "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self.size * 4, creationflags=_NOWIN)

    def read(self):
        buf = self.p.stdout.read(self.size)
        if len(buf) < self.size:
            return None
        return np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3).copy()

    def close(self):
        try:
            self.p.stdout.close()
            self.p.kill()
        except Exception:
            pass


class FrameWriter:
    def __init__(self, out_path, width, height, fps, audio_wav=None, codec="libx264", crf=19, preset="medium"):
        cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps}", "-i", "-"]
        if audio_wav:
            cmd += ["-i", audio_wav]
        if codec == "h264_nvenc":
            cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(crf)]
        else:
            cmd += ["-c:v", codec, "-crf", str(crf), "-preset", preset]
        cmd += ["-pix_fmt", "yuv420p"]
        if audio_wav:
            cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
        cmd += ["-movflags", "+faststart", out_path]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=_NOWIN)

    def write(self, frame):
        self.p.stdin.write(frame.tobytes())

    def close(self):
        self.p.stdin.close()
        rc = self.p.wait()
        if rc != 0:
            raise RuntimeError("영상 인코딩에 실패했습니다 (ffmpeg 오류).")
