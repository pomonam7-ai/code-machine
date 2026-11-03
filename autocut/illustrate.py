"""설명용 일러스트 생성기: 플랫 벡터 + 핸드드로잉 카툰 스타일 (완전 오프라인, GPU 불필요).
선은 손으로 그린 듯 살짝 흔들리고, 면은 파스텔 단색으로 채웁니다. 글자는 키워드 1개만."""
import math
import os
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

INK = (45, 42, 50, 255)
PAPER = (255, 250, 240, 255)
C = {
    "yellow": (255, 210, 90, 255), "coral": (255, 138, 122, 255), "mint": (127, 214, 181, 255),
    "sky": (126, 200, 242, 255), "lav": (185, 163, 240, 255), "peach": (255, 184, 140, 255),
    "pink": (255, 170, 200, 255), "white": (255, 255, 255, 255), "gray": (210, 210, 215, 255),
    "green": (140, 205, 110, 255), "blue": (95, 150, 230, 255), "red": (240, 95, 90, 255),
    "skin": (255, 214, 180, 255), "brown": (190, 135, 95, 255),
}
SS = 2  # 슈퍼샘플링 배율


# ---------------------------------------------------------------- 펜 (핸드드로잉 효과)
class Pen:
    def __init__(self, img, seed=0, width=7):
        self.img = img
        self.d = ImageDraw.Draw(img, "RGBA")
        self.rng = random.Random(seed)
        self.w = width * SS
        self.cx = self.cy = 0
        self.s = 1

    def at(self, cx, cy, s):
        self.cx, self.cy, self.s = cx * SS, cy * SS, s * SS
        return self

    def P(self, x, y):
        return (self.cx + x * self.s, self.cy + y * self.s)

    # 부드러운 노이즈로 선 흔들기
    def _wobble(self, pts, amp=None, closed=False):
        amp = (amp if amp is not None else 0.012) * self.s
        dense = []
        seq = pts + ([pts[0]] if closed else [])
        for (x1, y1), (x2, y2) in zip(seq, seq[1:]):
            n = max(2, int(math.hypot(x2 - x1, y2 - y1) / (6 * SS)))
            for i in range(n):
                t = i / n
                dense.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
        dense.append(seq[-1])
        ph1, ph2 = self.rng.uniform(0, 6.28), self.rng.uniform(0, 6.28)
        f1, f2 = self.rng.uniform(1.5, 3), self.rng.uniform(4, 7)
        out = []
        N = len(dense)
        for i, (x, y) in enumerate(dense):
            t = i / max(1, N - 1)
            ox = amp * (math.sin(t * f1 * 6.28 + ph1) + 0.4 * math.sin(t * f2 * 6.28 + ph2))
            oy = amp * (math.cos(t * f1 * 6.28 + ph2) + 0.4 * math.cos(t * f2 * 6.28 + ph1))
            out.append((x + ox, y + oy))
        return out

    def _stroke(self, pts, w=None, color=INK, closed=False):
        w = int((w or 1) * self.w)
        wp = self._wobble(pts, closed=closed)
        self.d.line(wp, fill=color, width=w, joint="curve")
        r = w / 2
        for p in (wp[0], wp[-1]):
            self.d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=color)

    def poly(self, pts, fill=None, w=1, stroke=True):
        P = [self.P(*p) for p in pts]
        if fill:
            self.d.polygon(self._wobble(P, amp=0.006, closed=True), fill=fill)
        if stroke:
            self._stroke(P, w, closed=True)

    def line(self, pts, w=1, color=INK):
        self._stroke([self.P(*p) for p in pts], w, color)

    def _ell_pts(self, x, y, rx, ry, a0=0, a1=360, n=None):
        n = n or max(16, int((a1 - a0) / 6))
        return [(x + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                 y + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]

    def ellipse(self, x, y, rx, ry=None, fill=None, w=1, stroke=True):
        ry = ry if ry is not None else rx
        pts = self._ell_pts(x, y, rx, ry)
        P = [self.P(*p) for p in pts]
        if fill:
            self.d.polygon(P, fill=fill)
        if stroke:
            # 손그림처럼 시작점이 살짝 겹치게
            a = self.rng.uniform(0, 360)
            pts2 = self._ell_pts(x, y, rx, ry, a, a + 372)
            self._stroke([self.P(*p) for p in pts2], w)

    def arc(self, x, y, rx, ry, a0, a1, w=1, color=INK):
        self.line(self._ell_pts(x, y, rx, ry, a0, a1), w, color)

    def rrect(self, x1, y1, x2, y2, r=0.1, fill=None, w=1, stroke=True):
        pts = []
        for cx, cy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
            pts += self._ell_pts(cx, cy, r, r, a0, a0 + 90, 6)
        self.poly(pts, fill, w, stroke)

    def dot(self, x, y, r=0.05, color=INK):
        X, Y = self.P(x, y)
        R = r * self.s
        self.d.ellipse([X - R, Y - R, X + R, Y + R], fill=color)

    def arrow(self, x1, y1, x2, y2, w=1.2, head=0.18):
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 0.08 * math.hypot(x2 - x1, y2 - y1)
        pts = [(x1 + (mx - x1) * t * 2, y1 + (my - y1) * t * 2) if t < .5 else
               (mx + (x2 - mx) * (t - .5) * 2, my + (y2 - my) * (t - .5) * 2) for t in np.linspace(0, 1, 12)]
        self.line(pts, w)
        ang = math.atan2(y2 - pts[-3][1], x2 - pts[-3][0])
        for da in (2.6, -2.6):
            self.line([(x2, y2), (x2 + head * math.cos(ang + da), y2 + head * math.sin(ang + da))], w)

    def face(self, x, y, sz=1.0, mood="smile"):
        self.dot(x - 0.16 * sz, y - 0.04 * sz, 0.045 * sz)
        self.dot(x + 0.16 * sz, y - 0.04 * sz, 0.045 * sz)
        if mood == "smile":
            self.arc(x, y + 0.04 * sz, 0.1 * sz, 0.07 * sz, 20, 160, 0.7)
        elif mood == "sad":
            self.arc(x, y + 0.14 * sz, 0.09 * sz, 0.05 * sz, 200, 340, 0.7)
        else:
            self.line([(x - 0.07 * sz, y + 0.1 * sz), (x + 0.07 * sz, y + 0.1 * sz)], 0.7)
        for sx in (-1, 1):
            self.ellipse(x + sx * 0.27 * sz, y + 0.07 * sz, 0.06 * sz, 0.035 * sz, fill=(255, 170, 175, 255), stroke=False)

    def sparkle(self, x, y, r=0.1, color=INK):
        self.line([(x - r, y), (x + r, y)], 0.6, color)
        self.line([(x, y - r), (x, y + r)], 0.6, color)

    def symbol(self, x, y, txt, size=0.6, color=INK, font=None):
        f = ImageFont.truetype(font, int(size * self.s)) if font else ImageFont.load_default()
        X, Y = self.P(x, y)
        self.d.text((X, Y), txt, font=f, fill=color, anchor="mm")


# ---------------------------------------------------------------- 아이콘 라이브러리
def i_money(p, F):
    for k, dy in enumerate((0.45, 0.28, 0.11)):
        p.ellipse(-0.35, dy, 0.42, 0.14, fill=C["yellow"])
    p.ellipse(-0.35, -0.06, 0.42, 0.14, fill=C["yellow"])
    p.symbol(-0.35, -0.08, "₩", 0.22, font=F)
    p.rrect(0.05, -0.55, 0.85, -0.05, 0.06, fill=C["mint"])
    p.ellipse(0.45, -0.3, 0.13, fill=C["green"])
    p.sparkle(0.75, 0.35, 0.09); p.sparkle(-0.8, -0.5, 0.07)


def i_time(p, F):
    p.ellipse(0, 0.05, 0.75, fill=C["sky"])
    p.ellipse(0, 0.05, 0.6, fill=C["white"], w=0.6)
    for a in range(0, 360, 90):
        r = math.radians(a)
        p.line([(0.5 * math.cos(r), 0.05 + 0.5 * math.sin(r)), (0.56 * math.cos(r), 0.05 + 0.56 * math.sin(r))], 0.8)
    p.line([(0, 0.05), (0, -0.38)], 1.1); p.line([(0, 0.05), (0.3, 0.2)], 1.1)
    p.dot(0, 0.05, 0.06)
    p.poly([(-0.55, -0.6), (-0.35, -0.75), (-0.25, -0.62)], fill=C["coral"])
    p.poly([(0.55, -0.6), (0.35, -0.75), (0.25, -0.62)], fill=C["coral"])


def i_idea(p, F):
    p.ellipse(0, -0.15, 0.55, 0.55, fill=C["yellow"])
    p.rrect(-0.22, 0.38, 0.22, 0.62, 0.06, fill=C["gray"])
    p.line([(-0.2, 0.48), (0.2, 0.48)], 0.6)
    p.face(0, -0.15, 1.0)
    for a in (-150, -120, -90, -60, -30):
        r = math.radians(a)
        p.line([(0.7 * math.cos(r), -0.15 + 0.7 * math.sin(r)), (0.9 * math.cos(r), -0.15 + 0.9 * math.sin(r))], 0.8)


def _bars(p, up=True):
    p.line([(-0.8, -0.8), (-0.8, 0.65), (0.85, 0.65)], 1.0)
    hs = (0.35, 0.6, 0.95, 1.25) if up else (1.25, 0.95, 0.6, 0.35)
    cols = (C["sky"], C["mint"], C["yellow"], C["coral"]) if up else (C["coral"], C["peach"], C["gray"], C["sky"])
    for i, (hh, c) in enumerate(zip(hs, cols)):
        x = -0.6 + i * 0.37
        p.rrect(x, 0.62 - hh, x + 0.25, 0.62, 0.04, fill=c)
    if up:
        p.arrow(-0.6, 0.1, 0.65, -0.85, 1.3, 0.2)
    else:
        p.arrow(-0.6, -0.85, 0.65, 0.2, 1.3, 0.2)


def i_growth(p, F): _bars(p, True)
def i_decline(p, F): _bars(p, False)


def i_compare(p, F):
    p.line([(0, -0.7), (0, 0.6)], 1.2)
    p.poly([(-0.3, 0.7), (0.3, 0.7), (0, 0.5)], fill=C["brown"])
    p.line([(-0.7, -0.45), (0.7, -0.6)], 1.2)
    for x, y, c in ((-0.7, -0.45, C["sky"]), (0.7, -0.6, C["coral"])):
        p.line([(x, y), (x - 0.22, y + 0.45)], 0.7); p.line([(x, y), (x + 0.22, y + 0.45)], 0.7)
        p.arc(x, y + 0.45, 0.28, 0.15, 0, 180, 1.0)
        p.poly([(x - 0.28, y + 0.45), (x + 0.28, y + 0.45), (x, y + 0.6)], fill=c, stroke=False)
    p.dot(0, -0.7, 0.07)


def i_warning(p, F):
    p.poly([(0, -0.8), (0.82, 0.65), (-0.82, 0.65)], fill=C["yellow"], w=1.2)
    p.line([(0, -0.35), (0, 0.2)], 1.8)
    p.dot(0, 0.42, 0.08)
    p.sparkle(-0.85, -0.5, 0.1); p.sparkle(0.85, -0.45, 0.08)


def i_check(p, F):
    p.ellipse(0, 0, 0.75, fill=C["mint"])
    p.line([(-0.35, 0.0), (-0.08, 0.28), (0.4, -0.3)], 2.0, C["white"])
    p.line([(-0.35, 0.0), (-0.08, 0.28), (0.4, -0.3)], 0.6)
    p.sparkle(0.8, -0.6, 0.1); p.sparkle(-0.85, 0.55, 0.08)


def i_question(p, F):
    p.ellipse(0, -0.1, 0.75, 0.62, fill=C["lav"])
    p.poly([(-0.3, 0.4), (-0.55, 0.8), (0.0, 0.48)], fill=C["lav"], stroke=False)
    p.line([(-0.3, 0.42), (-0.55, 0.8), (0.02, 0.5)], 1)
    p.symbol(0, -0.13, "?", 0.85, font=F)


def _person(p, x, y, sz, shirt, hair=INK, mood="smile"):
    p.rrect(x - 0.42 * sz, y + 0.3 * sz, x + 0.42 * sz, y + 1.0 * sz, 0.25 * sz, fill=shirt)
    p.ellipse(x, y - 0.1 * sz, 0.4 * sz, fill=C["skin"])
    p.arc(x, y - 0.12 * sz, 0.4 * sz, 0.4 * sz, 190, 350, 1.6, hair)
    p.face(x, y - 0.05 * sz, 0.8 * sz, mood)


def i_person(p, F):
    _person(p, 0, -0.2, 0.9, C["sky"])
    p.sparkle(0.7, -0.7, 0.09)


def i_team(p, F):
    _person(p, -0.55, 0.0, 0.55, C["coral"])
    _person(p, 0.55, 0.0, 0.55, C["mint"])
    _person(p, 0, -0.25, 0.65, C["sky"])


def i_talk(p, F):
    p.rrect(-0.9, -0.75, 0.25, -0.05, 0.2, fill=C["sky"])
    p.poly([(-0.6, -0.08), (-0.75, 0.15), (-0.4, -0.08)], fill=C["sky"])
    for x in (-0.55, -0.32, -0.09):
        p.dot(x, -0.4, 0.05)
    p.rrect(-0.15, 0.0, 0.9, 0.65, 0.2, fill=C["peach"])
    p.poly([(0.55, 0.62), (0.75, 0.85), (0.35, 0.62)], fill=C["peach"])
    p.line([(0.05, 0.25), (0.7, 0.25)], 0.7); p.line([(0.05, 0.42), (0.5, 0.42)], 0.7)


def i_phone(p, F):
    p.rrect(-0.42, -0.85, 0.42, 0.85, 0.12, fill=C["lav"])
    p.rrect(-0.32, -0.68, 0.32, 0.6, 0.05, fill=C["white"], w=0.6)
    p.dot(0, 0.72, 0.05)
    for i, c in enumerate((C["coral"], C["mint"], C["yellow"], C["sky"])):
        x, y = -0.15 + (i % 2) * 0.3, -0.42 + (i // 2) * 0.32
        p.rrect(x - 0.1, y - 0.1, x + 0.1, y + 0.1, 0.04, fill=c, w=0.5)
    p.sparkle(0.7, -0.6, 0.1)


def i_computer(p, F):
    p.rrect(-0.8, -0.65, 0.8, 0.35, 0.06, fill=C["gray"])
    p.rrect(-0.68, -0.53, 0.68, 0.23, 0.03, fill=C["sky"], w=0.6)
    p.line([(-0.5, -0.35), (-0.65, -0.18), (-0.5, -0.02)], 0.9, C["white"])
    p.line([(0.5, -0.35), (0.65, -0.18), (0.5, -0.02)], 0.9, C["white"])
    p.line([(-0.3, -0.25), (0.3, -0.25)], 0.8, C["white"]); p.line([(-0.3, -0.1), (0.1, -0.1)], 0.8, C["white"])
    p.poly([(-0.95, 0.42), (0.95, 0.42), (0.8, 0.62), (-0.8, 0.62)], fill=C["lav"])


def i_book(p, F):
    p.poly([(0, -0.45), (-0.85, -0.6), (-0.85, 0.5), (0, 0.65)], fill=C["coral"])
    p.poly([(0, -0.45), (0.85, -0.6), (0.85, 0.5), (0, 0.65)], fill=C["sky"])
    for dy in (-0.25, -0.05, 0.15):
        p.line([(-0.65, dy - 0.1), (-0.15, dy)], 0.6); p.line([(0.15, dy), (0.65, dy - 0.1)], 0.6)
    p.sparkle(0.0, -0.8, 0.1)


def i_target(p, F):
    for r, c in ((0.75, C["coral"]), (0.52, C["white"]), (0.3, C["coral"]), (0.1, C["white"])):
        p.ellipse(0, 0.05, r, fill=c, w=0.8)
    p.line([(0.02, 0.03), (0.75, -0.7)], 1.2)
    p.poly([(0.7, -0.65), (0.95, -0.75), (0.85, -0.55)], fill=C["yellow"])
    p.poly([(0.75, -0.7), (0.65, -0.95), (0.9, -0.85)], fill=C["yellow"])


def i_steps(p, F):
    cols = (C["sky"], C["mint"], C["yellow"])
    for i in range(3):
        x = -0.68 + i * 0.68
        p.rrect(x - 0.24, -0.24, x + 0.24, 0.24, 0.08, fill=cols[i])
        p.symbol(x, -0.02, str(i + 1), 0.32, font=F)
        if i < 2:
            p.arrow(x + 0.3, 0, x + 0.4, 0, 0.9, 0.08)


def i_heart(p, F):
    pts = []
    for t in np.linspace(0, 2 * math.pi, 60):
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x / 20, -y / 20 + 0.05))
    p.poly(pts, fill=C["pink"])
    p.face(0, -0.05, 0.9)
    p.sparkle(0.8, -0.65, 0.1); p.sparkle(-0.8, -0.6, 0.07)


