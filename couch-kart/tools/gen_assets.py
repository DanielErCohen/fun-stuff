#!/usr/bin/env python3
"""Generates the game's data: the Mode 7 track (tiles, map, palette, surface
map), the sprites (karts and drivers from tools/characters.py, countdown and
HUD letters), the title and results screen letters, and the perspective tables.

All art is original and drawn here in code, so there is nothing to license.
Writes into game/res/. Run from anywhere: python3 tools/gen_assets.py
"""
import hashlib
import inspect
import math
import multiprocessing
import os
import pickle
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import characters  # noqa: E402
import tracks  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "game", "res")

# Screen split, shared with game/main.c (keep in step).
SKY_LINES = 24      # lines of sky at the top of each half
FLOOR_LINES = 88    # Mode 7 floor lines in each half (SKY_LINES + FLOOR_LINES = 112)
ANGLES = 128        # steering resolution: 128 steps per full turn
HC = 40.0           # camera height: map pixels per screen pixel = HC / lines below horizon
K0 = 6              # lines between the horizon and the first floor line
FOCAL = 128.0       # focal length in screen pixels (90 degree field of view)
W0 = 64             # matches the VOFS offsets in main.c write_hdma(): w = floor line + W0


def bgr555(r, g, b):
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


# ---------------------------------------------------------------- tracks
# Each track (tools/tracks.py) is drawn as a 1024x1024 picture and cut into Mode 7 tiles. Mode 7 holds
# 256 unique 8x8 tiles; curved road edges make more, so the rarest edge tiles are swapped for the
# nearest-looking kept one. Coins, panels and slime fill one 16x16-pixel cell of the map (2x2 tiles);
# the game keeps a byte per cell in RAM (64x64 cells), so a kart finds what it drives over with one read.
CELL_COIN, CELL_PANEL = 1, 2
FLOOR_SETS = ["road", "coin", "panel", "slime_road", "slime_grass", "slime_dark"]
OB_PALS = {  # the moving obstacle's 5 colours (entries 10-14 of sprite palette 2): outline, main, shade, stripe, highlight
    "desert": [(40, 24, 16), (176, 128, 72), (128, 88, 48), (96, 64, 32), (232, 200, 144)],
    "snow": [(48, 64, 104), (248, 248, 255), (176, 192, 228), (208, 220, 248), (255, 255, 255)],
}
OB_PAL_DEFAULT = [(24, 16, 32), (248, 72, 72), (184, 40, 56), (248, 248, 248), (255, 240, 200)]


def reduce_tiles(uniq, counts, rgb, keep, budget):
    """Picks at most `budget` of the unique tiles (always those in `keep`) and maps every tile to the
    nearest-looking pick: farthest-point picks weighted by use, then two rounds of medoids."""
    vec = rgb[uniq].reshape(len(uniq), -1).astype(np.float32)
    weight = np.sqrt(counts.astype(np.float32))
    picks = list(dict.fromkeys(list(keep) + list(np.argsort(-counts)[:32])))
    mind = np.full(len(uniq), np.inf, np.float32)
    for c in picks:
        mind = np.minimum(mind, ((vec - vec[c]) ** 2).sum(1))
    while len(picks) < budget:
        c = int(np.argmax(mind * weight))
        if mind[c] == 0:
            break
        picks.append(c)
        mind = np.minimum(mind, ((vec - vec[c]) ** 2).sum(1))
    fixed = set(keep)
    for _ in range(2):
        cen = vec[picks]
        assign = np.array([int(np.argmin(((cen - v) ** 2).sum(1))) for v in vec])
        for k, c in enumerate(picks):
            if c in fixed:
                continue
            members = np.where(assign == k)[0]
            if len(members) > 1:
                d = ((vec[members][:, None, :] - vec[members][None, :, :]) ** 2).sum(2)
                picks[k] = int(members[np.argmin((d * counts[members][None, :]).sum(1))])
    cen = vec[picks]
    assign = np.array([int(np.argmin(((cen - v) ** 2).sum(1))) for v in vec])
    return picks, assign


def build_track(n):
    """Track n's tiles, map, palette, surface, starting cells, lap progress, and the facts main.c needs."""
    t = tracks.TRACKS[n]
    d = tracks.draw(t)
    pal_rgb = np.array(tracks.palette(t), np.uint8)
    rgb = np.zeros((256, 3), np.uint8)
    rgb[:len(pal_rgb)] = pal_rgb
    land = d["img"].reshape(128, 8, 128, 8).transpose(0, 2, 1, 3).reshape(16384, 64)
    uniq, inverse, counts = np.unique(land, axis=0, return_inverse=True, return_counts=True)
    inverse = inverse.reshape(-1)
    asphalt_tile = bytes(tracks.asphalt(x, y) for y in range(8) for x in range(8))
    grass, dark = bytes([tracks.GRASS] * 64), bytes([tracks.GRASS_DARK] * 64)
    arts = {"road": [[tracks.asphalt(x, y) for x in range(16)] for y in range(16)],
            "coin": tracks.coin_art(tracks.asphalt), "panel": tracks.panel_art(tracks.asphalt),
            "slime_road": tracks.slime_art(tracks.asphalt), "slime_grass": tracks.slime_art(tracks.plain(tracks.GRASS)),
            "slime_dark": tracks.slime_art(tracks.plain(tracks.GRASS_DARK))}
    for cell, dr in d["pads"]:
        arts[("pad", dr)] = tracks.pad_art(dr)
    for cell, dr in d["ramps"]:
        arts[("ramp", dr)] = tracks.ramp_art(dr)
    extra = list(dict.fromkeys(q for a in arts.values() for q in tracks.quarters(a)))
    extra.append(bytes([tracks.SKY_TILE] * 64))
    land_set = {bytes(u) for u in uniq}
    budget = 256 - sum(1 for q in extra if q not in land_set)
    keys = [bytes(u) for u in uniq]
    keep = [keys.index(k) for k in (grass, dark, asphalt_tile) if k in land_set]
    if len(uniq) > budget:
        picks, assign = reduce_tiles(uniq, counts, rgb, keep, budget)
    else:
        picks, assign = list(range(len(uniq))), np.arange(len(uniq))
    # tile 0 is plain grass: it also fills everything outside the map
    order = [keys.index(grass)] + [p for p in picks if keys[p] != grass]
    tiles = [keys[p] for p in order]
    index = {k: i for i, k in enumerate(tiles)}
    pos = {p: i for i, p in enumerate(order)}
    tmap = np.array([pos[picks[a]] for a in assign], np.int32)[inverse].astype(np.uint8)
    surface = d["surface"].reshape(-1).copy()

    def tile_ids(art):
        ids = []
        for q in tracks.quarters(art):
            if q not in index:
                index[q] = len(tiles)
                tiles.append(q)
            ids.append(index[q])
        return ids

    def at(cell, k):
        cx, cy = cell
        return (cy * 2 + (k >> 1)) * 128 + cx * 2 + (k & 1)

    def paint(cell, ids, surf=None):
        for k, tid in enumerate(ids):
            tmap[at(cell, k)] = tid
            if surf is not None:
                surface[at(cell, k)] = surf

    sets = {k: tile_ids(arts[k]) for k in FLOOR_SETS}
    road = sets["road"]
    name = t["name"]
    for cell in d["coins"] + d["panels"] + [c for c, _ in d["pads"]]:
        got = [int(tmap[at(cell, k)]) for k in range(4)]
        if got != road or any(surface[at(cell, k)] != tracks.S_ROAD for k in range(4)):
            sys.exit(f"{name}: floor cell {cell} is not plain road (tiles {got})")
    if len(set(d["coins"] + d["panels"])) != len(d["coins"]) + len(d["panels"]):
        sys.exit(f"{name}: two coins or panels share a cell")
    if {c for c, _ in d["ramps"]} & set(d["coins"] + d["panels"] + [c for c, _ in d["pads"]]):
        sys.exit(f"{name}: a coin, panel or pad lies on a ramp")
    for cell, dr in d["pads"]:
        paint(cell, tile_ids(arts[("pad", dr)]), tracks.S_PAD)
    for cell, dr in d["ramps"]:
        paint(cell, tile_ids(arts[("ramp", dr)]), tracks.S_RAMP)
    cells = bytearray(64 * 64)
    for c in d["coins"]:
        paint(c, sets["coin"])
        cells[c[1] * 64 + c[0]] = CELL_COIN
    for c in d["panels"]:
        paint(c, sets["panel"])
        cells[c[1] * 64 + c[0]] = CELL_PANEL
    if len(d["panels"]) != 4:
        sys.exit(f"{name}: {len(d['panels'])} panels; main.c expects 4")
    # the sky lines sample this tile; it is opaque, because snes9x2002 draws the backdrop colour wrong
    tmap[127 * 128 + 127] = tile_ids([[tracks.SKY_TILE] * 16 for _ in range(16)])[0]
    if surface[127 * 128 + 127] != tracks.S_GRASS:
        sys.exit(f"{name}: the sky tile's corner of the map is not off-road")
    if len(tiles) > 256:
        sys.exit(f"{name} uses {len(tiles)} unique tiles; Mode 7 allows 256")
    pal = bytearray(512)
    for i, c in enumerate(pal_rgb):
        struct.pack_into("<H", pal, i * 2, bgr555(*map(int, c)))
    sets["grass_dark"] = index[dark]
    mini = minimap_tiles(tracks.minimap(d))
    obpal = colour_bytes(OB_PALS.get(t["look"], OB_PAL_DEFAULT))
    files = {"pc7": b"".join(tiles), "mp7": bytes(tmap), "pal": bytes(pal), "surf": bytes(surface),
             "cells": bytes(cells), "prog": d["prog"].tobytes(), "mini": mini, "obpal": obpal}
    if not d["arena"]:
        files["steer"] = d["steer"].tobytes()   # the computer karts' steering map (battles have no computer karts)
    return files, sets, d, len(uniq)


