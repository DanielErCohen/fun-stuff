"""The four tracks, each a description that draw() turns into game data.

A track is a centre line in race order (starting on the start line), a road width, a look (the
colours of the shared palette layout) and its things: coins, item panels, boost pads, ramps, oil,
sand, water, pits, moving obstacles and an optional sandy shortcut. draw() makes from it:
- a 1024x1024 picture of palette indices, which gen_assets.py cuts into at most 256 Mode 7 tiles;
- a surface value per 8x8 tile (what driving over it does);
- a lap-progress value per 16x16 cell: 0-255 round the lap (checkpoint = value // 8, so 32
  checkpoints), or 255 off the track, where nothing counts;
- the rescue point of each checkpoint, the start grid and a 32x32 minimap.

All shapes are original and drawn here. Run `python3 tools/tracks.py DIR` to write a preview PNG
of each track picture into DIR.
"""
import math
import os
import re
import sys

import numpy as np

# ---------------------------------------------------------------- palette layout (shared by every track)
SKY, GRASS, GRASS_DARK, ROAD, SPECK, CURB_A, CURB_B, LINE_A, LINE_B, SKY_TILE = range(10)
COIN_GOLD, COIN_RIM, COIN_SHINE, PANEL, PANEL_STRIPE, YELLOW, SLIME, SLIME_RIM, SLIME_SHINE = range(10, 19)
PAD_ORANGE, OUTLINE = 19, 20
SAND, SAND_DARK, OIL, OIL_SHINE, WATER, WATER_LIGHT, PIT, PIT_EDGE, RAMP_A, RAMP_B = range(21, 31)

BASE_PAL = [
    (96, 160, 248), (72, 168, 64), (56, 144, 48), (104, 104, 112), (88, 88, 96), (216, 40, 40), (240, 240, 240),
    (24, 24, 24), (248, 248, 248), (96, 160, 248), (248, 200, 40), (200, 128, 16), (255, 248, 160), (136, 56, 200),
    (88, 24, 144), (255, 224, 64), (96, 216, 72), (40, 136, 40), (200, 255, 160), (248, 128, 24), (40, 32, 48),
    (224, 176, 104), (184, 136, 72), (36, 28, 44), (120, 104, 168), (40, 96, 200), (112, 168, 240), (20, 14, 26),
    (96, 72, 64), (248, 200, 40), (72, 52, 40),
]
# Each look recolours the sky, the off-road (light and dark), the road and its specks, and the curbs.
LOOKS = {
    "meadow": {},
    "desert": {SKY: (120, 184, 240), SKY_TILE: (120, 184, 240), GRASS: (232, 204, 136), GRASS_DARK: (216, 184, 112),
               ROAD: (128, 108, 100), SPECK: (112, 92, 84), CURB_A: (232, 112, 32), CURB_B: (248, 240, 216)},
    "snow": {SKY: (176, 208, 240), SKY_TILE: (176, 208, 240), GRASS: (240, 244, 252), GRASS_DARK: (212, 224, 244),
             ROAD: (100, 108, 136), SPECK: (84, 92, 120), CURB_A: (40, 104, 224), CURB_B: (248, 248, 248),
             PIT: (40, 64, 120), PIT_EDGE: (176, 208, 244)},   # the crevasse: deep ice, a bright rim
    "stadium": {SKY: (232, 168, 120), SKY_TILE: (232, 168, 120), GRASS: (96, 72, 120), GRASS_DARK: (80, 60, 104),
                ROAD: (176, 120, 96), SPECK: (160, 104, 84), CURB_A: (248, 224, 64), CURB_B: (40, 32, 48),
                PIT: (24, 16, 32), PIT_EDGE: (248, 224, 64)},
    "night": {SKY: (16, 20, 64), SKY_TILE: (16, 20, 64), GRASS: (32, 80, 72), GRASS_DARK: (24, 64, 60),
              ROAD: (72, 72, 96), SPECK: (58, 58, 80), CURB_A: (248, 200, 48), CURB_B: (72, 72, 216),
              WATER: (24, 56, 152), WATER_LIGHT: (72, 120, 216), SAND: (184, 152, 96), SAND_DARK: (152, 120, 72)},
}

# Surface values (main.c SURF_*): what driving over an 8x8 tile does.
S_GRASS, S_ROAD, S_PAD, S_RAMP, S_OIL, S_SAND, S_FALL = range(7)
NCP = 32          # checkpoints a lap
OFF = 255         # lap-progress value off the track
GRID_SIDES = ((-12, 12), (-18, 18), (0, 18))   # sideways from the centre line (right is positive) in each row: the computer karts start in no player's line
GRID_BACK = (20, 44, 62)   # px before the start line: the players, then two rows of computer karts (the row at 62 stops short of the Frosty Peaks crevasse, which ends 71 px before the line)
MARGIN = 40       # a cell counts for laps up to this far beyond the road edge
CURB = 4
STEP = 2.0        # centre line sample spacing, map pixels
WEST, SOUTH, EAST, NORTH = (-1, 0), (0, 1), (1, 0), (0, -1)
RUNUP = 130       # a rescued kart is put at least this far before a ramp, room to reach top speed
AIM = 40          # the steering map aims at the centre-line point this far (map px) beyond the cell's nearest sample
LOOK = 60         # the lift bit looks this far (map px) ahead along the route for its tightest bend
DODGE_FLAT, DODGE_EASE = 30, 45   # the steering map's sideways dodge: px held either side of its spot, px to ease back
SMOOTH = 20       # samples either side (STEP px each) that a bend's radius is measured across