def i_home(p, F):
    p.rrect(-0.6, -0.1, 0.6, 0.7, 0.04, fill=C["peach"])
    p.poly([(-0.8, -0.05), (0, -0.75), (0.8, -0.05)], fill=C["coral"])
    p.rrect(-0.15, 0.25, 0.15, 0.7, 0.03, fill=C["brown"])
    p.rrect(0.25, 0.05, 0.48, 0.28, 0.02, fill=C["sky"], w=0.6)
    p.rrect(-0.48, 0.05, -0.25, 0.28, 0.02, fill=C["sky"], w=0.6)


def i_globe(p, F):
    p.ellipse(0, 0, 0.75, fill=C["sky"])
    p.poly([(-0.45, -0.4), (-0.1, -0.5), (0.0, -0.2), (-0.3, 0.05), (-0.5, -0.1)], fill=C["green"], w=0.7)
    p.poly([(0.15, 0.05), (0.5, -0.05), (0.55, 0.35), (0.25, 0.5)], fill=C["green"], w=0.7)
    p.arc(0, 0, 0.98, 0.3, 200, 340, 0.8)


def i_rocket(p, F):
    p.poly([(0, -0.9), (0.28, -0.35), (0.28, 0.35), (-0.28, 0.35), (-0.28, -0.35)], fill=C["white"])
    p.ellipse(0, -0.25, 0.13, fill=C["sky"], w=0.7)
    p.poly([(-0.28, 0.05), (-0.55, 0.45), (-0.28, 0.35)], fill=C["coral"])
    p.poly([(0.28, 0.05), (0.55, 0.45), (0.28, 0.35)], fill=C["coral"])
    p.poly([(-0.16, 0.38), (0, 0.85), (0.16, 0.38)], fill=C["yellow"])
    for x in (-0.7, 0.7):
        p.line([(x, 0.4), (x, 0.75)], 0.6)