def minimap_tiles(m):
    """The 32x32 minimap as 4 rows of 4 sprite tiles (each row 128 bytes, copied to its own place)."""
    rows = [[MINI_MAP[v] for v in row] for row in m.tolist()]
    return sheet_to_tiles(rows, 4, 4)



# ---------------------------------------------------------------- fonts
# 5x7 letters, original, shared by the race sprites and the title and results screens.
FONT = {
    "A": ".###.#...##...#######...##...##...#", "B": "####.#...##...#####.#...##...#####.",
    "C": ".###.#...##....#....#....#...#.###.", "D": "####.#...##...##...##...##...#####.",
    "E": "######....#....####.#....#....#####", "F": "######....#....####.#....#....#....",
    "G": ".###.#...##....#.####...##...#.####", "H": "#...##...##...#######...##...##...#",
    "I": ".###...#....#....#....#....#...###.", "J": "..###...#....#....#.#..#.#..#..##..",
    "K": "#...##..#.#.#..##...#.#..#..#.#...#", "L": "#....#....#....#....#....#....#####",
    "M": "#...###.###.#.##.#.##...##...##...#", "N": "#...###..##.#.##..###...##...##...#",
    "O": ".###.#...##...##...##...##...#.###.", "P": "####.#...##...#####.#....#....#....",
    "Q": ".###.#...##...##...##.#.##..#..##.#", "R": "####.#...##...#####.#.#..#..#.#...#",
    "S": ".###.#...##.....###.....##...#.###.", "T": "#####..#....#....#....#....#....#..",
    "U": "#...##...##...##...##...##...#.###.", "V": "#...##...##...##...##...#.#.#...#..",
    "W": "#...##...##...##.#.##.#.##.#.#.#.#.", "X": "#...##...#.#.#...#...#.#.#...##...#",
    "Y": "#...##...#.#.#...#....#....#....#..", "Z": "#####....#...#...#...#...#....#####",
    "0": ".###.#...##..###.#.###..##...#.###.", "1": "..#...##....#....#....#....#...###.",
    "2": ".###.#...#....#...#...#...#...#####", "3": "####.....#....#.###.....#....#####.",
    "4": "...#...##..#.#.#..#.#####...#....#.", "5": "######....####.....#....##...#.###.",
    "6": ".###.#....#....####.#...##...#.###.", "7": "#####....#...#...#...#....#....#...",
    "8": ".###.#...##...#.###.#...##...#.###.", "9": ".###.#...##...#.####....#....#.###.",
    "!": "..#....#....#....#....#.........#..", "-": "................###................",
    ".": "................................#..", ":": ".......#...................#.......",
    "/": "....#....#...#...#...#...#....#....", "'": "..#....#...........................",
    ">": "#.....#.....#.....#...#...#...#....",
    " ": "",
}


def glyph(ch):
    """7 rows of 5 booleans."""
    bits = FONT.get(ch, "").ljust(35, ".")
    return [[bits[r * 5 + c] == "#" for c in range(5)] for r in range(7)]


def draw_glyph(ch, scale, w, h, ox, oy, fill, shade, outline, thick=1):
    """A w x h cell of palette indices: the glyph scaled up, its lower half shaded, a dark outline around it."""
    cell = [[0] * w for _ in range(h)]
    g = glyph(ch)
    for r in range(7):
        for c in range(5):
            if g[r][c]:
                for dy in range(scale):
                    for dx in range(scale):
                        y = oy + r * scale + dy
                        cell[y][ox + c * scale + dx] = shade if r * scale + dy >= 4 * scale else fill
    solid = [[v != 0 for v in row] for row in cell]
    for y in range(h):
        for x in range(w):
            if not solid[y][x] and any(0 <= y + dy < h and 0 <= x + dx < w and solid[y + dy][x + dx]
                                       for dy in range(-thick, thick + 1) for dx in range(-thick, thick + 1)):
                cell[y][x] = outline
    return cell


# ---------------------------------------------------------------- sprites
# Sprite colours: 8 palettes of 16 from CGRAM 128. In a race, 0 and 1 are the two players'
# animals (each animal's own palette, loaded at race start), 2 to 4 are text in white, yellow
# and green (1 outline, 2 fill, 3 shade, 4 and 5 the flag's black and white), 5 the items, and
# 6 and 7 the two computer animals' palettes (loaded at race start). The white text palette also
# holds the minimap's and the obstacle's colours in its unused entries 6 to 14 (MINI_FIRST, OB_FIRST),
# so that every sprite in a race but the karts shares palette 2.
MINI_FIRST, OB_FIRST = 6, 10
# The minimap's colours: outline, road, player 1's dot (blue), player 2's dot (red). The computer
# karts' dot is the text palette's white (entry 2).
MINI_COLOURS = [(16, 16, 40), (232, 232, 240), (96, 184, 255), (255, 112, 80)]
MINI_MAP = {0: 0, 1: MINI_FIRST, 2: MINI_FIRST + 1}  # minimap pixel value (tracks.minimap) to palette entry
OB_MAP = {i: OB_FIRST - 1 + i for i in range(6)}      # the obstacle's colours 1-5 to entries 10-14 (0 stays clear)
OB_MAP[0] = 0
BALLOON_MAP = {0: 0, 1: MINI_FIRST, 2: MINI_FIRST + 1, 3: MINI_FIRST + 2, 4: MINI_FIRST + 3}  # outline, highlight, blue, red


def text_pal(fill, shade, extra=()):
    return ([(0, 0, 0), (16, 16, 32), fill, shade, (24, 24, 24), (248, 248, 248)] + list(extra) + [(0, 0, 0)] * 16)[:16]


TEXT_PALS = [text_pal((248, 248, 248), (176, 184, 216), MINI_COLOURS + OB_PAL_DEFAULT), text_pal((255, 224, 64), (240, 128, 32)),
             text_pal((96, 232, 96), (32, 152, 56))]
# Sprite palette 5: the items, their effects and the coin counter.
ITEM_PAL = [(0, 0, 0), (24, 16, 32), (248, 128, 32), (200, 72, 16), (72, 200, 64), (32, 128, 40),
            (176, 104, 48), (112, 64, 32), (216, 176, 112), (120, 232, 88), (48, 152, 48),
            (248, 208, 48), (200, 136, 24), (248, 248, 248), (96, 200, 255), (255, 240, 120)]
CAST = characters.CHARACTERS

# Race sprite VRAM, 512 tiles in a sheet 16 tiles wide (main.c *_FRAME and GLYPH macros):
# - tiles 0-127 player 1's animal, 128-255 player 2's, each block 8 tile rows: near views 0-3
#   as 32x32 frames in rows 0-3, near view 4 at rows 4-7 columns 0-3, and 16x16 frames from
#   column 4 of rows 4-7, six per two rows: mid views 0-4, then far views 0-4;
# - tiles 256-511 shared: countdown 3, 2, 1, G in rows 16-19, O at rows 20-23 column 0, then
#   16x16 glyphs from column 4 of rows 20-23 (six per two rows) and all of rows 24-31 (eight).
#   Once GO has gone the countdown's tiles are free: the two computer animals' small frames go
#   into rows 16-17 (animal A) and 18-19 (animal B), see cpu_copies(); the "O" tiles (rows 20-23,
#   columns 0-3) stay free, reserved for the hit-the-leader shot's picture.
HUD_GLYPHS = "0123456789/LAPSTNDFIH"
SHARED_BIG = ["3", "2", "1", "G", "O"]
# Items, in the order of their numbers in main.c (1 boost, 2 shot, 3 peel, 4 coins), then the
# coin counter, the shot in flight at mid and far distance, drift sparks and the boost flame.
# The item pictures live in the ROM (items.pic, in the order of the item numbers) and each player's HUD
# picture is copied into a frame of its own ("hud0", "hud1") when it changes; only the shot's picture,
# also its near frame on the track, stays in the shared tiles.
ITEM_PICS = ["i_boost", "i_shot", "i_peel", "i_coins", "i_homing", "i_boost3", "i_shot3", "i_peel3", "i_shield",
             "i_star", "i_jump", "i_shrink", "i_steal", "i_fake", "i_leader"]  # main.c ITEM_* order from 1