# ---------------------------------------------------------------- floor cell pictures (16x16)
def disc(x, y, cx, cy, r):
    return (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r


def asphalt(x, y):
    return SPECK if (x & 7) == 3 and (y & 7) == 5 or (x & 7) == 6 and (y & 7) == 1 else ROAD


def plain(v):
    return lambda x, y: v


def coin_art(bg):
    def px(x, y):
        if not disc(x, y, 8, 8, 6.5):
            return bg(x, y)
        if not disc(x, y, 8, 8, 5.2):
            return COIN_RIM
        if 7 <= x <= 8 and 5 <= y <= 10:
            return COIN_RIM
        return COIN_SHINE if disc(x, y, 6, 6, 2) else COIN_GOLD
    return [[px(x, y) for x in range(16)] for y in range(16)]


def panel_art(bg):
    def px(x, y):
        if not (1 <= x <= 14 and 1 <= y <= 14):
            return bg(x, y)
        if x in (1, 14) or y in (1, 14):
            return OUTLINE
        if x in (2, 13) or y in (2, 13):
            return YELLOW
        if abs(x - 7.5) + abs(y - 7.5) <= 3.5:
            return YELLOW if abs(x - 7.5) + abs(y - 7.5) <= 2.5 else CURB_B
        return PANEL_STRIPE if (x + y) % 4 == 0 else PANEL
    return [[px(x, y) for x in range(16)] for y in range(16)]


def slime_art(bg):
    blobs = [(8, 9, 6.0), (5, 7, 3.2), (11, 7, 3.0), (8, 12, 3.5)]

    def inside(x, y, grow=0.0):
        return any(disc(x, y, cx, cy, r + grow) for cx, cy, r in blobs)

    def px(x, y):
        if not inside(x, y):
            return bg(x, y)
        if not inside(x, y, -1.2):
            return SLIME_RIM
        return SLIME_SHINE if disc(x, y, 5, 7, 1.2) or disc(x, y, 10, 10, 0.9) else SLIME
    return [[px(x, y) for x in range(16)] for y in range(16)]


def turned(up, direction):
    """A picture drawn pointing north, turned to point along `direction`."""
    def px(x, y):
        if direction == NORTH:
            return up(x, y)
        if direction == SOUTH:
            return up(x, 15 - y)
        if direction == WEST:
            return up(y, x)
        return up(y, 15 - x)
    return [[px(x, y) for x in range(16)] for y in range(16)]


def pad_art(direction):
    """An orange plate with two yellow chevrons pointing along the race direction."""
    def up(x, y):
        if not (1 <= x <= 14 and 1 <= y <= 14):
            return ROAD
        if x in (1, 14) or y in (1, 14):
            return OUTLINE
        u = abs(x - 7.5)
        for c in (2.5, 8.5):
            if u <= 5 and 0 <= y - c - u < 2.5:
                return YELLOW
        return PAD_ORANGE
    return turned(up, direction)


def ramp_art(direction):
    """A yellow ramp with dark stripes across it, its high (far) edge outlined."""
    def up(x, y):
        if y <= 1:
            return OUTLINE
        return RAMP_B if (y // 3) % 2 == 0 and 1 < x < 14 else RAMP_A
    return turned(up, direction)


def quarters(art):
    """The four 8x8 tiles of a 16x16 picture: top-left, top-right, bottom-left, bottom-right."""
    return [bytes(art[qy + j][qx + i] for j in range(8) for i in range(8)) for qy in (0, 8) for qx in (0, 8)]


# ---------------------------------------------------------------- centre lines
def catmull(ctrl, per=48):
    """A closed Catmull-Rom curve through the control points, which it passes in order."""
    n, out = len(ctrl), []
    for i in range(n):
        p0, p1, p2, p3 = (np.array(ctrl[(i + k - 1) % n], float) for k in range(4))
        for t in np.linspace(0, 1, per, endpoint=False):
            out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    return np.array(out)


def resample(pts, closed=True):
    """Points every STEP map pixels along a polyline, with their distance along it."""
    if closed:
        pts = np.vstack([pts, pts[:1]])
    cum = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
    s = np.arange(0, cum[-1] - (STEP / 2 if closed else -1e-9), STEP)
    return np.interp(s, cum, pts[:, 0]), np.interp(s, cum, pts[:, 1]), s, cum[-1]


def open_curve(ctrl, per=32):
    """An open Catmull-Rom curve from the first control point to the last."""
    ext = [2 * np.array(ctrl[0], float) - ctrl[1]] + [np.array(c, float) for c in ctrl] + [2 * np.array(ctrl[-1], float) - ctrl[-2]]
    out = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for t in np.linspace(0, 1, per, endpoint=False):
            out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    out.append(np.array(ctrl[-1], float))
    return np.array(out)


def splat(xs, ys, hw, reach):
    """Distance from each map pixel's centre to the nearest road edge (negative on the road) within
    `reach` px of the centre line, and which sample is nearest; infinity and -1 elsewhere."""
    field = np.full((1024, 1024), np.inf, np.float32)
    near = np.full((1024, 1024), -1, np.int32)
    for i in range(len(xs)):
        x, y = xs[i], ys[i]
        x0, x1 = max(0, int(x - reach)), min(1024, int(x + reach) + 1)
        y0, y1 = max(0, int(y - reach)), min(1024, int(y + reach) + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        gx = np.arange(x0, x1) + 0.5 - x
        gy = np.arange(y0, y1) + 0.5 - y
        d = np.sqrt(gx[None, :] ** 2 + gy[:, None] ** 2) - hw[i]
        sub, nsub = field[y0:y1, x0:x1], near[y0:y1, x0:x1]
        m = d < sub
        sub[m] = d[m]
        nsub[m] = i
    return field, near


# ---------------------------------------------------------------- the tracks
# Octagon midway between the oval's outer edge (|x| 400, |y| 300, |x|+|y| 560 round 512,512) and its
# inner edge (344, 244, 480): the oval's centre line, anticlockwise on the map from the start line.
_OV = [(0, -272), (-248, -272), (-372, -148), (-372, 148), (-248, 272), (248, 272), (372, 148), (372, -148), (248, -272)]

TRACKS = [
    {
        "name": "CLOVER OVAL", "look": "meadow", "oval": True, "width": 56,
        "route": [(512 + x, 512 + y) for x, y in _OV], "smooth": False,
        # cells (x, y), each on plain road: two cells across each straight
        "coins": [(28, 14), (28, 15), (27, 14), (27, 15), (8, 31), (9, 31), (8, 32), (9, 32), (8, 33), (9, 33),
                  (26, 48), (26, 49), (27, 48), (27, 49), (54, 31), (55, 31), (54, 30), (55, 30), (54, 29), (55, 29)],
        "panels": [(21, 14), (21, 15), (36, 48), (36, 49)],
        "pads": [((8, 26), SOUTH), ((9, 26), SOUTH), ((54, 38), NORTH), ((55, 38), NORTH)],
    },
    {
        # A peanut on the diagonal: two tight lobes joined by a pinched waist, run without a crossing.
        "name": "SANDY TWIST", "look": "desert", "width": 60,
        "route": [(560, 120), (400, 120), (260, 128), (150, 190), (110, 300), (150, 420), (260, 470),
                  (380, 470), (470, 520), (520, 620), (560, 760), (640, 880), (760, 912), (870, 860),
                  (912, 740), (880, 620), (790, 530), (700, 400), (690, 250), (720, 140), (680, 120)],
        "coins": [(0.10, -12), (0.10, 12), (0.12, -12), (0.12, 12), (0.30, -12), (0.30, 12), (0.32, -12), (0.32, 12),
                  (0.50, -12), (0.50, 12), (0.52, -12), (0.52, 12), (0.70, -12), (0.70, 12), (0.72, -12), (0.72, 12),
                  (0.88, -12), (0.88, 12), (0.90, -12), (0.90, 12)],
        "panels": [(0.20, -12), (0.20, 12), (0.62, -12), (0.62, 12)],
        "pads": [(0.04, -12), (0.04, 12)],
        "oil": [(0.40, 14), (0.79, -14)],
        "sand": [(0.56, -10, 26), (0.95, 10, 22)],   # (where, sideways, radius): drifts on the road
        "dodge": [(0.40, -16), (0.56, 21), (0.79, 17), (0.95, -17)],   # the computer karts' aim, sideways: past the oil and the sand
        "obstacles": [(0.27, 90)],                     # (where, frames to cross the road)
    },
    {
        # A long straight along the bottom with a ramp over a crevasse, then a climb of hairpins.
        "name": "FROSTY PEAKS", "look": "snow", "width": 60,
        "route": [(520, 900), (300, 900), (130, 880), (90, 780), (150, 690), (300, 650), (420, 610),
                  (430, 520), (330, 470), (180, 430), (110, 330), (160, 220), (300, 180), (440, 230),
                  (540, 330), (640, 300), (680, 180), (780, 110), (890, 160), (920, 300), (880, 440),
                  (790, 520), (760, 640), (860, 740), (900, 840), (820, 900), (700, 900)],
        "coins": [(0.14, -12), (0.14, 12), (0.16, -12), (0.16, 12), (0.33, -12), (0.33, 12), (0.35, -12), (0.35, 12),
                  (0.49, -12), (0.49, 12), (0.51, -12), (0.51, 12), (0.66, -12), (0.66, 12), (0.68, -12), (0.68, 12),
                  (0.82, -12), (0.82, 12), (0.84, -12), (0.84, 12)],
        "panels": [(0.24, -12), (0.24, 12), (0.74, -12), (0.74, 12)],
        "pads": [(0.93, -12), (0.93, 12)],
        "ramps": [(0.965, 48)],      # (where, gap after it): a ramp across the road and a crevasse beyond
        "obstacles": [(0.42, 80), (0.59, 70)],
    },
    {
        # Round a night harbour: the long bottom-right corner wraps a bay, and a sandy shortcut across
        # it jumps a canal (a ramp before it). On the sand a kart is too slow for the jump unless boosting.
        "name": "MOON HARBOUR", "look": "night", "width": 60,
        "route": [(560, 110), (400, 110), (240, 120), (130, 190), (100, 320), (150, 450), (260, 520), (290, 640),
                  (210, 750), (220, 870), (350, 920), (500, 900), (650, 900), (800, 910), (910, 850), (940, 720),
                  (910, 590), (840, 500), (780, 400), (800, 280), (760, 160), (660, 110)],
        "shortcut": {"from": (500, 900), "to": (840, 500), "via": [(600, 790), (640, 700), (640, 600), (720, 520)], "width": 40},
        "bay": True,                                  # water between the shortcut and the corner it cuts
        "canal": {"at": (640, 650), "gap": 40},       # a canal across the shortcut, with a ramp before it
        "coins": [(0.10, -12), (0.10, 12), (0.12, -12), (0.12, 12), (0.27, -12), (0.27, 12), (0.29, -12), (0.29, 12),
                  (0.42, -12), (0.42, 12), (0.44, -12), (0.44, 12), (0.62, -12), (0.62, 12), (0.64, -12), (0.64, 12),
                  (0.86, -12), (0.86, 12), (0.88, -12), (0.88, 12)],
        "panels": [(0.19, -12), (0.19, 12), (0.80, -12), (0.80, 12)],
        "pads": [(0.36, -12), (0.36, 12)],
    },
]


ARENA = {
    # The battle arena: an open square floor with a pit in each corner area and two rolling obstacles.
    # Its "route" is a ring round the middle, used to place coins, panels and obstacles; no laps count.
    "name": "SUNSET ARENA", "look": "stadium", "arena": True, "width": 72, "half": 232,
    "route": [(512, 362), (362, 362), (362, 662), (662, 662), (662, 362)], "smooth": False,
    "pit_squares": [(400, 400, 22), (624, 400, 22), (400, 624, 22), (624, 624, 22)],
    "grid": [(512, 700), (512, 324)], "angles": [0, 64 << 8],   # facing each other across the middle
    "rescue": (512, 512, 0),
    "coins": [(k / 20, -14 if k % 2 else 14) for k in range(20)],
    "panels": [(0.125, 0), (0.375, 0), (0.625, 0), (0.875, 0)],
    "pads": [],
    "obstacles": [(0.25, 90), (0.75, 90)],
}
TRACKS.append(ARENA)


def track_route(t):
    """Centre line samples (x, y, distance along, length) of the main road, from the start line."""
    pts = catmull(t["route"]) if t.get("smooth", True) else np.array(t["route"], float)
    return resample(pts)


def point_at(route, frac, lat=0.0):
    """Map point `frac` of the way round the main road and `lat` px to its right, and the direction there."""
    xs, ys, s, L = route
    i = int(round(frac * L / STEP)) % len(xs)
    j = (i + 2) % len(xs)
    dx, dy = xs[j] - xs[i - 2], ys[j] - ys[i - 2]
    n = math.hypot(dx, dy)
    dx, dy = dx / n, dy / n
    return xs[i] - dy * lat, ys[i] + dx * lat, dx, dy


def frac_of(route, pt):
    """How far round the main road (0-1) its nearest point to `pt` lies."""
    xs, ys, s, L = route
    return s[int(np.argmin(np.hypot(xs - pt[0], ys - pt[1])))] / L


def axis(dx, dy):
    """The nearest of the four map directions."""
    return (1 if dx > 0 else -1, 0) if abs(dx) >= abs(dy) else (0, 1 if dy > 0 else -1)


def polygon_mask(poly, X, Y):
    """Pixels inside a polygon (even-odd rule)."""
    inside = np.zeros(X.shape, bool)
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if y0 == y1:
            continue
        cond = ((Y >= min(y0, y1)) & (Y < max(y0, y1)))
        xc = x0 + (Y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= cond & (X < xc)
    return inside


def oval_picture(X, Y):
    """The first oval, pixel for pixel: the octagon loop of tools/gen_assets.py before tracks were data."""
    dx, dy = X + 0.5 - 512, Y + 0.5 - 512
    ax, ay, ad = np.abs(dx), np.abs(dy), np.abs(dx) + np.abs(dy)
    out_x, out_y, out_d, road = 400, 300, 560, 56
    in_x, in_y, in_d = out_x - road, out_y - road, out_d - 80
    inside_outer = (ax <= out_x) & (ay <= out_y) & (ad <= out_d)
    inside_inner = (ax <= in_x) & (ay <= in_y) & (ad <= in_d)
    img = np.where((((X >> 5) + (Y >> 5)) & 1) == 0, GRASS, GRASS_DARK).astype(np.uint8)
    on = inside_outer & ~inside_inner
    d_out = np.minimum(np.minimum(out_x - ax, out_y - ay), (out_d - ad) / math.sqrt(2))
    d_in = np.maximum(np.maximum(ax - in_x, ay - in_y), (ad - in_d) / math.sqrt(2))
    curb = on & (np.minimum(d_out, d_in) < CURB)
    line = on & ~curb & (dx >= 0) & (dx < 8) & (dy < 0)
    flat = on & ~curb & ~line
    speck = ((X & 7) == 3) & ((Y & 7) == 5) | ((X & 7) == 6) & ((Y & 7) == 1)
    img[flat] = np.where(speck, SPECK, ROAD)[flat]
    img[curb] = np.where((((X >> 3) + (Y >> 3)) & 1) == 1, CURB_A, CURB_B)[curb]
    img[line] = np.where((((X >> 2) + (Y >> 2)) & 1) == 1, LINE_A, LINE_B)[line]
    return img, on


def draw(t):
    """Everything the game needs of track t, before it is cut into tiles."""
    Y, X = np.mgrid[0:1024, 0:1024]
    route = track_route(t)
    xs, ys, s, L = route
    hw = t["width"] / 2
    reach = hw + MARGIN + 12
    main_f, main_n = splat(xs, ys, np.full(len(xs), hw), reach)
    fine = np.minimum(np.floor(s / L * 256).astype(int) % 256, OFF - 1)  # 255 means off the track
    sc_f, sc_n, sc_fine, sc_pts = None, None, None, None
    if "shortcut" in t:
        sc = t["shortcut"]
        fa, fb = frac_of(route, sc["from"]), frac_of(route, sc["to"])
        a, b = point_at(route, fa), point_at(route, fb)
        sc_pts = open_curve([(a[0], a[1])] + sc["via"] + [(b[0], b[1])])
        sx, sy, ss, sl = resample(sc_pts, closed=False)
        sc_f, sc_n = splat(sx, sy, np.full(len(sx), sc["width"] / 2), sc["width"] / 2 + MARGIN + 12)
        f0, f1 = fa * 256, fb * 256
        sc_fine = np.minimum(np.floor(f0 + (f1 - f0) * ss / sl).astype(int) % 256, OFF - 1)
        sc_xy = (sx, sy, ss, sl)

    # the picture: off-road in 32 px squares, the road with curbs, the start line
    speck = ((X & 7) == 3) & ((Y & 7) == 5) | ((X & 7) == 6) & ((Y & 7) == 1)
    if t.get("oval"):
        img, road = oval_picture(X, Y)
    elif t.get("arena"):
        img = np.where((((X >> 5) + (Y >> 5)) & 1) == 0, GRASS, GRASS_DARK).astype(np.uint8)
        h = t["half"]
        ax, ay = np.abs(X + 0.5 - 512), np.abs(Y + 0.5 - 512)
        road = (ax < h) & (ay < h)
        curb = road & (np.maximum(ax, ay) >= h - CURB)
        img[road] = np.where(speck, SPECK, ROAD)[road]
        img[curb] = np.where((((X >> 3) + (Y >> 3)) & 1) == 1, CURB_A, CURB_B)[curb]
    else:
        img = np.where((((X >> 5) + (Y >> 5)) & 1) == 0, GRASS, GRASS_DARK).astype(np.uint8)
        road = main_f < 0
        curb = road & (main_f >= -CURB)
        if sc_f is not None:
            curb &= ~(sc_f < 0)
        sx0, sy0, sdx, sdy = point_at(route, 0.0)
        along = (X + 0.5 - sx0) * sdx + (Y + 0.5 - sy0) * sdy
        side = (X + 0.5 - sx0) * -sdy + (Y + 0.5 - sy0) * sdx
        line = road & ~curb & (along >= -8) & (along < 0) & (np.abs(side) < hw + 2)
        flat = road & ~curb & ~line
        img[flat] = np.where(speck, SPECK, ROAD)[flat]
        img[curb] = np.where((((X >> 3) + (Y >> 3)) & 1) == 1, CURB_A, CURB_B)[curb]
        img[line] = np.where((((X >> 2) + (Y >> 2)) & 1) == 1, LINE_A, LINE_B)[line]
    cls = np.where(road, S_ROAD, S_GRASS).astype(np.uint8)  # what each pixel does to a kart
    for cx, cy, r in t.get("pit_squares", []):
        band = (np.abs(X + 0.5 - cx) < r) & (np.abs(Y + 0.5 - cy) < r)
        edge = band & ((np.abs(X + 0.5 - cx) >= r - 3) | (np.abs(Y + 0.5 - cy) >= r - 3))
        img[band] = PIT
        img[edge] = PIT_EDGE
        cls[band] = S_FALL

    sand_pat = np.where(speck, SAND_DARK, SAND)
    if sc_f is not None:
        path = (sc_f < 0) & ~road
        img[path] = sand_pat[path]
        cls[path] = S_SAND
    for frac, lat, r in t.get("sand", []):
        cx, cy, _, _ = point_at(route, frac, lat)
        m = (X + 0.5 - cx) ** 2 + ((Y + 0.5 - cy) * 1.3) ** 2 <= r * r
        img[m] = sand_pat[m]
        cls[m] = S_SAND
    for frac, lat in t.get("oil", []):
        cx, cy, _, _ = point_at(route, frac, lat)
        m = np.zeros(X.shape, bool)
        for ox, oy, r in ((0, 0, 11), (-8, 4, 7), (7, -5, 7), (3, 8, 6)):
            m |= (X + 0.5 - cx - ox) ** 2 + (Y + 0.5 - cy - oy) ** 2 <= r * r
        shine = m & ((X + 0.5 - cx + 3) ** 2 + (Y + 0.5 - cy + 3) ** 2 <= 9)
        img[m] = OIL
        img[shine] = OIL_SHINE
        cls[m] = S_OIL
    wave = ((Y & 7) == 2) & (((X + (Y >> 3) * 3) & 15) < 6)
    if t.get("bay"):
        i0, i1 = int(fa * L / STEP), int(fb * L / STEP)
        poly = list(zip(xs[i0:i1 + 1], ys[i0:i1 + 1])) + list(zip(sc_xy[0][::-1], sc_xy[1][::-1]))
        m = polygon_mask(poly, X + 0.5, Y + 0.5) & (main_f > 14) & (sc_f > 12)
        img[m] = np.where(wave, WATER_LIGHT, WATER)[m]
        cls[m] = S_FALL
    for poly in t.get("water", []):
        m = polygon_mask(poly, X + 0.5, Y + 0.5) & ~road
        img[m] = np.where(wave, WATER_LIGHT, WATER)[m]
        cls[m] = S_FALL

    ramps, pits = [], []
    for frac, gap in t.get("ramps", []):
        ramps.append((point_at(route, frac), gap, hw))
    if "canal" in t and sc_f is not None:
        sx, sy, ss, sl = sc_xy
        i = int(np.argmin(np.hypot(sx - t["canal"]["at"][0], sy - t["canal"]["at"][1])))
        dx, dy = sx[min(i + 2, len(sx) - 1)] - sx[max(i - 2, 0)], sy[min(i + 2, len(sx) - 1)] - sy[max(i - 2, 0)]
        n = math.hypot(dx, dy)
        ramps.append(((sx[i], sy[i], dx / n, dy / n), t["canal"]["gap"], t["shortcut"]["width"] / 2))
    ramp_cells, fall_bands = [], []
    for (rx, ry, dx, dy), gap, rhw in ramps:
        d = axis(dx, dy)
        # one row of cells across the road; the crevasse (or canal) starts at the ramp's far edge
        cx, cy = int(rx // 16), int(ry // 16)
        span = int(rhw // 16) + 1
        row = [(cx + k * abs(d[1]), cy + k * abs(d[0])) for k in range(-span, span + 1)]
        row = [c for c in row if road[c[1] * 16 + 8, c[0] * 16 + 8] or (sc_f is not None and sc_f[c[1] * 16 + 8, c[0] * 16 + 8] < 0)]
        ramp_cells += [(c, d) for c in row]
        far = (cx * 16 + 8 + d[0] * 8, cy * 16 + 8 + d[1] * 8)  # the ramp row's far edge, centre
        along = (X + 0.5 - far[0]) * d[0] + (Y + 0.5 - far[1]) * d[1]
        side = (X + 0.5 - far[0]) * -d[1] + (Y + 0.5 - far[1]) * d[0]
        band = (along >= 0) & (along < gap) & (np.abs(side) < rhw + 70)
        kind = "water" if "canal" in t else "pit"
        if kind == "pit":
            edge = band & ((along < 3) | (along >= gap - 3))
            depth = band & ((((along.astype(int) >> 2) + (side.astype(int) >> 3)) & 3) == 0)  # cracks in the ice
            img[band] = PIT
            img[depth] = PIT_EDGE
            img[edge] = PIT_EDGE
        else:
            img[band] = np.where(wave, WATER_LIGHT, WATER)[band]
        cls[band] = S_FALL
        fall_bands.append((far, d, gap))

    # surface per 8x8 tile, from what its pixels do
    tiles_cls = cls.reshape(128, 8, 128, 8).transpose(0, 2, 1, 3).reshape(128, 128, 64)
    count = lambda k: (tiles_cls == k).sum(axis=2)  # noqa: E731
    c_road, c_sand, c_oil, c_fall = count(S_ROAD), count(S_SAND), count(S_OIL), count(S_FALL)
    surface = np.where(c_road + c_sand + c_oil >= 32, np.where(c_sand > c_road, S_SAND, S_ROAD), S_GRASS)
    surface = np.where(c_oil >= 16, S_OIL, surface)
    surface = np.where(c_fall >= 24, S_FALL, surface).astype(np.uint8)

    # lap progress per 16x16 cell: the nearest centre line sample, main road or shortcut
    prog = np.full((64, 64), OFF, np.uint8)
    cy, cx = np.mgrid[0:64, 0:64]
    px, py = cx * 16 + 8, cy * 16 + 8
    mf, mn = main_f[py, px], main_n[py, px]
    best = np.where(mf <= MARGIN, fine[np.maximum(mn, 0)], OFF)
    if sc_f is not None:
        sf, sn = sc_f[py, px], sc_n[py, px]
        use = (sf <= MARGIN) & (sf < mf)
        best = np.where(use, sc_fine[np.maximum(sn, 0)], best)
    prog[:] = best
    if t.get("arena"):
        prog[:] = OFF  # no laps in the arena

    if t.get("arena"):
        steer, lifted, widest = np.zeros((64, 64), np.uint8), 0, 0.0  # battles have no computer karts
    else:
        py_, px_ = np.mgrid[0:64, 0:64]
        steer, lifted, widest = steer_map(t, route, main_f[py_ * 16 + 8, px_ * 16 + 8])
        off = dodge_offsets(t, route)
        for i in np.where(np.abs(off) > 8)[0]:   # the dodged line must run over plain road, or it dodges into something worse
            ddx, ddy = xs[(i + 1) % len(xs)] - xs[i - 1], ys[(i + 1) % len(xs)] - ys[i - 1]
            q = np.hypot(ddx, ddy)
            x, y = int(xs[i] - ddy / q * off[i]), int(ys[i] + ddx / q * off[i])
            if cls[y, x] != S_ROAD:
                sys.exit(f"{t['name']}: the dodged aim point at ({x}, {y}) is not on plain road")

    flat_road = (img == np.where(speck, SPECK, ROAD)) & (cls == S_ROAD)
    used = set()

    def plain_cell(c):
        cx, cy = c
        return 0 <= cx < 64 and 0 <= cy < 64 and c not in used and flat_road[cy * 16:cy * 16 + 16, cx * 16:cx * 16 + 16].all()

    def cell_of(frac, lat):
        """The plain-road cell nearest to the point `frac` round the road and `lat` px to its right,
        on the same side of the centre line: coins and panels need a cell of plain road."""
        for df in (0, 0.004, -0.004, 0.008, -0.008, 0.012, -0.012):
            for dl in (0, -4, 4, -8, 8, -12):
                l = lat + (dl if lat >= 0 else -dl)
                if lat * l < 0:
                    continue
                x, y, _, _ = point_at(route, frac + df, l)
                c = (int(x // 16), int(y // 16))
                if plain_cell(c):
                    used.add(c)
                    return c
        sys.exit(f"{t['name']}: no plain road cell near {frac} round the track, {lat} px to the right")

    def as_cells(spec):
        out = []
        for c in spec:
            out.append(c if isinstance(c[0], int) else cell_of(*c))
            used.add(out[-1])
        return out

    coins = as_cells(t["coins"])
    panels = as_cells(t["panels"])
    pads = []
    for p in t["pads"]:
        if isinstance(p[0], tuple):
            pads.append(p)
        else:
            c = cell_of(*p)
            x, y, dx, dy = point_at(route, p[0])
            pads.append((c, axis(dx, dy)))

    # rescue points: the middle of each checkpoint on the main road, facing along it; one that lies on the
    # run-up to a ramp, on it or just past the gap it jumps is moved back to RUNUP px before the ramp, so
    # a rescued kart gets up to speed and has to jump again; then back onto plain road (no pad, sand or oil)
    pad_cells = {c for c, _ in pads}
    hazards = [((frac * L - 16) % L, 16 + 8 + gap + 60) for frac, gap in t.get("ramps", [])]
    rescue = []
    for k in range(NCP if not t.get("arena") else 0):
        sr = (k + 0.5) / NCP * L
        for s0, span in hazards:
            if (sr - (s0 - RUNUP)) % L < RUNUP + span:
                sr = (s0 - RUNUP) % L
        for _ in range(64):
            x, y, dx, dy = point_at(route, sr / L)
            if flat_road[int(y), int(x)] and (int(x) // 16, int(y) // 16) not in pad_cells:
                break
            sr = (sr - 4) % L
        else:
            sys.exit(f"{t['name']}: no plain road for checkpoint {k}'s rescue point")
        rescue.append((int(round(x)), int(round(y)), heading(dx, dy)))
    if t.get("arena"):
        rescue = [t["rescue"]] * NCP
    sx, sy, sdx, sdy = point_at(route, 0.0)   # the start line and the race direction there
    n = (-sdy, sdx)  # right of the race direction
    # six places: the two players side by side 20 px before the line, then the computer karts in two more rows
    # (karts 2 and 3, then 4 and 5) 44 and 62 px before it
    if t.get("oval"):
        grid = [(536, 228), (536, 252), (560, 258), (560, 222), (578, 240), (578, 222)]  # the computer karts: the left one first, as on the other tracks, none in a player's line
    elif t.get("arena"):
        grid = list(t["grid"]) + [(488, 740), (536, 740), (488, 780), (536, 780)]  # unused: battles have no computer karts
    else:
        grid = [(int(round(sx - back * sdx + side * n[0])), int(round(sy - back * sdy + side * n[1])))
                for back, sides in zip(GRID_BACK, GRID_SIDES) for side in sides]
    if not t.get("arena"):
        for k, (gx, gy) in enumerate(grid):
            if surface[gy // 8, gx // 8] != S_ROAD or not flat_road[gy - 4:gy + 5, gx - 4:gx + 5].all():
                sys.exit(f"{t['name']}: grid place {k} at ({gx}, {gy}) is not on plain road")
            if (gx // 16, gy // 16) in used:
                sys.exit(f"{t['name']}: grid place {k} at ({gx}, {gy}) lies on a coin, panel or boost pad cell")
    obstacles = []
    for frac, frames in t.get("obstacles", []):
        ox, oy, odx, ody = point_at(route, frac)
        reachx = hw + 12
        x0, y0 = ox + ody * reachx, oy - odx * reachx       # left of the road, rolling to its right
        x1, y1 = ox - ody * reachx, oy + odx * reachx
        obstacles.append((x0, y0, x1, y1, frames))
    return {
        "img": img, "road": road, "surface": surface, "prog": prog, "route": route, "length": L,
        "coins": coins, "panels": panels, "pads": pads, "ramps": ramp_cells, "rescue": rescue, "grid": grid,
        "angle": heading(sdx, sdy), "angles": (t["angles"] + [0] * 4) if "angles" in t else [heading(sdx, sdy)] * 6, "arena": t.get("arena", False), "obstacles": obstacles, "falls": fall_bands,
        "shortcut": sc_pts, "fine": fine, "steer": steer, "steer_lift": lifted, "steer_widest": widest,
    }


def heading(dx, dy):
    """Kart angle for direction (dx, dy): forward is (sin a, -cos a), 128 steps a turn, in the high byte."""
    return (round(math.atan2(dx, -dy) / (2 * math.pi) * 128) % 128) << 8


def kart_types():
    """The (accel, top, turn) rows of main.c's kart_types, light, medium, heavy."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "game", "main.c")).read()
    block = src[src.index("const KartType kart_types[3]"):]
    rows = re.findall(r"\{(\d+), (\d+), (\d+)\}", block[:block.index("};")])
    return [tuple(int(v) for v in r) for r in rows]


def hold_radius():
    """The tightest circle (map px) any kart type can hold at its top speed on the road: speed (top / 16 px a frame)
    over its turn (turn / 256 steps of 2 pi / 128 radians a frame). The heavy kart's is the largest, about 93 px."""
    return max((top / 16) / (turn / 256 * 2 * math.pi / 128) for _, top, turn in kart_types())


def dodge_offsets(t, route):
    """Sideways offset (map px, to the right) of the steering map's aim point at each route sample: the track's "dodge"
    entries (where, sideways) hold the aim that far to one side for DODGE_FLAT px each way and ease back over DODGE_EASE,
    so the computer karts drive past oil and sand that lie on one side of the road."""
    xs, ys, s, L = route
    off = np.zeros(len(xs))
    for frac, lat in t.get("dodge", []):
        d = np.abs(((s - frac * L + L / 2) % L) - L / 2)
        w = np.clip(1 - (d - DODGE_FLAT) / DODGE_EASE, 0, 1)
        w = 0.5 - 0.5 * np.cos(np.pi * w)
        off = np.where(np.abs(w * lat) > np.abs(off), w * lat, off)
    return off


def steer_map(t, route, road_dist):
    """One byte per 16x16 floor cell (the index of the lap-progress map): bits 0-6 the heading (0-127, the game's angle
    units) from the cell's centre to the centre-line point AIM px beyond its nearest main-route sample, for every cell, road
    or not; bit 7 set where the route's tightest bend within LOOK px of that sample is under hold_radius(). The shortcut and
    the bay are never aimed at. Exits when a heading on the main road points against the race direction."""
    xs, ys, s, L = route
    n = len(xs)
    cy, cx = np.mgrid[0:64, 0:64]
    px, py = (cx * 16 + 8).reshape(-1), (cy * 16 + 8).reshape(-1)
    near = np.empty(len(px), int)
    for a in range(0, len(px), 512):
        d2 = (xs[None, :] - px[a:a + 512, None]) ** 2 + (ys[None, :] - py[a:a + 512, None]) ** 2
        near[a:a + 512] = np.argmin(d2, axis=1)
    j = (near + int(round(AIM / STEP))) % n
    dx, dy = xs[(j + 1) % n] - xs[j - 1], ys[(j + 1) % n] - ys[j - 1]
    side = dodge_offsets(t, route)[j] / np.maximum(np.hypot(dx, dy), 1e-9)
    tx, ty = xs[j] - dy * side - px, ys[j] + dx * side - py     # the aim point, moved sideways where the track says
    tdx, tdy = xs[(near + 1) % n] - xs[near - 1], ys[(near + 1) % n] - ys[near - 1]
    short = np.hypot(tx, ty) < 3          # standing on the target: follow the road itself
    tx, ty = np.where(short, tdx, tx), np.where(short, tdy, ty)
    head = np.round(np.arctan2(tx, -ty) / (2 * math.pi) * 128).astype(int) % 128
    # the radius of the bend at every sample, through the samples SMOOTH either side of it
    a, b = np.arange(n) - SMOOTH, np.arange(n) + SMOOTH
    ax, ay, bx, by = xs[a % n], ys[a % n], xs[b % n], ys[b % n]
    ab, ac, bc = np.hypot(ax - xs, ay - ys), np.hypot(bx - xs, by - ys), np.hypot(bx - ax, by - ay)
    area2 = np.abs((xs - ax) * (by - ay) - (ys - ay) * (bx - ax))      # twice the triangle's area
    radius = np.where(area2 > 1e-6, ab * ac * bc / (2 * np.maximum(area2, 1e-6)), 1e9)
    ahead = int(round(LOOK / STEP))
    tight = np.array([radius[i:i + ahead + 1].min() if i + ahead < n else min(radius[i:].min(), radius[:i + ahead + 1 - n].min())
                      for i in range(n)])
    lift = (tight[near] < hold_radius()).astype(int)
    out = (head | lift << 7).astype(np.uint8).reshape(64, 64)
    # on every road cell of the main route the heading must point along the race direction
    on_road = road_dist[cy, cx].reshape(-1) < 0
    hx, hy = np.sin(head * 2 * math.pi / 128), -np.cos(head * 2 * math.pi / 128)
    cosine = (hx * tdx + hy * tdy) / np.maximum(np.hypot(tdx, tdy), 1e-9)
    bad = np.where(on_road & (cosine <= 0))[0]
    if len(bad):
        sys.exit(f"{t['name']}: the steering map points against the race direction on road cells "
                 f"{[(int(px[k]) // 16, int(py[k]) // 16) for k in bad[:6]]}")
    return out, int(lift.sum()), float(np.degrees(np.arccos(np.clip(cosine[on_road], -1, 1))).max())


def checkpoint_at(d, k):
    """Where checkpoint k starts on the main road: (x, y, dx, dy) in map pixels."""
    return point_at(d["route"], k / NCP)


def palette(t):
    cols = list(BASE_PAL)
    for i, c in LOOKS[t["look"]].items():
        cols[i] = c
    return cols


def minimap(d):
    """32x32 picture: the centre line (2) with a dark outline (1), shortcut included; 0 is see-through."""
    m = np.zeros((32, 32), np.uint8)
    if d["arena"]:  # the arena's floor, filled
        m[d["road"].reshape(32, 32, 32, 32).mean(axis=(1, 3)) > 0.5] = 2
        pts = []
    else:
        xs, ys, _, _ = d["route"]
        pts = list(zip(xs, ys))
    if d["shortcut"] is not None:
        sx, sy, _, _ = resample(d["shortcut"], closed=False)
        pts += list(zip(sx, sy))
    for x, y in pts:
        m[min(31, int(y / 32)), min(31, int(x / 32))] = 2
    out = m.copy()
    for y in range(32):
        for x in range(32):
            if m[y, x] == 0 and any(0 <= y + j < 32 and 0 <= x + i < 32 and m[y + j, x + i] == 2
                                    for j in (-1, 0, 1) for i in (-1, 0, 1)):
                out[y, x] = 1
    return out


def preview(dirname):
    """A PNG of each track picture (half size) for a person to look at."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import retro_run as rr
    for i, t in enumerate(TRACKS):
        d = draw(t)
        pal = np.array(palette(t), np.uint8)
        rgb = pal[d["img"][::2, ::2]]
        for k in range(NCP):  # checkpoint starts as white dots
            x, y, _, _ = checkpoint_at(d, k)
            rgb[int(y) // 2 - 1:int(y) // 2 + 2, int(x) // 2 - 1:int(x) // 2 + 2] = (255, 255, 255)
        path = os.path.join(dirname, f"track{i}.png")
        rr.write_png(path, 512, 512, rgb.tobytes())
        print(path, f"length {d['length']:.0f} px")
        if not d["arena"]:  # the steering map: a line from each cell's centre along its heading, red where the kart lifts
            arrows = rgb.copy()
            for cy in range(64):
                for cx in range(64):
                    b = int(d["steer"][cy, cx])
                    a = (b & 127) * 2 * math.pi / 128
                    ox, oy = cx * 8 + 4, cy * 8 + 4
                    col = (255, 40, 40) if b & 128 else (255, 255, 255)
                    for k in range(0, 7):
                        x, y = int(round(ox + k * math.sin(a))), int(round(oy - k * math.cos(a)))
                        if 0 <= x < 512 and 0 <= y < 512:
                            arrows[y, x] = (255, 224, 0) if k >= 5 else col
            path = os.path.join(dirname, f"track{i}-steer.png")
            rr.write_png(path, 512, 512, arrows.tobytes())
            print(path, f"steering map: {d['steer_lift']} cells lift, widest road heading {d['steer_widest']:.0f} degrees off the race direction")


if __name__ == "__main__":
    preview(sys.argv[1] if len(sys.argv) > 1 else ".")