def i_lock(p, F):
    p.arc(0, -0.2, 0.35, 0.45, 180, 360, 1.8)
    p.line([(-0.35, -0.2), (-0.35, 0.05)], 1.8); p.line([(0.35, -0.2), (0.35, 0.05)], 1.8)
    p.rrect(-0.6, 0.0, 0.6, 0.8, 0.1, fill=C["yellow"])
    p.dot(0, 0.32, 0.09); p.line([(0, 0.35), (0, 0.55)], 1.2)


def i_gear(p, F):
    pts = []
    for i in range(48):
        a = 2 * math.pi * i / 48
        r = 0.75 if (i // 3) % 2 == 0 else 0.58
        pts.append((r * math.cos(a), r * math.sin(a)))
    p.poly(pts, fill=C["gray"])
    p.ellipse(0, 0, 0.25, fill=C["white"])
    p.sparkle(0.85, -0.75, 0.08)


def i_calendar(p, F):
    p.rrect(-0.75, -0.6, 0.75, 0.75, 0.08, fill=C["white"])
    p.rrect(-0.75, -0.6, 0.75, -0.25, 0.08, fill=C["coral"])
    for x in (-0.4, 0.4):
        p.line([(x, -0.78), (x, -0.45)], 1.4)
    for r in range(3):
        for c_ in range(4):
            p.dot(-0.48 + c_ * 0.32, -0.02 + r * 0.25, 0.04)
    p.ellipse(0.16, 0.23, 0.12, fill=None, w=0.9)


def i_search(p, F):
    p.ellipse(-0.15, -0.15, 0.5, fill=C["sky"], w=1.2)
    p.ellipse(-0.15, -0.15, 0.36, fill=(205, 232, 250, 255), w=0.6)
    p.line([(0.22, 0.22), (0.7, 0.7)], 2.6)
    p.arc(-0.2, -0.2, 0.22, 0.22, 200, 260, 0.8, C["white"])


def i_pie(p, F):
    p.ellipse(0, 0, 0.75, fill=C["sky"])
    pts = [(0, 0)] + [(0.75 * math.cos(math.radians(a)), 0.75 * math.sin(math.radians(a))) for a in range(-90, 30, 8)]
    p.poly([(x + 0.08, y - 0.06) for x, y in pts], fill=C["coral"])
    p.symbol(-0.25, 0.2, "%", 0.4, font=F)


def i_gift(p, F):
    p.rrect(-0.65, -0.15, 0.65, 0.75, 0.05, fill=C["coral"])
    p.rrect(-0.75, -0.4, 0.75, -0.12, 0.05, fill=C["pink"])
    p.rrect(-0.12, -0.4, 0.12, 0.75, 0.0, fill=C["yellow"])
    p.ellipse(-0.25, -0.55, 0.22, 0.14, fill=C["yellow"]); p.ellipse(0.25, -0.55, 0.22, 0.14, fill=C["yellow"])


def i_car(p, F):
    p.poly([(-0.85, 0.3), (-0.85, 0.0), (-0.45, -0.05), (-0.25, -0.4), (0.35, -0.4), (0.55, -0.05),
            (0.88, 0.05), (0.88, 0.3)], fill=C["coral"])
    p.poly([(-0.18, -0.3), (0.05, -0.3), (0.05, -0.07), (-0.35, -0.07)], fill=C["sky"], w=0.6)
    p.poly([(0.15, -0.3), (0.32, -0.3), (0.45, -0.07), (0.15, -0.07)], fill=C["sky"], w=0.6)
    for x in (-0.5, 0.5):
        p.ellipse(x, 0.33, 0.18, fill=C["gray"])
    for y in (-0.15, 0.05):
        p.line([(-1.0, y), (-0.92, y)], 0.6)


def i_food(p, F):
    p.arc(0, 0.05, 0.8, 0.65, 0, 180, 1.0)
    p.poly([(x, y) for x, y in p._ell_pts(0, 0.05, 0.8, 0.65, 0, 180)], fill=C["white"], stroke=False)
    p.line([(-0.8, 0.05), (0.8, 0.05)], 1.0)
    for x, c in ((-0.35, C["green"]), (0.0, C["coral"]), (0.35, C["yellow"])):
        p.ellipse(x, -0.08, 0.2, 0.15, fill=c, w=0.7)
    for x in (-0.3, 0.0, 0.3):
        p.line([(x, -0.4), (x + 0.05, -0.55), (x, -0.7)], 0.6)


def i_star(p, F):
    pts = []
    for i in range(10):
        a = math.radians(-90 + i * 36)
        r = 0.8 if i % 2 == 0 else 0.36
        pts.append((r * math.cos(a), r * math.sin(a) + 0.05))
    p.poly(pts, fill=C["yellow"])
    p.face(0, 0.08, 0.7)
    p.sparkle(0.8, -0.65, 0.09); p.sparkle(-0.75, 0.6, 0.07)


def i_chat_ai(p, F):  # 로봇 / AI
    p.rrect(-0.55, -0.45, 0.55, 0.4, 0.15, fill=C["sky"])
    p.line([(0, -0.45), (0, -0.7)], 1.0); p.ellipse(0, -0.78, 0.08, fill=C["coral"], w=0.7)
    p.ellipse(-0.22, -0.08, 0.1, fill=C["white"], w=0.7); p.ellipse(0.22, -0.08, 0.1, fill=C["white"], w=0.7)
    p.dot(-0.22, -0.08, 0.04); p.dot(0.22, -0.08, 0.04)
    p.arc(0, 0.12, 0.15, 0.08, 20, 160, 0.7)
    p.rrect(-0.4, 0.45, 0.4, 0.8, 0.08, fill=C["gray"])


def i_doc(p, F):
    p.poly([(-0.55, -0.8), (0.3, -0.8), (0.6, -0.5), (0.6, 0.8), (-0.55, 0.8)], fill=C["white"])
    p.poly([(0.3, -0.8), (0.3, -0.5), (0.6, -0.5)], fill=C["gray"], w=0.7)
    for y, l in ((-0.35, 0.7), (-0.12, 0.85), (0.11, 0.6), (0.34, 0.8)):
        p.line([(-0.35, y), (-0.35 + l * 0.8, y)], 0.7)
    p.line([(-0.35, 0.58), (-0.2, 0.68), (0.05, 0.48)], 1.0, C["red"])


def i_health(p, F):
    p.rrect(-0.25, -0.75, 0.25, 0.75, 0.06, fill=C["red"])
    p.rrect(-0.75, -0.25, 0.75, 0.25, 0.06, fill=C["red"], stroke=False)
    p.poly([(-0.25, -0.75), (0.25, -0.75), (0.25, -0.25), (0.75, -0.25), (0.75, 0.25), (0.25, 0.25),
            (0.25, 0.75), (-0.25, 0.75), (-0.25, 0.25), (-0.75, 0.25), (-0.75, -0.25), (-0.25, -0.25)], fill=C["red"])


ICONS = {
    "money": (i_money, "돈", ["돈", "비용", "가격", "수익", "월급", "투자", "금액", "매출", "이자", "자산", "저축", "예산", "가성비", "할인", "만원", "억"]),
    "time": (i_time, "시간", ["시간", "분 동안", "기간", "오래", "빨리", "속도", "타이밍", "마감", "시각", "순간"]),
    "idea": (i_idea, "아이디어", ["아이디어", "생각", "팁", "꿀팁", "방법", "해결", "발상", "노하우", "비결", "요령"]),
    "growth": (i_growth, "상승", ["증가", "성장", "상승", "오르*", "늘어*", "늘리*", "높아*", "향상", "개선", "급등", "올라*"]),
    "decline": (i_decline, "하락", ["감소", "하락", "줄어*", "줄이*", "떨어*", "낮아*", "손실", "급락", "적자"]),
    "compare": (i_compare, "비교", ["비교", "차이", "반면", "대신", "장단점", "장점", "단점", "어느 쪽", "vs", "균형"]),
    "warning": (i_warning, "주의", ["주의", "조심", "문제", "위험", "실수", "오류", "에러", "경고", "함정", "피해", "사기"]),
    "check": (i_check, "완료", ["정답", "완료", "성공", "확인", "체크", "해결됐", "통과", "끝"]),
    "question": (i_question, "왜?", ["왜", "질문", "궁금", "무엇일까", "뭘까", "어떻게 하면", "이유"]),
    "person": (i_person, "", ["사람", "고객", "사용자", "유저", "본인", "개인", "직원", "학생", "선생님"]),
    "team": (i_team, "함께", ["팀", "함께", "사람들", "모두", "구독자", "커뮤니티", "협업", "가족", "친구들"]),
    "talk": (i_talk, "대화", ["대화", "소통", "설명", "이야기", "말하*", "인터뷰", "상담", "의견", "피드백"]),
    "phone": (i_phone, "앱", ["휴대폰", "스마트폰", "핸드폰", "앱", "어플", "모바일", "카톡", "문자"]),
    "computer": (i_computer, "", ["컴퓨터", "노트북", "프로그램", "코드", "코딩", "인터넷", "웹", "사이트", "소프트웨어", "개발"]),
    "book": (i_book, "공부", ["공부", "책", "배우*", "학습", "지식", "독서", "강의", "수업", "교육"]),
    "target": (i_target, "목표", ["목표", "목적", "핵심", "집중", "포인트", "타겟", "정확"]),
    "steps": (i_steps, "", ["단계", "순서", "과정", "첫째", "첫 번째", "둘째", "두 번째", "먼저", "그다음", "마지막으로", "절차", "프로세스"]),
    "heart": (i_heart, "", ["좋아하*", "사랑", "마음", "감정", "행복", "기분", "감사", "응원"]),
    "home": (i_home, "집", ["집", "가정", "부동산", "아파트", "월세", "전세", "이사", "생활"]),
    "globe": (i_globe, "세계", ["세계", "해외", "글로벌", "나라", "외국", "여행", "지구", "국제"]),
    "rocket": (i_rocket, "시작", ["시작", "출시", "런칭", "도전", "급성장", "로켓", "창업"]),
    "lock": (i_lock, "보안", ["보안", "비밀", "안전", "개인정보", "비밀번호", "잠금", "보호"]),
    "gear": (i_gear, "원리", ["설정", "시스템", "원리", "작동", "기능", "구조", "메커니즘", "자동화", "기술"]),
    "calendar": (i_calendar, "일정", ["날짜", "일정", "매일", "매주", "주간", "달력", "계획", "스케줄", "기한", "주말"]),
    "search": (i_search, "분석", ["찾*", "검색", "분석", "조사", "리서치", "살펴*", "발견", "데이터"]),
    "pie": (i_pie, "비율", ["비율", "퍼센트", "절반", "%", "프로", "통계", "점유율"]),
    "gift": (i_gift, "혜택", ["선물", "혜택", "보너스", "무료", "이벤트", "공짜", "보상"]),
    "car": (i_car, "", ["자동차", "운전", "이동", "출퇴근", "교통", "차량"]),
    "food": (i_food, "", ["음식", "먹*", "요리", "식사", "밥", "메뉴", "식단", "다이어트"]),
    "star": (i_star, "중요", ["최고", "추천", "중요", "꼭", "베스트", "필수", "인기"]),
    "ai": (i_chat_ai, "AI", ["AI", "인공지능", "로봇", "챗GPT", "GPT", "자동", "알고리즘", "클로드"]),
    "doc": (i_doc, "", ["문서", "서류", "계약", "보고서", "리포트", "정리", "목록", "리스트", "기록", "메모"]),
    "health": (i_health, "건강", ["건강", "병원", "운동", "치료", "약", "몸", "의사"]),
}


# ---------------------------------------------------------------- 폰트
def find_font(cfg_path="", hand=True):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands = [cfg_path] if cfg_path else []
    fd = os.path.join(here, "assets", "fonts")
    if os.path.isdir(fd):
        cands += [os.path.join(fd, f) for f in sorted(os.listdir(fd)) if f.lower().endswith((".ttf", ".otf", ".ttc"))]
    cands += [r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\malgun.ttf",
              r"C:\Windows\Fonts\NanumGothicBold.ttf", r"C:\Windows\Fonts\gulim.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
              "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
              "/System/Library/Fonts/AppleSDGothicNeo.ttc", "/Library/Fonts/AppleGothic.ttf"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


# ---------------------------------------------------------------- 카드 합성
def _mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3)) + (255,)