ITEM_ART = ["hud0", "hud1", "i_shot", "gR"]  # gR: the R of "3RD", which HUD_GLYPHS lacks
EFFECT_ART = ["coin", "shot_mid", "shot_far", "spark0", "spark1", "flame0", "flame1"]
# Then the wrong-way sign, the moving obstacle at three sizes and the minimap's three dots (player 1,
# player 2, a computer kart). "_mini" marks
# the 2x2 small frames that make the 32x32 minimap, which each race copies from its track.
TRACK_ART = ["wrong_way", "_mini", "_mini", "ob_near", "ob_mid", "ob_far", "dot1", "dot2", "dot3", "_mini", "_mini"]
SHARED_SMALL = ["g" + c for c in HUD_GLYPHS] + ["flag"] + ITEM_ART + EFFECT_ART + TRACK_ART


def colour_bytes(cols):
    """Colours as the 15-bit words of CGRAM, without padding to a palette."""
    return b"".join(struct.pack("<H", bgr555(*c)) for c in cols)



def block_big(i):
    """(x, y) in pixels of 32x32 frame i in a block: four in the first band, then one."""
    return ((i % 4) * 32, 0) if i < 4 else (0, 32)


def block_small(k, rows):
    """(x, y) in pixels of 16x16 frame k after the 32x32 ones: six per two rows next to the
    big frame at column 0, then eight per two rows once `rows` of those bands are used."""
    if k < 6 * rows:
        return 32 + (k % 6) * 16, 32 + (k // 6) * 16
    k -= 6 * rows
    return (k % 8) * 16, 32 + rows * 16 + (k // 8) * 16


def flag():
    cell = [[0] * 16 for _ in range(16)]
    for y in range(1, 16):
        cell[y][2] = 1
        cell[y][3] = 1
    for y in range(1, 10):
        for x in range(4, 15):
            cell[y][x] = 4 if ((x - 4) // 3 + (y - 1) // 3) & 1 else 5
    for x in range(4, 15):
        cell[0][x] = 1
        cell[10][x] = 1
    for y in range(0, 11):
        cell[y][15] = 1
    return cell


def outlined(cell):
    """Adds the dark outline (colour 1) around the drawn pixels of a 16x16 cell."""
    solid = [[v != 0 for v in row] for row in cell]
    for y in range(16):
        for x in range(16):
            if not solid[y][x] and any(0 <= y + dy < 16 and 0 <= x + dx < 16 and solid[y + dy][x + dx]
                                       for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                cell[y][x] = 1
    return cell


def draw_art(fn):
    return outlined([[fn(x + 0.5, y + 0.5) for x in range(16)] for y in range(16)])


def inside(x, y, cx, cy, rx, ry):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1


def carrot(x, y):
    """A carrot pointing down-left, leaves at the top right: the boost."""
    ax, ay = 3.0, 13.0
    bx, by = 11.0, 5.0
    vx, vy = bx - ax, by - ay
    u = ((x - ax) * vx + (y - ay) * vy) / (vx * vx + vy * vy)
    d = ((x - ax) * vy - (y - ay) * vx) / math.hypot(vx, vy)
    if 0 <= u <= 1 and abs(d) <= 0.6 + 3.0 * u:
        return 3 if d > 0.8 or (int(u * 8) % 3 == 1 and abs(d) < 1) else 2
    if inside(x, y, 12.5, 2.5, 1.4, 2.2) or inside(x, y, 14.0, 4.5, 2.0, 1.2):
        return 5 if x > 13 else 4
    return 0


def acorn(scale):
    def fn(x, y):
        x, y = 8 + (x - 8) / scale, 8 + (y - 8) / scale
        if inside(x, y, 8, 10, 4.4, 4.8) and y > 6:
            return 7 if x > 10.2 else 6
        if inside(x, y, 8, 6.2, 5.4, 2.6):
            return 7 if (int(x) + int(y)) % 3 == 0 else 8
        if 7.4 <= x <= 8.8 and 1.6 <= y <= 4:
            return 7
        return 0
    return fn


def slime_icon(x, y):
    if inside(x, y, 8, 11, 6.2, 3.4) or inside(x, y, 6, 8, 2.6, 2.6) or inside(x, y, 10.5, 9, 2.2, 2.2):
        if inside(x, y, 6, 8, 1, 1) or inside(x, y, 11, 11, 0.9, 0.7):
            return 13
        return 10 if y > 12.6 else 9
    return 0


def coin_icon(cx, cy, r):
    def fn(x, y):
        if not inside(x, y, cx, cy, r, r):
            return 0
        if not inside(x, y, cx, cy, r - 1.2, r - 1.2):
            return 12
        return 15 if inside(x, y, cx - r / 3, cy - r / 3, r / 3, r / 3) else 11
    return fn


def two_coins(x, y):
    return coin_icon(6, 10, 4.6)(x, y) or coin_icon(10.5, 6, 4.6)(x, y)


def homing(x, y):
    """The shot with a blue cap and a white eye: it sees where the other kart is."""
    v = acorn(1.0)(x, y)
    if v in (7, 8) and y < 8.6:
        if inside(x, y, 9.6, 6.2, 1.3, 1.1):
            return 13
        return 14
    return v


def triple(fn):
    """Three small copies of an item picture."""
    def f(x, y):
        for ox, oy in ((4.3, 4.6), (11.7, 4.6), (8.0, 11.4)):
            v = fn(8 + (x - ox) * 2.1, 8 + (y - oy) * 2.1)
            if v:
                return v
        return 0
    return f


def shield(x, y):
    r = math.hypot(x - 8, y - 8)
    if 4.6 <= r <= 6.6:
        return 13 if inside(x, y, 5.4, 4.8, 2.0, 1.6) else 14
    return 0


def star(x, y):
    a = math.atan2(y - 8.6, x - 8) + math.pi / 2
    r = math.hypot(x - 8, y - 8.6)
    edge = 3.0 + 3.8 * abs(math.cos(a * 2.5)) ** 2.2
    if r <= edge:
        return 15 if inside(x, y, 6.6, 6.8, 1.6, 1.6) else (12 if r > edge - 1.1 else 11)
    return 0


def feather(x, y):
    """A white feather leaning right: the jump."""
    u, v = (x - 8) * 0.8 + (y - 8) * 0.6, -(x - 8) * 0.6 + (y - 8) * 0.8
    if abs(v) <= 0.5 and -6.5 <= u <= 6.5:
        return 6
    if inside(u, v, -0.5, 0, 6, 2.8) and u > -5:
        return 14 if v > 0 else 13
    return 0


def bolt(x, y):
    """A yellow lightning bolt: the shrink."""
    pts = [(10.5, 1.0), (4.0, 9.0), (7.8, 9.0), (5.5, 15.0), (12.0, 6.6), (8.2, 6.6), (10.5, 1.0)]
    inside_poly = False
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside_poly = not inside_poly
    return 11 if inside_poly else 0


def magnet(x, y):
    """A horseshoe magnet: the steal."""
    r = math.hypot(x - 8, y - 7)
    if y <= 7 and 2.6 <= r <= 6.2:
        return 2
    if 7 < y <= 14 and (1.8 <= x <= 5.4 or 10.6 <= x <= 14.2):
        return 13 if y > 11 else 2
    return 0


def comet(scale):
    """The hit-the-leader shot: a glowing comet, a white core in a pale ring with a blue rim and a tail of blue
    and yellow streaming up and to the left."""
    def fn(x, y):
        x, y = 8 + (x - 8) / scale, 8 + (y - 8) / scale
        hx, hy = 10.4, 9.8
        r = math.hypot(x - hx, y - hy)
        if r <= 3.4:
            return 13 if r <= 1.5 else (15 if r <= 2.5 else 14)
        ux, uy = -0.74, -0.67
        t = (x - hx) * ux + (y - hy) * uy
        d = abs(-(x - hx) * uy + (y - hy) * ux)
        if 2.0 <= t <= 11.5 and d <= 2.8 * (1 - t / 12.5):
            if d < 0.8:
                return 15
            return 14 if t < 6.5 else 11
        return 0
    return fn


def fake_panel(x, y):
    """An item panel with a crooked mark: the fake panel."""
    if not (2 <= x <= 14 and 3 <= y <= 13):
        return 0
    if 2.8 <= x <= 13.2 and 3.8 <= y <= 12.2:
        r = math.hypot(x - 8, y - 6.8)
        if (y <= 7.4 and 1.4 <= r <= 3.2 and x > 6) or (7.0 <= x <= 9.0 and 8.0 <= y <= 9.8) or inside(x, y, 8, 11.2, 0.9, 0.8):
            return 3
        return 14
    return 6


def spark(diagonal):
    def fn(x, y):
        dx, dy = x - 8, y - 8
        if diagonal:
            dx, dy = (dx + dy) / 1.4, (dx - dy) / 1.4
        if abs(dx) + abs(dy) <= 1.6:
            return 13
        if (abs(dx) <= 0.8 and abs(dy) <= 5.5) or (abs(dy) <= 0.8 and abs(dx) <= 5.5):
            return 14
        return 0
    return fn


def flame(phase):
    def fn(x, y):
        w = 4.2 + (0.8 if phase else 0)
        if 3 <= y <= 14 and abs(x - 8) <= w * (y - 2) / 12 + (0.6 if phase and y > 9 else 0):
            return 15 if abs(x - 8) <= w * (y - 2) / 24 else 2
        return 0
    return fn


def wrong_way(x, y):
    """An orange sign with a white U-turn arrow."""
    if not inside(x, y, 8, 8, 7.2, 7.2):
        return 0
    r = math.hypot(x - 8, y - 8.5)
    if y <= 8.5 and 2.2 <= r <= 4.4:
        return 13
    if 9.6 <= x <= 12.4 and 8.5 <= y <= 12:
        return 13
    if 8.5 <= y <= 13.5 and abs(x - 4.7) <= 2.4 - (y - 8.5) * 0.48:
        return 13
    return 3 if not inside(x, y, 8, 8, 6, 6) else 2


def ball(r):
    """The rolling obstacle, sitting on row 15: its colours are the track's (snowball, tumbleweed, beach ball), see ART_REMAP."""
    cy = 15.5 - r

    def fn(x, y):
        if not inside(x, y, 8, cy, r, r):
            return 0
        if inside(x, y, 8 - r / 2.6, cy - r / 2.6, r / 4, r / 4):
            return 5
        if abs((x - 8) - (y - cy) * 0.6) < r / 4:
            return 4
        return 3 if (x - 8) + (y - cy) > r * 0.5 else 2
    return fn


def dot(colour):
    def fn(x, y):
        return colour if 6 <= x < 9 and 6 <= y < 9 else 0
    return fn


ITEM_DRAW = {"i_boost": carrot, "i_shot": acorn(1.0), "i_peel": slime_icon, "i_coins": two_coins,
             "i_homing": homing, "i_boost3": triple(carrot), "i_shot3": triple(acorn(1.0)), "i_peel3": triple(slime_icon),
             "i_shield": shield, "i_star": star, "i_jump": feather, "i_shrink": bolt, "i_steal": magnet, "i_fake": fake_panel,
             "i_leader": comet(1.0),
             "coin": coin_icon(8, 8, 5.5), "shot_mid": acorn(0.65), "shot_far": acorn(0.4),
             "spark0": spark(False), "spark1": spark(True), "flame0": flame(0), "flame1": flame(1),
             "wrong_way": wrong_way, "ob_near": ball(7), "ob_mid": ball(4.6), "ob_far": ball(2.8), "dot1": dot(3), "dot2": dot(4), "dot3": dot(2)}
# Drawn pictures that use the colours of sprite palette 2's entries 6-14: pixel value to palette entry
# (the outline draw_art adds is 1). The text palette's own entries (2 white) stay.
ART_REMAP = {"ob_near": OB_MAP, "ob_mid": OB_MAP, "ob_far": OB_MAP,
             "dot1": {1: MINI_FIRST, 3: MINI_FIRST + 2}, "dot2": {1: MINI_FIRST, 4: MINI_FIRST + 3}, "dot3": {1: MINI_FIRST}}


def _render_one(i):
    fr = characters.frames(CAST[i])
    return {k: [f.tolist() for f in v] if isinstance(v, list) else v.tolist() for k, v in fr.items()}


def _model_key(ch):
    """Changes when the model, its palette or the renderer changes."""
    shapes = [(s[0], s[3]) + tuple(np.asarray(a).round(5).tobytes() for a in s[1:3])
              + (repr(s[4]) if not isinstance(s[4], np.ndarray) else s[4].round(6).tobytes(),)
              for s in ch["model"]()]
    src = inspect.getsource(characters.render) + inspect.getsource(characters.frames) + inspect.getsource(characters.sdf)
    sizes = (characters.NEAR, characters.MID, characters.FAR, characters.BUST_SCALE, characters.BUST_HEAD,
             characters.BUST_ELEVATION, characters.ELEVATION, characters.SS, characters.MATERIALS, characters.KART_MATERIALS)
    return hashlib.sha1(pickle.dumps((shapes, src, sizes, ch.get("bust_view")))).hexdigest()


def character_frames():
    """[{near, mid, far: 5 views each, bust}] per animal. Rendering takes about 20 s an animal,
    so each animal is cached by its model's key and only changed ones render, in parallel."""
    cache = os.path.join(OUT, "characters.cache")
    stored = {}
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            stored = pickle.load(f)
        if not isinstance(stored, dict) or "per_model" not in stored:
            stored = {}
    per_model = stored.get("per_model", {})
    keys = [_model_key(ch) for ch in CAST]
    todo = [i for i, k in enumerate(keys) if k not in per_model]
    if todo:
        print(f"rendering {len(todo)} animals")
        with multiprocessing.Pool(min(len(todo), os.cpu_count() or 1)) as pool:
            for i, fr in zip(todo, pool.map(_render_one, todo)):
                per_model[keys[i]] = fr
        per_model = {k: per_model[k] for k in keys}
        with open(cache + ".tmp", "wb") as f:
            pickle.dump({"per_model": per_model}, f)
        os.replace(cache + ".tmp", cache)  # an interrupted run leaves no half-written cache
    return [per_model[k] for k in keys]


def snes_4bpp(pixels_8x8):
    out = bytearray(32)
    for y in range(8):
        for x in range(8):
            v = pixels_8x8[y][x]
            bit = 7 - x
            for p in range(4):
                if v >> p & 1:
                    off = y * 2 + (p & 1) + (16 if p >= 2 else 0)
                    out[off] |= 1 << bit
    return out


def sheet_to_tiles(sheet, tiles_wide, tiles_high):
    data = bytearray()
    for ty in range(tiles_high):
        for tx in range(tiles_wide):
            data += snes_4bpp([row[tx * 8:tx * 8 + 8] for row in sheet[ty * 8:ty * 8 + 8]])
    return bytes(data)


def paste(sheet, art, x, y):
    for j, row in enumerate(art):
        sheet[y + j][x:x + len(row)] = row


def pal_bytes(cols):
    out = bytearray(32)
    for i, c in enumerate(cols):
        struct.pack_into("<H", out, i * 2, bgr555(*c))
    return bytes(out)


def animal_block(fr):
    """One animal's 128 race tiles (4 KB), the block main.c copies to player 1's or player 2's place."""
    sheet = [[0] * 128 for _ in range(64)]
    for v in range(5):
        near = [list(row) for row in fr["near"][v]]
        near[31] = [0] * 32  # the own kart's frame ends on line 112 of its half: its last row would show in the other half
        paste(sheet, near, *block_big(v))
    for k in range(10):
        paste(sheet, fr["mid"][k] if k < 5 else fr["far"][k - 5], *block_small(k, 2))
    return sheet_to_tiles(sheet, 16, 8)


def shared_block():
    """The race's 256 shared tiles (8 KB): countdown and glyphs."""
    art = {}
    for d in "321GO":
        art[d] = draw_glyph(d, 4, 32, 32, 6, 1, 2, 3, 1, 2)
    for c in HUD_GLYPHS:
        art["g" + c] = draw_glyph(c, 2, 16, 16, 1, 1, 2, 3, 1)
    art["flag"] = flag()
    art["gR"] = draw_glyph("R", 2, 16, 16, 1, 1, 2, 3, 1)
    for name, fn in ITEM_DRAW.items():
        art[name] = draw_art(fn)
        if name in ART_REMAP:
            art[name] = [[ART_REMAP[name].get(v, v) for v in row] for row in art[name]]
    for name in ("_mini", "_free", "hud0", "hud1"):
        art[name] = [[0] * 16 for _ in range(16)]
    if len(SHARED_SMALL) > 12 + 32:
        sys.exit(f"shared sprite glyphs: {len(SHARED_SMALL)} of 44")
    sheet = [[0] * 128 for _ in range(128)]
    for i, name in enumerate(SHARED_BIG):
        paste(sheet, art[name], *block_big(i))
    for k, name in enumerate(SHARED_SMALL):
        paste(sheet, art[name], *block_small(k, 2))
    return sheet_to_tiles(sheet, 16, 16)


# Select screen sprites: the 18 portraits as 32x32 frames, four per band of 4 tile rows (tiles
# 0-319), then the cursor frames as 16x16 in rows 20-23: player 1 then player 2, each top and
# bottom half of its bracket, open then locked. Sprite palettes 0-5 hold the portraits, three
# animals each in cast order; palette 6 the cursors.
CURSOR_PAL = [(0, 0, 0), (16, 8, 24), (248, 248, 248), (96, 184, 255), (32, 96, 208), (255, 112, 80), (192, 40, 32)]
DIGITS_3X5 = {"1": ".#.##..#..#.###", "2": "##...#.#.#..###"}


def cursor_frame(player, locked, bottom):
    """Half a bracket: player 1's runs down the left edge of a portrait and opens to the right,
    player 2's mirrors it on the right edge. The top half carries the player's number, inside the
    portrait's corner. A locked pick has a thicker bracket and its number on a white box."""
    light, dark = (3, 4) if player == 0 else (5, 6)
    w, arm = (4, 3) if locked else (2, 2)
    cell = [[0] * 16 for _ in range(16)]
    arm_rows = range(15 - arm, 15) if bottom else range(1, 1 + arm)
    for y in (range(0, 15) if bottom else range(1, 16)):
        for x in range(2, 2 + w):
            cell[y][x] = dark if x == 1 + w and y not in arm_rows else light
    for y in arm_rows:
        for x in range(2, 14):
            cell[y][x] = light
    if player == 1:
        cell = [row[::-1] for row in cell]
    if not bottom:
        g = DIGITS_3X5["12"[player]]
        ox, oy = (9 if player == 0 else 4), 5
        if locked:
            for y in range(oy - 1, oy + 6):
                for x in range(ox - 1, ox + 4):
                    cell[y][x] = 2
        for r in range(5):
            for c in range(3):
                if g[r * 3 + c] == "#":
                    cell[oy + r][ox + c] = dark if locked else 2
    solid = [[v != 0 for v in row] for row in cell]
    for y in range(16):
        for x in range(16):
            if not solid[y][x] and any(0 <= y + dy < 16 and 0 <= x + dx < 16 and solid[y + dy][x + dx]
                                       for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                cell[y][x] = 1
    return cell


def item_pictures():
    """Each item's 16x16 HUD picture as 4 sprite tiles (top-left, top-right, bottom-left, bottom-right),
    128 bytes an item in item-number order from 1: main.c copies the top two and the bottom two tiles."""
    out = bytearray()
    for name in ITEM_PICS:
        art = draw_art(ITEM_DRAW[name])
        out += sheet_to_tiles(art, 2, 2)
    return bytes(out)


LEADER_FRAMES = ((0, 0, 1.0), (16, 0, 0.65), (0, 16, 0.4))  # near, mid and far comet: x, y in the 32x32 block, scale


def leader_picture():
    """The leader shot's three frames on the track (near, mid, far, like the shot's) as a 4 x 4 tile block, 512 bytes in
    four tile rows of 128: main.c copies them over the tiles of the countdown's "O" (rows 20-23, columns 0-3 of the
    shared sheet) once GO is gone."""
    sheet = [[0] * 32 for _ in range(32)]
    for x, y, scale in LEADER_FRAMES:
        paste(sheet, draw_art(comet(scale)), x, y)
    return sheet_to_tiles(sheet, 4, 4)


def leader_tile(i):
    """Sprite tile of the leader shot's frame i (0 near, 1 mid, 2 far): the "O" block's tiles."""
    x, y, _ = LEADER_FRAMES[i]
    return tile_of(*block_big(SHARED_BIG.index("O")), 256) + (y // 8) * 16 + x // 8


def balloons_art(n, colour):
    """n balloons on strings in a player's colour (white text palette 2: 3 player 1's blue, 4 player 2's red,
    remapped to entries 8 and 9 on the way out; outline and highlight are 6 and 7), as a finished 16x16 cell: the balloons are outlined, the strings are 1-pixel lines drawn after the outline."""
    spots = {1: [(8, 5)], 2: [(4.4, 5), (11.6, 5)], 3: [(2.9, 5.8), (8, 3.4), (13.1, 5.8)]}[n]  # a pixel of outline between
    r = {1: (3.2, 3.8), 2: (2.7, 3.3), 3: (2.1, 2.8)}[n]

    def fn(x, y):
        for cx, cy in spots:
            if inside(x, y, cx, cy, *r):
                return 2 if inside(x, y, cx - r[0] / 3, cy - r[1] / 3, 0.8, 0.8) else colour
        return 0
    cell = draw_art(fn)
    for cx, cy in spots:  # strings to the kart below
        top = cy + r[1] + 1.5
        for y in range(int(top), 16):
            t = (y + 0.5 - top) / (15.5 - top)
            x = int(cx + (8 - cx) * t)
            if 0 <= x < 16 and cell[y][x] == 0:
                cell[y][x] = 1
    return [[BALLOON_MAP[v] for v in row] for row in cell]


def battle_pictures():
    """A balloon battle's pictures, 128 bytes each like items.pic: player 1's 1, 2, 3 balloons, then
    player 2's; main.c copies them over the lap and banner letters, which a battle never shows."""
    out = bytearray()
    for colour in (3, 4):
        for n in (1, 2, 3):
            out += sheet_to_tiles(balloons_art(n, colour), 2, 2)
    return bytes(out)


def select_sprites(frames):
    """The select screen's 384 sprite tiles (12 KB) and its 7 sprite palettes."""
    sheet = [[0] * 128 for _ in range(192)]
    for i, (ch, fr) in enumerate(zip(CAST, frames)):
        paste(sheet, characters.portrait_indices(ch, i % 3, np.array(fr["bust"])).tolist(), (i % 4) * 32, (i // 4) * 32)
    for f in range(8):  # player, locked, bottom
        paste(sheet, cursor_frame(f >> 2, (f >> 1) & 1, f & 1), (f % 8) * 16, 160)
    pals = b"".join(pal_bytes(characters.portrait_palette(CAST[g * 3:g * 3 + 3])) for g in range(6))
    return sheet_to_tiles(sheet, 16, 24), pals + pal_bytes(CURSOR_PAL)


# ---------------------------------------------------------------- title and results screens
# Mode 1 background tiles: 0-63 small letters for ASCII 32-95 (white fill 2 on a dark
# shadow 1), then 16x16 big letters as 4 tiles each (top-left, top-right, bottom-left,
# bottom-right) in yellow 4 shaded to orange 5. Palette 1 swaps white for yellow. The
# background is colour 6, not the transparent 0, because snes9x2002 draws the backdrop wrong.
BIG_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ!-"
UI_BG = 6
UI_PAL = [(32, 24, 72), (16, 8, 24), (248, 248, 248), (160, 160, 200), (255, 224, 64), (240, 128, 32), (32, 24, 72),
          (232, 184, 40), (176, 128, 24), (200, 204, 216), (136, 140, 160), (205, 127, 50), (140, 84, 30)]
# After the big letters: the podium's gold block (tile 176), silver block (177) and bronze block (178), shaded at the bottom.
PODIUM_TILES = [(7, 8), (9, 10), (11, 12)]


def build_ui():
    tiles = bytearray()
    for code in range(32, 96):
        cell = [[0] * 8 for _ in range(8)]
        g = glyph(chr(code))
        for r in range(7):
            for c in range(5):
                if g[r][c]:
                    cell[r + 1][c + 2] = 1
        for r in range(7):
            for c in range(5):
                if g[r][c]:
                    cell[r][c + 1] = 2
        tiles += snes_4bpp([[v or UI_BG for v in row] for row in cell])
    for ch in BIG_LETTERS:
        cell = draw_glyph(ch, 2, 16, 16, 3, 1, 4, 5, 1)
        for ty in (0, 8):
            for tx in (0, 8):
                tiles += snes_4bpp([[v or UI_BG for v in row[tx:tx + 8]] for row in cell[ty:ty + 8]])
    if len(tiles) // 32 != 176:
        sys.exit("the podium tiles must follow the big letters at tile 176 (main.c podium_block)")
    for fill, shade in PODIUM_TILES:
        tiles += snes_4bpp([[shade if y == 7 else fill] * 8 for y in range(8)])
    pal = bytearray(64)
    for p in range(2):
        for i, c in enumerate(UI_PAL):
            if p == 1 and i == 2:
                c = UI_PAL[4]
            struct.pack_into("<H", pal, (p * 16 + i) * 2, bgr555(*c))
    return bytes(tiles), bytes(pal)


# ---------------------------------------------------------------- tables
def build_tables():
    """S[a][l] = s(l)*cos(a), T[a][l] = t(l)*cos(a), in 8.8 fixed point.

    For floor line l: s = HC/(l+K0) map pixels per screen pixel sideways,
    d = s*FOCAL the distance ahead, t = d/(l+W0). The game picks rows of these
    tables for the matrix: A=s*cos, B=t*sin, C=s*sin, D=-t*cos, with
    sin(a)=cos(a-90 deg) and -cos(a)=cos(a+180 deg), so no maths runs per frame.
    """
    S, T = bytearray(), bytearray()
    for a in range(ANGLES):
        c = math.cos(2 * math.pi * a / ANGLES)
        for l in range(FLOOR_LINES):
            s = HC / (l + K0)
            t = s * FOCAL / (l + W0)
            S += struct.pack("<h", round(256 * s * c))
            T += struct.pack("<h", round(256 * t * c))
    sin = struct.pack(f"<{ANGLES}h", *(round(256 * math.sin(2 * math.pi * a / ANGLES)) for a in range(ANGLES)))
    return bytes(S), bytes(T), sin


# ---------------------------------------------------------------- select screen background
# One picture drawn here: the heading, a panel in each animal's kart colour behind its portrait,
# the name and kart type under it in a small font, and the controls. main.c places the portrait
# sprites on the panels: panel i at x = SEL_X + 40 * (i % 6), y = SEL_Y + 56 * (i // 6).
SEL_X, SEL_Y = 8, 32
TINY = {
    "A": ".#.|#.#|###|#.#|#.#", "B": "##.|#.#|##.|#.#|##.", "C": ".##|#..|#..|#..|.##", "D": "##.|#.#|#.#|#.#|##.",
    "E": "###|#..|##.|#..|###", "F": "###|#..|##.|#..|#..", "G": ".##|#..|#.#|#.#|.##", "H": "#.#|#.#|###|#.#|#.#",
    "I": "#|#|#|#|#", "J": "..#|..#|..#|#.#|.#.", "K": "#.#|#.#|##.|#.#|#.#", "L": "#..|#..|#..|#..|###",
    "M": "#...#|##.##|#.#.#|#...#|#...#", "N": "#..#|##.#|#.##|#..#|#..#", "O": ".#.|#.#|#.#|#.#|.#.",
    "P": "##.|#.#|##.|#..|#..", "Q": ".#.|#.#|#.#|##.|.##", "R": "##.|#.#|##.|#.#|#.#", "S": ".##|#..|.#.|..#|##.",
    "T": "###|.#.|.#.|.#.|.#.", "U": "#.#|#.#|#.#|#.#|###", "V": "#.#|#.#|#.#|#.#|.#.",
    "W": "#...#|#...#|#.#.#|##.##|#...#", "X": "#.#|#.#|.#.|#.#|#.#", "Y": "#.#|#.#|.#.|.#.|.#.",
    "Z": "###|..#|.#.|#..|###", "-": "...|...|###|...|...", " ": "..|..|..|..|..", ":": ".|#|.|#|.",
}
UI_SHADOW, UI_WHITE, UI_GREY, UI_YELLOW, UI_ORANGE = (16, 8, 24), (248, 248, 248), (160, 160, 200), (255, 224, 64), (240, 128, 32)
UI_BG_RGB = (32, 24, 72)
TYPE_RGB = [(96, 232, 96), UI_YELLOW, UI_ORANGE]


def tiny_width(s):
    return sum(len(TINY[c].split("|")[0]) + 1 for c in s) - 1


def draw_tiny(img, s, cx, y, colour):
    """Small text centred on cx with a shadow one pixel down and right."""
    x = cx - tiny_width(s) // 2
    for c in s:
        rows = TINY[c].split("|")
        for r, row in enumerate(rows):
            for k, b in enumerate(row):
                if b == "#":
                    img[y + r + 1][x + k + 1] = img[y + r + 1][x + k + 1] if img[y + r + 1][x + k + 1] != UI_BG_RGB else UI_SHADOW
        for r, row in enumerate(rows):
            for k, b in enumerate(row):
                if b == "#":
                    img[y + r][x + k] = colour
        x += len(rows[0]) + 1


def draw_small(img, s, x, y, colour):
    """The 5x7 font, 6 pixels a letter, with a shadow."""
    for i, ch in enumerate(s):
        g = glyph(ch)
        for dy, dx, col in ((1, 1, UI_SHADOW), (0, 0, colour)):
            for r in range(7):
                for c in range(5):
                    if g[r][c]:
                        img[y + r + dy][x + i * 6 + c + dx] = col


def select_background():
    img = [[UI_BG_RGB] * 256 for _ in range(256)]
    head = "PICK AN ANIMAL"
    for i, ch in enumerate(head):
        cell = draw_glyph(ch, 2, 16, 16, 3, 1, 4, 5, 1)
        for y in range(16):
            for x in range(16):
                v = cell[y][x]
                if v:
                    img[6 + y][(256 - 16 * len(head)) // 2 + i * 16 + x] = {1: UI_SHADOW, 4: UI_YELLOW, 5: UI_ORANGE}[v]
    for i, ch in enumerate(CAST):
        x, y = SEL_X + 40 * (i % 6), SEL_Y + 56 * (i // 6)
        for yy in range(y - 1, y + 33):
            for xx in range(x - 1, x + 33):
                edge = yy in (y - 1, y + 32) or xx in (x - 1, x + 32)
                img[yy][xx] = UI_SHADOW if edge else ch["palette"][characters.KART_M]
        draw_tiny(img, ch["name"], x + 16, y + 35, UI_WHITE)
        draw_tiny(img, characters.TYPE_NAMES[ch["type"]], x + 16, y + 43, TYPE_RGB[ch["type"]])
    line = "MOVE: D-PAD  PICK: B OR START  UNDO: Y"
    draw_small(img, line, (256 - 6 * len(line)) // 2, 200, UI_WHITE)
    draw_small(img, "PLAYER 1", 40, 212, CURSOR_PAL[3])
    draw_small(img, "PLAYER 2", 256 - 40 - 48, 212, CURSOR_PAL[5])
    # palettes: 0 the text, 1-6 the panels of three animals each
    text = [(0, 0, 0), UI_SHADOW, UI_WHITE, UI_GREY, UI_YELLOW, UI_ORANGE, UI_BG_RGB, CURSOR_PAL[3], CURSOR_PAL[5],
            TYPE_RGB[0]]
    pals = [text] + [[(0, 0, 0), UI_SHADOW, UI_BG_RGB] + [ch["palette"][characters.KART_M] for ch in CAST[g * 3:g * 3 + 3]]
                     for g in range(6)]
    tiles, index, tmap = [], {}, bytearray(2048)
    for ty in range(32):
        for tx in range(32):
            block = [img[ty * 8 + j][tx * 8:tx * 8 + 8] for j in range(8)]
            used = {c for row in block for c in row}
            p = next((k for k, pal in enumerate(pals) if used <= set(pal)), None)
            if p is None:
                sys.exit(f"select screen tile ({tx},{ty}) mixes colours no palette holds: {used}")
            data = bytes(snes_4bpp([[pals[p].index(c) for c in row] for row in block]))
            if data not in index:
                index[data] = len(tiles)
                tiles.append(data)
            struct.pack_into("<H", tmap, (ty * 32 + tx) * 2, index[data] | p << 10)
    if len(tiles) > 384:
        sys.exit(f"select screen uses {len(tiles)} tiles; 384 fit below the map")
    return b"".join(tiles), bytes(tmap), b"".join(pal_bytes(p) for p in pals) + bytes(32 * (8 - len(pals))), len(tiles)


def cast_sources():
    """data.asm includes cast.asm (one ROM section per animal's race tiles), main.c includes cast.h."""
    asm = ["; generated by tools/gen_assets.py"]
    for i in range(len(CAST)):
        asm += [f'.section ".cast{i}" superfree', f"cast_gfx_{i}:", f'.incbin "res/cast_{i}.pic"', ".ends"]
    h = ["// generated by tools/gen_assets.py from tools/characters.py", f"#define CAST {len(CAST)}"]
    h += [f"extern char {', '.join(f'cast_gfx_{i}' for i in range(len(CAST)))};"]
    h += ["u8 *const cast_gfx[CAST] = {" + ", ".join(f"&cast_gfx_{i}" for i in range(len(CAST))) + "};"]
    h += ["const char *const cast_names[CAST] = {" + ", ".join(f'"{ch["name"]}"' for ch in CAST) + "};"]
    h += ["const u8 cast_type[CAST] = {" + ", ".join(str(ch["type"]) for ch in CAST) + "}; // 0 light, 1 medium, 2 heavy"]
    return "\n".join(asm) + "\n", "\n".join(h) + "\n"


def tile_of(x, y, base=0):
    """Sprite tile number of the frame whose top-left pixel is (x, y) in a 16-tile-wide sheet."""
    return base + (y // 8) * 16 + x // 8


def shared_tile(name):
    return tile_of(*block_small(SHARED_SMALL.index(name), 2), 256)


# A computer kart's animal needs only its mid views 0-4 and far views 0, 2 and 4 (views 1 and 3 show
# as 0 and 4 at far size): 8 small frames of its 4 KB block, copied once the countdown's tiles are
# free into one band of two tile rows of the shared tiles, animal A in rows 16-17 and B in rows 18-19.
CPU_FRAMES = [0, 1, 2, 3, 4, 5, 7, 9]   # block_small() indices: mid 0-4, far 0, far 2, far 4
CPU_FAR_VIEW = [5, 5, 6, 7, 7]          # far views 0-4 as indices into CPU_FRAMES
CPU_BASE = 256                           # first tile of animal A's band; B's is 32 tiles on


def cpu_tile(a, i):
    """Shared tile number of the top-left tile of computer animal a's frame i (0-7 of CPU_FRAMES)."""
    return CPU_BASE + 32 * a + 2 * i


def cpu_copies():
    """The copies from an animal's block to its band, as (source tile, destination tile within the band,
    tiles) in runs of whole tile rows, each frame's top row then bottom row, merged where they touch."""
    runs = []
    for row in (0, 1):
        for i, k in enumerate(CPU_FRAMES):
            src = tile_of(*block_small(k, 2)) + 16 * row
            dst = 2 * i + 16 * row
            if runs and runs[-1][0] + runs[-1][2] == src and runs[-1][1] + runs[-1][2] == dst:
                runs[-1][2] += 2
            else:
                runs.append([src, dst, 2])
    return runs


def layout_source():
    """Race sprite tile numbers and floor tile sets for main.c, from the same functions that place them."""
    near = [tile_of(*block_big(v)) for v in range(5)]
    small = [tile_of(*block_small(k, 2)) for k in range(10)]
    count = [tile_of(*block_big(i), 256) for i in range(5)]
    glyphs = [tile_of(*block_small(k, 2), 256) for k in range(len(HUD_GLYPHS) + 1)]
    h = ["// generated by tools/gen_assets.py: race sprite tiles (each player's animal block, then the shared tiles)",
         "#define PLAYER_BLOCK(p) ((p) << 7)",
         "const u8 near_off[5] = {" + ", ".join(map(str, near)) + "};   // near views 0-4 in a block",
         "const u8 small_off[10] = {" + ", ".join(map(str, small)) + "}; // mid views 0-4, then far views 0-4",
         "const u16 count_tile[5] = {" + ", ".join(map(str, count)) + "}; // 3, 2, 1, G, O",
         "const u16 glyph_tile[%d] = {" % len(glyphs) + ", ".join(map(str, glyphs)) + "}; // \"%s\", then the flag" % HUD_GLYPHS,
         f"const u16 hud_tile[2] = {{{shared_tile('hud0')}, {shared_tile('hud1')}}}; // each player's HUD item picture, copied in",
         f"#define ITEM_PICS {len(ITEM_PICS)}",
         f"#define TILE_LEADER {leader_tile(0)} // the leader shot's picture: 4 rows of 4 tiles from here (the countdown's \"O\"), copied in after GO",
         ] + [f"#define TILE_{n.upper()} {shared_tile(n)}" for n in EFFECT_ART + ["wrong_way", "dot1", "dot2", "dot3", "gR"]] + [
         f"#define TILE_MINIMAP {minimap_tile()} // a 32x32 frame over four of the small ones, copied from the track",
         f"#define CPU_BASE {CPU_BASE} // computer animal a's 8 small frames: tiles CPU_BASE + 32 a, two rows of 16 (mid 0-4, far 0, 2, 4)"]
    runs = cpu_copies()
    if len(runs) > 8:
        sys.exit(f"{len(runs)} copies for a computer animal; main.c load_cpu_gfx has room for 8")
    h += [f"#define CPU_COPIES {len(runs)}",
          "const u16 cpu_src[CPU_COPIES] = {" + ", ".join(str(r[0] << 5) for r in runs) + "}; // byte offset in the animal's block",
          "const u16 cpu_dst[CPU_COPIES] = {" + ", ".join(str(r[1]) for r in runs) + "}; // tile in the band",
          "const u16 cpu_len[CPU_COPIES] = {" + ", ".join(str(r[2] << 5) for r in runs) + "}; // bytes"]
    return "\n".join(h) + "\n"


def minimap_tile():
    t = tile_of(*block_small(SHARED_SMALL.index("_mini"), 2), 256)
    # the four "_mini" frames must form one 32x32 block: k, k + 1 and the two 8 frames later
    want = sorted([t, t + 2, t + 32, t + 34])
    got = sorted(tile_of(*block_small(i, 2), 256) for i, n in enumerate(SHARED_SMALL) if n == "_mini")
    if got != want:
        sys.exit(f"minimap frames {got} do not form a 32x32 block at tile {t}")
    return t


def tracks_sources(built):
    """data.asm includes tracks.asm (each track's tiles, map and surface in sections of their own);
    main.c includes tracks.h (pointers to them, and each track's facts as flat tables)."""
    asm, h = ["; generated by tools/gen_assets.py from tools/tracks.py"], [
        "// generated by tools/gen_assets.py from tools/tracks.py", f"#define TRACKS {len(built)}",
        f"#define NCP {tracks.NCP} // checkpoints a lap: lap progress / 8"]
    names = []
    for n, (files, sets, d, _) in enumerate(built):
        asm += [f'.section ".trk{n}_tiles" superfree', f"trk{n}_tiles:", f'.incbin "res/trk{n}.pc7"', ".ends",
                f'.section ".trk{n}_map" superfree', f"trk{n}_map:", f'.incbin "res/trk{n}.mp7"', ".ends",
                f'.section ".trk{n}_surf" superfree', f"trk{n}_surf:", f'.incbin "res/trk{n}.surf"', ".ends",
                f'.section ".trk{n}_misc" superfree', f"trk{n}_pal:", f'.incbin "res/trk{n}.pal"',
                f"trk{n}_cells:", f'.incbin "res/trk{n}.cells"', f"trk{n}_prog:", f'.incbin "res/trk{n}.prog"',
                f"trk{n}_mini:", f'.incbin "res/trk{n}.mini"', f"trk{n}_obpal:", f'.incbin "res/trk{n}.obpal"'] + (
                [f"trk{n}_steer:", f'.incbin "res/trk{n}.steer"'] if "steer" in files else [f"trk{n}_steer:"]) + [".ends"]
        names += [f"trk{n}_{k}" for k in ("tiles", "map", "surf", "pal", "cells", "prog", "mini", "obpal", "steer")]
    h.append("extern char " + ", ".join(names) + ";")
    T = range(len(built))
    for k in ("tiles", "map", "surf", "pal", "cells", "prog", "mini", "obpal", "steer"):
        h.append(f"u8 *const trk_{k}[TRACKS] = {{" + ", ".join(f"&trk{n}_{k}" for n in T) + "};")
    h.append("const u16 trk_tiles_size[TRACKS] = {" + ", ".join(str(len(b[0]["pc7"])) for b in built) + "};")
    h.append("const char *const trk_names[TRACKS] = {" + ", ".join(f'"{tracks.TRACKS[n]["name"]}"' for n in T) + "};")
    h.append("// per track, flat so they stay in the ROM: the 4 map tiles of each floor cell picture (road, coin,")
    h.append("// panel, slime on road, light and dark off-road), the plain dark off-road tile, the 4 panel cells")
    h.append("const u8 trk_floor[TRACKS * 24] = {" + ", ".join(str(v) for b in built for f in FLOOR_SETS for v in b[1][f]) + "};")
    h.append("const u8 trk_grass_dark[TRACKS] = {" + ", ".join(str(b[1]["grass_dark"]) for b in built) + "};")
    h.append("const u16 trk_panels[TRACKS * 4] = {" + ", ".join(str(y * 64 + x) for b in built for x, y in b[2]["panels"]) + "};")
    if any(len(b[2]["coins"]) > 24 for b in built):
        sys.exit("a track has more than 24 coins (main.c ARENA_COINS)")
    h.append("// each track's coin cells (a coin battle puts taken coins back), up to 24, then how many")
    h.append("const u16 trk_coins[TRACKS * 24] = {" + ", ".join(str(y * 64 + x) for b in built for x, y in (b[2]["coins"] + [(0, 0)] * 24)[:24]) + "};")
    h.append("const u8 trk_ncoins[TRACKS] = {" + ", ".join(str(len(b[2]["coins"])) for b in built) + "};")
    h.append("// the start grid (x, y of the six karts: the two players, then the four computer karts, map pixels) and each kart's heading there")
    h.append("const s16 trk_grid[TRACKS * 12] = {" + ", ".join(str(v) for b in built for p in b[2]["grid"] for v in p) + "};")
    h.append("const u16 trk_angle[TRACKS * 6] = {" + ", ".join(str(a) for b in built for a in b[2]["angles"]) + "}; // each kart's")
    h.append("// where a rescued kart is put back: x, y (map pixels) and heading at the middle of each checkpoint")
    h.append("const s16 trk_rescue[TRACKS * NCP * 3] = {" + ", ".join(
        str(v - 65536 if v > 32767 else v) for b in built for r in b[2]["rescue"] for v in r) + "};")
    h.append("// moving obstacles (at most 2): start x, y and step per frame (1/16 px), and frames each way")
    obs = []
    for b in built:
        o = b[2]["obstacles"]
        if len(o) > 2:
            sys.exit("a track has more than 2 moving obstacles")
        for k in range(2):
            if k < len(o):
                x0, y0, x1, y1, frames = o[k]
                obs += [round(x0 * 16), round(y0 * 16), round((x1 - x0) * 16 / frames), round((y1 - y0) * 16 / frames), frames]
            else:
                obs += [0, 0, 0, 0, 0]
    h.append("const s16 trk_obstacles[TRACKS * 10] = {" + ", ".join(map(str, obs)) + "};")
    h.append("#define PANELS 4")
    h += [f"#define FLOOR_{f.upper()} {i}" for i, f in enumerate(FLOOR_SETS)]
    return "\n".join(asm) + "\n", "\n".join(h) + "\n"


# Projection of things on the track (game/proj.asm): indexed by f = distance ahead / 2, in map pixels.
NEAR_FWD, MID_FWD = 84, 150   # nearer than 84 px the 32x32 frame, nearer than 150 the mid frame


def proj_tables():
    """Per f = distance ahead / 2 (words): the ground line in the half, with the size class times 16
    (0 near, 16 mid, 32 far: the frame record's offset) in the high byte. Then per sideways offset
    on screen in pixels (bytes): its bearing in table steps."""
    sl, bear = bytearray(512), bytearray(256)
    for f in range(256):
        fwd = 2 * f + 1
        size = 0 if 2 * f < NEAR_FWD else 1 if 2 * f < MID_FWD else 2  # nearer than 56 px is hidden first
        struct.pack_into("<BB", sl, 2 * f, min(255, 18 + 5120 // fwd), size * 16)
        bear[f] = round(math.atan(f / FOCAL) * ANGLES / (2 * math.pi))
    return bytes(sl + bear)


def cam_tables():
    """Per steering angle (words): D0 * sin / 256 as C truncates it (the camera sits D0 map pixels behind
    the kart) and the angle's row offset in the perspective tables, for camera() in game/proj.asm; then
    24 * sin / 256, for drop_peel() in main.c (slime drops 24 px behind)."""
    D0, ROW_BYTES = 57, FLOOR_LINES * 2
    sin = [round(256 * math.sin(2 * math.pi * a / ANGLES)) for a in range(ANGLES)]
    return (struct.pack(f"<{ANGLES}h", *(int(D0 * v / 256) for v in sin)) + struct.pack(f"<{ANGLES}H", *(a * ROW_BYTES for a in range(ANGLES)))
            + struct.pack(f"<{ANGLES}h", *(int(24 * v / 256) for v in sin)))  # then 24 * sin / 256: where slime drops


def step_table():
    """The distance a kart moves in one frame along each axis, in 1/256 px: row a (a heading, 128 rows of 128 bytes), column
    v (a speed in 1/16 px a frame, 0 to 63: the most any kart reaches is 62) holds round(256 sin a) * v as a signed 16-bit
    word, so proj.asm mk_move reads sin x speed from the table (the x axis; the y axis reads the row a quarter turn on)
    instead of multiplying."""
    sin = [round(256 * math.sin(2 * math.pi * a / ANGLES)) for a in range(ANGLES)]
    return b"".join(struct.pack("<h", sin[a] * v) for a in range(ANGLES) for v in range(64))


def obj_frames():
    """For each kind of moving thing (player 1's kart, player 2's kart, a shot, an obstacle, then four computer karts:
    animal A in palette 6, B in 7, A in 7, B in 6) and size (near, mid, far):
    box, ground row, large flag, attribute base (palette), whether it mirrors, a spare byte, and the
    tile of each of the 5 views."""
    out = bytearray()
    contact = (27, 13, 12)  # tools/characters.py NEAR, MID, FAR ground rows (main.c *_CONTACT)
    for kind in range(9):
        for sz in range(3):
            if kind == 8:  # the leader shot: the comet in the tiles the countdown's "O" frees
                tiles = [leader_tile(sz)] * 5
                rec = [16, (14, 12, 10)[sz], 0, 0x30 | (5 << 1), 0, 0]
            elif kind >= 4:  # computer karts: animal A or B in palette 6 or 7; the mid frames serve near and mid
                a, pal = ((0, 6), (1, 7), (0, 7), (1, 6))[kind - 4]
                tiles = [cpu_tile(a, v if sz < 2 else CPU_FAR_VIEW[v]) for v in range(5)]
                rec = [16, contact[1 if sz < 2 else 2], 0, 0x30 | (pal << 1), 0x40, 0]
            elif kind == 3:
                tiles = [shared_tile(("ob_near", "ob_mid", "ob_far")[sz])] * 5
                rec = [16, 15, 0, 0x30 | (2 << 1), 0, 0]
            elif kind < 2:
                base = kind << 7
                tiles = [base + (tile_of(*block_big(v)) if sz == 0 else tile_of(*block_small(v + 5 * (sz - 1), 2)))
                         for v in range(5)]
                rec = [32 if sz == 0 else 16, contact[sz], 1 if sz == 0 else 0, 0x30 | (kind << 1), 0x40, 0]
            else:
                t = shared_tile(("i_shot", "shot_mid", "shot_far")[sz])
                tiles = [t] * 5
                rec = [16, (14, 12, 10)[sz], 0, 0x30 | (5 << 1), 0, 0]
            out += bytes(rec) + struct.pack("<5H", *tiles)
    return bytes(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    built = [build_track(n) for n in range(len(tracks.TRACKS))]
    S, T, sin = build_tables()
    frames = character_frames()
    ui, ui_pal = build_ui()
    sel_obj, sel_obj_pal = select_sprites(frames)
    sel_bg, sel_map, sel_pal, nsel = select_background()
    cast_asm, cast_h = cast_sources()
    files = {
        "proj.bin": proj_tables(), "obj_frames.bin": obj_frames(), "cam.bin": cam_tables(), "items.pic": item_pictures(), "battle.pic": battle_pictures(), "leader.pic": leader_picture(), "step.bin": step_table(),
        "shared.pic": shared_block(), "shared.pal": b"".join(pal_bytes(p) for p in TEXT_PALS + [ITEM_PAL]),
        "cast.pal": b"".join(pal_bytes(ch["palette"]) for ch in CAST),
        "select_obj.pic": sel_obj, "select_obj.pal": sel_obj_pal,
        "select_bg.pic": sel_bg, "select_bg.map": sel_map, "select_bg.pal": sel_pal,
        "ui.pic": ui, "ui.pal": ui_pal, "persp_s.bin": S, "persp_t.bin": T, "sin.bin": sin,
        "cast.asm": cast_asm.encode(), "cast.h": cast_h.encode(), "layout.h": layout_source().encode(),
    }
    tasm, th = tracks_sources(built)
    files["tracks.asm"], files["tracks.h"] = tasm.encode(), th.encode()
    files["layout.inc"] = ("; generated by tools/gen_assets.py: sprite tiles game/proj.asm draws\n"
                           + "".join(f".DEFINE TILE_{n.upper()} {shared_tile(n)}\n" for n in ("dot1", "dot2", "dot3"))
                           + "".join(f".DEFINE GLYPH_{i} {tile_of(*block_small(i, 2), 256)}\n" for i in range(len(HUD_GLYPHS) + 1))).encode()
    for n, (tf, _, _, _) in enumerate(built):
        for ext, data in tf.items():
            files[f"trk{n}.{ext}"] = data
    for i, fr in enumerate(frames):
        files[f"cast_{i}.pic"] = animal_block(fr)
    for name, data in files.items():
        path = os.path.join(OUT, name)
        if os.path.exists(path) and open(path, "rb").read() == data:
            continue  # unchanged files keep their time, so make rebuilds only what changed
        with open(path, "wb") as f:
            f.write(data)
    ntiles = "/".join(f"{len(b[0]['pc7']) // 64} (of {b[3]})" for b in built)
    print(f"assets: track tiles {ntiles}, {len(CAST)} animals, select screen {nsel} tiles, tables {len(S)}+{len(T)} bytes")


if __name__ == "__main__":
    main()