def render_card(concepts, label="", seed=0, size=(960, 720), font=None, sd_image=None):
    W, H = size
    k = W / 960.0
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    pen = Pen(img, seed, width=7 * k)
    rng = random.Random(seed)
    m = 26 * k
    # 그림자 + 종이 카드
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([int((m + 10 * k) * SS), int((m + 14 * k) * SS), int((W - m + 10 * k) * SS),
                                          int((H - m + 14 * k) * SS)], int(40 * k * SS), fill=(0, 0, 0, 70))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10 * k * SS)))
    pen.at(W / 2, H / 2, 1)
    hw, hh = W / 2 - m, H / 2 - m
    pen.rrect(-hw, -hh, hw, hh, 38 * k, fill=PAPER, w=1.1)
    # 배경 장식: 연한 블롭 (카드 안쪽에만)
    for _ in range(3):
        rx, ry = rng.uniform(60, 110) * k, rng.uniform(50, 90) * k
        bx, by = rng.uniform(-hw + rx + 10, hw - rx - 10), rng.uniform(-hh + ry + 10, hh - ry - 10)
        col = _mix(PAPER, rng.choice([C["yellow"], C["mint"], C["sky"], C["pink"], C["lav"], C["peach"]]), 0.22)
        pen.ellipse(bx, by, rx, ry, fill=col, stroke=False)

    has_label = bool(label)
    cy = H / 2 - (45 * k if has_label else 0)
    if sd_image is not None:
        side = int(min(W, H) * (0.66 if has_label else 0.8))
        im = sd_image.convert("RGBA").resize((side * SS, side * SS), Image.LANCZOS)
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.size[0], im.size[1]], int(30 * k * SS), fill=255)
        img.paste(im, (int((W / 2) * SS - im.size[0] / 2), int(cy * SS - im.size[1] / 2)), mask)
    else:
        concepts = [c for c in concepts if c in ICONS][:2] or ["idea"]
        if len(concepts) == 1:
            ICONS[concepts[0]][0](pen.at(W / 2, cy, (235 if has_label else 280) * k), font)
        else:
            ICONS[concepts[0]][0](pen.at(W * 0.27, cy, 170 * k), font)
            ICONS[concepts[1]][0](pen.at(W * 0.73, cy, 170 * k), font)
            pen.at(W / 2, cy, 70 * k).arrow(-0.6, 0.0, 0.6, 0.0, 1.3, 0.3)
        # 반짝이 장식 (모서리 쪽)
        for sx in (rng.uniform(70, 120) * k, W - rng.uniform(70, 120) * k):
            pen.at(sx, rng.uniform(50, 90) * k + m, 1).sparkle(0, 0, 13 * k)
    if has_label and font:
        fsize = (92 if len(label) <= 4 else 72) * k
        f = ImageFont.truetype(font, int(fsize * SS))
        tx, ty = W / 2 * SS, (H - m - 80 * k) * SS
        bbox = pen.d.textbbox((tx, ty), label, font=f, anchor="mm")
        pad = 22 * k * SS
        pen.cx = pen.cy = 0; pen.s = 1
        hl = (bbox[0] - pad, bbox[1] + pad * 0.7, bbox[2] + pad, bbox[3] + pad * 0.35)
        pen.d.polygon(pen._wobble([(hl[0], hl[1]), (hl[2], hl[1] - 6 * SS), (hl[2], hl[3]), (hl[0], hl[3] + 4 * SS)], amp=4 * k, closed=True),
                      fill=_mix(PAPER, C["yellow"], 0.75))
        pen.d.text((tx, ty), label, font=f, fill=INK, anchor="mm")
    return img.resize((W, H), Image.LANCZOS)


# ---------------------------------------------------------------- 선택적: 로컬 Stable Diffusion
class SDEngine:
    STYLE = ("flat vector illustration, hand-drawn cartoon style, thick wobbly ink outlines, pastel flat colors, "
             "cute, simple shapes, minimal, centered, plain off-white background, no text, no letters")

    def __init__(self, model_id, log):
        import torch
        from diffusers import AutoPipelineForText2Image
        if not torch.cuda.is_available():
            raise RuntimeError("GPU(CUDA)가 없어 Stable Diffusion을 쓸 수 없습니다")
        log(f"  로컬 이미지 모델 로딩: {model_id} (첫 실행 시 수 GB 다운로드)")
        self.pipe = AutoPipelineForText2Image.from_pretrained(model_id, torch_dtype=torch.float16, variant="fp16").to("cuda")
        self.turbo = "turbo" in model_id

    def generate(self, subject, seed=0):
        import torch
        g = torch.Generator("cuda").manual_seed(seed)
        kw = dict(num_inference_steps=4, guidance_scale=0.0) if self.turbo else dict(num_inference_steps=28, guidance_scale=6.0)
        return self.pipe(prompt=f"{subject}, {self.STYLE}", negative_prompt=None if self.turbo else "text, watermark, photo, realistic",
                         width=768, height=768, generator=g, **kw).images[0]
