#!/usr/bin/env python3
"""ROM tests: plays game/couchkart.sfc headless on several SNES emulators and
fails when a frame is dropped, the logic needs too much of the frame, the
picture differs from the reference renderer, or the race rules break.

Eight races per emulator, through the real menus:
0. Title (showing the otter and the T-Rex), Start on player 2's pad, then the
   select screen: player 1 picks the frog (a light kart); player 2 tries the
   frog too and is refused, then picks the triceratops (heavy). The track menu
   follows: the cursor wraps, and B picks the Clover Oval for a single race. The
   race must load both animals' tiles and colours and the track, and the HUD
   shows each player's animal.
1. Countdown, both drive (the picture checks),
   then collisions, grass, the map edge and the other kart's sprite are set up
   by writing work RAM. Player 1 then laps by being moved over each of the 32
   checkpoints in turn, including a skipped checkpoint and a cut off the track
   that must not count; the last lap shows the final-lap banner once. Before
   that: the minimap, the wrong-way sign, and the things on the track: the
   cost of projecting both karts and 4 shots, coins, item panels and their
   draws by place, the boost, the shot (flight, bounce, hit and spin), slime,
   a boost pad, and the hop and drift. The finish has the other kart and 4
   shots in view, the busiest frame. Player 2 never finishes, so the results
   screen comes 10 seconds after player 1 does.
2. Start on the results screen gives a rematch with the same animals and the
   coins and panels back: player 1 makes a rocket start and player 2, pressing
   too early, spins its wheels; player 2 laps first, then player 1 crosses the
   line, so the results come once both have finished. Select returns to the select screen,
   with each cursor on its last pick.
3. Player 2 picks, undoes it with Y, then both press B on the red panda on the
   same frame (player 1 gets it and player 2's cursor flashes); player 1 undoes
   a pick during the wait before the race. Then player 1 races the red panda
   (medium), player 2 the triceratops again; the race loads them. Kart types are measured in races 1 and 3: from a standing start
   on the top straight, frames to top speed, the top speed and the turn per
   frame, which must follow light, medium, heavy in order and match the table.
   Race 3 is the first of a cup (chosen in the track menu): four races, one on
   each track, with each track's own checks (its data loaded, the picture,
   skipped checkpoints and cuts, its features: oil, sand and an obstacle on the
   Sandy Twist; the ramp, its trick and the crevasse rescue and obstacles on the
   Frosty Peaks; the bay rescue and laps through the shortcut on the Moon
   Harbour) and its busiest frame (both karts, 4 shots and 2 obstacles in view
   as a kart finishes). The winners alternate and two races end with the loser
   not finishing, so the points tie and the last race's winner takes the cup;
   the podium follows. Last, Select and a single race on the Moon Harbour.

Last, after the battles, a race on the Clover Oval with computer karts (cpu_race_checks): their six grid places on every
track, hidden until their frames are loaded, drawn in both halves with the right picture, palette and view, hit by a shot, an
obstacle and a star kart, bumped, ranked 1 to 6 with the HUD reading 1ST to 6TH, aimed at by items, finishing (a computer kart
first, then the players, and a timeout with only a computer kart home), the busiest frame with 0 to 4 of them in view (in their
costly states: on the grass, spinning, boosting), the third odds table for places 3 to 6, the leader shot (it flies over grass and
water to the kart in first place, a shield blocks it, a star ignores it, a kart in the air is hit on landing, a holder in first
sends it to second, its own picture and HUD picture), and each computer kart's item decisions kind by kind (the effect lands on a
player, the HUDs are never written, the gate holds a decision back on a busy frame); in the full races on each track every
computer kart uses at least one item.

snes9x2002 and snes9x2005 are the old, fast emulators cheap game sticks ship;
snes9x is the current one. Run: python3 tools/test_rom.py [--shots DIR]
"""
import argparse
import ctypes as C
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import characters  # noqa: E402
import gen_assets  # noqa: E402
import tracks  # noqa: E402
import m7_model  # noqa: E402
import retro_run as rr  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM = os.path.join(ROOT, "game", "couchkart.sfc")
SYM = os.path.join(ROOT, "game", "couchkart.sym")
CORES = ["snes9x2002", "snes9x2005", "snes9x"]
MAX_LINES = 180      # logic budget: lines of the 262 per frame, counted from vblank
VBLANK_LINES = 37    # max_lines reads this when the line counter never latched: "not measured"
KART_LINE = 108      # screen line in each half where the own kart's wheels touch the floor (main.c)
MATCH = 0.96         # share of floor pixels that must equal the reference renderer (measured 97-98%)
WEST = 96 << 8       # the grid faces west
GRID = ((536, 228), (536, 252))
COUNTDOWN = 180      # frames of 3, 2, 1 before GO
AFTER_FIRST, AFTER_BOTH = 600, 90
GO_FRAMES = 60       # how long GO shows (main.c)
MAX_GRASS, EDGE_SPEED, BUMP = 16, 3, 10
# What each stretch of the busiest frame is: the ROM's probe() stores the line counter at 20 points
# (main.c race_frame), so stretch k runs from probe k - 1 to probe k.
PHASES = ["vblank work (hdma, map, hud tiles)", "clock, timers", "items, tricks, drive (players)", "computer karts drive", "ground", "bump, keep on map",
          "camera", "floor things", "steer homing shots", "move shots", "obstacles, hits", "slipstream", "panels",
          "players' laps", "computer karts' laps", "places", "banners, own kart, fx", "minimap", "draw_objects", "battle clock, item decisions"]
ST_TITLE, ST_COUNTDOWN, ST_RACE, ST_RESULTS, ST_SELECT, ST_TRACKS, ST_PODIUM = 0, 1, 2, 3, 4, 5, 6
NCP = tracks.NCP     # checkpoints a lap
TRK = [tracks.draw(t) for t in tracks.TRACKS]  # each track's centre line, checkpoints and things, as built
MENU_ROWS = [9, 11, 13, 15, 17, 19, 21]  # the track menu: the cup, each track, the two battles (main.c menu_row)
CPU_ROW = 23         # the line under it, after a blank row: COMPUTER KARTS and their number, changed with left and right; a blank row, then two help lines
BALLOONS, COIN_TIME, COIN_BACK = 3, 3600, 120
BAL_SLOT = lambda h: 72 + 2 * h  # noqa: E731  in half h: the own kart's balloons, then the other kart's
BATTLE_PICS = gen_assets.battle_pictures()  # player 1's 1, 2, 3 balloons, then player 2's: 128 bytes each
TRACK_NAMES = [t["name"] for t in tracks.TRACKS[:4]]  # the race tracks; the arena is track 4
ARENA_NO = 4
# Race sprite tiles, from the functions gen_assets.py places the frames with (main.c reads res/layout.h)
T = gen_assets.tile_of
NEAR_TILE = lambda p, v: p * 128 + T(*gen_assets.block_big(v))  # noqa: E731
MID_TILE = lambda p, v: p * 128 + T(*gen_assets.block_small(v, 2))  # noqa: E731
FAR_TILE = lambda p, v: p * 128 + T(*gen_assets.block_small(5 + v, 2))  # noqa: E731
COUNT_TILE = {k: T(*gen_assets.block_big(i), 256) for i, k in enumerate((3, 2, 1, "G", "O"))}
GLYPH = lambda ch: T(*gen_assets.block_small(gen_assets.HUD_GLYPHS.index(ch), 2), 256)  # noqa: E731
BUST_TILE = lambda i: (i >> 2) * 64 + (i & 3) * 4  # noqa: E731  select screen portraits
CURSOR_TILE = lambda p, lock, bottom: 320 + p * 8 + lock * 4 + bottom * 2  # noqa: E731
HUD_SLOT = lambda p: 4 + p * 10  # noqa: E731
BANNER_SLOT = lambda p: 24 + p * 8  # noqa: E731
RESULTS_WAIT = 60    # frames the results screen ignores buttons
SELECT_WAIT = 20     # frames the select screen ignores buttons
START_WAIT = 40      # frames from the second pick to the race
SEL_X, SEL_Y = gen_assets.SEL_X, gen_assets.SEL_Y
UI_MAP = 0x5800      # Mode 1 map, VRAM words
CAST = characters.CHARACTERS
NAMES = [ch["name"] for ch in CAST]
LIGHT, MEDIUM, HEAVY = characters.LIGHT, characters.MEDIUM, characters.HEAVY
B, START, SELECT, LEFT, RIGHT, UP, DOWN = (rr.BUTTONS[k] for k in ("b", "start", "select", "left", "right", "up", "down"))
X, Y, L, R = (rr.BUTTONS[k] for k in ("x", "y", "l", "r"))
SLOTS = 94           # race sprite slots in use (main.c SLOTS)
OB_SLOTS = {0: (60, 61), 1: (62, 63)}  # the obstacles in each half (proj.asm)
DOT_SLOT = lambda k, half: 64 + k + 2 * half  # noqa: E731  kart k's minimap dot in a half
MINI_SLOT = lambda p: 92 + p  # noqa: E731
WRONG_SLOT = lambda p: 70 + p  # noqa: E731
MINI_X, MINI_Y = 8, 76
TILE_MINIMAP = gen_assets.minimap_tile()
TILE_DOT = [gen_assets.shared_tile("dot1"), gen_assets.shared_tile("dot2")]
TILE_DOT3 = gen_assets.shared_tile("dot3")  # a computer kart's minimap dot
TILE_R = gen_assets.shared_tile("gR")       # the R of "3RD"
# The colours the minimap, the balloons and the obstacle had when they had palettes of their own (sprite
# palettes 6 and 7); since sprite palette 2 holds them, the pictures must still show exactly these.
MINI_OUTLINE, MINI_ROAD, MINI_BLUE, MINI_RED = (16, 16, 40), (232, 232, 240), (96, 184, 255), (255, 112, 80)
PAL_WHITE = 2
CPU_SLOT = 100       # an OAM slot the game leaves hidden: the colour check draws computer-animal frames there
# Computer animal a's frames in the shared tiles: mid views 0-4 (two tiles wide each), then far views 0, 2, 4;
# animal A in tile rows 16-17 (tile 256), B in rows 18-19 (tile 288). The source is the 4 KB block of its animal.
CPU_FRAME_SRC = [gen_assets.block_small(v, 2) for v in range(5)] + [gen_assets.block_small(5 + v, 2) for v in (0, 2, 4)]
CPU_TILE = lambda a, i: 256 + 32 * a + 2 * i  # noqa: E731
TILE_WRONG = gen_assets.shared_tile("wrong_way")
OB_TILES = [gen_assets.shared_tile(n) for n in ("ob_near", "ob_mid", "ob_far")]
AIR_MIN, AIR_MAX, TRICK_FRAMES, TRICK_SPIN, FALL_FRAMES, OB_REACH = 8, 56, 40, 16, 60, 12
WRONG_STEPS, FINAL_FRAMES = 3, 90
CUP_POINTS = [3, 1]                 # a two-player cup: first, second when it finishes (main.c cup_points)
CUP_POINTS_CPU = [9, 6, 4, 3, 2]    # a cup with computer karts: places 1 to 5 for a kart that finished
PAL_GREEN = 4
S_FALL, S_RAMP = tracks.S_FALL, tracks.S_RAMP
ITEM_SLOT = lambda p: 48 + p * 4  # noqa: E731  the item picture, then the coin and its two digits
FX_SLOT = lambda p: 56 + p * 2  # noqa: E731     sparks or flame at the own kart
SHOT_SLOTS = {0: range(40, 44), 1: range(44, 48)}
# main.c rules for pickups, items and tricks
CELL_COIN, CELL_PANEL, CELL_PEEL, CELL_FAKE = 1, 2, 3, 4
BOOST, SHOT, PEEL, COINS = 1, 2, 3, 4
HOMING, BOOST3, SHOT3, PEEL3, SHIELD, STAR, JUMP, SHRINK, STEAL, FAKE, LEADER = range(5, 16)
ITEMS = 15
STRONG = {BOOST, SHOT, HOMING, BOOST3, SHOT3, STAR, SHRINK}  # the draws that help a kart catch up
SHIELD_FRAMES, STAR_FRAMES, JUMP_FRAMES, SHRINK_FRAMES, SHRINK_TOP, SLIP_FRAMES = 600, 360, 36, 240, 26, 40
PAL_YELLOW = 3
MAX_COINS, COIN_LOSS = 10, 2
OIL_SPEED = 24       # oil spins a kart at this speed or more (proj.asm)
ROLL_FRAMES, PANEL_TICKS = 60, 75
BOOST_FRAMES, BOOST_EXTRA, PAD_FRAMES, DRIFT_FRAMES, ROCKET_FRAMES = 120, 16, 30, 40, 45
ROCKET_WINDOW, WHEELSPIN, SPIN_FRAMES = 20, 45, 64
HOP_FRAMES, DRIFT_CHARGE = 8, 40
REFUSE_FRAMES = 30
MAX_PER_THING = 5    # lines one projected thing may cost (proj.asm)
HUD_TILE = [gen_assets.shared_tile("hud0"), gen_assets.shared_tile("hud1")]  # each player's HUD item frame
ITEM_PICS = gen_assets.item_pictures()  # 128 bytes an item from item 1: top two tiles, then bottom two
LEADER_TILES = [gen_assets.leader_tile(i) for i in range(3)]  # the leader shot's near, mid and far frames: the tiles the countdown's "O" held
LEADER_PIC = open(os.path.join(ROOT, "game", "res", "leader.pic"), "rb").read() if os.path.exists(os.path.join(ROOT, "game", "res", "leader.pic")) else b""
LEADER_STEP = 6      # px a frame on each axis (proj.asm LEADER_STEP 96); a shot and a homing shot go 4
CPU_RECHECK, CPU_PATIENCE = 8, 300
EAST, SOUTH_A, NORTH_A = 32 << 8, 64 << 8, 0


class TestFailure(Exception):
    pass


def check(ok, msg):
    if not ok:
        raise TestFailure(msg)


def floor_match(shot, model, covered=frozenset()):
    """Share of floor pixels that equal the model at the same spot or one pixel
    away: emulators round the Mode 7 maths slightly differently, which moves
    edges by a pixel. A wrong angle, camera or perspective fails by far more.
    Pixels under a sprite's box (`covered`) are not floor and are skipped."""
    def same(o, o2):
        return all(abs(shot[o + i] - model[o2 + i]) <= 16 for i in range(3))
    hits = total = 0
    for y in list(range(24, 112)) + list(range(136, 224)):
        for x in range(256):
            if (x, y) in covered:
                continue
            o = (y * 256 + x) * 3
            total += 1
            if any(same(o, (ny * 256 + nx) * 3) for ny in (y, y - 1, y + 1)
                   for nx in (x, x - 1, x + 1) if 0 <= nx < 256 and ny < 224):
                hits += 1
    return hits / total


def pixel(g, x, y):
    w, _, img = g.r.frame
    return tuple(img[(y * w + x) * 3:(y * w + x) * 3 + 3])


def close(got, rgb):
    """A screen pixel equals a colour as CGRAM keeps it (5 bits a channel), give or take a rounding step."""
    return all(abs(a - ((b >> 3) << 3)) <= 8 for a, b in zip(got, rgb))


def box_colours(g, x, y, n):
    """The colours on screen in the n x n box at (x, y)."""
    w, h, img = g.r.frame
    return {tuple(img[(yy * w + xx) * 3:(yy * w + xx) * 3 + 3]) for yy in range(max(0, y), min(h, y + n)) for xx in range(max(0, x), min(w, x + n))}


def shows(seen, rgb):
    return any(close(c, rgb) for c in seen)


def heading(tx, ty):
    """Kart angle for direction (tx, ty); forward is (sin a, -cos a), 128 steps a turn."""
    return (round(math.atan2(tx, -ty) / (2 * math.pi) * 128) % 128) << 8


class Game:
    def __init__(self, core, syms, shots):
        self.r = rr.Runner(core, ROM)
        self.syms, self.shots, self.core = syms, shots, core
        self.f = 0
        self.max_in_race = 0

    def off(self, name, i=0):
        return rr.wram_offset(self.syms[name]) + i

    def u8(self, name, i=0):
        return self.r.wram()[self.off(name, i)]

    def u16(self, name, i=0):
        o = self.off(name, i * 2)
        ram = self.r.wram()
        return ram[o] | ram[o + 1] << 8

    def lines(self):
        """max_lines, and the per-phase table of the frame that set it, kept when it is the busiest seen."""
        m = self.u16("max_lines")
        if m > self.busiest[0]:
            raw = [self.u16("phase_best", i) for i in range(self.u16("phase_cnt"))]
            used = [v - 225 if v >= 225 else v + 37 for v in raw]
            self.busiest = (m, [b - a for a, b in zip(used, used[1:])], used[0] if used else 0)
        return m

    def phase_table(self):
        """(the per-phase lines of the frame behind max_lines, the lines before the loop starts); empty on a ROM without probes."""
        raw = [self.u16("phase_best", i) for i in range(self.u16("phase_cnt"))]
        used = [v - 225 if v >= 225 else v + 37 for v in raw]
        return [b - a for a, b in zip(used, used[1:])], used[0] if used else 0

    def kart(self, p):
        """(x, y, speed, angle) with x and y in map pixels."""
        x, y, speed, angle = struct.unpack_from("<hhhH", self.r.wram(), self.off("karts", p * 12))
        return x >> 4, y >> 4, speed, angle

    def place(self, p, x, y, angle, speed=0):
        self.r.poke(self.off("karts", p * 12), struct.pack("<hhhHhh", int(x * 16), int(y * 16), speed, angle, 0, 0))

    def oam(self, slot):
        """(x, y, tile, attr, large) of a sprite slot from the game's OAM copy."""
        ram = self.r.wram()
        o = self.off("oamMemory", slot * 4)
        hi = ram[self.off("oamMemory", 512 + (slot >> 2))] >> ((slot & 3) * 2)
        attr = ram[o + 3]
        return ram[o] | (hi & 1) << 8, ram[o + 1], ram[o + 2] | (attr & 1) << 8, attr, (hi >> 1) & 1

    def vram(self):
        p = self.r.lib.retro_get_memory_data(3)  # RETRO_MEMORY_VIDEO_RAM
        return C.string_at(p, self.r.lib.retro_get_memory_size(3))

    def rom_words(self, name, n):
        """n signed 16-bit values of a constant table in the ROM (LoROM)."""
        a = self.syms[name]
        o = ((a >> 16) & 0x7F) * 0x8000 + (a & 0xFFFF) - 0x8000
        return list(struct.unpack_from(f"<{n}h", self.rom, o))

    def rom_bytes(self, name, n):
        """n bytes of a constant table: in the ROM, or in work RAM where tcc-816 placed it (it puts
        some const arrays, such as two-dimensional ones, in initialised RAM)."""
        a = self.syms[name]
        if (a >> 16) in (0x7E, 0x7F):
            o = rr.wram_offset(a)
            return self.r.wram()[o:o + n]
        o = ((a >> 16) & 0x7F) * 0x8000 + (a & 0xFFFF) - 0x8000
        return self.rom[o:o + n]

    def s8(self, name, i=0):
        v = self.u8(name, i)
        return v - 256 if v > 127 else v

    def set8(self, name, i, v):
        self.r.poke(self.off(name, i), bytes([v & 255]))

    def set16(self, name, i, v):
        self.r.poke(self.off(name, 2 * i), struct.pack("<H", v & 0xFFFF))

    def cell_tiles(self, c):
        """The 4 map tiles of floor cell c as video memory holds them."""
        v = self.vram()
        a = (c >> 6) * 256 + (c & 63) * 2
        return [v[(a + d) * 2] for d in (0, 1, 128, 129)]

    def map_text(self, x, y, n):
        """n small letters of the Mode 1 map from column x of row y."""
        v = self.vram()
        o = (UI_MAP + y * 32 + x) * 2
        return "".join(chr(32 + v[o + 2 * i]) for i in range(n))

    def run(self, n, p0=(), p1=()):
        for _ in range(n):
            self.r.pressed = {0: set(p0), 1: set(p1)}
            self.r.run_frame()
            self.f += 1

    def press(self, port, button):
        """Taps a button for 3 frames, then lets go for 3."""
        self.run(3, *([(button,), ()] if port == 0 else [(), (button,)]))
        self.run(3)

    def shot(self, name):
        if self.shots:
            self.r.shot(os.path.join(self.shots, f"{self.core}-{name}.png"))

    def state(self):
        return self.u8("game_state")

    def wait_state(self, want, limit):
        for i in range(limit):
            if self.state() == want:
                return i
            self.run(1)
        raise TestFailure(f"state {want} not reached in {limit} frames (state {self.state()})")


def camera_errors(g):
    """Checks the camera from the outside: the floor under each player's own kart sprite,
    at the centre column of its wheel line, must be the kart's own map position, and the
    floor near the horizon must lie ahead of the kart in the direction it faces."""
    ram = g.r.wram()
    params = m7_model.line_params(ram, g.syms, g.rom)
    errors = []
    for p in (0, 1):
        kx, ky, speed, angle = g.kart(p)
        X, Y = m7_model.map_point(params, 128, p * 112 + KART_LINE)
        near = 3 + speed // 16  # the tables in RAM place the camera where the kart was a frame ago
        if abs(X - kx) > near or abs(Y - ky) > near:
            errors.append(f"player {p + 1} floor under kart is ({X},{Y}), kart is at ({kx},{ky})")
        a = 2 * math.pi * ((angle >> 8) & 127) / 128
        fx, fy = math.sin(a), -math.cos(a)
        X, Y = m7_model.map_point(params, 128, p * 112 + 30)
        ahead, side = (X - kx) * fx + (Y - ky) * fy, (X - kx) * -fy + (Y - ky) * fx
        if ahead < 200 or abs(side) > ahead / 10:
            errors.append(f"player {p + 1} horizon point ({X},{Y}) is not ahead of kart ({kx},{ky}) facing {fx:.2f},{fy:.2f}")
    return errors


def sprite_cover(g):
    """Screen pixels inside the box of a sprite on screen."""
    out = set()
    for slot in range(SLOTS):
        x, y, _, _, large = g.oam(slot)
        if y >= 224:
            continue
        n = 32 if large else 16
        x = x - 512 if x >= 256 else x
        out.update((xx, yy) for yy in range(y, min(224, y + n)) for xx in range(max(0, x), min(256, x + n)))
    return out


def picture_checks(g, label, stats):
    ram = g.r.wram()
    stats["match"] = min(stats["match"], floor_match(g.r.frame[2], m7_model.predict(ram, g.syms, g.rom, g.vram()), sprite_cover(g)))
    errs = camera_errors(g)
    check(not errs, f"{label}: " + "; ".join(errs))


def kart_stats(g):
    """The kart type table in the ROM: [(accel, top, turn)] for light, medium, heavy."""
    w = g.rom_words("kart_types", 9)
    return [tuple(w[i * 3:i * 3 + 3]) for i in range(3)]


def kart_of(g, p):
    return g.stats[CAST[g.u8("pick", p)]["type"]]


def title_checks(g):
    for p, cx in ((0, 8), (1, 24)):
        name = NAMES[g.u8("pick", p)]
        shown = g.map_text(cx - len(name) // 2, 16, len(name))
        check(shown == name, f"title shows {shown!r} for player {p + 1}, expected {name!r}")
        check(g.oam(p)[2] == NEAR_TILE(p, 4) and (g.oam(p)[3] >> 1) & 7 == p,
              f"title: player {p + 1}'s picture is tile {g.oam(p)[2]} attr {g.oam(p)[3]}")


def to_select(g, port):
    """Start on a pad opens the select screen: every portrait in place, each cursor on its player's last pick."""
    g.press(port, START)
    g.wait_state(ST_SELECT, 30)
    g.run(SELECT_WAIT)
    for i in range(len(CAST)):
        x, y, tile, attr, large = g.oam(4 + i)
        want = (SEL_X + 40 * (i % 6), SEL_Y + 56 * (i // 6), BUST_TILE(i), i // 3)
        check((x, y, tile, (attr >> 1) & 7) == want and large,
              f"select: portrait {NAMES[i]} at ({x},{y}) tile {tile} palette {(attr >> 1) & 7}, expected {want}")
    res = os.path.join(ROOT, "game", "res")
    v = g.vram()
    bg = open(os.path.join(res, "select_bg.pic"), "rb").read()
    check(v[0x8000:0x8000 + len(bg)] == bg and v[UI_MAP * 2:UI_MAP * 2 + 2048] == open(os.path.join(res, "select_bg.map"), "rb").read(),
          "select: background tiles or map not loaded")
    check(v[0xC000:0xC000 + 384 * 32] == open(os.path.join(res, "select_obj.pic"), "rb").read(), "select: portrait sprites not loaded")
    hidden = [s for s in range(4 + len(CAST), SLOTS) if g.oam(s)[1] != 224]
    check(not hidden, f"select: sprites left on screen in slots {hidden}")
    # colours, read from the picture since CGRAM is not readable: each portrait shows its animal's skin
    # (the sprite palette) on its kart colour (the background palette), and the cursors their players' colours
    w, _, img = g.r.frame
    def colours(x0, y0, x1, y1):
        return {tuple(img[(y * w + x) * 3:(y * w + x) * 3 + 3]) for y in range(y0, y1) for x in range(x0, x1)}
    def has(seen, rgb):
        want = tuple((c >> 3) << 3 for c in rgb)
        return any(all(abs(a - b) <= 8 for a, b in zip(c, want)) for c in seen)
    for i, ch in enumerate(CAST):
        x, y = SEL_X + 40 * (i % 6), SEL_Y + 56 * (i // 6)
        seen = colours(x, y, x + 32, y + 32)
        for slot in (characters.KART_M, characters.ch_portrait_slot(ch)):
            check(has(seen, ch["palette"][slot]), f"select: {ch['name']}'s portrait lacks colour {ch['palette'][slot]}")
    for p in (0, 1):
        x, y = g.oam(p * 2)[:2]
        check(has(colours(x, y, x + 16, y + 16), gen_assets.CURSOR_PAL[3 + 2 * p]), f"select: player {p + 1}'s cursor colour")
    for p in (0, 1):
        check(g.u8("cursor", p) == g.u8("pick", p) and not g.u8("locked", p),
              f"select: player {p + 1} cursor {g.u8('cursor', p)} locked {g.u8('locked', p)}, last pick {g.u8('pick', p)}")
        cursor_check(g, p)


def cursor_check(g, p):
    c, lock = g.u8("cursor", p), g.u8("locked", p)
    x, y, tile, attr, _ = g.oam(p * 2)
    want = (SEL_X + 40 * (c % 6) + (22 if p else -6), SEL_Y + 56 * (c // 6) - 2, CURSOR_TILE(p, lock, 0), 6)
    check((x if x < 256 else x - 512, y, tile, (attr >> 1) & 7) == want,
          f"select: player {p + 1} cursor sprite at ({x},{y}) tile {tile}, expected {want} for {NAMES[c]}")


def move(g, port, keys):
    for k in keys:
        g.press(port, k)


def pick(g, port, want, taken=False):
    """Presses B on the animal under player `port`'s cursor; it must lock, or be refused when taken."""
    check(g.u8("cursor", port) == want, f"select: player {port + 1} cursor on {NAMES[g.u8('cursor', port)]}, expected {NAMES[want]}")
    cursor_check(g, port)
    before = g.u8("pick", port)
    g.press(port, B)
    if taken:
        check(not g.u8("locked", port) and g.u8("pick", port) == before,
              f"select: player {port + 1} picked {NAMES[want]}, which player {2 - port} holds")
        flash_check(g, port)
    else:
        check(g.u8("locked", port) and g.u8("pick", port) == want,
              f"select: player {port + 1} pressed B on {NAMES[want]}: locked {g.u8('locked', port)}, pick {g.u8('pick', port)}")
        cursor_check(g, port)


def flash_check(g, port):
    """A refused pick flashes the cursor for about half a second, then it shows again."""
    seen = {g.oam(port * 2)[1] == 224}
    for _ in range(REFUSE_FRAMES):
        g.run(1)
        seen.add(g.oam(port * 2)[1] == 224)
    check(seen == {True, False}, f"select: player {port + 1}'s refused pick did not flash the cursor")
    check(g.u8("refuse_t", port) == 0, f"select: player {port + 1}'s cursor still flashing")
    cursor_check(g, port)


def race_loads_picks(g, label):
    """The race has each player's animal in its sprite tiles and colours, and on the HUD."""
    vram = g.vram()
    res = os.path.join(ROOT, "game", "res")
    for p in (0, 1):
        a = g.u8("pick", p)
        block = open(os.path.join(res, f"cast_{a}.pic"), "rb").read()
        got = vram[0xC000 + p * 4096:0xC000 + (p + 1) * 4096]
        check(got == block, f"{label}: player {p + 1}'s sprite tiles are not the {NAMES[a]}'s")
        check(g.u8("kart_type", p) == CAST[a]["type"], f"{label}: player {p + 1} drives type {g.u8('kart_type', p)}")
        icon = g.oam(HUD_SLOT(p) + 9)
        check(icon[2] == MID_TILE(p, 4) and (icon[3] >> 1) & 7 == p, f"{label}: player {p + 1}'s HUD picture {icon}")
    shared = bytearray(open(os.path.join(res, "shared.pic"), "rb").read())
    got = bytearray(vram[0xE000:0xE000 + 8192])
    for r in range(4):  # the minimap's tiles are the track's, checked with the track
        a = (TILE_MINIMAP - 256 + 16 * r) * 32
        shared[a:a + 128] = got[a:a + 128] = bytes(128)
    check(got == shared, f"{label}: shared tiles")
    cpu_pick_checks(g, label)
    glyph_checks(g, label)
    # the own kart's 32x32 frame ends on the half's last line + 1: its bottom row must be empty in every view
    for p in (0, 1):
        for v in range(5):
            t = NEAR_TILE(p, v) + 16 * 3  # the bottom row of 8x8 tiles in a 32x32 frame
            rows = [vram[0xC000 + (t + k) * 32 + o] for k in range(4) for o in (14, 15, 30, 31)]
            check(not any(rows), f"{label}: player {p + 1}'s view {v} has pixels on its bottom row, which shows in the other half")
    # colours: the own kart sprite in each half shows that animal's kart and skin colours (CGRAM is not
    # readable, so the picture is the check)
    w, h, img = g.r.frame
    for p in (0, 1):
        pal = CAST[g.u8("pick", p)]["palette"]
        seen = set()
        for y in range(p * 112 + 81, p * 112 + 112):
            for x in range(112, 144):
                o = (y * w + x) * 3
                seen.add(tuple(img[o:o + 3]))
        for slot in (characters.KART_M, characters.SKIN_M):
            want = tuple((c >> 3) << 3 for c in pal[slot])
            check(any(all(abs(a - b) <= 8 for a, b in zip(c, want)) for c in seen),
                  f"{label}: player {p + 1}'s kart sprite lacks the {NAMES[g.u8('pick', p)]}'s colour {want}")


def type_checks(g, p, out):
    """From a standing start on the top straight: frames to top speed, the top speed, and the turn per frame."""
    calm(g)
    park(g, 1 - p)
    g.place(p, 700, 240, WEST)
    g.r.poke(g.off("accel_frac", p), b"\0")
    pad = [(B,), ()] if p == 0 else [(), (B,)]
    speeds = []
    for _ in range(100):
        g.run(1, *pad)
        speeds.append(g.kart(p)[2])
    top = max(speeds)
    frames = speeds.index(top) + 1
    check(all(s == top for s in speeds[frames:]), f"player {p + 1} speed fell after reaching {top}: {speeds}")
    a0 = g.kart(p)[3]
    g.run(1, *([(B, LEFT), ()] if p == 0 else [(), (B, LEFT)]))
    turn = (a0 - g.kart(p)[3]) & 0xFFFF
    kind = CAST[g.u8("pick", p)]["type"]
    accel, want_top, want_turn = g.stats[kind]
    check(top == want_top and turn == want_turn and frames == -(-want_top * 16 // accel),
          f"{characters.TYPE_NAMES[kind]} kart: {frames} frames to top speed {top}, turn {turn}; "
          f"table says top {want_top}, turn {want_turn}, accel {accel}")
    out[kind] = (frames, top, turn)


def type_order(measured):
    """Light picks up speed fastest and turns sharpest, heavy reaches the highest top speed."""
    check(sorted(measured) == [LIGHT, MEDIUM, HEAVY], f"kart types measured: {sorted(measured)}")
    (fl, tl, rl), (fm, tm, rm), (fh, th, rh) = (measured[k] for k in (LIGHT, MEDIUM, HEAVY))
    check(fl < fm < fh, f"frames to top speed light {fl}, medium {fm}, heavy {fh}")
    check(tl < tm < th, f"top speed light {tl}, medium {tm}, heavy {th}")
    check(rl > rm > rh, f"turn per frame light {rl}, medium {rm}, heavy {rh}")


def results_checks(g, label):
    """The results name each player's animal and show its picture."""
    for p in (0, 1):
        row = 11 if p == g.u8("winner") else 16
        name = NAMES[g.u8("pick", p)]
        check(g.map_text(11, row, len(name)) == name, f"{label}: row {row} reads {g.map_text(11, row, len(name))!r}, expected {name!r}")
        check(g.oam(p)[2] == NEAR_TILE(p, 4) and (g.oam(p)[3] >> 1) & 7 == p,
              f"{label}: player {p + 1}'s picture is tile {g.oam(p)[2]} attr {g.oam(p)[3]}")
        t = time_str(g.u16("finish_time", p)) if g.u8("finished", p) else "NO TIME"  # the same wording as with computer karts
        check(g.map_text(23, row, len(t)) == t, f"{label}: player {p + 1}'s time reads {g.map_text(23, row, len(t))!r}, expected {t!r}")
    hidden = [s for s in range(2, SLOTS) if g.oam(s)[1] != 224]
    check(not hidden, f"{label}: race sprites left on screen in slots {hidden}")
    # the winner's name in big letters: tiles 64 + 4 * letter, on row 5 (or 4 when it needs two lines)
    name = NAMES[g.u8("pick", g.u8("winner"))]
    v = g.vram()
    row = 5 if len(name) + 6 <= 16 else 4
    x = 16 - (len(name) + 6) if row == 5 else 16 - len(name)
    got = "".join(gen_assets.BIG_LETTERS[(v[(UI_MAP + row * 32 + x + 2 * i) * 2] - 64) // 4] if name[i] != " " else " "
                  for i in range(len(name)))
    check(got == name, f"{label}: big winner line reads {got!r}, expected {name!r}")


def time_str(f):
    """"M:SS.CC" from frames at 60 a second, as main.c time_text writes it."""
    m = min(f // 3600, 9)
    f = 35999 if f // 3600 > 9 else f
    f -= m * 3600
    s = f // 60
    return f"{m}:{s:02d}.{((f - s * 60) * 100) // 60:02d}"


def animal_of(g, k):
    """Kart k's animal: a player's pick or one of the two computer animals."""
    return g.u8("pick", k) if k < 2 else g.u8("cpu_pick", (k - 2) & 1)


def big_line(g, name):
    """The big letters of a "NAME WINS!" heading as the map spells the name part (row 5, or row 4 for a long name)."""
    v = g.vram()
    row = 5 if len(name) + 6 <= 16 else 4
    x = 16 - (len(name) + 6) if row == 5 else 16 - len(name)
    return "".join(gen_assets.BIG_LETTERS[(v[(UI_MAP + row * 32 + x + 2 * i) * 2] - 64) // 4] if name[i] != " " else " "
                   for i in range(len(name)))


def cpu_results_checks(g, label, first, points=None):
    """The results with computer karts: one row of two lines a kart, in place order from row 9, three rows apart, each with
    the place, the animal, PLAYER 1, PLAYER 2 or COMPUTER 1 to 3 (by kart number, so two computer karts of one animal differ), and
    the time or NO TIME for a kart that did not finish (and, in a cup, its points). `first` is the karts that must lead, in order. Returns the karts in place order."""
    n = 2 + g.u8("cpu_n")
    places = [g.u8("place", k) for k in range(n)]
    check(sorted(places) == list(range(1, n + 1)), f"{label}: places {places} are not 1 to {n}")
    ranking = sorted(range(n), key=lambda k: places[k])
    check(ranking[:len(first)] == first, f"{label}: the karts in place order are {ranking}, expected {first} first")
    for r, k in enumerate(ranking):
        row = 9 + 3 * r
        got = g.map_text(7, row, 3)
        check(got == PLACE_TEXT[r], f"{label}: row {r + 1} place reads {got!r}, expected {PLACE_TEXT[r]!r}")
        name = NAMES[animal_of(g, k)]
        got = g.map_text(11, row, len(name))
        check(got == name, f"{label}: row {r + 1} (kart {k}) animal reads {got!r}, expected {name!r}")
        who = f"COMPUTER {k - 1}" if k > 1 else f"PLAYER {k + 1}"  # a computer kart is numbered by its kart number
        got = g.map_text(11, row + 1, len(who))
        check(got == who, f"{label}: row {r + 1} (kart {k}) driver reads {got!r}, expected {who!r}")
        t = time_str(g.u16("finish_time", k)) if g.u8("finished", k) else "NO TIME"
        got = g.map_text(23, row, len(t))
        check(got == t, f"{label}: row {r + 1} (kart {k}) time reads {got!r}, expected {t!r}")
        if points is not None:
            txt = f"{points[k]} POINTS"
            got = g.map_text(23, row + 1, len(txt))
            check(got == txt, f"{label}: row {r + 1} (kart {k}) points read {got!r}, expected {txt!r}")
    name = NAMES[animal_of(g, ranking[0])]
    got = big_line(g, name)
    check(got == name, f"{label}: the big heading reads {got!r}, expected the first place's {name!r}")
    seen = [sl for sl in range(SLOTS) if g.oam(sl)[1] != 224]
    check(not seen, f"{label}: sprites on the results screen: slots {seen}")
    check(g.map_text(7, 24, 5) == "START" and g.map_text(7, 26, 6) == "SELECT", f"{label}: the START and SELECT lines are not on rows 24 and 26")
    return ranking


def cpu_pick_checks(g, label):
    """The computer karts' two animals are in the cast, differ from each other and from both players' picks."""
    a, b = g.u8("cpu_pick", 0), g.u8("cpu_pick", 1)
    picks = (g.u8("pick", 0), g.u8("pick", 1))
    check(a < len(CAST) and b < len(CAST) and a != b and a not in picks and b not in picks,
          f"{label}: the computer karts' animals {a} and {b} against the players' {picks}")


def glyph_checks(g, label):
    """The two small frames that are free all race hold the R of "3RD" (drawn like the HUD letters) and a computer
    kart's minimap dot (a white 3x3 square with a dark ring), at tiles 426 and 490."""
    check((TILE_R, TILE_DOT3) == (426, 490), f"{label}: the R glyph and the computer dot are at tiles {TILE_R} and {TILE_DOT3}")
    v = g.vram()

    def frame(t):
        return v[0xE000 + (t - 256) * 32:0xE000 + (t - 256) * 32 + 64] + v[0xE000 + (t - 256 + 16) * 32:0xE000 + (t - 256 + 16) * 32 + 64]

    def tiles(cell):  # a 16x16 picture as the two tile rows of a small frame
        raw = gen_assets.sheet_to_tiles(cell, 2, 2)
        return raw[:64] + raw[64:]
    r_art = gen_assets.draw_glyph("R", 2, 16, 16, 1, 1, 2, 3, 1)
    check(frame(TILE_R) == tiles(r_art), f"{label}: the R glyph's tiles are not the R")
    check(frame(TILE_R) != frame(GLYPH("P")), f"{label}: the R glyph is the P's picture")
    dot = [[6 if 5 <= x <= 9 and 5 <= y <= 9 else 0 for x in range(16)] for y in range(16)]
    for y in range(6, 9):
        for x in range(6, 9):
            dot[y][x] = 2
    check(frame(TILE_DOT3) == tiles(dot), f"{label}: the computer kart's dot tiles are not a white square in a dark ring")


def expect_cpu(g, rng, label):
    """The computer animals a race start picks from `rng`: the (rng low byte mod 16)th animal nobody picked, then
    the (rng high byte mod 15)th of those left once the first is out (main.c choose_cpu)."""
    free = [i for i in range(len(CAST)) if i not in (g.u8("pick", 0), g.u8("pick", 1))]
    a = free[(rng & 255) % (len(CAST) - 2)]
    b = [i for i in free if i != a][((rng >> 8) & 255) % (len(CAST) - 3)]
    got = (g.u8("cpu_pick", 0), g.u8("cpu_pick", 1))
    check(got == (a, b), f"{label}: with rng {rng:#06x} the computer karts' animals are {got}, expected {(a, b)}")


def record_checks(g):
    """The frame records of the four computer karts (obj_frames, 3 sizes of 16 bytes each a kind, after the
    players' karts, the shot and the obstacle): the mid frames serve the near and the mid size, the far frames
    0, 2, 4 the far size (views 1 and 3 as 0 and 4), animal A or B in palette 6 or 7; each has the view flag
    (byte 4) that marks a kart for lift, shrink and views, which the shot and the obstacle lack."""
    rec = g.rom_bytes("obj_frames", 8 * 3 * 16)
    for kind, (animal, pal) in enumerate(((0, 6), (1, 7), (0, 7), (1, 6))):
        for sz in range(3):
            o = (4 + kind) * 48 + sz * 16
            tiles = struct.unpack_from("<5H", rec, o + 6)
            first = 256 + 32 * animal
            want = [first + 2 * v for v in range(5)] if sz < 2 else [first + 2 * f for f in (5, 5, 6, 7, 7)]
            check(tuple(rec[o:o + 6]) == (16, (13, 13, 12)[sz], 0, 0x30 | (pal << 1), 0x40, 0) and list(tiles) == want,
                  f"computer kart {kind + 2} size {sz}: record {tuple(rec[o:o + 6])} tiles {list(tiles)}, expected tiles {want} in palette {pal}")
    for kind, name in ((0, "player 1's kart"), (1, "player 2's kart"), (2, "the shot"), (3, "the obstacle")):
        flags = [rec[kind * 48 + sz * 16 + 4] for sz in range(3)]
        check(all(flags) == (kind < 2) and any(flags) == (kind < 2), f"{name}'s records have view flags {flags}")
    check(rec[3 * 48 + 3] == 0x30 | (2 << 1), "the obstacle is not drawn in palette 2")


def cpu_checks(g, label):
    """Once GO has gone (60 frames) and the countdown's tiles are free, each computer animal's 8 small frames
    are in video memory, the same bytes as in its block; the digits' "O" tiles are untouched; palettes 6 and 7
    show the two computer animals' colours, so an animal drawn in the other's palette is a recolour."""
    cpu_pick_checks(g, label)
    check(g.u8("cpu_gfx_ready") == 1 and g.u8("cpu_loaded") == 2, f"{label}: the computer animals' frames are not loaded")
    v = g.vram()
    res = os.path.join(ROOT, "game", "res")
    picks = [g.u8("cpu_pick", i) for i in (0, 1)]
    for i, a in enumerate(picks):
        block = open(os.path.join(res, f"cast_{a}.pic"), "rb").read()
        for f, (x, y) in enumerate(CPU_FRAME_SRC):
            for row in (0, 1):
                src = T(x, y) + 16 * row
                dst = CPU_TILE(i, f) + 16 * row
                check(v[0x6000 * 2 + dst * 32:0x6000 * 2 + dst * 32 + 64] == block[src * 32:src * 32 + 64],
                      f"{label}: computer animal {'AB'[i]} ({NAMES[a]}) frame {f} row {row}: tiles {dst} are not the block's tiles {src}")
    if not g.u8("leader_ready"):
        g.run(3)
        v = g.vram()
    check(g.u8("leader_ready"), f"{label}: the leader shot's picture was not loaded once the computer animals' frames were")
    for r in range(4):  # the "O" of GO, rows 20-23 columns 0-3, holds the leader shot's picture now that GO is gone
        a = (COUNT_TILE["O"] - 256 + 16 * r) * 32
        check(v[0xE000 + a:0xE000 + a + 128] == LEADER_PIC[r * 128:(r + 1) * 128], f"{label}: the 'O' tiles of the countdown do not hold the leader shot's picture")
    # palettes: draw the first mid frame of animal A in palette 6, B in 7 and A in 7 on slots the game does not use
    # and look at the screen; a recolour shows B's colours on A's picture
    wanted = [(0, 6, picks[0]), (1, 7, picks[1]), (0, 7, picks[1])]
    ram_off = g.off("oamMemory", CPU_SLOT * 4)
    for k, (animal, pal, _) in enumerate(wanted):
        g.r.poke(ram_off + 4 * k, bytes([30 + 70 * k, 50, CPU_TILE(animal, 0) & 255, 0x30 | (pal << 1) | (CPU_TILE(animal, 0) >> 8)]))
    g.r.poke(g.off("oamMemory", 512 + CPU_SLOT // 4), b"\0")  # small, x below 256
    g.run(3)
    seen = [box_colours(g, 30 + 70 * k, 50, 16) for k in range(3)]
    for k, (animal, pal, who) in enumerate(wanted):
        pal_rgb = CAST[who]["palette"]
        check(shows(seen[k], pal_rgb[characters.SKIN_M]) and any(shows(seen[k], pal_rgb[c]) for c in (characters.KART_L, characters.KART_M, characters.KART_D)),
              f"{label}: animal {'AB'[animal]} in palette {pal} lacks {NAMES[who]}'s skin or kart colours")
    for k in range(3):
        g.r.poke(ram_off + 4 * k + 1, bytes([224]))
    g.run(1)


CPU_LOAD_LINES = 22  # lines one computer animal's copy may add to a quiet frame (measured: 17 to 19)


def cpu_load_cost(g):
    """The vblank copy of a computer animal's frames starts when GO's 60 frames are over, one animal a frame; the
    frames that copy cost at most CPU_LOAD_LINES more than the frames just before. Both karts stand still."""
    while g.u16("timer") > 3:
        g.run(1)
    check(not g.u8("cpu_loaded"), "the computer animals' frames were copied before GO had gone")
    g.set16("max_lines", 0, 0)
    g.run(2)
    base = g.u16("max_lines")
    g.set16("max_lines", 0, 0)
    g.run(6)
    loading = g.u16("max_lines")
    check(g.u8("cpu_loaded") == 2, f"the computer animals' frames not copied {g.u16('timer')} frames after GO: {g.u8('cpu_loaded')} of 2")
    check(loading - base <= CPU_LOAD_LINES, f"copying a computer animal's frames cost {loading - base} lines more than a quiet frame ({loading} against {base})")
    g.cpu_cost = loading - base  # for the report


def start_race(g, port, rng=None):
    """Taps Start on a pad and notes the frame the race screen appears. With `rng`, the random number the race start picks the
    computer animals with (see choose())."""
    pad = (START,)
    for i in range(10):
        if rng is not None:
            g.set16("rng", 0, rng_unstep(rng))
        g.run(1, *([pad, ()] if port == 0 else [(), pad]))
        if i >= 2:
            pad = ()
        if g.state() == ST_COUNTDOWN:
            break
    check(g.state() == ST_COUNTDOWN, f"Start on pad {port + 1} did not start a race")
    g.countdown_from = g.f
    for p in (0, 1):
        check(g.u8("lap", p) == 0 and g.u8("cp", p) == NCP - 1 and not g.u8("finished", p),
              f"new race: player {p + 1} lap {g.u8('lap', p)}, checkpoint {g.u8('cp', p)}, finished {g.u8('finished', p)}")


def countdown(g):
    """Both hold accelerate through the countdown: nobody moves before GO, each number shows for a
    second in both halves, and GO comes 180 frames after the race screen. Returns the GO frame."""
    began = g.countdown_from
    g.run(30, (B,), (B,))
    g.shot("countdown")
    for i in range(400):
        if g.state() == ST_RACE:
            break
        for p in range(2 + g.u8("cpu_n")):  # the computer karts too: they start at GO
            x, y, speed, _ = g.kart(p)
            check((x, y, speed) == (*trk(g)["grid"][p], 0), f"countdown frame {i}: kart {p} moved to ({x},{y}) speed {speed}")
        for p in (0, 1):
            shown = g.oam(BANNER_SLOT(p))
            t = g.f - began
            want = COUNT_TILE[3 - t // 60] if t < COUNTDOWN and 2 <= t % 60 <= 57 else None
            check(want is None or (shown[2] == want and shown[1] == p * 112 + 36),
                  f"countdown frame {g.f - began}: player {p + 1} shows tile {shown[2]} at line {shown[1]}, expected {want}")
        g.run(1, (B,), (B,))
    check(g.state() == ST_RACE and abs(g.f - began - COUNTDOWN) <= 2,
          f"GO came {g.f - began} frames after the race screen, expected {COUNTDOWN}")
    for p in (0, 1):
        check(g.oam(BANNER_SLOT(p))[2] == COUNT_TILE["G"] and g.oam(BANNER_SLOT(p) + 1)[2] == COUNT_TILE["O"],
              f"player {p + 1} does not see GO")
    return g.f


def hud_check(g, p):
    """The lap digit and the place in player p's half match the race state."""
    lap = min(max(g.u8("lap", p), 1), 3)
    place = g.u8("place", p)
    digit, first = g.oam(HUD_SLOT(p) + 3), g.oam(HUD_SLOT(p) + 6)
    suffix = (g.oam(HUD_SLOT(p) + 7)[2], g.oam(HUD_SLOT(p) + 8)[2])
    check(digit[2] == GLYPH(str(lap)) and digit[1] == p * 112 + 4,
          f"player {p + 1} HUD shows lap tile {digit[2]}, expected lap {lap}")
    want = (GLYPH("S"), GLYPH("T")) if place == 1 else (GLYPH("N"), GLYPH("D"))
    check(first[2] == GLYPH(str(place)) and suffix == want,
          f"player {p + 1} HUD shows place tiles {first[2]} {suffix}, expected place {place}")


def drive_checks(g, stats):
    """The first drive: both accelerate west; player 1 steers left 61 frames, player 2 right 31."""
    go, fd0 = g.f, g.u16("frames_done")
    for t in range(1, 601):
        p0, p1 = [B], [B]
        if 190 <= t <= 250:
            p0.append(LEFT)
        if 190 <= t <= 220:
            p1.append(RIGHT)
        rng_before = g.u16("rng")
        g.run(1, p0, p1)
        rng_want = (rng_before >> 1) ^ 0xB400 if rng_before & 1 else rng_before >> 1
        check(g.u16("rng") == rng_want, f"{t} frames after GO: the random number went from {rng_before} to {g.u16('rng')}, expected {rng_want}")
        if t == GO_FRAMES + 10:
            check(all(g.oam(BANNER_SLOT(p) + i)[1] == 224 for p in (0, 1) for i in (0, 1)),
                  f"{t} frames after GO: the GO banner is still up: {[g.oam(BANNER_SLOT(p) + i)[1] for p in (0, 1) for i in (0, 1)]}")
        if t in (140, 270, 600):
            # a frame's picture matches the tables in RAM at the end of that same frame;
            # RAM from one frame earlier scores 88-95%, so a one-frame lag fails the test
            picture_checks(g, f"{t} frames after GO", stats)
        if t == 140:
            g.shot("mid-race")
            for p in (0, 1):
                x, y, _, _ = g.kart(p)
                check(x < GRID[p][0] - 100 and y == GRID[p][1],
                      f"140 frames after GO: player {p + 1} at ({x},{y}), expected well west of {GRID[p][0]} on y {GRID[p][1]}")
    for p, want in ((0, (WEST - 61 * kart_of(g, 0)[2]) & 0xFFFF), (1, (WEST + 31 * kart_of(g, 1)[2]) & 0xFFFF)):
        check(g.kart(p)[3] == want, f"player {p + 1} angle {g.kart(p)[3]}, expected {want}")
    stats["frames"] += g.f - go
    stats["done"] += (g.u16("frames_done") - fd0) & 0xFFFF


def physics_checks(g):
    calm(g)
    # karts that touch: pushed BUMP apart, both slowed by a quarter, along x or y and either way
    for (x0, y0), (x1, y1) in (((606, 240), (600, 241)), ((600, 240), (601, 246)), ((600, 240), (606, 241)),
                               ((600, 246), (601, 240))):
        bumps = g.u16("bumps")
        g.place(0, x0, y0, WEST, 30)
        g.place(1, x1, y1, WEST, 30)
        g.run(1)
        (ax, ay, s0, _), (bx, by, s1, _) = g.kart(0), g.kart(1)
        apart = max(abs(ax - bx), abs(ay - by))
        check(g.u16("bumps") == bumps + 1 and apart >= BUMP and s0 < 25 and s1 < 25,
              f"collision from ({x0},{y0}) and ({x1},{y1}): karts {apart} px apart, speeds {s0} and {s1}")
    # level overlap on both axes (6 px): pushed along x, so the y gap stays
    g.place(0, 600, 240, WEST, 30)
    g.place(1, 606, 246, WEST, 30)
    g.run(1)
    (ax, ay, _, _), (bx, by, _, _) = g.kart(0), g.kart(1)
    check(abs(ax - bx) >= BUMP and ay - by == -6, f"a tie on both axes: x gap {abs(ax - bx)}, y gap {ay - by}")
    # a kart in the air or sinking out of sight touches nothing: either kart, either state
    for name, q in (("air_t", 0), ("air_t", 1), ("fall_t", 0), ("fall_t", 1)):
        calm(g)
        g.place(0, 600, 240, WEST, 30)
        g.place(1, 601, 241, WEST, 30)
        g.set8(name, q, 20)
        g.set8("air_len", q, 40)
        bumps = g.u16("bumps")
        g.run(1)
        check(g.u16("bumps") == bumps, f"karts touched with player {q + 1} in {name}: bumps {g.u16('bumps') - bumps}")
    calm(g)
    g.place(0, 600, 160, WEST)  # out of the way on the outer grass
    # top speed on the road, then the grass slows the kart down
    top = kart_of(g, 1)[1]
    g.place(1, 700, 240, WEST)
    g.run(60, (), (B,))
    check(g.kart(1)[2] == top, f"road: speed {g.kart(1)[2]} after 60 frames, expected {top}")
    g.place(1, 516, 120, WEST, top)
    g.run(40, (), (B,))
    check(g.kart(1)[2] <= MAX_GRASS, f"grass: speed {g.kart(1)[2]} after 40 frames, expected at most {MAX_GRASS}")
    # the map edge stops each kart on every side
    for q in (0, 1):
        for name, (x0, y0, ang, want) in (("west", (8, 512, WEST, (0, None))), ("east", (1015, 512, EAST, (1023, None))),
                                          ("north", (512, 8, NORTH_A, (None, 0))), ("south", (512, 1015, SOUTH_A, (None, 1023)))):
            g.place(1 - q, 600, 160, WEST)
            g.place(q, x0, y0, ang, MAX_GRASS)
            g.run(30, (B,) if q == 0 else (), (B,) if q == 1 else ())
            x, y, speed, _ = g.kart(q)
            check((want[0] is None or x == want[0]) and (want[1] is None or y == want[1]) and speed <= EDGE_SPEED,
                  f"map edge {name}, player {q + 1}: kart at ({x},{y}) with speed {speed}")


def view_checks(g):
    """Player 1's sprite of player 2: size by distance, angle and mirror by heading."""
    cases = [  # (distance ahead, heading change, size, view, mirrored)
        (20, 0, "near", 0, 0), (20, 16, "near", 1, 0), (20, 32, "near", 2, 0), (20, 48, "near", 3, 0),
        (20, 64, "near", 4, 0), (20, -48, "near", 3, 1), (20, -32, "near", 2, 1), (20, -16, "near", 1, 1),
        (60, 0, "mid", 0, 0), (150, 0, "far", 0, 0),
        (20, 0, "near", 1, 1, 45),  # ahead and 45 px to the right: seen from behind-left
    ]
    for dist, turn, size, view, flip, *right in cases:
        g.place(0, 700, 240, WEST)
        g.place(1, 700 - dist, 240 - (right[0] if right else 0), (WEST + (turn << 8)) & 0xFFFF)
        g.run(1)
        x, y, tile, attr, large = g.oam(2)
        want = {"near": NEAR_TILE(1, view), "mid": MID_TILE(1, view), "far": FAR_TILE(1, view)}[size]
        box = 32 if size == "near" else 16
        label = f"other kart {dist} px ahead, turned {turn}"
        check(tile == want and (attr >> 6 & 1) == flip and large == (size == "near"),
              f"{label}: tile {tile} mirrored {attr >> 6 & 1} large {large}, expected tile {want} mirrored {flip}")
        check(y + box <= 112, f"{label}: sprite rows {y}-{y + box} cross into player 2's half")
        centre = x + box // 2
        check(centre > 180 if right else abs(centre - 128) <= 1, f"{label}: sprite centred at x {centre}")
        if turn == 0:
            check(g.oam(3)[1] == 224, f"{label}: player 2 sees the kart straight behind it")
        if (dist, turn) == (20, 32):
            g.shot("other-kart-side")
    # a kart in the air (here off a ramp, 20 frames into a 40-frame jump: lift 25) is drawn higher in the
    # other half: by its lift near, half of it at mid distance
    for dist, lift in ((20, 25), (60, 12)):
        g.place(0, 700, 240, WEST)
        g.place(1, 700 - dist, 240, WEST)
        g.run(1)
        y0 = g.oam(2)[1]
        g.set8("air_len", 1, 40)
        g.set8("air_t", 1, 21)
        g.run(1)
        check(g.u8("kart_lift", 1) == 25 and y0 - g.oam(2)[1] == lift,
              f"kart in the air {dist} px ahead: drawn {y0 - g.oam(2)[1]} lines higher with lift {g.u8('kart_lift', 1)}, expected {lift}")
        g.set8("air_t", 1, 0)
        g.run(1)
    # player 2 sees player 1 near (slot 3, large) and far (small)
    for dist, large in ((20, True), (150, False)):
        g.place(1, 700, 240, WEST)
        g.place(0, 700 - dist, 240, WEST)
        g.run(1)
        o = g.oam(3)
        check(o[1] != 224 and o[4] == large and o[2] == (NEAR_TILE(0, 0) if large else FAR_TILE(0, 0)),
              f"player 2 sees player 1 {dist} px ahead as {o}")


def trk(g):
    """The track being raced, as built (tools/tracks.py draw())."""
    return TRK[g.u8("track_no")]


def cross(g, p, j, frames=20):
    """Moves kart p along the road over the start of checkpoint j, 2 px a frame from 24 px before it to
    14 px past, as driving there would: lap counting reads only where the kart is. The kart is held on
    the floor and still, so a ramp, oil, a pit or an obstacle on the way does not stop the walk."""
    x, y, dx, dy = tracks.checkpoint_at(trk(g), j)
    a = heading(dx, dy)
    for k in range(frames):
        d = -24 + 2 * k
        g.place(p, x + d * dx, y + d * dy, a)
        for name in ("fall_t", "air_t", "spin_t"):
            g.set8(name, p, 0)
        g.run(1)


def busy_scene(g, p):
    """The finish costs the most: the other kart, 4 shots and both obstacles in view as kart p crosses the line."""
    x, y, dx, dy = tracks.checkpoint_at(trk(g), 0)
    nx, ny = -dy, dx
    g.place(1 - p, x + 16 * dx + 14 * nx, y + 16 * dy + 14 * ny, heading(dx, dy), 32)
    shots_in_view(g, 1 - p, home=p + 1)
    for i, (ahead, side) in enumerate(((60, -26), (80, 26))):
        g.set16("ob_x", i, int((x + ahead * dx + side * nx) * 16))
        g.set16("ob_y", i, int((y + ahead * dy + side * ny) * 16))
        g.set16("ob_dx", i, 0)
        g.set16("ob_dy", i, 0)
        g.set16("ob_len", i, 1000)
        g.set8("ob_on", i, 1)


def full_laps(g, p, stats, final=True):
    # final: also check the final-lap banner's picture and that it goes after 1.5 s
    """Moves kart p over every checkpoint in order from where it is until it finishes; checks each lap's
    count, and the final-lap banner when the last lap starts."""
    while not g.u8("finished", p):
        lap, j = g.u8("lap", p), (g.u8("cp", p) + 1) % NCP
        if lap == 3 and j == 0:
            busy_scene(g, p)
        cross(g, p, j)
        check(g.u8("cp", p) == j, f"{TRACK_NAMES[g.u8('track_no')]}: player {p + 1} lap {lap}: checkpoint {j} not counted (at {g.u8('cp', p)})")
        want = lap + 1 if j == 0 else lap
        check(g.u8("lap", p) == want, f"player {p + 1}: lap {g.u8('lap', p)} after checkpoint {j}, expected {want}")
        if j == 0:
            stats["laps"].append(g.u8("lap", p))
            if want == 3 and final:
                final_lap_check(g, p)
            elif want == 3:
                check(g.u8("banner_t", p) > 0, f"player {p + 1} started the last lap without the final-lap banner")
        hud_check(g, p)
    check(g.u8("lap", p) == 4, f"player {p + 1} finished on lap count {g.u8('lap', p)}")
    g.run(4)
    banner = [g.oam(BANNER_SLOT(p) + i) for i in range(8)]
    check(all(b[1] == p * 112 + 40 for b in banner) and banner[0][2] == GLYPH("F"),
          f"player {p + 1} finish banner: {[(b[1], b[2]) for b in banner]}")
    check(g.u8("finals", p) == 1, f"player {p + 1} saw the final-lap banner {g.u8('finals', p)} times, expected once")
    calm(g)  # the shots put in view for the finish would otherwise hit the next kart to lap


def final_lap_check(g, p):
    """The last lap starts: "FINAL LAP" in green in that half for 1.5 s, then gone."""
    t = g.u8("banner_t", p)
    check(t > 0, f"player {p + 1} started the last lap without the final-lap banner")
    banner = [g.oam(BANNER_SLOT(p) + i) for i in range(8)]
    want = [GLYPH(c) for c in "FINALLAP"]
    check([b[2] for b in banner] == want and all(b[1] == p * 112 + 40 and (b[3] >> 1) & 7 == PAL_GREEN for b in banner),
          f"player {p + 1} final-lap banner: {[(b[1], b[2]) for b in banner]}, expected tiles {want}")
    g.shot("final-lap")
    g.run(t + 1)
    check(all(g.oam(BANNER_SLOT(p) + i)[1] == 224 for i in range(8)), f"player {p + 1}'s final-lap banner stayed")


def finish_second(g, p, stats):
    """Kart p, already on its last lap's last checkpoint, crosses the line: it finishes too."""
    g.set8("lap", p, 3)
    g.set8("cp", p, NCP - 1)
    cross(g, p, 0)
    check(g.u8("finished", p), f"player {p + 1} crossed the line on the last lap and did not finish")
    calm(g)


def position_checks(g):
    """The place follows who is ahead, and a kart touching the infield keeps its place."""
    g.place(0, 560, 240, WEST)
    g.place(1, 530, 240, WEST)
    g.run(2)
    check((g.u8("place", 0), g.u8("place", 1)) == (2, 1), f"player 2 ahead: places {g.u8('place', 0)}/{g.u8('place', 1)}")
    hud_check(g, 0)
    hud_check(g, 1)
    g.place(1, 590, 240, WEST)
    g.run(2)
    check((g.u8("place", 0), g.u8("place", 1)) == (1, 2), f"player 1 ahead: places {g.u8('place', 0)}/{g.u8('place', 1)}")
    hud_check(g, 0)
    hud_check(g, 1)
    g.place(0, 560, 400, WEST)  # into the infield, level with player 2's octant
    g.run(2)
    check((g.u8("place", 0), g.u8("place", 1)) == (1, 2), f"infield: places {g.u8('place', 0)}/{g.u8('place', 1)}")
    # level progress, both karts off the track with the same lap, checkpoint and step: player 1 is ahead, and the HUD follows
    saved = [(g.u8("lap", q), g.u8("cp", q), g.u8("frac", q)) for q in (0, 1)]
    for q in (0, 1):
        g.set8("lap", q, 1)
        g.set8("cp", q, 5)
        g.set8("frac", q, 10)
    g.place(0, 600, 160, WEST)
    g.place(1, 600, 175, WEST)
    g.set8("place", 0, 2)
    g.set8("place", 1, 1)
    g.run(2)
    check(g.u16("prog", 0) == g.u16("prog", 1), f"level progress: the karts' progress {g.u16('prog', 0)} and {g.u16('prog', 1)} differ")
    check((g.u8("place", 0), g.u8("place", 1)) == (1, 2), f"level progress: places {g.u8('place', 0)}/{g.u8('place', 1)}")
    hud_check(g, 0)
    hud_check(g, 1)
    for q in (0, 1):
        g.set8("lap", q, saved[q][0])
        g.set8("cp", q, saved[q][1])
        g.set8("frac", q, saved[q][2])


def off_track_near(d, k):
    """A map point beside checkpoint k's middle where the lap progress map says off the track."""
    x, y, dx, dy = tracks.point_at(d["route"], (k + 0.5) / NCP)
    for r in range(40, 300, 8):
        for side in (1, -1):
            px, py = x - dy * r * side, y + dx * r * side
            if 0 <= px < 1024 and 0 <= py < 1024 and d["prog"][int(py) // 16, int(px) // 16] == tracks.OFF:
                return px, py
    raise TestFailure(f"no off-track cell found beside checkpoint {k}")


def skip_checks(g, p):
    """A kart that misses a checkpoint gains nothing until it goes back for it; off the track nothing counts."""
    while g.u8("cp", p) != 0:  # start just past the start line, so the skipped lap ends on it
        cross(g, p, (g.u8("cp", p) + 1) % NCP)
    lap, cp = g.u8("lap", p), 0
    # checkpoint 1 is skipped: from checkpoint 2 round to the start line, everything is out of order
    for j in (3, 4, 9, 17, 25, NCP - 1, 0):
        cross(g, p, j)
        check(g.u8("cp", p) == cp and g.u8("lap", p) == lap,
              f"player {p + 1} skipped checkpoint 1 but crossing {j} gave checkpoint {g.u8('cp', p)} lap {g.u8('lap', p)}")
    # off the track beside the next checkpoint (a cut through the infield): still nothing
    g.place(p, *off_track_near(trk(g), cp + 1), WEST, 0)
    g.run(10)
    check(g.u8("cp", p) == cp, f"player {p + 1}: off the track counted checkpoint {g.u8('cp', p)}")
    # and nothing for a kart off the track one checkpoint before the last (off the track is no checkpoint)
    g.set8("cp", p, NCP - 2)
    g.run(10)
    check(g.u8("cp", p) == NCP - 2, f"player {p + 1}: off the track counted checkpoint {g.u8('cp', p)} after {NCP - 2}")
    g.set8("cp", p, cp)



# ---------------------------------------------------------------- pickups, items and tricks

def hud_picture(g, p):
    """The item whose picture player p's HUD frame holds in video memory, or 0 for none of them."""
    v = g.vram()
    a = 0xC000 + HUD_TILE[p] * 32
    got = v[a:a + 64] + v[a + 512:a + 576]
    for i in range(len(ITEM_PICS) // 128):
        if ITEM_PICS[i * 128:(i + 1) * 128] == got:
            return i + 1
    return 0


def calm(g):
    """Clears every item, trick and shot, so a check starts from a plain kart. The computer karts are parked (cpu_hold): a
    check of their driving clears it."""
    g.set8("cpu_hold", 0, 1)
    for p in (0, 1):
        for name in ("boost_t", "spin_t", "spin_off", "hop_t", "wheelspin_t", "drift", "charge", "roll", "item", "coins",
                     "air_t", "trick", "trick_t", "fall_t", "kart_lift", "wrong", "uses", "shrink_t", "slip"):
            g.set8(name, p, 0)
        g.set16("shield_t", p, 0)
        g.set16("star_t", p, 0)
    for i in range(4):
        g.set8("shot_on", i, 0)
        g.set8("shot_home", i, 0)
    for i in range(2):  # the obstacles roll only in their own checks and the busiest frame
        g.set8("ob_on", i, 0)
        g.set8("ob_struck", i, 0)
    for h in (0, 1):  # a finish banner left up would show on lap 1 in every later screenshot
        g.set8("banner_left", h, 0)
        for i in range(8):
            g.set8("oamMemory", (BANNER_SLOT(h) + i) * 4 + 1, 224)
    g.run(1)


def cell_mid(cell):
    cx, cy = cell
    return cx * 16 + 8, cy * 16 + 8


def cell_no(cell):
    return cell[1] * 64 + cell[0]


def drive_over(g, p, cell, d, frames=20, speed=32, keys=(), before=30):
    """Places kart p `before` px before the middle of a cell, heading d (dx, dy) at `speed`, and drives over it."""
    mx, my = cell_mid(cell)
    g.place(p, mx - before * d[0], my - before * d[1], heading(*d), speed)
    pad = (B,) + tuple(keys)
    g.run(frames, *([pad, ()] if p == 0 else [(), pad]))


def race_dir(cell):
    """The race direction on the straight a floor cell lies on."""
    cx, cy = cell
    return (-1, 0) if cy < 20 else (1, 0) if cy > 40 else (0, 1) if cx < 20 else (0, -1)


def top_of(g, p, coins=None):
    c = g.u8("coins", p) if coins is None else coins
    return kart_of(g, p)[1] + (c >> 1)


def floor_set(g, k):
    """Map tiles of floor picture k: 0 road, 1 coin, 2 panel, 3-5 slime on road, light and dark grass."""
    return list(g.rom_bytes("floor_set", 24)[k * 4:k * 4 + 4])


def tap(g, p, keys, hold=()):
    """Presses keys on pad p for one frame while `hold` stays down, then holds `hold` for a frame."""
    pads = [tuple(hold) + tuple(keys), tuple(hold)]
    g.run(1, *([pads[0], ()] if p == 0 else [(), pads[0]]))
    g.run(1, *([pads[1], ()] if p == 0 else [(), pads[1]]))


def coin_checks(g, out):
    """A coin is taken once, leaves the map and raises the top speed; every two coins add a step."""
    calm(g)
    park(g, 1)
    left = [k for k in TRK[0]["coins"] if g.u8("cells", cell_no(k)) == CELL_COIN]
    check(left, "no coin left on the track to test with")
    cell = left[-1]
    c = cell_no(cell)
    check(g.cell_tiles(c) == floor_set(g, 1), f"coin at {cell}: map tiles {g.cell_tiles(c)}")
    drive_over(g, 0, cell, race_dir(cell), frames=12, before=8)
    check(g.u8("coins", 0) == 1 and g.u8("cells", c) == 0, f"coin: player 1 has {g.u8('coins', 0)} coins, cell holds {g.u8('cells', c)}")
    check(g.cell_tiles(c) == floor_set(g, 0), f"coin taken but the map still shows tiles {g.cell_tiles(c)}")
    check(g.oam(ITEM_SLOT(0) + 2)[2] == GLYPH("1"), f"coin counter shows tile {g.oam(ITEM_SLOT(0) + 2)[2]}, expected 1")
    drive_over(g, 0, cell, race_dir(cell), frames=12, before=8)
    check(g.u8("coins", 0) == 1, f"the same coin was taken twice: {g.u8('coins', 0)} coins")
    # top speed: none, 4 and 10 coins (driving east on the top straight, where no coin lies)
    speeds = {}
    for n, frames in ((0, 56), (4, 12), (10, 12)):
        g.set8("coins", 0, n)
        if n == 0:
            g.place(0, 540, 232, EAST)
        g.run(frames, (B,), ())
        speeds[n] = g.kart(0)[2]
        check(speeds[n] == top_of(g, 0, n), f"{n} coins: top speed {speeds[n]}, expected {top_of(g, 0, n)}")
    check(speeds[0] < speeds[4] < speeds[10], f"coins do not raise the top speed: {speeds}")
    left = [k for k in TRK[0]["coins"] if g.u8("cells", cell_no(k)) == CELL_COIN]
    drive_over(g, 0, left[-1], race_dir(left[-1]), frames=12, before=8)
    check(g.u8("coins", 0) == MAX_COINS and g.u8("cells", cell_no(left[-1])) == 0,
          f"a coin taken at {MAX_COINS} coins: {g.u8('coins', 0)} coins")
    out["coin top speeds"] = speeds
    g.set8("coins", 0, 0)


def panel_checks(g, out):
    """A panel gives a random item from the leader's or the trailing kart's draws, spins it in the HUD,
    and comes back after a while; the kart behind gets more boosts and shots."""
    odds = list(g.rom_bytes("odds", 48))
    lead, behind, rest = odds[:16], odds[16:32], odds[32:]
    good = lambda t: sum(1 for i in t if i in STRONG)  # noqa: E731
    check(good(behind) > good(lead) and set(lead + behind + rest) <= set(range(1, ITEMS + 1)),
          f"draws: leader {lead}, behind {behind}, the rest {rest}")
    check(set(lead + behind + rest) == set(range(1, ITEMS + 1)), f"some items are never drawn: {set(range(1, ITEMS + 1)) - set(lead + behind + rest)}")
    # the third table, for places 3 to 6: weighted to the catch-up items, holding the leader shot twice, which the other two never draw
    check(good(rest) >= 14 and rest.count(LEADER) == 2 and LEADER not in lead + behind,
          f"the third table {rest}: {good(rest)} catch-up draws of 16 (at least 14 wanted), {rest.count(LEADER)} leader shots (2 wanted)")
    calm(g)
    # both on the top straight in the same lap and checkpoint: player 1 further on, so first
    for p in (0, 1):
        g.set8("lap", p, 1)
        g.set8("cp", p, 0)
    a, b = TRK[0]["panels"][0], TRK[0]["panels"][1]
    ca, cb = cell_no(a), cell_no(b)
    ax, ay = cell_mid(a)
    bx, by = cell_mid(b)
    g.place(0, ax + 30, ay, WEST, 32)
    g.place(1, bx + 70, by, WEST, 32)
    tiles, places, taken = set(), {}, None
    # every draw gives the two places different items, so a kart drawing from the wrong table fails below
    same = [i for i in range(16) if len({lead[i], behind[i], rest[i]}) < 3]
    check(not same, f"draws {same} give two places the same item")
    for f in range(40):
        g.set16("rng", 0, 0x20)
        g.run(1, (B,), (B,))
        for p, c in ((0, ca), (1, cb)):
            if p not in places and g.u8("cells", c) == 0:
                places[p] = g.u8("place", p)
                taken = taken or g.f
        if f == 24:
            g.shot("panel-spin")
        if g.u8("roll", 0):
            tiles.add(hud_picture(g, 0))
    check(places.get(0) == 1 and places.get(1) == 2, f"panels: places at the pickups {places}, expected player 1 first")
    for c in (ca, cb):
        check(g.u8("cells", c) == 0 and g.cell_tiles(c) == floor_set(g, 0), f"panel {c} taken but cell {g.u8('cells', c)} tiles {g.cell_tiles(c)}")
    g.run(ROLL_FRAMES)
    for p, table in ((0, lead), (1, behind)):
        it, r = g.u8("item", p), g.u8("last_roll", p)
        check(it == table[r] and g.u8("roll", p) == 0, f"player {p + 1} drew {r} and holds item {it}, expected {table[r]}")
        check(g.oam(ITEM_SLOT(p))[2] == HUD_TILE[p] and hud_picture(g, p) == it,
              f"player {p + 1} HUD shows tile {g.oam(ITEM_SLOT(p))[2]} holding picture {hud_picture(g, p)} for item {it}")
    check(len(tiles & {1, 2, 3, 4}) >= 3, f"the item picture did not spin: pictures {tiles}")
    # holding an item, a kart leaves the next panel where it is
    held = g.u8("item", 0)
    c = TRK[0]["panels"][2]
    drive_over(g, 0, c, race_dir(c))
    check(g.u8("cells", cell_no(c)) == CELL_PANEL and g.u8("item", 0) == held and not g.u8("roll", 0),
          f"a kart holding item {held} took a panel: cell {g.u8('cells', cell_no(c))}, item {g.u8('item', 0)}")
    park(g, 0)
    # it comes back after PANEL_TICKS ticks of 4 frames
    g.run(PANEL_TICKS * 4 - (g.f - taken) - 8)
    check(g.u8("cells", ca) == 0, f"a panel came back after {g.f - taken} frames, expected {PANEL_TICKS * 4}")
    g.run(16)
    check(g.u8("cells", ca) == CELL_PANEL and g.cell_tiles(ca) == floor_set(g, 2),
          f"panel not back after {g.f - taken} frames: cell {g.u8('cells', ca)}, tiles {g.cell_tiles(ca)}")
    out["panel draws"] = {"leader": g.u8("item", 0), "behind": g.u8("item", 1)}


def use(g, p, it, hold=(B,)):
    g.set8("item", p, it)
    g.set8("roll", p, 0)
    tap(g, p, (X,), hold)
    check(g.u8("item", p) == 0, f"player {p + 1} pressed X but still holds item {it}")
    check(g.oam(ITEM_SLOT(p))[1] == 224, f"player {p + 1}'s item picture stays after use")


def boost_checks(g, out):
    """The boost holds the kart above its top speed for its time, also on the grass."""
    calm(g)
    park(g, 1)
    g.place(0, 560, 232, EAST)
    g.run(60, (B,), ())
    top = top_of(g, 0)
    use(g, 0, BOOST)
    check(g.kart(0)[2] == top + BOOST_EXTRA, f"boost: speed {g.kart(0)[2]}, expected {top + BOOST_EXTRA}")
    g.run(1, (B,), ())
    for s in (FX_SLOT(0), FX_SLOT(0) + 1):
        fx = g.oam(s)
        check(fx[1] != 224 and fx[1] + 16 <= 112 and (fx[0] + 12 <= 112 or fx[0] >= 140),
              f"boost: flame sprite at ({fx[0]},{fx[1]}), expected beside the kart inside player 1's half")
    g.shot("boost")
    g.place(0, 516, 120, WEST, top + BOOST_EXTRA)  # the outer grass
    g.run(30, (B,), ())
    check(g.kart(0)[2] == top + BOOST_EXTRA, f"boost on the grass: speed {g.kart(0)[2]}")
    left = g.u8("boost_t", 0)
    g.run(left + 1, (B,), ())
    check(g.u8("boost_t", 0) == 0 and g.kart(0)[2] < top + BOOST_EXTRA, f"boost never ended: {g.u8('boost_t', 0)} frames left")
    g.run(2, (B,), ())
    check(all(g.oam(s)[1] == 224 for s in (FX_SLOT(0), FX_SLOT(0) + 1)),
          f"boost over: the flame stays at {[g.oam(s)[:2] for s in (FX_SLOT(0), FX_SLOT(0) + 1)]}")
    check(left + 30 + 2 >= BOOST_FRAMES - 2, f"boost lasted {left + 32} frames, expected {BOOST_FRAMES}")
    g.run(20, (B,), ())
    check(g.kart(0)[2] <= 16, f"after the boost on the grass: speed {g.kart(0)[2]}")
    out["boost"] = top + BOOST_EXTRA


def shot_checks(g, out):
    """The shot flies ahead, bounces off the track edge, and spins the kart it hits, which drops coins."""
    calm(g)
    g.place(0, 700, 236, WEST)
    g.place(1, 560, 236, WEST)
    g.set8("coins", 1, 5)
    use(g, 0, SHOT, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    x0 = struct.unpack_from("<h", g.r.wram(), g.off("shot_x", 2 * i))[0] >> 4
    g.run(10)
    x1 = struct.unpack_from("<h", g.r.wram(), g.off("shot_x", 2 * i))[0] >> 4
    check(x0 - x1 >= 35, f"shot moved from x {x0} to {x1} in 10 frames")
    seen = [s for s in SHOT_SLOTS[0] if g.oam(s)[1] != 224]
    check(seen, "shot in flight: no sprite in player 1's half")
    g.shot("shot-in-flight")
    for _ in range(40):
        if not g.u8("shot_on", i):
            break
        g.run(1)
    check(not g.u8("shot_on", i) and g.u8("spin_t", 1) > 0, f"the shot did not hit player 2: spin {g.u8('spin_t', 1)}")
    check(g.u8("coins", 1) == 5 - COIN_LOSS, f"hit kart has {g.u8('coins', 1)} coins, expected {5 - COIN_LOSS}")
    check(g.u8("spin_t", 0) == 0, "the thrower spun too")
    g.set8("item", 1, BOOST)
    tap(g, 1, (X,))
    check(g.u8("item", 1) == BOOST, "a spinning kart used its item")
    g.set8("item", 1, 0)
    spin_checks(g, 1, out)
    # a shot thrown at the outer edge bounces back onto the road
    calm(g)
    park(g, 1)
    g.place(0, 640, 250, heading(-1, -1))
    use(g, 0, SHOT, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    ys, flipped = [], False
    for _ in range(30):
        g.run(1)
        dy = struct.unpack_from("<h", g.r.wram(), g.off("shot_dy", 2 * i))[0]
        ys.append(struct.unpack_from("<h", g.r.wram(), g.off("shot_y", 2 * i))[0] >> 4)
        flipped |= dy > 0
    check(flipped and min(ys) >= 206 and g.u8("shot_on", i), f"shot at the edge: bounced {flipped}, lowest y {min(ys)}")
    # and off the left straight's outer edge, across the x axis
    calm(g)
    g.place(0, 150, 480, heading(-1, 0))
    use(g, 0, SHOT, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    xs, flipped = [], False
    for _ in range(12):  # the road is 56 px wide: later it bounces back off the inner edge towards its thrower
        g.run(1)
        flipped |= struct.unpack_from("<h", g.r.wram(), g.off("shot_dx", 2 * i))[0] > 0
        xs.append(struct.unpack_from("<h", g.r.wram(), g.off("shot_x", 2 * i))[0] >> 4)
    check(flipped and min(xs) >= 106 and g.u8("shot_on", i),
          f"shot at the side edge: bounced {flipped}, x {xs}, on {g.u8('shot_on', i)}, hits {g.u16('hits', 0)}/{g.u16('hits', 1)}")
    # thrown along a straight into the corner, it turns with the road instead of coming straight back
    for x, y, d, turn in ((330, 240, (-1, 0), "dy"), (140, 600, (0, 1), "dx")):
        calm(g)
        park(g, 1)
        g.place(0, x, y, heading(*d))
        use(g, 0, SHOT, ())
        i = next(i for i in range(4) if g.u8("shot_on", i))
        turned = False
        for _ in range(60):
            g.run(1)
            turned |= struct.unpack_from("<h", g.r.wram(), g.off("shot_" + turn, 2 * i))[0] > 0
        check(turned and g.u8("spin_t", 0) == 0,
              f"shot thrown along the straight from ({x},{y}) into the corner: turned {turned}, thrower spin {g.u8('spin_t', 0)}")
    # thrown at the map edge from the grass, it comes back onto the map and flies on
    calm(g)
    g.place(0, 12, 600, heading(-1, 0))
    use(g, 0, SHOT, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    g.run(10)
    x = struct.unpack_from("<h", g.r.wram(), g.off("shot_x", 2 * i))[0] >> 4
    check(g.u8("shot_on", i) and 20 <= x < 1024, f"a shot thrown at the map edge is at x {x}")
    calm(g)


def spin_checks(g, p, out):
    """A hit kart spins for about a second through its views, takes no pedal, and then drives again."""
    shown, speeds, seen = set(), [], set()
    pad = [(B,), ()] if p == 0 else [(), (B,)]
    for f in range(SPIN_FRAMES + 2):
        o = g.oam(p)
        shown.add((o[2], (o[3] >> 6) & 1))
        o = g.oam(2 + (1 - p))  # the spinning kart in the other player's half
        if o[1] != 224:
            seen.add((o[2], (o[3] >> 6) & 1))
        if f == 20:
            g.shot("spin")
        if not g.u8("spin_t", p):
            break
        speeds.append(g.kart(p)[2])
        g.run(1, *pad)
    check(f >= SPIN_FRAMES - 4, f"spin lasted {f} frames, expected {SPIN_FRAMES}")
    check(len(shown) >= 6, f"spinning kart showed only {len(shown)} views: {sorted(shown)}")
    check(len(seen) >= 6, f"the other player saw the spinning kart in only {len(seen)} views: {sorted(seen)}")
    check(all(b <= a for a, b in zip(speeds, speeds[1:])), f"a spinning kart sped up: {speeds}")
    g.run(2, *pad)
    o = g.oam(p)
    check(o[2] == NEAR_TILE(p, 0) and not (o[3] >> 6) & 1, f"after the spin player {p + 1} shows tile {o[2]}")
    out["spin views"] = len(shown)


def peel_checks(g, out):
    """Slime dropped behind stays in the floor and spins the kart that drives over it."""
    calm(g)
    park(g, 1)
    g.place(0, 660, 232, WEST, 16)
    use(g, 0, PEEL, ())
    cells = [c for c in range(4096) if g.u8("cells", c) == CELL_PEEL]
    check(len(cells) == 1, f"slime cells after a drop: {cells}")
    c = cells[0]
    cx, cy = c & 63, c >> 6
    check(cx * 16 > 660 - 2 and g.cell_tiles(c) == floor_set(g, 3), f"slime at cell ({cx},{cy}), map tiles {g.cell_tiles(c)}")
    g.run(60)
    check(g.u8("cells", c) == CELL_PEEL, "the slime went away by itself")
    park(g, 0)
    mx, my = cell_mid((cx, cy))
    g.place(1, mx + 60, my, WEST)
    g.run(2)
    g.shot("slime")
    hits = g.u16("hits", 1)
    g.set8("boost_t", 1, 200)  # a boosting kart: the hit ends its boost
    drive_over(g, 1, (cx, cy), (-1, 0), frames=12)
    check(g.u8("spin_t", 1) > 0 and g.u16("hits", 1) == hits + 1, "the kart that drove over the slime did not spin")
    check(g.u8("boost_t", 1) == 0, f"a hit kart kept its boost: {g.u8('boost_t', 1)} frames")
    check(g.u8("cells", c) == 0 and g.cell_tiles(c) == floor_set(g, 0), f"slime stays after a hit: tiles {g.cell_tiles(c)}")
    # five drops: four stay, the oldest goes
    calm(g)
    park(g, 1)
    drops = []
    for k in range(5):
        g.place(0, 700 - 40 * k, 232, WEST)
        use(g, 0, PEEL, ())
        drops.append(next(c for c in range(4096) if g.u8("cells", c) == CELL_PEEL and c not in drops))
    g.run(1)
    have = [c for c in range(4096) if g.u8("cells", c) == CELL_PEEL]
    check(sorted(have) == sorted(drops[1:]) and g.cell_tiles(drops[0]) == floor_set(g, 0),
          f"after 5 drops slime lies in {have}, expected {drops[1:]}")
    # behind the kart lies a panel: the slime is not dropped and the item stays
    calm(g)
    pc = TRK[0]["panels"][3]
    mx, my = cell_mid(pc)
    if g.u8("cells", cell_no(pc)) == CELL_PANEL:
        g.place(0, mx + 24, my, EAST)
        g.set8("item", 0, PEEL)
        tap(g, 0, (X,), ())
        check(g.u8("item", 0) == PEEL and g.u8("cells", cell_no(pc)) == CELL_PANEL, "slime was dropped onto a panel")
    calm(g)


def sh16(g, name, i):
    return struct.unpack_from("<h", g.r.wram(), g.off(name, 2 * i))[0]


def cells_of(g, kind):
    ram, o = g.r.wram(), g.off("cells")
    return [c for c in range(4096) if ram[o + c] == kind]


def homing_checks(g, out):
    """A straight shot passes a kart 28 px off its line; a homing shot turns towards it and hits it."""
    for it in (SHOT, HOMING):
        calm(g)
        g.place(0, 300, 760, EAST)  # the bottom straight: the slime test left slime on the top one
        g.place(1, 460, 788, EAST)
        hits = g.u16("hits", 1)
        use(g, 0, it, ())
        i = next(i for i in range(4) if g.u8("shot_on", i))
        turned, f = False, 0
        for f in range(50):
            if not g.u8("shot_on", i):
                break
            g.run(1)
            turned |= sh16(g, "shot_dy", i) > 0
        if it == SHOT:
            check(g.u16("hits", 1) == hits and g.u8("shot_on", i), f"a straight shot hit a kart 28 px off its line: hits {g.u16('hits', 1) - hits}")
        else:
            check(turned and g.u16("hits", 1) == hits + 1 and g.u8("spin_t", 1) > 0,
                  f"the homing shot did not find the other kart: turned {turned}, hits {g.u16('hits', 1) - hits}, frames {f}")
            out["homing hit after"] = f
    # it follows the road's edge and keeps chasing: thrown at the outer edge, it bounces and still hits
    calm(g)
    g.place(0, 340, 790, heading(1, 1))
    g.place(1, 520, 770, EAST)
    hits = g.u16("hits", 1)
    use(g, 0, HOMING, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    for f in range(80):
        if not g.u8("shot_on", i):
            break
        g.run(1)
    check(g.u16("hits", 1) == hits + 1, f"a homing shot thrown at the edge did not hit: on {g.u8('shot_on', i)}, home {g.u8('shot_home', i)}")
    calm(g)
    # a homing shot whose step no longer fits its heading (it bounced) takes the heading its step gives, then turns 4 steps:
    # straight up, right, down or left when one step is 0, else the mirror, a quarter turn back or a quarter turn on of the old one
    table = list(struct.unpack_from("<128h", g.r.wram(), g.off("shot_step")))  # a shot's x step for each heading
    for name, dx, dy, old_ang, want in (("up", 0, -64, 77, 0), ("right", 64, 0, 77, 32), ("down", 0, 64, 77, 64), ("left", -64, 0, 77, 96),
                                        ("mirror", None, None, 10, 118), ("quarter back", None, None, 50, 14), ("quarter on", None, None, 20, 84)):
        calm(g)
        g.place(0, 300, 788, EAST)
        g.place(1, 700, 788, EAST)
        j = 0
        g.set8("shot_on", j, 1)
        g.set16("shot_life", j, 200)
        g.set8("shot_grace", j, 20)
        g.set8("shot_owner", j, 0)
        g.set8("shot_home", j, 2)
        g.set8("shot_ang", j, old_ang)
        g.r.poke(g.off("shot_x", 2 * j), struct.pack("<h", 400 * 16))
        g.r.poke(g.off("shot_y", 2 * j), struct.pack("<h", 788 * 16))
        if dx is None:
            dx, dy = table[want], -table[(want + 32) & 127]
        g.r.poke(g.off("shot_dx", 2 * j), struct.pack("<h", dx))
        g.r.poke(g.off("shot_dy", 2 * j), struct.pack("<h", dy))
        g.run(4)
        got = g.u8("shot_ang", j)
        check(min((got - want) % 128, (want - got) % 128) <= 4 and g.u8("shot_home", j) == 2,
              f"a homing shot ({name}) kept heading {got}, expected near {want}: home {g.u8('shot_home', j)}")
        g.set8("shot_on", j, 0)
        calm(g)


def triple_checks(g, out):
    """A triple item gives three uses: its picture for two, the single item's for the last."""
    calm(g)
    park(g, 1)
    g.place(0, 300, 804, EAST)
    g.set8("roll_item", 0, BOOST3)
    g.set8("roll", 0, 1)
    g.run(2)
    check(g.u8("item", 0) == BOOST3 and g.u8("uses", 0) == 3 and hud_picture(g, 0) == BOOST3,
          f"a drawn triple boost: item {g.u8('item', 0)}, uses {g.u8('uses', 0)}, picture {hud_picture(g, 0)}")
    for k, want in enumerate((BOOST3, BOOST, 0)):
        g.set8("boost_t", 0, 0)
        tap(g, 0, (X,), ())
        check(g.u8("boost_t", 0) >= BOOST_FRAMES - 2 and g.u8("item", 0) == want,
              f"triple boost, use {k + 1}: boost {g.u8('boost_t', 0)}, item {g.u8('item', 0)}, expected {want}, uses {g.u8('uses', 0)}, star {g.u16('star_t', 0)}")
        shown = g.oam(ITEM_SLOT(0))[1] != 224
        check(shown == bool(want) and (not want or hud_picture(g, 0) == want),
              f"triple boost, use {k + 1}: picture shown {shown}, holding {hud_picture(g, 0)}, expected {want}")
    calm(g)
    g.place(0, 300, 804, EAST)
    g.set8("item", 0, SHOT3)
    g.set8("uses", 0, 3)
    for k in range(3):
        tap(g, 0, (X,), ())
    flying = sum(g.u8("shot_on", i) for i in range(4))
    check(flying == 3 and g.u8("item", 0) == 0, f"a triple shot threw {flying} shots, item left {g.u8('item', 0)}")
    calm(g)
    g.place(0, 300, 804, EAST, 32)
    before = set(cells_of(g, CELL_PEEL))  # up to 4 from earlier checks: count the new cells, not the total
    g.set8("item", 0, PEEL3)
    g.set8("uses", 0, 3)
    for k in range(3):
        tap(g, 0, (X,), (B,))
        g.run(10, (B,), ())
    new = set(cells_of(g, CELL_PEEL)) - before
    check(g.u8("item", 0) == 0 and len(new) == 3 and g.u8("coins", 0) == 0,
          f"a triple slime dropped {len(new)} new slimes, item left {g.u8('item', 0)}, coins {g.u8('coins', 0)}")
    out["triples"] = flying
    calm(g)


def shield_checks(g, out):
    """The shield takes one hit and keeps its picture until then; the next hit spins the kart."""
    calm(g)
    g.place(0, 520, 804, EAST)
    g.place(1, 380, 804, EAST)
    g.set8("coins", 0, 4)
    g.set8("item", 0, SHIELD)
    tap(g, 0, (X,), ())
    check(g.u8("item", 0) == 0 and g.u16("shield_t", 0) >= SHIELD_FRAMES - 3 and hud_picture(g, 0) == SHIELD
          and g.oam(ITEM_SLOT(0))[1] != 224, f"shield: item {g.u8('item', 0)}, frames {g.u16('shield_t', 0)}, picture {hud_picture(g, 0)}")
    # a panel is left where it is while the shield's picture holds the item box
    c = TRK[0]["panels"][2]
    check(g.u8("cells", cell_no(c)) == CELL_PANEL, f"shield: panel {c} is not there to test with")
    drive_over(g, 0, c, race_dir(c))
    check(g.u8("cells", cell_no(c)) == CELL_PANEL and not g.u8("roll", 0), "a shielded kart took a panel")
    g.place(0, 520, 804, EAST)
    hits = g.u16("hits", 0)
    for k in range(2):
        use(g, 1, SHOT, ())
        i = next(i for i in range(4) if g.u8("shot_on", i))
        for _ in range(50):
            if not g.u8("shot_on", i):
                break
            g.run(1)
        g.run(1)
        if k == 0:
            check(g.u8("spin_t", 0) == 0 and g.u8("coins", 0) == 4 and g.u16("shield_t", 0) == 0 and g.oam(ITEM_SLOT(0))[1] == 224,
                  f"shielded kart hit: spin {g.u8('spin_t', 0)}, coins {g.u8('coins', 0)}, shield {g.u16('shield_t', 0)}")
        else:
            check(g.u8("spin_t", 0) > 0 and g.u16("hits", 0) == hits + 1, "the second shot did not hit once the shield was gone")
    # it runs out
    calm(g)
    g.set8("item", 0, SHIELD)
    tap(g, 0, (X,), ())
    g.set16("shield_t", 0, 2)
    g.run(3)
    check(g.u16("shield_t", 0) == 0 and g.oam(ITEM_SLOT(0))[1] == 224, f"the shield never ran out: {g.u16('shield_t', 0)}")
    calm(g)


def star_checks(g, out):
    """The star boosts, flashes the kart, spins the kart it touches, and no shot hurts it."""
    calm(g)
    park(g, 1)
    g.place(0, 300, 804, EAST)
    g.set8("item", 0, STAR)
    tap(g, 0, (X,), (B,))
    pals = set()
    for _ in range(20):
        g.run(1, (B,), ())
        pals.add((g.oam(0)[3] >> 1) & 7)
    top = top_of(g, 0)
    check(g.u16("star_t", 0) > 0 and g.kart(0)[2] == top + BOOST_EXTRA and pals == {0, PAL_YELLOW},
          f"star: frames {g.u16('star_t', 0)}, speed {g.kart(0)[2]} (top {top}), palettes {pals}")
    x, y = g.kart(0)[:2]
    g.place(1, x + 14, y, EAST)
    g.run(6, (B,), ())
    check(g.u8("spin_t", 1) > 0 and g.u8("spin_t", 0) == 0, f"star touch: spin {g.u8('spin_t', 0)} / {g.u8('spin_t', 1)}")
    calm(g)
    g.set16("star_t", 1, 200)  # and the other way round
    g.place(1, 300, 804, EAST, 20)
    g.place(0, 304, 804, EAST, 20)
    g.run(3)
    check(g.u8("spin_t", 0) > 0 and g.u8("spin_t", 1) == 0, f"star touch from player 2: spin {g.u8('spin_t', 0)} / {g.u8('spin_t', 1)}")
    calm(g)
    g.set16("star_t", 0, 200)
    g.place(0, 560, 804, EAST)
    g.place(1, 760, 804, WEST)
    hits = g.u16("hits", 0)
    use(g, 1, SHOT, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    for _ in range(60):
        if not g.u8("shot_on", i):
            break
        g.run(1)
    check(not g.u8("shot_on", i) and g.u8("spin_t", 0) == 0 and g.u16("hits", 0) == hits,
          f"a shot hurt a kart with a star: on {g.u8('shot_on', i)}, spin {g.u8('spin_t', 0)}")
    g.set16("star_t", 0, 1)
    g.run(3)
    check((g.oam(0)[3] >> 1) & 7 == 0, "the kart keeps flashing after the star")
    out["star speed"] = top + BOOST_EXTRA
    calm(g)


def jump_checks(g, out):
    """The jump lifts the kart high over slime, which stays where it is."""
    calm(g)
    park(g, 1)
    c = (30, 50)
    mx, my = cell_mid(c)
    g.set8("cells", cell_no(c), CELL_PEEL)
    g.place(0, mx - 30, my, EAST, 32)
    g.set8("item", 0, JUMP)
    tap(g, 0, (X,), (B,))
    lift = 0
    for _ in range(JUMP_FRAMES):
        g.run(1, (B,), ())
        lift = max(lift, g.u8("kart_lift", 0))
    x = g.kart(0)[0]
    check(lift >= 15 and x > mx + 16 and g.u8("spin_t", 0) == 0 and g.u8("cells", cell_no(c)) == CELL_PEEL,
          f"jump: lift {lift}, x {x} past {mx}, spin {g.u8('spin_t', 0)}, cell {g.u8('cells', cell_no(c))}")
    g.set8("cells", cell_no(c), 0)
    out["jump lift"] = lift
    # over the other kart without touching it
    calm(g)
    g.place(0, 300, 804, EAST, 32)
    g.place(1, 330, 804, EAST)
    bumps = g.u16("bumps")
    g.set8("item", 0, JUMP)
    tap(g, 0, (X,), (B,))
    g.run(30, (B,), ())
    check(g.u16("bumps") == bumps and g.kart(0)[0] > 340, f"jump over a kart: bumps {g.u16('bumps') - bumps}, x {g.kart(0)[0]}")
    # and a shot thrown at it passes harmlessly
    calm(g)
    g.place(0, 500, 804, EAST)
    g.place(1, 440, 804, EAST)
    hits = g.u16("hits", 0)
    g.set8("item", 0, JUMP)
    tap(g, 0, (X,), ())
    use(g, 1, SHOT, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    for _ in range(20):
        if not g.u8("shot_on", i):
            break
        g.run(1)
    check(not g.u8("shot_on", i) and g.u8("spin_t", 0) == 0 and g.u16("hits", 0) == hits and g.u8("air_t", 0) > 0,
          f"a shot at a jumping kart: on {g.u8('shot_on', i)}, spin {g.u8('spin_t', 0)}, in the air {g.u8('air_t', 0)}")
    calm(g)


def shrink_checks(g, out):
    """The other kart turns small in both halves and slow, for its time; a shield takes it instead."""
    calm(g)
    g.place(0, 300, 804, EAST)
    g.place(1, 390, 804, EAST)
    g.run(2)
    before = g.oam(2)
    use(g, 0, SHRINK, ())
    g.run(1)
    own, seen = g.oam(1), g.oam(2)
    check(g.u8("shrink_t", 1) > 0 and own[2] == MID_TILE(1, 0) and not own[4] and seen[2] != before[2] and not seen[4],
          f"shrink: frames {g.u8('shrink_t', 1)}, own tile {own[2]} large {own[4]}, seen tile {before[2]} -> {seen[2]} large {seen[4]}")
    g.shot("shrink")
    g.run(30, (), (B,))
    g.set8("boost_t", 1, 60)  # boosting too: still held to the small top speed
    x0 = g.kart(1)[0]
    g.run(30, (), (B,))
    moved = g.kart(1)[0] - x0
    check(g.kart(1)[2] <= SHRINK_TOP and moved <= 30 * SHRINK_TOP / 16 + 1,
          f"a shrunk kart reached speed {g.kart(1)[2]} and moved {moved} px in 30 frames, expected at most {SHRINK_TOP} ({30 * SHRINK_TOP / 16:.0f} px)")
    g.set8("shrink_t", 1, 1)
    g.run(3, (), (B,))
    check(g.oam(1)[2] == NEAR_TILE(1, 0) and g.oam(1)[4], f"after the shrink player 2 shows tile {g.oam(1)[2]}")
    calm(g)
    g.set16("shield_t", 1, 100)
    use(g, 0, SHRINK, ())
    check(g.u8("shrink_t", 1) == 0 and g.u16("shield_t", 1) == 0, f"a shield did not take the shrink: {g.u8('shrink_t', 1)}")
    calm(g)


def steal_checks(g, out):
    """Steal takes the other kart's item; with nothing to take it is kept."""
    calm(g)
    g.set8("item", 1, SHOT)
    g.set8("item", 0, STEAL)
    tap(g, 0, (X,), ())
    check(g.u8("item", 0) == SHOT and g.u8("item", 1) == 0 and hud_picture(g, 0) == SHOT and g.oam(ITEM_SLOT(1))[1] == 224,
          f"steal: items {g.u8('item', 0)} / {g.u8('item', 1)}, picture {hud_picture(g, 0)}")
    calm(g)
    g.set8("item", 0, STEAL)
    tap(g, 0, (X,), ())
    check(g.u8("item", 0) == STEAL, "steal was used up with nothing to take")
    calm(g)


def fake_checks(g, out):
    """The fake panel is dropped behind, drawn like a panel, and spins the kart that takes it."""
    calm(g)
    park(g, 1)
    g.place(0, 520, 790, EAST, 16)  # mid-road, between the coins and the panel
    use(g, 0, FAKE, ())
    cells = cells_of(g, CELL_FAKE)
    check(len(cells) == 1 and g.cell_tiles(cells[0]) == floor_set(g, 2), f"fake panels {cells}")
    c = cells[0]
    park(g, 0)
    hits = g.u16("hits", 1)
    drive_over(g, 1, (c & 63, c >> 6), (1, 0), frames=40, before=60)
    check(g.u8("spin_t", 1) > 0 and g.u16("hits", 1) == hits + 1 and g.u8("cells", c) == 0 and g.cell_tiles(c) == floor_set(g, 0),
          f"the fake panel: spin {g.u8('spin_t', 1)}, cell {g.u8('cells', c)}, tiles {g.cell_tiles(c)}")
    calm(g)


def slip_checks(g, out):
    """Close behind the other kart on its line for a second gives a boost; beside it, none."""
    for side, want in ((0, True), (-24, False)):
        calm(g)
        g.place(0, 400, 806, EAST, top_of(g, 0))
        g.place(1, 370, 806 + side, EAST, top_of(g, 1))
        got = None
        for f in range(100):
            g.run(1, (B,), (B,))
            if g.u8("boost_t", 1) and got is None:
                got = f
        check((got is not None) == want and not g.u8("boost_t", 0),
              f"slipstream {abs(side)} px to the side: boost after {got} frames, the kart ahead boosted {g.u8('boost_t', 0)}")
        if want:
            # 15 ticks of 4 frames, the first within 4 frames of the start
            check(55 <= got <= 60, f"slipstream boost after {got} frames, expected 56 to 59")
            out["slipstream after"] = got
    calm(g)


def second_set_checks(g, out):
    homing_checks(g, out)
    triple_checks(g, out)
    shield_checks(g, out)
    star_checks(g, out)
    jump_checks(g, out)
    shrink_checks(g, out)
    steal_checks(g, out)
    fake_checks(g, out)
    slip_checks(g, out)


def pad_checks(g, out):
    """A boost pad (its own surface) gives a short boost."""
    calm(g)
    park(g, 1)
    cell, d = TRK[0]["pads"][0]
    top = top_of(g, 0)
    got = 0
    mx, my = cell_mid(cell)
    g.place(0, mx - 30 * d[0], my - 30 * d[1], heading(*d), 30)
    for _ in range(20):
        g.run(1, (B,), ())
        got = max(got, g.u8("boost_t", 0))
    check(got >= PAD_FRAMES - 1 and g.kart(0)[2] == top + BOOST_EXTRA, f"boost pad: boost {got}, speed {g.kart(0)[2]}")
    out["pad"] = got
    calm(g)


def drift_checks(g, out):
    """Hop on R, land steering left: a drift that charges; letting go when charged gives a boost.
    Let go early, and nothing."""
    for hold, want in ((6, False), (30, True)):
        calm(g)
        park(g, 1)
        top = top_of(g, 0)
        g.place(0, 720, 232, WEST, top)
        g.run(1, (B,), ())
        y0 = g.oam(0)[1]
        g.run(1, (B, R, LEFT), ())
        check(g.u8("hop_t", 0) > 0, "R did not hop")
        g.run(3, (B, R, LEFT), ())
        check(g.oam(0)[1] < y0, f"hop: kart sprite at line {g.oam(0)[1]}, ground {y0}")
        g.run(HOP_FRAMES, (B, R, LEFT), ())
        check(g.s8("drift", 0) == -1, f"landing with R and left held: drift {g.s8('drift', 0)}")
        turn = kart_of(g, 0)[2]
        for keys, step in (((B, R, LEFT), turn + (turn >> 1)), ((B, R), turn), ((B, R, RIGHT), turn >> 1)):
            a0 = g.kart(0)[3]
            g.run(1, keys, ())
            got = (a0 - g.kart(0)[3]) & 0xFFFF
            check(got == step, f"drifting left with {keys}: turned {got}, expected {step}")
        g.run(hold, (B, R, LEFT), ())
        charged = g.u8("charge", 0)
        if want:
            check(charged >= DRIFT_CHARGE and g.oam(FX_SLOT(0))[1] != 224, f"drift: charge {charged}, sparks {g.oam(FX_SLOT(0))}")
            g.shot("drift-sparks")
        g.run(1, (B,), ())
        b = g.u8("boost_t", 0)
        check(g.s8("drift", 0) == 0 and (b >= DRIFT_FRAMES - 1) == want,
              f"let go after {hold} frames of drift (charge {charged}): boost {b}, expected {'one' if want else 'none'}")
    out["drift charge"] = charged
    calm(g)


def shots_in_view(g, p, home=0):
    """4 shots ahead of kart p, flying the way it faces, so both halves draw them; home: homing shots
    chasing kart home - 1, whose first turn takes the slowest way (a heading to work out after a bounce)."""
    x, y, _, angle = g.kart(p)
    a = 2 * math.pi * ((angle >> 8) & 127) / 128
    fx, fy = math.sin(a), -math.cos(a)
    for i, (ahead, side) in enumerate(((70, -10), (90, 10), (110, -14), (130, 14))):
        sx, sy = x + fx * ahead - fy * side, y + fy * ahead + fx * side
        g.r.poke(g.off("shot_x", 2 * i), struct.pack("<h", int(sx * 16)))
        g.r.poke(g.off("shot_y", 2 * i), struct.pack("<h", int(sy * 16)))
        g.r.poke(g.off("shot_dx", 2 * i), struct.pack("<h", int(fx * 64)))
        g.r.poke(g.off("shot_dy", 2 * i), struct.pack("<h", int(fy * 64)))
        g.set16("shot_life", i, 200)
        g.set8("shot_grace", i, 0)
        g.set8("shot_owner", i, p)
        g.set8("shot_home", i, home)
        g.set8("shot_ang", i, 1)
        g.set8("shot_on", i, 1)


def proj_checks(g, out):
    """Both karts face each other with 4 shots and 2 obstacles between them: all 14 sprites drawn, and the
    cost per thing."""
    calm(g)
    g.place(0, 700, 240, WEST)
    g.place(1, 560, 240, EAST)
    for i, (x, y) in enumerate(((650, 225), (640, 255), (620, 232), (610, 248))):
        g.r.poke(g.off("shot_x", 2 * i), struct.pack("<hh", x * 16, 0)[:2])
        g.r.poke(g.off("shot_y", 2 * i), struct.pack("<h", y * 16))
        g.set16("shot_dx", i, 0)
        g.set16("shot_dy", i, 0)
        g.set16("shot_life", i, 100)
        g.set8("shot_grace", i, 30)
        g.set8("shot_owner", i, 0)
        g.set8("shot_on", i, 1)
    for i, (x, y) in enumerate(((630, 228), (625, 252))):
        g.set16("ob_x", i, x * 16)
        g.set16("ob_y", i, y * 16)
        g.set16("ob_dx", i, 0)
        g.set16("ob_dy", i, 0)
        g.set16("ob_len", i, 1000)
        g.set8("ob_on", i, 1)
    g.run(1)
    shown = [s for s in [2, 3] + list(range(40, 48)) + list(range(60, 64)) if g.oam(s)[1] != 224]
    check(len(shown) == 14, f"projection: only slots {shown} drawn of the other karts, 4 shots and 2 obstacles in both halves")
    wrong = [s for s in list(range(40, 48)) + list(range(60, 64)) if g.oam(s)[4] or g.oam(s)[0] > 255]
    check(not wrong, f"projection: shots or obstacles in slots {wrong} have their high bits set")
    lines, n = g.u16("pj_lines"), g.u16("pj_count")
    check(n == 14 and lines <= MAX_PER_THING * n, f"projection: {lines} lines for {n} things, budget {MAX_PER_THING} each")
    out["projection"] = (lines, n)
    g.run(1)  # the picture shows the sprites a frame after they are written
    g.shot("busy")
    for p in (0, 1):  # the same scene, and both drop slime on the same frame
        g.set8("item", p, PEEL)
    g.run(1, (X,), (X,))
    g.run(1)
    peels = [c for c in range(4096) if g.u8("cells", c) == CELL_PEEL]
    check(len(peels) == 2, f"both dropping slime at once: slime in cells {peels}")
    for c in peels:  # clear them the way the game does: a kart drives over each
        drive_over(g, 0, (c & 63, c >> 6), (-1, 0), frames=12)
        calm(g)
    check(not any(g.u8("cells", c) == CELL_PEEL for c in peels), "the slime from the busy frame stayed")
    calm(g)


def rocket_countdown(g):
    """At the edges of the window: player 1 presses the pedal ROCKET_WINDOW frames before GO (a rocket
    start), player 2 two frames earlier (wheels spin). Returns the GO frame."""
    down = [False, False]
    while g.state() != ST_RACE:
        t = g.u16("timer")
        down[0] |= t <= ROCKET_WINDOW
        down[1] |= t <= ROCKET_WINDOW + 2
        g.run(1, (B,) if down[0] else (), (B,) if down[1] else ())
    check(g.u8("boost_t", 0) >= ROCKET_FRAMES - 2 and g.u8("wheelspin_t", 1) >= WHEELSPIN - 2,
          f"rocket start: player 1 boost {g.u8('boost_t', 0)}, player 2 wheelspin {g.u8('wheelspin_t', 1)}")
    x1 = g.kart(1)[0]
    g.run(WHEELSPIN - 5, (B,), (B,))
    check(g.kart(1)[0] == x1, "spinning wheels moved the kart")
    check(GRID[0][0] - g.kart(0)[0] > 80, f"rocket start: player 1 only reached x {g.kart(0)[0]}")
    # back to the grid, as the race's other checks expect: player 1 has crossed the start line
    calm(g)
    for p in (0, 1):
        g.place(p, *GRID[p], WEST)
        g.set8("lap", p, 0)
        g.set8("cp", p, NCP - 1)
        g.set8("frac", p, 0)
    g.run(2)
    return g.f

def park(g, p):
    """Out of the way, off the track: the middle of the map on the oval, a far corner elsewhere."""
    g.place(p, *((512, 512) if g.u8("track_no") == 0 else off_track_near(trk(g), 8)), WEST)


# ---------------------------------------------------------------- battles

def balloon_picture(g, slot):
    """(player, count) of the balloon picture a sprite shows, from the frames start_race copied in."""
    v = g.vram()
    t = g.oam(slot)[2]
    a = 0xC000 + t * 32
    got = v[a:a + 64] + v[a + 512:a + 576]
    for i in range(6):
        if BATTLE_PICS[i * 128:(i + 1) * 128] == got:
            return i // 3, i % 3 + 1
    return None


def battle_busy(g):
    """The arena's busiest frame: the karts facing each other with 4 shots and both obstacles between them."""
    calm(g)
    g.place(0, 512, 640, NORTH_A)
    g.place(1, 512, 480, SOUTH_A)
    for i, (x, y) in enumerate(((500, 600), (524, 590), (505, 560), (520, 540))):
        g.set16("shot_x", i, x * 16)
        g.set16("shot_y", i, y * 16)
        g.set16("shot_dx", i, 0)
        g.set16("shot_dy", i, 0)
        g.set16("shot_life", i, 100)
        g.set8("shot_grace", i, 30)
        g.set8("shot_owner", i, 0)
        g.set8("shot_on", i, 1)
    for i, (x, y) in enumerate(((470, 560), (554, 560))):
        g.set16("ob_x", i, x * 16)
        g.set16("ob_y", i, y * 16)
        g.set16("ob_dx", i, 0)
        g.set16("ob_dy", i, 0)
        g.set16("ob_len", i, 1000)
        g.set8("ob_on", i, 1)
    g.run(1, (X,), (X,))
    g.run(2)
    g.shot("battle-busy")
    calm(g)


def battle_name_clear(g, label):
    """The longest animal's name (the triceratops, player 2 here) has nothing written after it on its row: the count of balloons or
    coins is on the line below, so the two never run together ("TRICERATOPS3 COINS")."""
    w = g.u8("winner")
    for k, row in ((w, 11), (1 - w, 16)):
        name = NAMES[g.u8("pick", k)]
        rest = g.map_text(11 + len(name), row, 32 - 11 - len(name))
        check(not rest.strip(), f"{label}: row {row} has {rest.strip()!r} after the name {name!r}")
    check(NAMES[g.u8("pick", 1)] == "TRICERATOPS", f"{label}: player 2 is {NAMES[g.u8('pick', 1)]}, not the longest name")


def balloon_battle_checks(g, stats, out):
    """Balloons: 3 each, shown over each kart in both halves in its player's colour; no lap count; a hit pops
    one, a fall into a pit pops one; the kart with none left loses and the results say so."""
    for h in (0, 1):
        check(all(g.oam(4 + h * 10 + k)[1] == 224 for k in range(6)), f"balloon battle: half {h + 1} shows lap or place letters")
        check(balloon_picture(g, BAL_SLOT(h)) == (h, BALLOONS) and g.oam(BAL_SLOT(h))[1] < h * 112 + 81,
              f"balloon battle: half {h + 1}'s own balloons show {balloon_picture(g, BAL_SLOT(h))}")
        check(balloon_picture(g, BAL_SLOT(h) + 1) == (1 - h, BALLOONS),
              f"balloon battle: half {h + 1} shows the other kart's balloons as {balloon_picture(g, BAL_SLOT(h) + 1)} ({g.oam(BAL_SLOT(h) + 1)})")
    check((g.u8("place", 0), g.u8("place", 1)) == (2, 2), f"balloon battle: level at the start, but places {g.u8('place', 0)} {g.u8('place', 1)}")
    g.shot("balloon-battle")
    # the balloons keep the colours they had in their own palette: outline, white highlight, and the player's blue or red
    g.run(2)
    for h in (0, 1):
        bx, by = g.oam(BAL_SLOT(h))[:2]
        seen = box_colours(g, bx, by, 16)
        want = (MINI_OUTLINE, MINI_ROAD, MINI_BLUE if h == 0 else MINI_RED)
        lacking = [rgb for rgb in want if not shows(seen, rgb)]
        check(not lacking, f"balloon battle: player {h + 1}'s balloons lack the colours {lacking}: slot {g.oam(BAL_SLOT(h))} sees {sorted(seen)[:10]}")
    battle_busy(g)
    g.set8("balloons", 0, BALLOONS)
    g.set8("balloons", 1, BALLOONS)
    for want in (2, 1):
        calm(g)
        g.set8("shot_struck", 1, 1)
        g.run(2)
        check(g.u8("balloons", 1) == want and g.u8("spin_t", 1) > 0, f"balloon battle: a hit left {g.u8('balloons', 1)} balloons, expected {want}")
        check(balloon_picture(g, BAL_SLOT(1)) == (1, want), f"balloon battle: player 2's balloons show {balloon_picture(g, BAL_SLOT(1))} after a hit")
        # the kart behind draws from the trailing kart's panel table
        check((g.u8("place", 0), g.u8("place", 1)) == (1, 2), f"balloon battle: 3 against {want} balloons, places {g.u8('place', 0)} {g.u8('place', 1)}")
    calm(g)
    cx, cy, r = tracks.ARENA["pit_squares"][0]
    g.place(1, cx, cy + r + 10, NORTH_A, 20)
    for _ in range(FALL_FRAMES):
        g.run(1, (), (B,))
        if g.u8("fall_t", 1):
            break
    # while it sinks, neither a shot nor a star kart's touch hurts it
    g.set8("shot_struck", 1, 1)
    g.set16("star_t", 0, 30)
    x, y = g.kart(1)[:2]
    g.place(0, x, y + 4, NORTH_A)
    g.run(2)
    check(g.u8("fall_t", 1) and g.u8("balloons", 1) == 1, f"balloon battle: a sinking kart lost a balloon to a shot or a touch: {g.u8('balloons', 1)} left")
    park(g, 0)
    g.set16("star_t", 0, 0)
    for _ in range(FALL_FRAMES + 40):
        g.run(1, (), (B,))
        if g.u8("done_count"):
            break
    check(g.u8("balloons", 1) == 0 and g.u8("winner") == 0, f"balloon battle: after the fall player 2 has {g.u8('balloons', 1)} balloons, winner {g.u8('winner') + 1}")
    g.set8("balloons", 0, 1)  # what happens in the 1.5 s before the results does not change them
    g.wait_state(ST_RESULTS, 200)
    g.run(5)
    head = g.map_text(9, 2, 14)
    check(head == "BALLOON BATTLE", f"balloon battle results: heading {head!r}")
    check(g.map_text(22, 12, 10) == "3 BALLOONS" and g.map_text(22, 17, 3) == "OUT",
          f"balloon battle results: rows read {g.map_text(22, 12, 10)!r} and {g.map_text(22, 17, 3)!r}")
    battle_name_clear(g, "balloon battle results")
    check(g.map_text(7, 11, 3) == "1ST" and g.map_text(7, 16, 3) == "2ND",
          f"balloon battle results: places read {g.map_text(7, 11, 3)!r} and {g.map_text(7, 16, 3)!r}")
    g.shot("balloon-results")
    out["balloon pops"] = g.u16("pops", 1)


def coin_battle_checks(g, stats, out):
    """Coins: 60 s on the clock in each half; coins count past 10 but their speed only to 10; a taken coin
    comes back; when time runs out the most coins win, a tie going to the last to take the lead."""
    g.run(2)
    for h in (0, 1):
        tens, ones = g.oam(4 + h * 10)[2], g.oam(5 + h * 10)[2]
        check((tens, ones) == (GLYPH("6"), GLYPH("0")), f"coin battle: half {h + 1}'s clock shows tiles {tens} {ones}, expected 60")
    g.run(61)
    for h in (0, 1):
        tens, ones = g.oam(4 + h * 10)[2], g.oam(5 + h * 10)[2]
        check((tens, ones) == (GLYPH("5"), GLYPH("9")), f"coin battle: a second in, half {h + 1}'s clock shows tiles {tens} {ones}, expected 59")
    check(g.u8("leader_ready"), "coin battle: the leader shot's picture was not loaded after GO (a battle has no computer animals to wait for)")
    calm(g)
    park(g, 1)
    taken = [c for c in range(4096) if g.u8("cells", c) == CELL_COIN]
    c = taken[0]
    g.set8("coins", 0, 10)
    drive_over(g, 0, (c & 63, c >> 6), (1, 0), frames=12, before=8)
    if g.u8("coins", 0) != 11:
        drive_over(g, 0, (c & 63, c >> 6), (0, 1), frames=12, before=8)
    check(g.u8("coins", 0) == 11 and g.oam(ITEM_SLOT(0) + 2)[2] == GLYPH("1") and g.oam(ITEM_SLOT(0) + 3)[2] == GLYPH("1"),
          f"coin battle: 10 coins and one more makes {g.u8('coins', 0)}, shown {g.oam(ITEM_SLOT(0) + 2)[2]} {g.oam(ITEM_SLOT(0) + 3)[2]}")
    g.run(COIN_BACK + 4)
    check(g.u8("cells", c) == CELL_COIN, "coin battle: a taken coin did not come back")
    # speed: 20 coins drive as fast as 10
    g.set8("coins", 0, 20)
    g.place(0, 400, 700, EAST)
    g.run(60, (B,), ())
    check(g.kart(0)[2] == top_of(g, 0, 10), f"coin battle: 20 coins give top speed {g.kart(0)[2]}, expected {top_of(g, 0, 10)}")
    calm(g)
    # the lead: player 1 reaches 5 first, player 2 then ties: player 1 keeps it, and wins the tie
    g.set8("coins", 0, 4)
    g.set8("coins", 1, 5)
    g.set8("lead_p", 0, 1)
    c = next(c for c in range(4096) if g.u8("cells", c) == CELL_COIN)
    park(g, 1)
    drive_over(g, 0, (c & 63, c >> 6), (1, 0), frames=12, before=8)
    if g.u8("coins", 0) != 5:
        drive_over(g, 0, (c & 63, c >> 6), (0, 1), frames=12, before=8)
    check(g.u8("coins", 0) == 5 and g.u8("lead_p") == 1, f"coin battle: a tie took the lead from player 2 ({g.u8('coins', 0)} coins, lead {g.u8('lead_p') + 1})")
    # a hit that costs the leader its lead hands the lead mark to the other kart; places follow the coins
    calm(g)
    g.set8("coins", 0, 6)
    g.set8("coins", 1, 5)
    g.set8("lead_p", 0, 0)
    g.set8("shot_struck", 0, 1)
    g.run(2)
    check(g.u8("coins", 0) == 4 and g.u8("lead_p") == 1 and (g.u8("place", 0), g.u8("place", 1)) == (2, 1),
          f"coin battle: after a hit at 6 against 5: coins {g.u8('coins', 0)}, lead {g.u8('lead_p') + 1}, places {g.u8('place', 0)} {g.u8('place', 1)}")
    calm(g)
    # time runs out with player 1 ahead, though player 2 holds the lead mark: the most coins win
    g.set8("coins", 0, 7)
    g.set8("coins", 1, 3)
    g.set16("battle_time", 0, 5)
    for _ in range(20):
        g.run(1)
        if g.u8("done_count"):
            break
    g.set8("coins", 1, 50)  # what happens in the 1.5 s before the results does not change them
    g.wait_state(ST_RESULTS, 200)
    g.run(5)
    check(g.u8("winner") == 0, f"coin battle: 7 against 3 coins, winner {g.u8('winner') + 1}")
    check(g.map_text(11, 2, 11) == "COIN BATTLE" and g.map_text(22, 12, 7) == "7 COINS" and g.map_text(22, 17, 7) == "3 COINS",
          f"coin battle results: {g.map_text(11, 2, 11)!r}, {g.map_text(22, 12, 7)!r}, {g.map_text(22, 17, 7)!r}")
    battle_name_clear(g, "coin battle results")
    check(g.map_text(7, 11, 3) == "1ST" and g.map_text(7, 16, 3) == "2ND",
          f"coin battle results: places read {g.map_text(7, 11, 3)!r} and {g.map_text(7, 16, 3)!r}")
    g.shot("coin-results")
    # a rematch from the results: a tie goes to the last to take the lead, here player 2
    g.run(RESULTS_WAIT + 5)
    start_race(g, 0)
    g.run(2)
    clock = (g.oam(4)[2], g.oam(5)[2])
    countdown(g)
    check(g.u8("battle") == 2 and g.u8("track_no") == ARENA_NO, "coin battle rematch is not a coin battle on the arena")
    check(clock == (GLYPH("6"), GLYPH("0")) and g.u8("lead_p") == 0, f"coin battle rematch: clock tiles {clock} in the countdown, lead {g.u8('lead_p') + 1}")
    calm(g)
    g.set8("coins", 0, 4)
    g.set8("coins", 1, 4)
    c = next(c for c in range(4096) if g.u8("cells", c) == CELL_COIN)
    park(g, 0)
    drive_over(g, 1, (c & 63, c >> 6), (1, 0), frames=12, before=8)
    if g.u8("coins", 1) != 5:
        drive_over(g, 1, (c & 63, c >> 6), (0, 1), frames=12, before=8)
    g.set8("coins", 0, 5)
    g.set16("battle_time", 0, 5)
    g.wait_state(ST_RESULTS, 200)
    check(g.u8("lead_p") == 1 and g.u8("winner") == 1, f"coin battle: a 5-5 tie went to player {g.u8('winner') + 1}, lead {g.u8('lead_p') + 1}")


# ---------------------------------------------------------------- tracks, menus and the cup

def menu_checks(g):
    """After both picks: the track menu lists the cup and the four tracks; the cursor wraps both ways."""
    g.wait_state(ST_TRACKS, START_WAIT + 10)
    g.run(SELECT_WAIT + 2)
    check(g.map_text(8, MENU_ROWS[0], 20) == "CUP: ALL FOUR TRACKS", f"track menu: first row reads {g.map_text(8, MENU_ROWS[0], 20)!r}")
    for i, name in enumerate(TRACK_NAMES):
        check(g.map_text(8, MENU_ROWS[i + 1], len(name)) == name, f"track menu: row {i + 1} reads {g.map_text(8, MENU_ROWS[i + 1], len(name))!r}")
    for p in (0, 1):  # both animals shown
        x, y, tile, attr, large = g.oam(4 + p)
        check(tile == BUST_TILE(g.u8("pick", p)) and large and y < 112, f"track menu: player {p + 1}'s portrait {g.oam(4 + p)}")
    for row, name in ((5, "BALLOON BATTLE"), (6, "COIN BATTLE")):
        check(g.map_text(8, MENU_ROWS[row], len(name)) == name, f"track menu: row {row} reads {g.map_text(8, MENU_ROWS[row], len(name))!r}")
    for port, key, want in ((0, UP, 6), (1, DOWN, 0), (1, DOWN, 1)):
        g.press(port, key)
        menu_cursor_check(g, want)
    # the random number steps on every menu frame, not only in races: 20 idle frames are 20 steps
    r0 = g.u16("rng")
    g.run(20)
    want = r0
    for _ in range(20):
        want = rng_step(want)
    check(g.u16("rng") == want and r0 != want, f"track menu: the random number went from {r0:#06x} to {g.u16('rng'):#06x} in 20 idle frames, expected {want:#06x}")
    # below the menu: a blank row, the computer karts line, a blank row, then the help (which says how to change the number)
    check(not g.map_text(0, CPU_ROW - 1, 32).strip() and not g.map_text(0, CPU_ROW + 1, 32).strip(),
          f"track menu: the rows around the computer karts line read {g.map_text(0, CPU_ROW - 1, 32)!r} and {g.map_text(0, CPU_ROW + 1, 32)!r}, expected blank")
    check(g.map_text(1, CPU_ROW + 2, 31) == "D-PAD: CHOOSE  B: RACE  Y: BACK" and g.map_text(1, CPU_ROW + 3, 26) == "LEFT/RIGHT: COMPUTER KARTS",
          f"track menu: the help reads {g.map_text(1, CPU_ROW + 2, 31)!r} and {g.map_text(1, CPU_ROW + 3, 26)!r}")
    cpu_menu_checks(g)


def cpu_row_check(g, want):
    """The number of computer karts is held, and the line under the menu shows it (or NONE with a battle under the cursor)."""
    n = g.u8("cpu_menu")
    check(n == want, f"track menu: {n} computer karts chosen, expected {want}")
    txt = "COMPUTER KARTS: " + ("NONE" if g.u8("menu_pos") > 4 else str(want) + "   ")
    check(g.map_text(8, CPU_ROW, 20) == txt, f"track menu: the computer karts line reads {g.map_text(8, CPU_ROW, 20)!r}, expected {txt!r}")


def cpu_menu_checks(g):
    """The line COMPUTER KARTS: it starts on the most, left and right on either pad count down and up and wrap round
    between 0 and the most, a battle under the cursor shows NONE and left and right leave the choice alone. Ends on 0
    with the cursor on the first track, which is what the other checks of the game expect."""
    check(g.u8("cpu_n") == 0, f"power-on: {g.u8('cpu_n')} computer karts racing before any race")
    cpu_row_check(g, CPU_FIT)
    g.shot("track-menu-computer")
    for port, key, want in ((0, LEFT, 2), (1, LEFT, 1), (0, LEFT, 0), (1, LEFT, CPU_FIT), (0, RIGHT, 0), (1, RIGHT, 1), (0, RIGHT, 2)):
        g.press(port, key)
        cpu_row_check(g, want)
    for _ in range(4):  # down to the first battle
        g.press(0, DOWN)
    menu_cursor_check(g, 5)
    cpu_row_check(g, 2)
    for key in (LEFT, RIGHT):
        g.press(0, key)
        cpu_row_check(g, 2)
    g.press(0, UP)
    cpu_row_check(g, 2)
    g.press(0, LEFT)
    g.press(0, LEFT)
    cpu_row_check(g, 0)
    for _ in range(3):
        g.press(0, UP)
    menu_cursor_check(g, 1)
    cpu_row_check(g, 0)


def menu_cursor_check(g, want):
    check(g.u8("menu_pos") == want, f"track menu: cursor on row {g.u8('menu_pos')}, expected {want}")
    marks = [i for i, r in enumerate(MENU_ROWS) if g.map_text(6, r, 1) == ">"]
    check(marks == [want], f"track menu: the cursor shows on rows {marks}, expected {want}")


def rng_step(r):
    """One step of the game's random number (main.c main, proj.asm clock_step): a 16-bit shift register with taps $B400."""
    return (r >> 1) ^ (0xB400 if r & 1 else 0)


def rng_unstep(r):
    """The value rng_step() turns into r."""
    return (((r ^ 0xB400) << 1) | 1) & 0xFFFF if r & 0x8000 else (r << 1) & 0xFFFF


def choose(g, port, pos, rng=None):
    """Moves the track menu's cursor to `pos` and presses B: a race on that track, or the cup. With `rng`, that is the random
    number the race start picks the computer animals with: the menu steps it every frame, so it is set to the value that steps
    into it before each frame until the race starts."""
    while g.u8("menu_pos") != pos:
        g.press(port, DOWN)
    menu_cursor_check(g, pos)
    for i in range(40):
        if rng is not None:
            g.set16("rng", 0, rng_unstep(rng))
        g.run(1, *([(B,), ()] if port == 0 and i < 3 else [(), (B,)] if i < 3 else [(), ()]))
        if g.state() == ST_COUNTDOWN:
            break
    check(g.state() == ST_COUNTDOWN and i < 12, f"B on the track menu row {pos} did not start a race within 12 frames ({i})")
    g.countdown_from = g.f
    want_track = 0 if pos == 0 else ARENA_NO if pos >= 5 else pos - 1
    want_battle = {5: 1, 6: 2}.get(pos, 0)
    check(g.u8("cup_on") == (pos == 0) and g.u8("track_no") == want_track and g.u8("battle") == want_battle,
          f"track menu row {pos}: cup {g.u8('cup_on')}, track {g.u8('track_no')}, battle {g.u8('battle')}")
    want_cpu = 0 if want_battle else min(g.u8("cpu_menu"), CPU_FIT)
    check(g.u8("cpu_n") == want_cpu, f"track menu row {pos}: the race has {g.u8('cpu_n')} computer karts, expected {want_cpu} (menu {g.u8('cpu_menu')})")


def race_loads_track(g, n, label):
    """Track n's tiles, map, starting cells and minimap are loaded, and both karts stand on its grid."""
    res = os.path.join(ROOT, "game", "res")
    v = g.vram()
    tiles = open(os.path.join(res, f"trk{n}.pc7"), "rb").read()
    check(g.u8("track_no") == n, f"{label}: track {g.u8('track_no')} raced, expected {n}")
    check(v[1:2 * len(tiles):2] == tiles, f"{label}: the track's tiles are not in video memory")
    check(v[0:0x8000:2] == open(os.path.join(res, f"trk{n}.mp7"), "rb").read(), f"{label}: the track's map is not in video memory")
    check(bytes(g.r.wram()[g.off("cells"):g.off("cells") + 4096]) == open(os.path.join(res, f"trk{n}.cells"), "rb").read(),
          f"{label}: the floor cells are not the track's")
    mini = open(os.path.join(res, f"trk{n}.mini"), "rb").read()
    for r in range(4):
        a = 0xC000 + (TILE_MINIMAP + 16 * r) * 32
        check(v[a:a + 128] == mini[r * 128:(r + 1) * 128], f"{label}: minimap row {r} not in the sprite tiles")
    d = TRK[n]
    if not d["arena"]:
        _, _, sdx, sdy = tracks.point_at(d["route"], 0.0)
        check(d["angle"] == heading(sdx, sdy), f"{label}: the grid faces {d['angle'] >> 8}, the road at the start line {heading(sdx, sdy) >> 8}")
    for p in (0, 1):
        x, y, speed, angle = g.kart(p)
        check((x, y, angle) == (*d["grid"][p], d["angles"][p]), f"{label}: player {p + 1} starts at ({x},{y}) angle {angle}")
    surf = open(os.path.join(res, f"trk{n}.surf"), "rb").read()
    bad = [k for k, (x, y, a) in enumerate(d["rescue"]) if surf[(y // 8) * 128 + x // 8] != tracks.S_ROAD]
    check(not bad, f"{label}: rescue points of checkpoints {bad} are not on plain road")


def minimap_checks(g):
    """Each half shows the minimap in its corner and a dot for each kart where that kart is."""
    g.run(1)
    for h in (0, 1):
        x, y, tile, attr, large = g.oam(MINI_SLOT(h))
        check((x, y, tile, (attr >> 1) & 7, large) == (MINI_X, h * 112 + MINI_Y, TILE_MINIMAP, PAL_WHITE, 1),
              f"minimap in half {h + 1}: {g.oam(MINI_SLOT(h))}")
        for k in (0, 1):
            kx, ky, _, _ = g.kart(k)
            x, y, tile, attr, large = g.oam(DOT_SLOT(k, h))
            want = (MINI_X - 7 + (kx >> 5), h * 112 + MINI_Y - 7 + (ky >> 5), TILE_DOT[k], PAL_WHITE, 0)
            check((x, y, tile, (attr >> 1) & 7, large) == want, f"minimap dot of player {k + 1} in half {h + 1}: {(x, y, tile)}, expected {want}")
    g.run(1)
    g.shot("minimap")
    # the colours are the ones the minimap had in its own palette: outline and road in the picture, a blue dot
    # for player 1 and a red one for player 2 at the middle of their sprites (CGRAM is not readable)
    for h in (0, 1):
        seen = box_colours(g, MINI_X, h * 112 + MINI_Y, 32)
        for name, rgb in (("outline", MINI_OUTLINE), ("road", MINI_ROAD)):
            check(shows(seen, rgb), f"minimap in half {h + 1} lacks its {name} colour {rgb}")
    saved = bytes(g.r.wram()[g.off("karts"):g.off("karts") + 24])
    g.place(1, 800, 700, WEST)  # apart, so one dot does not cover the other on the minimap
    g.run(2)
    for h in (0, 1):
        for k, rgb in ((0, MINI_BLUE), (1, MINI_RED)):
            x, y = g.oam(DOT_SLOT(k, h))[:2]
            got = pixel(g, x + 7, y + 7)
            check(close(got, rgb), f"minimap dot of player {k + 1} in half {h + 1} is {got}, expected {rgb}")
    g.r.poke(g.off("karts"), saved)
    g.run(2)


def wrong_way_checks(g, out):
    """Driving backwards past a checkpoint shows the wrong-way sign in that half; turned back, it goes."""
    calm(g)
    park(g, 1)
    g.place(0, 600, 240, EAST, 30)  # the top straight runs west
    seen = 0
    for f in range(40):
        g.run(1, (B,), ())
        if g.oam(WRONG_SLOT(0))[1] != 224:
            seen = seen or f
    o = g.oam(WRONG_SLOT(0))
    check(seen and o[2] == TILE_WRONG and o[1] < 112, f"wrong way: the sign never showed in player 1's half ({o})")
    check(g.oam(WRONG_SLOT(1))[1] == 224, "wrong way: the sign showed in player 2's half")
    g.run(1)
    g.shot("wrong-way")
    g.place(0, g.kart(0)[0], 240, WEST, 30)
    for f in range(30):
        g.run(1, (B,), ())
        if g.oam(WRONG_SLOT(0))[1] == 224:
            break
    check(g.oam(WRONG_SLOT(0))[1] == 224, "wrong way: the sign stayed after turning back")
    out["wrong way after"] = seen
    calm(g)


def drive_from_grid(g, stats):
    """Both drive from the grid for 2 s; the picture matches the tables on the way."""
    go, fd0 = g.f, g.u16("frames_done")
    for t in range(1, 121):
        g.run(1, (B,), (B,))
        if t in (70, 120):  # GO has gone at 60
            picture_checks(g, f"track {g.u8('track_no') + 1}, {t} frames after GO", stats)
    stats["frames"] += g.f - go
    stats["done"] += (g.u16("frames_done") - fd0) & 0xFFFF


def approach(g, p, x, y, dx, dy, back, speed, keys=(B,)):
    """Kart p `back` px before (x, y) heading (dx, dy) at `speed`, holding `keys` from the next frame."""
    g.place(p, x - back * dx, y - back * dy, heading(dx, dy), speed)


def oil_sand_checks(g, out):
    """Sandy Twist: oil spins a kart without costing coins; a sand drift slows it like the off-road."""
    calm(g)
    park(g, 1)
    t = tracks.TRACKS[1]
    x, y, dx, dy = tracks.point_at(trk(g)["route"], *t["oil"][0])
    g.set8("coins", 0, 4)
    approach(g, 0, x, y, dx, dy, 30, 32)
    for _ in range(20):
        g.run(1, (B,), ())
        if g.u8("spin_t", 0):
            break
    check(g.u8("spin_t", 0) >= SPIN_FRAMES - 4 and g.u8("coins", 0) == 4, f"oil: spin {g.u8('spin_t', 0)} (expected {SPIN_FRAMES}), coins {g.u8('coins', 0)}")
    g.shot("oil")
    # a kart crawling on the oil below OIL_SPEED is not spun again, or one that spun to a halt there would never get out
    g.place(0, x, y, heading(dx, dy), 8)
    g.set8("spin_t", 0, 0)
    g.run(6, (B,), ())
    check(not g.u8("spin_t", 0) and 8 <= g.kart(0)[2] < OIL_SPEED, f"oil: a kart crawling on the oil at speed {g.kart(0)[2]} spun ({g.u8('spin_t', 0)})")
    park(g, 0)  # off the oil first: calm() runs a frame, and oil spins a kart again
    calm(g)
    frac, lat, r = t["sand"][0]
    x, y, dx, dy = tracks.point_at(trk(g)["route"], frac, lat)
    approach(g, 0, x, y, dx, dy, 4, kart_of(g, 0)[1])
    g.run(14, (B,), ())
    check(g.kart(0)[2] == MAX_GRASS and not g.u8("spin_t", 0),
          f"sand: speed {g.kart(0)[2]} (spin {g.u8('spin_t', 0)}) after 14 frames in the drift, expected {MAX_GRASS}")
    out["sand speed"] = g.kart(0)[2]
    calm(g)


def ob_pos(g, i=0):
    """Obstacle i's position in 1/16 map pixels."""
    ram = g.r.wram()
    return struct.unpack_from("<h", ram, g.off("ob_x", 2 * i))[0], struct.unpack_from("<h", ram, g.off("ob_y", 2 * i))[0]


def obstacle_checks(g, out):
    """An obstacle rolls across the road and back, shows in the half that sees it, and spins the kart it hits."""
    calm(g)
    park(g, 1)
    n = g.u8("track_no")
    x0, y0, x1, y1, frames = TRK[n]["obstacles"][0]
    g.set16("ob_x", 0, round(x0 * 16))
    g.set16("ob_y", 0, round(y0 * 16))
    g.set16("ob_dx", 0, round((x1 - x0) * 16 / frames))
    g.set16("ob_dy", 0, round((y1 - y0) * 16 / frames))
    g.set16("ob_len", 0, frames)
    g.set16("ob_t", 0, 0)
    g.set8("ob_on", 0, 1)
    # watch it from 70 px before its path's middle, along the road
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    fx, fy = (y1 - y0), -(x1 - x0)  # along the road: the path runs across it
    nrm = math.hypot(fx, fy)
    fx, fy = fx / nrm, fy / nrm
    g.place(0, mx - 70 * fx, my - 70 * fy, heading(fx, fy))
    g.run(frames)
    ox, oy = ob_pos(g)
    check(abs(ox / 16 - x1) < 3 and abs(oy / 16 - y1) < 3, f"obstacle after {frames} frames at ({ox / 16:.0f},{oy / 16:.0f}), expected ({x1:.0f},{y1:.0f})")
    g.run(frames // 2)
    ox2, oy2 = ob_pos(g)
    mid = math.hypot(ox2 / 16 - (x0 + x1) / 2, oy2 / 16 - (y0 + y1) / 2)
    check(mid < 4, f"obstacle half way back should be at its path's middle, is {mid:.0f} px from it")
    seen = [s for s in OB_SLOTS[0] if g.oam(s)[1] != 224]
    check(seen and g.oam(seen[0])[2] in OB_TILES, f"obstacle 70 px ahead not drawn in player 1's half: {[g.oam(s) for s in OB_SLOTS[0]]}")
    g.run(1)
    g.shot("obstacle")
    # the obstacle shows the track's own five colours (CGRAM is not readable, so the screen is the check)
    ox, oy = g.oam(seen[0])[:2]
    look = gen_assets.OB_PALS.get(tracks.TRACKS[n]["look"], gen_assets.OB_PAL_DEFAULT)
    got = box_colours(g, ox, oy, 16)
    lacking = [rgb for rgb in look if not shows(got, rgb)]
    check(not lacking, f"obstacle on track {n + 1} lacks its colours {lacking} (look {tracks.TRACKS[n]['look']})")
    # put it on the kart: a hit
    g.set8("coins", 0, 5)
    hits = g.u16("hits", 0)
    kx, ky, _, _ = g.kart(0)
    g.set16("ob_x", 0, (kx + 6) * 16)
    g.set16("ob_y", 0, ky * 16)
    g.set16("ob_dx", 0, 0)
    g.set16("ob_dy", 0, 0)
    g.run(2)
    check(g.u8("spin_t", 0) > 0 and g.u16("hits", 0) == hits + 1 and g.u8("coins", 0) == 5 - COIN_LOSS,
          f"obstacle on the kart: spin {g.u8('spin_t', 0)}, hits {g.u16('hits', 0) - hits}, coins {g.u8('coins', 0)}")
    out[f"obstacle {n}"] = frames
    calm(g)


def ramp_cells(d):
    """The ramp row's middle cell, its direction, and where the gap beyond it ends."""
    cells = [c for c, _ in d["ramps"]]
    c = cells[len(cells) // 2]
    return c, d["ramps"][0][1]


def jump(g, p, cell, direction, speed, keys=()):
    """Kart p drives onto the ramp at `speed` (at top speed holding the pedal from 24 px before it, slower
    coasting from 2 px before); returns (frames in the air, highest lift, the jump's length)."""
    mx, my = cell_mid(cell)
    dx, dy = direction
    fast = speed >= kart_of(g, p)[1]
    back = 8 + (24 if fast else 2)
    g.place(p, mx - back * dx, my - back * dy, heading(dx, dy), speed)
    v = int(trk(g)["prog"][int(my - back * dy) // 16, int(mx - back * dx) // 16])
    g.set8("cp", p, v >> 3)  # the checkpoint a kart driving here would have reached
    g.set8("fine", p, v)
    air, lift, lens = 0, 0, 0
    g.air_spin = 0  # the most the shown heading was turned while in the air
    pad_keys = (B,) if fast else ()
    for f in range(120):
        k = pad_keys + (tuple(keys) if 4 <= air <= 6 else ())
        g.run(1, *([k, ()] if p == 0 else [(), k]))
        if g.u8("air_t", p):
            air += 1
            lens = g.u8("air_len", p)
            lift = max(lift, g.u8("kart_lift", p))
            g.air_spin = max(g.air_spin, g.u8("spin_off", p))
            if air == 10 and keys:
                g.shot("ramp-trick")
            elif air == 10 and speed >= 32:
                g.shot("ramp-jump")
        elif air:
            break
    return air, lift, lens


def ramp_checks(g, out):
    """Frosty Peaks: the ramp lifts a kart longer and higher at speed; fast, it clears the crevasse, and L in
    the air gives the trick's boost on landing; slow, it falls in, sinks from view, and is put back on its
    last checkpoint after a pause, two coins lighter."""
    d = trk(g)
    cell, direction = ramp_cells(d)
    calm(g)
    park(g, 1)
    top = kart_of(g, 0)[1]
    fast = jump(g, 0, cell, direction, top)
    check(not g.u8("fall_t", 0) and fast[0] >= top - 2, f"fast jump: {fast[0]} frames in the air, fall {g.u8('fall_t', 0)}")
    check(g.u8("boost_t", 0) == 0, f"a jump without the trick boosted: {g.u8('boost_t', 0)}")
    calm(g)
    # another button in the air (X, with no item) is not a trick: neither L nor R was pressed, so no turn and no boost on landing
    other = jump(g, 0, cell, direction, top, keys=(X,))
    check(other[0] >= top - 2 and g.air_spin == 0 and g.u8("boost_t", 0) == 0 and not g.u8("trick", 0),
          f"ramp: X pressed in the air gave a trick: air {other[0]}, turn {g.air_spin}, boost {g.u8('boost_t', 0)}, trick {g.u8('trick', 0)}")
    calm(g)
    slow = jump(g, 0, cell, direction, 18)
    check(slow[0] < fast[0] and slow[1] < fast[1], f"ramp: slow jump {slow}, fast jump {fast}: not longer at speed")
    out["jump frames slow/fast"] = (slow[0], fast[0])
    out["jump lift slow/fast"] = (slow[1], fast[1])
    # the slow one fell into the crevasse
    for _ in range(10):
        if g.u8("fall_t", 0):
            break
        g.run(1)
    check(g.u8("fall_t", 0) > 0, "a slow jump did not fall into the crevasse")
    calm_fall(g, 0)
    # put back before the ramp, with room to get up to speed: driving on, it clears the crevasse
    mx, my = cell_mid(cell)
    kx, ky, _, _ = g.kart(0)
    before = -((kx - mx) * direction[0] + (ky - my) * direction[1])
    check(before >= 100, f"crevasse: rescued {before:.0f} px before the ramp, expected at least 100")
    for _ in range(150):
        g.run(1, (B,), ())
        if g.u8("fall_t", 0):
            break
    check(not g.u8("fall_t", 0), "crevasse: driving on from the rescue point fell in again")
    # a ramp under a kart at speed 2 or less lifts nothing
    park(g, 0)
    calm(g)
    mx, my = cell_mid(cell)
    g.place(0, mx, my, heading(*direction), 2)
    g.run(2)
    check(not g.u8("air_t", 0), f"a kart at speed 2 on the ramp was lifted: {g.u8('air_t', 0)} frames in the air")
    park(g, 0)
    calm(g)
    # the trick: L pressed in the air
    calm(g)
    trick = jump(g, 0, cell, direction, top, keys=(L,))
    check(g.u8("boost_t", 0) >= TRICK_FRAMES - 2 and not g.u8("fall_t", 0),
          f"ramp trick: boost {g.u8('boost_t', 0)} after landing, fall {g.u8('fall_t', 0)}")
    out["trick boost"] = g.u8("boost_t", 0)
    check(g.air_spin > 0, "ramp trick: the kart did not turn in the air")
    check(g.u8("trick_t", 0) == 0 and g.u8("spin_off", 0) == 0,
          f"ramp trick: still turning after landing (trick_t {g.u8('trick_t', 0)}, spin_off {g.u8('spin_off', 0)})")
    calm(g)


def calm_fall(g, p):
    """A kart has just fallen in: it sinks from view, and after FALL_FRAMES is put back in the middle of
    its last checkpoint, facing on, with 2 coins less."""
    g.set8("coins", p, 5)
    rescues = g.u16("rescues", p)
    cp = g.u8("cp", p)
    kx, ky, _, ka = g.kart(p)  # the other kart 70 px behind, looking at it
    a = 2 * math.pi * ((ka >> 8) & 127) / 128
    g.place(1 - p, kx - 70 * math.sin(a), ky + 70 * math.cos(a), ka)
    sunk = seen = False
    frames = 0
    for _ in range(FALL_FRAMES + 5):
        g.run(1)
        frames += 1
        sunk |= g.oam(p)[1] == 224
        seen |= g.u8("fall_t", p) > 2 and g.oam(2 + (1 - p))[1] != 224  # the other half shows it
        if g.u16("rescues", p) != rescues:
            break
    check(frames >= FALL_FRAMES - 12, f"a kart that fell in was put back after {frames} frames, expected about {FALL_FRAMES}")
    x, y, speed, angle = g.kart(p)
    rx, ry, ra = trk(g)["rescue"][cp]
    check(g.u16("rescues", p) == rescues + 1 and (x, y, angle, speed) == (rx, ry, ra, 0) and g.u8("coins", p) == 5 - COIN_LOSS,
          f"rescue: kart at ({x},{y}) angle {angle} speed {speed} coins {g.u8('coins', p)}, expected ({rx},{ry}) angle {ra} with {5 - COIN_LOSS}")
    check(sunk and not seen, f"a kart that fell in stayed in view (own half {not sunk}, other half {seen})")
    park(g, 1 - p)
    g.run(2)
    check(g.oam(p)[1] != 224, "the rescued kart is not drawn")


def bay_checks(g, out):
    """Moon Harbour: driving off the bay corner into the water: rescued; the shortcut's canal needs a boost;
    laps count through the shortcut."""
    d = trk(g)
    calm(g)
    park(g, 1)
    surf = open(os.path.join(ROOT, "game", "res", "trk3.surf"), "rb").read()
    # from the middle of the corner road, steer straight at the nearest water
    x, y, dx, dy = tracks.point_at(d["route"], 0.62)
    best = min(((tx * 8 + 4 - x) ** 2 + (ty * 8 + 4 - y) ** 2, tx, ty) for ty in range(128) for tx in range(128)
               if surf[ty * 128 + tx] == S_FALL and abs(tx * 8 - x) < 160 and abs(ty * 8 - y) < 160)
    _, tx, ty = best
    wx, wy = tx * 8 + 4, ty * 8 + 4
    n = math.hypot(wx - x, wy - y)
    g.place(0, x, y, heading((wx - x) / n, (wy - y) / n), 24)
    for _ in range(80):
        g.run(1, (B,), ())
        if g.u8("fall_t", 0):
            break
    check(g.u8("fall_t", 0) > 0, f"drove from ({x:.0f},{y:.0f}) at the bay ({wx},{wy}) and did not fall in")
    g.shot("bay")
    calm_fall(g, 0)
    # the canal on the shortcut: at sand speed the ramp's jump falls short; boosting, it clears the canal
    calm(g)
    cell, direction = ramp_cells(d)
    slow = jump(g, 0, cell, direction, MAX_GRASS)
    for _ in range(10):
        if g.u8("fall_t", 0):
            break
        g.run(1)
    check(g.u8("fall_t", 0) > 0, f"canal: a kart at sand speed jumped {slow[0]} frames and did not fall in")
    calm_fall(g, 0)
    calm(g)
    g.set8("boost_t", 0, 200)
    fast = jump(g, 0, cell, direction, kart_of(g, 0)[1] + BOOST_EXTRA)
    g.run(10, (B,), ())
    check(not g.u8("fall_t", 0) and fast[0] > slow[0], f"canal: a boosting kart jumped {fast[0]} frames and fell in {g.u8('fall_t', 0)}")
    out["canal jump slow/boost"] = (slow[0], fast[0])
    # the shortcut: its cells carry the lap progress from its start to its end, so walking it counts
    # every checkpoint on the way, in order
    calm(g)
    sx, sy, _, sl = tracks.resample(d["shortcut"], closed=False)
    first = d["prog"][int(sy[0]) // 16, int(sx[0]) // 16] >> 3
    g.set8("cp", 0, first)
    g.set8("lap", 0, 1)
    seen = [first]
    for i in range(0, len(sx), 1):
        g.place(0, sx[i], sy[i], heading(sx[min(i + 1, len(sx) - 1)] - sx[max(i - 1, 0)], sy[min(i + 1, len(sx) - 1)] - sy[max(i - 1, 0)]))
        for name in ("fall_t", "air_t", "spin_t"):
            g.set8(name, 0, 0)
        g.run(1)
        if g.u8("cp", 0) != seen[-1]:
            seen.append(g.u8("cp", 0))
    last = d["prog"][int(sy[-1]) // 16, int(sx[-1]) // 16] >> 3
    check(seen == list(range(first, last + 1)) and len(seen) > 3,
          f"through the shortcut the checkpoints went {seen}, expected {first} to {last} in order")
    out["shortcut checkpoints"] = len(seen) - 1
    calm(g)


def results_cup_checks(g, label, want_points):
    """The cup's results: which race of the four, and each player's points so far."""
    r = g.u8("cup_race")
    head = g.map_text(9, 2, 15)
    check(head == f"CUP RACE {r + 1} OF 4", f"{label}: heading {head!r}")
    check([g.u8("points", p) for p in (0, 1)] == want_points, f"{label}: points {[g.u8('points', p) for p in (0, 1)]}, expected {want_points}")
    for p in (0, 1):
        row = (11 if p == g.u8("winner") else 16) + 1
        txt = f"{want_points[p]} POINTS"
        check(g.map_text(23, row, len(txt)) == txt, f"{label}: player {p + 1}'s points read {g.map_text(23, row, len(txt))!r}")


def podium_checks(g, want_winner, want_points):
    """The podium: the cup's winner named, on the gold block, the other on the silver one, both with points."""
    g.wait_state(ST_PODIUM, 30)
    g.run(5)
    check(g.u8("cup_winner") == want_winner, f"podium: cup winner {g.u8('cup_winner') + 1}, expected {want_winner + 1}")
    for p, (x, y) in ((want_winner, (112, 88)), (1 - want_winner, (48, 112))):
        o = g.oam(p)
        check((o[0], o[1], o[2], o[4]) == (x, y, NEAR_TILE(p, 4), 1), f"podium: player {p + 1}'s animal {o}, expected at ({x},{y})")
    v = g.vram()
    check(v[(UI_MAP + 15 * 32 + 12) * 2] == 176 and v[(UI_MAP + 18 * 32 + 4) * 2] == 177, "podium: the blocks are not drawn")
    for p, col in ((want_winner, 14), (1 - want_winner, 4)):
        txt = f"{want_points[p]} POINTS"
        check(g.map_text(col, 23, len(txt)) == txt, f"podium: player {p + 1}'s points read {g.map_text(col, 23, len(txt))!r}")
    name = NAMES[g.u8("pick", want_winner)]
    row = 5 if len(name) + 6 <= 16 else 4
    x = 16 - (len(name) + 6) if row == 5 else 16 - len(name)
    got = "".join(gen_assets.BIG_LETTERS[(v[(UI_MAP + row * 32 + x + 2 * i) * 2] - 64) // 4] if name[i] != " " else " "
                  for i in range(len(name)))
    check(got == name, f"podium: big winner line reads {got!r}, expected {name!r}")
    g.shot("podium")


def cup_race(g, n, winner, loser_finishes, stats, measured, items, budget):
    """Race n of the cup on track n: its checks, then `winner` laps every checkpoint and the other kart
    finishes second or not at all. Returns at the results screen."""
    g.set16("max_lines", 0, 0)
    countdown(g)
    if n == 0:
        check(g.u8("wheelspin_t", 0) > 0 and g.u8("wheelspin_t", 1) > 0, "cup race 1: pedals held from 3 did not spin the wheels")
        race_loads_picks(g, "cup race 1")
        g.shot("race-3")
    race_loads_track(g, n, f"cup race {n + 1}")
    race_from, fd_from = g.f, g.u16("frames_done")
    drive_from_grid(g, stats)
    cpu_checks(g, f"cup race {n + 1}")
    if n == 0:
        type_checks(g, 0, measured)
        type_order(measured)
    elif n == 1:
        oil_sand_checks(g, items)
        obstacle_checks(g, items)
    elif n == 2:
        ramp_checks(g, items)
        obstacle_checks(g, items)
    else:
        bay_checks(g, items)
    calm(g)
    park(g, 1 - winner)
    for p in (0, 1):  # the feature checks drove over checkpoints: count the laps from the grid again
        g.set8("lap", p, 0)
        g.set8("cp", p, NCP - 1)
        g.set8("finals", p, 0)
    skip_checks(g, winner)
    full_laps(g, winner, stats, final=n == 0)
    if loser_finishes:
        finish_second(g, 1 - winner, stats)
    stats["frames"] += g.f - race_from
    stats["done"] += (g.u16("frames_done") - fd_from) & 0xFFFF
    budget[TRACK_NAMES[n]] = g.lines()
    check(VBLANK_LINES < budget[TRACK_NAMES[n]] <= MAX_LINES, f"{TRACK_NAMES[n]}: logic used {budget[TRACK_NAMES[n]]} of 262 lines")
    g.wait_state(ST_RESULTS, AFTER_FIRST + 30)
    g.run(RESULTS_WAIT + 5)


# ---------------------------------------------------------------- computer karts (parked on the grid, drawn, placed)

CPU_PAL = [6, 7, 7, 6]       # computer kart 2 to 5: animal A in palette 6, B in 7, A in 7, B in 6
CPU_ANIMAL = [0, 1, 0, 1]
GRID_BACK = (20, 44, 62)     # px before the start line: the players, then the two rows of computer karts (tools/tracks.py)
GRID_SIDES = ((-12, 12), (-18, 18), (0, 18))  # sideways from the centre line in each row (tools/tracks.py): no computer kart starts in a player's line
CPU_FIT = 3          # computer karts that fit the logic budget on the busiest frame, measured (main.c CPU_MAX)
CPU_ALT = 1          # cpu_alt's default (main.c main): the karts of each half projected on alternate frames
CPU_FAR = 360                # computer karts are drawn up to this far ahead of the camera (proj.asm CPU_FAR)
CPU_SLOT_OF = lambda h, k: 76 + 4 * h + (k - 2)  # noqa: E731  computer kart k in half h
CPU_DOT_OF = lambda h, k: 84 + 4 * h + (k - 2)   # noqa: E731  its minimap dot
PLACE_TEXT = ["1ST", "2ND", "3RD", "4TH", "5TH", "6TH"]
SPRITE_LINE_LIMITS = (32, 34)  # sprites and 8-pixel tiles one screen line can hold


def cpu_calm(g):
    """calm() for the computer karts too: no spin, hop, boost, lift, shrink, item or coins on karts 2 to 5; and every computer
    kart projected on every frame, so a check can look at one frame (the checks of cpu_alt set it themselves)."""
    g.set8("cpu_alt", 0, 0)
    for k in range(2, 6):
        for name in ("boost_t", "spin_t", "spin_off", "hop_t", "wheelspin_t", "drift", "charge", "roll", "item", "coins",
                     "air_t", "trick", "trick_t", "fall_t", "kart_lift", "uses", "shrink_t", "cpu_use_t", "cpu_used"):
            g.set8(name, k, 0)
        g.set16("shield_t", k, 0)
        g.set16("star_t", k, 0)
        g.set16("cpu_age", k, 0)
    g.set8("cpu_due", 0, 0)
    calm(g)


def grid_expect(n):
    """Track n's six grid places as the tools place them, row by row (two karts a row): 20, 44 and 62 px before the
    start line, each row's places sideways from the centre line as GRID_SIDES says."""
    d = TRK[n]
    sx, sy, sdx, sdy = tracks.point_at(d["route"], 0.0)
    if n == 0:
        sx += 4  # the oval's line is painted at x 512 to 520 (centre 516), the route's start is at 512
    nx, ny = -sdy, sdx
    return [[(sx - back * sdx + side * nx, sy - back * sdy + side * ny) for side in sides] for back, sides in zip(GRID_BACK, GRID_SIDES)]


def grid_checks(g, label):
    """Six grid places on every race track, read from the ROM: the players in the front row, the computer karts in
    two rows behind, each place on plain road and 14 px or more from every other (karts closer than 10 touch)."""
    words = g.rom_words("trk_grid", 60)
    angles = struct.unpack_from("<30H", g.rom_bytes("trk_angle", 60), 0)
    res = os.path.join(ROOT, "game", "res")
    for n in range(4):
        pts = [(words[n * 12 + 2 * k], words[n * 12 + 2 * k + 1]) for k in range(6)]
        for row, want in enumerate(grid_expect(n)):
            got = pts[2 * row:2 * row + 2]
            ok = all(any(abs(gx - wx) <= 1.5 and abs(gy - wy) <= 1.5 for wx, wy in want) for gx, gy in got) and got[0] != got[1]
            check(ok, f"{label}: {TRACK_NAMES[n]} grid row {row} is {got}, expected the places {[(round(x), round(y)) for x, y in want]}")
        surf = open(os.path.join(res, f"trk{n}.surf"), "rb").read()
        bad = [k for k, (x, y) in enumerate(pts) if surf[(y // 8) * 128 + x // 8] != tracks.S_ROAD]
        check(not bad, f"{label}: {TRACK_NAMES[n]} grid places {bad} are not on plain road")
        close_pair = [(i, j) for i in range(6) for j in range(i + 1, 6) if max(abs(pts[i][0] - pts[j][0]), abs(pts[i][1] - pts[j][1])) < BUMP + 4]
        check(not close_pair, f"{label}: {TRACK_NAMES[n]} grid places {close_pair} are closer than {BUMP + 4} px")
        check(all(angles[n * 6 + k] == TRK[n]["angle"] for k in range(6)), f"{label}: {TRACK_NAMES[n]} computer karts do not face along the road")


def cpu_expect(g, viewer, k):
    """What the drawing should show of computer kart k in `viewer`'s half, from the karts' positions and the same
    rules the game states in docs/engine.md: None when it is hidden, else (centre column, top line, tile, palette,
    mirrored). The column and line come from the camera and the perspective table, so they may be a pixel off."""
    vx, vy, _, vang = g.kart(viewer)
    kx, ky, _, kang = g.kart(k)
    idx = (vang >> 8) & 127
    sn = [round(256 * math.sin(2 * math.pi * a / 128)) for a in range(128)]
    cam_x = vx - int(57 * sn[idx] / 256)
    cam_y = vy + int(57 * sn[(idx + 32) & 127] / 256)
    s, c = sn[idx] / 256, sn[(idx + 32) & 127] / 256
    dx, dy = kx - cam_x, ky - cam_y
    fwd, lat = dx * s - dy * c, dx * c + dy * s
    if g.u8("fall_t", k) or fwd < 56 or fwd >= CPU_FAR or abs(lat) > fwd:
        return None
    off = int(abs(lat) * 64 / (int(fwd) // 2))
    centre = 128 + (off if lat >= 0 else -off)
    f2 = 2 * (int(fwd) // 2)
    size = 0 if f2 < gen_assets.NEAR_FWD else 1 if f2 < gen_assets.MID_FWD else 2
    if g.u8("shrink_t", k) and size < 2:
        size += 1
    top = min(255, 18 + 5120 // (f2 + 1)) - (13 if size < 2 else 12) - (g.u8("kart_lift", k) >> size)
    if centre - 8 < 0 or centre + 8 > 256 or top + 16 > 112:
        return None
    bear = round(math.atan(off / gen_assets.FOCAL) * 128 / (2 * math.pi))
    sector = (((kang >> 8) + g.u8("spin_off", k)) - (bear if lat >= 0 else -bear) - idx + 8) // 16 & 7
    view = [0, 1, 2, 3, 4, 3, 2, 1][sector]
    a = CPU_ANIMAL[k - 2]
    tile = CPU_TILE(a, view if size < 2 else (5, 5, 6, 7, 7)[view])
    return centre, top, tile, CPU_PAL[k - 2], sector > 4


def cpu_sprite_check(g, label, viewer, k, tol=2):
    """Computer kart k's sprite in `viewer`'s half is where, how and in which tile and palette it should be (or hidden)."""
    want = cpu_expect(g, viewer, k)
    x, y, tile, attr, large = g.oam(CPU_SLOT_OF(viewer, k))
    if want is None:
        check(y == 224, f"{label}: computer kart {k} should be hidden in half {viewer + 1} but shows at ({x},{y}) tile {tile}")
        return
    centre, top, wtile, pal, flip = want
    check(y != 224 and not large and x < 256, f"{label}: computer kart {k} is not drawn small in half {viewer + 1}: ({x},{y}) large {large}")
    check(abs(x + 8 - centre) <= tol and abs(y - (viewer * 112 + top)) <= tol,
          f"{label}: computer kart {k} in half {viewer + 1} at ({x + 8},{y}), expected ({centre},{viewer * 112 + top})")
    check(tile == wtile and (attr >> 1) & 7 == pal and (attr >> 6) & 1 == flip,
          f"{label}: computer kart {k} in half {viewer + 1}: tile {tile} palette {(attr >> 1) & 7} mirrored {(attr >> 6) & 1}, "
          f"expected tile {wtile} palette {pal} mirrored {int(flip)}")


# players side by side facing west on the top straight, the computer karts ahead of both at 100 to 215 px from the camera
CPU_SCENE = ((655, 215, 0), (625, 252, 16), (590, 228, 32), (545, 245, 80))


def cpu_scene(g, shift=0):
    cpu_calm(g)
    g.place(0, 700 + shift, 232, WEST)
    g.place(1, 700 + shift, 248, WEST)
    for k, (x, y, turn) in zip(range(2, 6), CPU_SCENE):
        g.place(k, x + shift, y, (WEST + (turn << 8)) & 0xFFFF)
    g.run(2)


def line_load(g):
    """The sprites and 8-pixel tiles every screen line carries now, from the game's OAM copy: (most sprites, most tiles)."""
    sprites, tiles = [0] * 224, [0] * 224
    g.line_detail = {}
    for slot in range(128):
        x, y, _, _, large = g.oam(slot)
        if y >= 224:
            continue
        n = 32 if large else 16
        x = x - 512 if x >= 256 else x
        if x + n <= 0 or x >= 256:
            continue
        for line in range(y + 1, min(224, y + n + 1)):
            g.line_detail.setdefault(line, []).append(slot)
            sprites[line] += 1
            tiles[line] += (min(256, x + n) - max(0, x)) // 8 + (1 if (min(256, x + n) - max(0, x)) % 8 else 0)
    return max(sprites), max(tiles)


def cpu_hidden_before_ready(g):
    """Before the computer animals' frames are in video memory, no computer kart is drawn, even one in view; their
    minimap dots show from the countdown on."""
    check(not g.u8("cpu_gfx_ready"), "computer karts: the frames were loaded before GO")
    # the leader shot's picture is not in yet (the tiles still hold the O of GO), so the shot is kept, not fired
    check(not g.u8("leader_ready"), "computer karts: the leader shot's picture was loaded before GO was over")
    v = g.vram()
    o_art = open(os.path.join(ROOT, "game", "res", "shared.pic"), "rb").read()
    for r in range(4):
        a = (LEADER_TILES[0] + 16 * r) * 32
        check(v[0xC000 + a:0xC000 + a + 128] == o_art[a - 256 * 32:a - 256 * 32 + 128], f"computer karts: the O of GO is not in tile row {r} of the leader shot's tiles while GO shows")
    g.set8("item", 0, LEADER)
    tap(g, 0, (X,), ())
    check(g.u8("item", 0) == LEADER and not any(g.u8("shot_on", i) for i in range(4)), "computer karts: a leader shot was fired before its picture was loaded")
    g.set8("item", 0, 0)
    x0, y0, a0 = g.kart(2)[0], g.kart(2)[1], g.kart(2)[3]
    g.place(2, 440, 240, WEST)  # ahead of both players, in view
    g.run(6)
    shown = [s for s in range(76, 84) if g.oam(s)[1] != 224]
    check(not shown, f"computer karts: slots {shown} drawn before their frames were loaded")
    for h in (0, 1):
        for k in range(2, 2 + g.u8("cpu_n")):
            kx, ky = g.kart(k)[:2]
            x, y, tile, attr, large = g.oam(CPU_DOT_OF(h, k))
            want = (MINI_X - 7 + (kx >> 5), h * 112 + MINI_Y - 7 + (ky >> 5), TILE_DOT3, PAL_WHITE, 0)
            check((x, y, tile, (attr >> 1) & 7, large) == want, f"computer kart {k}'s minimap dot in half {h + 1}: {(x, y, tile)}, expected {want}")
    g.place(2, x0, y0, a0)
    g.run(2)
    g.set8("cpu_n", 0, 4)  # the checks that follow place all four


def cpu_start_checks(g, label):
    """At the race start the computer karts stand on their grid places, still, facing along the road, with their
    animals' kart types; the two players are where they always were."""
    d = trk(g)
    for k in range(2, 6):
        x, y, speed, angle = g.kart(k)
        check((x, y, speed, angle) == (*d["grid"][k], 0, d["angles"][k]), f"{label}: computer kart {k} at ({x},{y}) speed {speed} angle {angle}, expected {d['grid'][k]}")
        check(g.u8("kart_type", k) == CAST[g.u8("cpu_pick", (k - 2) & 1)]["type"], f"{label}: computer kart {k} drives type {g.u8('kart_type', k)}")
    check(len({g.kart(k)[:2] for k in range(6)}) == 6, f"{label}: two karts share a grid place")


def cpu_draw_checks(g, label):
    """Four computer karts ahead of both players: each is drawn in both halves, small, with its animal's frame for the
    heading it is seen at, in its palette, mirrored where the view says, at the column and line its distance gives;
    one behind the camera, one too far, one in the air, spinning, shrunk or sunk follow the kart rules."""
    cpu_scene(g)
    g.run(1)
    for viewer in (0, 1):
        for k in range(2, 6):
            check(cpu_expect(g, viewer, k) is not None, f"{label}: the scene does not show computer kart {k} in half {viewer + 1}")
            cpu_sprite_check(g, label, viewer, k)
    check(len({cpu_expect(g, 0, k)[2] for k in range(2, 6)}) >= 3, f"{label}: the scene shows too few different frames")
    g.run(6)  # the dots are placed one a frame, each every 4 frames
    g.shot("computer-karts")
    # the dots show all six karts
    for viewer in (0, 1):
        for k in range(2, 6):
            kx, ky = g.kart(k)[:2]
            x, y, tile, attr, large = g.oam(CPU_DOT_OF(viewer, k))
            want = (MINI_X - 7 + (kx >> 5), viewer * 112 + MINI_Y - 7 + (ky >> 5), TILE_DOT3, PAL_WHITE, 0)
            check((x, y, tile, (attr >> 1) & 7, large) == want, f"{label}: dot of computer kart {k} in half {viewer + 1}: {(x, y, tile)}, expected {want}")
    # the dots' colours: a white square on the minimap, shown at the middle of each dot sprite (the karts far apart,
    # so no dot covers another)
    g.place(0, 512, 600, WEST)
    g.place(1, 640, 760, WEST)
    for k, (x, y) in zip(range(2, 6), ((160, 160), (480, 130), (800, 160), (160, 480))):
        g.place(k, x, y, WEST)
    g.run(6)
    for k in range(2, 6):
        x, y = g.oam(CPU_DOT_OF(0, k))[:2]
        got = pixel(g, x + 7, y + 7)
        check(all(c > 230 for c in got), f"{label}: the middle of computer kart {k}'s dot is {got}, expected white")
    # headings: all eight sectors, every view and both mirrors, for one kart at a mid distance
    cpu_scene(g)
    seen = set()
    for turn in range(0, 128, 8):
        g.place(2, 640, 240, (WEST + (turn << 8)) & 0xFFFF)
        g.run(2)
        cpu_sprite_check(g, f"{label} heading {turn}", 0, 2)
        cpu_sprite_check(g, f"{label} heading {turn}", 1, 2)
        seen.add((g.oam(76)[2], (g.oam(76)[3] >> 6) & 1))
    check(len(seen) >= 8, f"{label}: only {len(seen)} different pictures over a full turn: {sorted(seen)}, kart 2 {g.kart(2)}")
    # sizes by distance: mid at 117 px from the camera, far at 207; behind the camera or too near, hidden; past the cap, hidden
    for ahead, y, why in ((60, 238, "mid"), (150, 238, "far"), (283, 238, "far, near the draw distance"),
                          (-5, 210, "nearer than 56 px"), (-60, 210, "behind the camera"), (323, 238, "past the draw distance")):
        g.place(2, 700 - ahead, y, WEST)
        g.run(2)
        for v in (0, 1):
            cpu_sprite_check(g, f"{label} {why}", v, 2)
    g.place(2, 700 - 283, 238, WEST)  # 340 from the camera: shown; 380: hidden
    g.run(2)
    check(g.oam(CPU_SLOT_OF(0, 2))[1] != 224, f"{label}: a computer kart 340 px from the camera is hidden")
    g.place(2, 700 - 323, 238, WEST)
    g.run(2)
    check(g.oam(CPU_SLOT_OF(0, 2))[1] == 224, f"{label}: a computer kart 380 px from the camera is drawn")
    # in the air (lifted), spinning, shrunk and sunk: the kart rules apply to computer karts as to the players
    g.place(2, 640, 238, WEST)
    g.run(2)
    y0 = g.oam(CPU_SLOT_OF(0, 2))[1]
    g.set8("air_len", 2, 40)
    g.set8("air_t", 2, 21)
    g.run(1)
    check(g.u8("kart_lift", 2) == 25, f"{label}: computer kart in the air has lift {g.u8('kart_lift', 2)}, expected 25")
    cpu_sprite_check(g, f"{label} in the air", 0, 2)
    check(y0 - g.oam(CPU_SLOT_OF(0, 2))[1] >= 8, f"{label}: a computer kart in the air is only {y0 - g.oam(CPU_SLOT_OF(0, 2))[1]} lines higher")
    g.set8("air_t", 2, 0)
    g.run(2)
    g.set8("spin_t", 2, 40)
    views = set()
    for _ in range(20):
        g.run(1)
        cpu_sprite_check(g, f"{label} spinning", 0, 2)
        views.add(g.oam(CPU_SLOT_OF(0, 2))[2])
    check(len(views) >= 4, f"{label}: a spinning computer kart showed {len(views)} pictures")
    g.set8("spin_t", 2, 0)
    g.set8("spin_off", 2, 0)
    g.run(2)
    t0 = g.oam(CPU_SLOT_OF(0, 2))[2]
    g.set8("shrink_t", 2, 100)
    g.run(2)
    cpu_sprite_check(g, f"{label} shrunk", 0, 2)
    check(g.oam(CPU_SLOT_OF(0, 2))[2] != t0, f"{label}: a shrunk computer kart is drawn in the same size")
    g.set8("shrink_t", 2, 0)
    g.run(2)
    g.set8("fall_t", 2, 30)
    g.run(2)
    check(g.oam(CPU_SLOT_OF(0, 2))[1] == 224 and g.oam(CPU_SLOT_OF(1, 2))[1] == 224, f"{label}: a sunk computer kart is drawn")
    cpu_calm(g)
    # cpu_n below 4: only that many are drawn
    cpu_scene(g)
    g.set8("cpu_n", 0, 2)
    g.run(2)
    check(g.oam(CPU_SLOT_OF(0, 2))[1] != 224 and g.oam(CPU_SLOT_OF(0, 3))[1] != 224, f"{label}: with 2 computer karts racing, they are not drawn")
    stale = [CPU_SLOT_OF(v, k) for v in (0, 1) for k in (4, 5) if g.oam(CPU_SLOT_OF(v, k))[1] != 224]
    check(len(stale) == 4, f"{label}: with 2 racing the other two keep their sprites: {stale}")  # they stay as drawn: the game never lowers cpu_n mid-race
    g.set8("cpu_n", 0, 4)
    cpu_calm(g)


def cpu_snapshot(g):
    """(x, y) of the eight computer kart sprites, half 1's four then half 2's four."""
    return [g.oam(CPU_SLOT_OF(h, k))[:2] for h in (0, 1) for k in range(2, 6)]


def cpu_alt_checks(g, label):
    """With cpu_alt set, each half's computer kart sprites are projected on alternate frames: of two frames, one moves
    half 1's four sprites and the other half 2's, and after both every sprite is where it should be."""
    cpu_scene(g)
    g.set8("cpu_alt", 0, 1)
    g.run(2)
    before = cpu_snapshot(g)
    for k in range(2, 6):
        x, y, _, ang = g.kart(k)
        g.place(k, x - 14, y + 6, ang)
    moved = []
    for _ in range(2):
        g.run(1)
        now = cpu_snapshot(g)
        moved.append((now[:4] != before[:4], now[4:] != before[4:]))
        before = now
    check(all(a != b for a, b in moved) and moved[0] != moved[1],
          f"{label}: the halves' computer karts moved on frames {moved}, expected one half or the other on each frame")
    g.run(2)
    for viewer in (0, 1):
        for k in range(2, 6):
            cpu_sprite_check(g, f"{label} after two frames", viewer, k)
    g.set8("cpu_alt", 0, 0)
    g.run(2)
    before = cpu_snapshot(g)
    for k in range(2, 6):
        x, y, _, ang = g.kart(k)
        g.place(k, x + 14, y - 6, ang)
    g.run(1)
    now = cpu_snapshot(g)
    check(now[:4] != before[:4] and now[4:] != before[4:], f"{label}: with cpu_alt off a frame left a half's computer karts where they were")
    g.set8("cpu_alt", 0, CPU_ALT)
    cpu_calm(g)


def cpu_lag(g, alt):
    """The most pixels any computer kart sprite is off where the current camera puts it, over 24 frames of player 1 turning
    left with the pedal down: 0 or 1 or 2 when every sprite is projected every frame; with alternate frames half the sprites
    show the last frame's camera."""
    cpu_scene(g)
    g.set8("cpu_alt", 0, alt)
    g.place(0, 700, 232, WEST, 20)
    g.run(4)
    worst = 0
    for _ in range(24):
        g.run(1, (B, LEFT), ())
        for k in range(2, 6):
            want = cpu_expect(g, 0, k)
            x, y = g.oam(CPU_SLOT_OF(0, k))[:2]
            if want is not None and y != 224:
                worst = max(worst, abs(x + 8 - want[0]), abs(y - want[1]))
    g.set8("cpu_alt", 0, CPU_ALT)
    cpu_calm(g)
    return worst


def cpu_hud_checks(g, label):
    """A computer kart has no HUD: a lap it finishes and a wrong-way run leave every HUD and balloon slot alone."""
    cpu_calm(g)
    park(g, 0)
    park(g, 1)
    for k in (2, 4, 5):
        g.place(k, 300 + 40 * k, 160, WEST)
    g.set8("lap", 3, 1)
    g.set8("cp", 3, NCP - 1)
    cross(g, 3, 0)
    check(g.u8("lap", 3) == 2, f"{label}: computer kart 3 crossed the line and is on lap {g.u8('lap', 3)}")
    check(g.oam(HUD_SLOT(3) + 3)[1] == 224, f"{label}: a computer kart's lap drew a lap digit into slot {HUD_SLOT(3) + 3}")
    # backwards along the top straight (the race runs west): after three steps back it would show the sign
    g.set8("wrong", 3, 0)
    for f in range(48):
        g.place(3, 420 + 4 * f, 240, EAST, 0)
        g.run(1)
    check(g.u8("wrong", 3) >= 3 and g.u8("wrong_shown", 3) == 1, f"{label}: computer kart 3 driving backwards: wrong {g.u8('wrong', 3)}, shown {g.u8('wrong_shown', 3)}")
    guarded = [s for s in range(60, 76) if not 64 <= s <= 67]  # the obstacles, the wrong-way signs and the balloons (64-67 are the dots)
    check(all(g.oam(s)[1] == 224 for s in guarded), f"{label}: a computer kart's wrong-way run drew into slots {[s for s in guarded if g.oam(s)[1] != 224]}")
    g.set8("wrong_shown", 3, 0)
    g.set8("wrong", 3, 0)
    cpu_calm(g)


def cpu_bump_checks(g, label):
    """A player pushes a computer kart, both lose a quarter of their speed, and a star kart's touch hits it."""
    cpu_calm(g)
    park(g, 1)
    for k in (3, 4, 5):
        g.place(k, 300 + 40 * k, 160, WEST)
    for (x0, y0), (x1, y1) in (((606, 240), (600, 241)), ((600, 240), (601, 246))):
        bumps = g.u16("bumps")
        g.place(0, x0, y0, WEST, 30)
        g.place(2, x1, y1, WEST, 0)
        g.run(1)
        (ax, ay, s0, _), (bx, by, s2, _) = g.kart(0), g.kart(2)
        check(g.u16("bumps") == bumps + 1 and max(abs(ax - bx), abs(ay - by)) >= BUMP and s0 < 25,
              f"{label}: a player touched computer kart 2 from ({x0},{y0}) and ({x1},{y1}): bumps {g.u16('bumps') - bumps}, apart {max(abs(ax - bx), abs(ay - by))}, speed {s0}")
    # two computer karts touch each other too
    g.place(3, 500, 240, WEST, 20)
    g.place(5, 504, 241, WEST, 20)
    bumps = g.u16("bumps")
    g.run(1)
    check(g.u16("bumps") == bumps + 1, f"{label}: computer karts 3 and 5 touched without a bump")
    # a star kart hits the computer kart it touches
    cpu_calm(g)
    park(g, 1)
    for k in (3, 4, 5):
        g.place(k, 300 + 40 * k, 160, WEST)
    g.set16("star_t", 0, 60)
    g.place(0, 600, 240, WEST, 30)
    g.place(2, 601, 241, WEST)
    g.run(2)
    check(g.u8("spin_t", 2) > 0, f"{label}: a star kart's touch did not spin computer kart 2")
    cpu_calm(g)
    # the map edge holds a computer kart, which keeps at most the edge speed
    park(g, 1)
    g.place(0, 600, 160, WEST)
    g.place(4, -20, 500, WEST, 20)
    g.run(2)
    x, y, speed, _ = g.kart(4)
    check(x == 0 and speed <= EDGE_SPEED, f"{label}: computer kart 4 past the map edge is at ({x},{y}) with speed {speed}")
    # a shrunk computer kart counts its shrink down
    g.place(4, 300, 160, WEST)
    g.set8("shrink_t", 3, 6)
    g.run(8)
    check(g.u8("shrink_t", 3) == 0, f"{label}: computer kart 3's shrink stands at {g.u8('shrink_t', 3)} after 8 frames")
    cpu_calm(g)


def cpu_hit_checks(g, label):
    """A shot and a moving obstacle hit a computer kart, which spins and drops coins; a shot that misses it flies on."""
    cpu_calm(g)
    park(g, 1)
    for k in (2, 4, 5):
        g.place(k, 300 + 40 * k, 160, WEST)
    g.place(0, 700, 236, WEST)
    g.place(3, 560, 236, WEST)
    g.set8("coins", 3, 5)
    hits3 = g.u16("hits", 3)
    use(g, 0, SHOT, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    for _ in range(50):
        if not g.u8("shot_on", i):
            break
        g.run(1)
    check(not g.u8("shot_on", i) and g.u8("spin_t", 3) > 0 and g.u16("hits", 3) == hits3 + 1, f"{label}: the shot did not hit computer kart 3: spin {g.u8('spin_t', 3)}")
    check(g.u8("coins", 3) == 5 - COIN_LOSS, f"{label}: the hit computer kart has {g.u8('coins', 3)} coins, expected {5 - COIN_LOSS}")
    check(all(g.oam(s)[1] == 224 for s in (60, 61, 62, 63)), f"{label}: a hit computer kart drew a coin counter into a player's slots: {[g.oam(s)[1] for s in (60, 61, 62, 63)]}")
    check(g.u8("spin_t", 0) == 0 and g.u8("spin_t", 2) == 0 and g.u8("spin_t", 4) == 0, f"{label}: another kart spun with the hit")
    cpu_calm(g)
    # a young shot (in its first 20 frames, which it spends spared from its thrower) hits a computer kart 40 px from its start
    g.place(0, 700, 236, WEST)
    g.place(4, 640, 236, WEST)
    hits4 = g.u16("hits", 4)
    use(g, 0, SHOT, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    for _ in range(12):
        if not g.u8("shot_on", i):
            break
        g.run(1)
    check(not g.u8("shot_on", i) and g.u8("spin_t", 4) > 0 and g.u16("hits", 4) == hits4 + 1,
          f"{label}: a shot in its first 20 frames did not hit computer kart 4 40 px ahead: spin {g.u8('spin_t', 4)}, grace {g.u8('shot_grace', i)}")
    cpu_calm(g)
    # a kart in the air takes no harm from the shot
    g.place(0, 700, 236, WEST)
    g.place(5, 560, 236, WEST)
    g.set8("air_t", 5, 100)
    g.set8("air_len", 5, 100)
    use(g, 0, SHOT, ())
    g.run(50)
    check(g.u8("spin_t", 5) == 0, f"{label}: a computer kart in the air was hit by a shot")
    cpu_calm(g)
    # a computer kart that is not racing (here kart 5 with 3 racing) is not in the way of a shot
    g.set8("cpu_n", 0, 3)
    for k in (2, 3, 4):
        g.place(k, 300 + 40 * k, 160, WEST)
    g.place(0, 700, 236, WEST)
    g.place(5, 560, 236, WEST)
    use(g, 0, SHOT, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    g.set16("shot_life", i, 200)
    g.run(45)
    check(g.u8("shot_on", i) and g.u8("spin_t", 5) == 0, f"{label}: a shot ended on computer kart 5, which is not racing: on {g.u8('shot_on', i)}, spin {g.u8('spin_t', 5)}")
    g.set8("shot_on", i, 0)
    g.set8("cpu_n", 0, 4)
    cpu_calm(g)
    # an obstacle on computer kart 4 hits it, and one beside it does not
    for k in (2, 3, 5):
        g.place(k, 300 + 40 * k, 160, WEST)
    g.place(4, 640, 240, WEST)
    for i, (dx_, dy_) in enumerate(((0, 0), (40, 40))):
        g.set16("ob_x", i, (640 + dx_) * 16)
        g.set16("ob_y", i, (240 + dy_) * 16)
        g.set16("ob_dx", i, 0)
        g.set16("ob_dy", i, 0)
        g.set16("ob_len", i, 1000)
        g.set8("ob_on", i, 1)
    g.set8("coins", 4, 5)
    hits4 = g.u16("hits", 4)
    g.run(3)
    check(g.u8("spin_t", 4) > 0 and g.u8("coins", 4) == 5 - COIN_LOSS and g.u16("hits", 4) == hits4 + 1,
          f"{label}: an obstacle on computer kart 4 left spin {g.u8('spin_t', 4)}, coins {g.u8('coins', 4)}")
    check(g.u8("spin_t", 2) == 0 and g.u8("spin_t", 3) == 0 and g.u8("spin_t", 5) == 0, f"{label}: an obstacle hit a kart it was not on")
    cpu_calm(g)
    # a hit computer kart changes its coins but draws no counter: kart 2's would land in the sparks' slots, kart 5's in the wrong-way signs'
    for k, slots in ((2, (58, 59)), (5, (70, 71))):
        g.place(k, 300 + 40 * k, 160, WEST)
        g.set8("coins", k, 5)
        g.set8("shot_struck", k, 1)
        g.run(2)
        check(g.u8("spin_t", k) > 0 and g.u8("coins", k) == 5 - COIN_LOSS, f"{label}: computer kart {k} was not hit: spin {g.u8('spin_t', k)}, coins {g.u8('coins', k)}")
        check(all(g.oam(s)[1] == 224 for s in slots), f"{label}: computer kart {k}'s hit drew a coin counter into slots {slots}")
        cpu_calm(g)


def set_order(g, ranking, top=24, step=3):
    """Puts the karts in `ranking` (first to last) on the track at checkpoints 24, 21, ... on lap 1, each in the middle of
    its checkpoint, so rank_all sees six different progresses; the others of the six sit on the grid's far side."""
    d = trk(g)
    for place_, k in enumerate(ranking):
        c = top - step * place_
        x, y, dx, dy = tracks.point_at(d["route"], (c + 0.5) / NCP)
        g.set8("lap", k, 1)
        g.set8("cp", k, c)
        g.set8("frac", k, 12)
        g.place(k, x, y, heading(dx, dy))
    g.run(8)  # a computer kart's progress is read every 4th frame, and the places worked out every 4th


def place_tiles(g, p):
    """The three HUD tiles of player p's place, as (tile numbers)."""
    return [g.oam(HUD_SLOT(p) + 6 + i)[2] for i in range(3)]


def place_tiles_want(n):
    """The tiles for "1ST" to "6TH": the number, then S, N, R, T or H as the place needs (the R is a tile of its own)."""
    letters = PLACE_TEXT[n - 1]
    return [GLYPH(letters[0])] + [TILE_R if ch == "R" else GLYPH(ch) for ch in letters[1:]]


def cpu_place_checks(g, label):
    """Six karts rank by progress: every order of a player among computer karts gives places 1 to 6 and the HUD shows
    "1ST" to "6TH" (the R of 3RD is its own tile) for the players."""
    cpu_calm(g)
    orders = [[0, 2, 3, 4, 5, 1], [2, 0, 3, 4, 5, 1], [2, 3, 0, 4, 5, 1], [2, 3, 4, 0, 5, 1], [2, 3, 4, 5, 0, 1],
              [2, 3, 4, 5, 1, 0], [1, 2, 3, 0, 4, 5], [2, 1, 3, 4, 0, 5], [2, 3, 1, 4, 5, 0]]
    for ranking in orders:
        set_order(g, ranking)
        got = [g.u8("place", k) for k in range(6)]
        want = [ranking.index(k) + 1 for k in range(6)]
        check(got == want, f"{label}: order {ranking}: places {got}, expected {want}")
        for p in (0, 1):
            check(place_tiles(g, p) == place_tiles_want(want[p]),
                  f"{label}: player {p + 1} is {PLACE_TEXT[want[p] - 1]} but the HUD shows tiles {place_tiles(g, p)}, expected {place_tiles_want(want[p])}")
    g.shot("place-6th")
    # equal progress: the lower number is ahead, a computer kart behind a player
    for k in range(6):
        g.set8("lap", k, 1)
        g.set8("cp", k, 5)
        g.set8("frac", k, 9)
    for k in range(6):
        g.place(k, 330 + 60 * k, 130, WEST)  # off the track: the progress stays
    g.run(8)
    check([g.u8("place", k) for k in range(6)] == [1, 2, 3, 4, 5, 6], f"{label}: level progress places {[g.u8('place', k) for k in range(6)]}")
    cpu_calm(g)


def cpu_item_checks(g, label):
    """A panel draws from the leader's table for first place, second place's for second and the third table for places 3 to 6,
    computer karts and players alike; an item aimed at another kart (a homing shot, a shrink, a steal) takes the kart
    directly ahead in place, the one behind for the leader, and the other player when no computer kart races."""
    odds = list(g.rom_bytes("odds", 48))
    cpu_calm(g)
    set_order(g, [2, 3, 0, 4, 1, 5])
    pc = cell_no(TRK[0]["panels"][0])
    px, py = cell_mid(TRK[0]["panels"][0])
    for n, (k, table) in enumerate(((2, 0), (3, 16), (0, 32), (4, 32), (1, 32), (5, 32), (2, 0), (5, 32))):  # places 1 to 6, then two more draws
        g.set16("rng", 0, 0x20 + 5 * n)
        g.set8("item", k, 0)
        g.set8("roll", k, 0)
        g.set8("cpu_use_t", k, 0)  # the countdown of an earlier roll would end this one early
        g.set8("cells", pc, CELL_PANEL)  # the one panel again
        g.set8("panel_wait", 0, 0)
        before = g.u8("place", k)
        g.place(k, px, py, WEST)
        g.run(2)
        check(g.u8("roll", k) > 0, f"{label}: kart {k} (draw {n + 1}) drove over a panel and took none (cell {g.u8('cells', pc)}, item {g.u8('item', k)}, shield {g.u16('shield_t', k)}, at {g.kart(k)[:2]} for {px, py})")
        want = odds[table + g.u8("last_roll", k)]
        check(g.u8("roll_item", k) == want, f"{label}: kart {k} in place {before} drew item {g.u8('roll_item', k)}, expected {want} from the table at {table}")
        check(before == {2: 1, 3: 2, 0: 3, 4: 4, 1: 5, 5: 6}[k], f"{label}: kart {k} was in place {before}")
        # put the kart back on its checkpoint
        set_order(g, [2, 3, 0, 4, 1, 5])
    cpu_calm(g)
    set_order(g, [2, 3, 0, 4, 1, 5])
    # player 1 (third) aims at the kart directly ahead (computer kart 3, second): a shrink, a homing shot, a steal
    use(g, 0, SHRINK, ())
    check(g.u8("shrink_t", 3) > 0 and g.u8("shrink_t", 2) == 0 and g.u8("shrink_t", 1) == 0, f"{label}: the shrink hit {[g.u8('shrink_t', k) for k in range(6)]}, expected only kart 3")
    cpu_calm(g)
    set_order(g, [2, 3, 0, 4, 1, 5])
    use(g, 0, HOMING, ())
    i = next(i for i in range(4) if g.u8("shot_on", i))
    check(g.u8("shot_home", i) == 1 + 3, f"{label}: the homing shot chases {g.u8('shot_home', i) - 1}, expected kart 3")
    g.set8("shot_on", i, 0)
    cpu_calm(g)
    set_order(g, [2, 3, 0, 4, 1, 5])
    g.set8("item", 3, SHOT)
    g.set8("item", 0, STEAL)
    g.set8("roll", 0, 0)
    tap(g, 0, (X,), ())
    check(g.u8("item", 0) == SHOT and g.u8("item", 3) == 0, f"{label}: the steal took items {g.u8('item', 0)} / {g.u8('item', 3)}, expected the shot from kart 3")
    cpu_calm(g)
    # the leader aims at the kart behind it
    set_order(g, [0, 2, 3, 4, 1, 5])
    use(g, 0, SHRINK, ())
    check(g.u8("shrink_t", 2) > 0 and g.u8("shrink_t", 1) == 0, f"{label}: the leader's shrink hit {[g.u8('shrink_t', k) for k in range(6)]}, expected kart 2")
    cpu_calm(g)
    # with no computer karts racing it is the other player, as it always was
    g.set8("cpu_n", 0, 0)
    set_order(g, [0, 1, 2, 3, 4, 5])
    use(g, 0, SHRINK, ())
    check(g.u8("shrink_t", 1) > 0 and g.u8("shrink_t", 2) == 0, f"{label}: with no computer karts the shrink hit {[g.u8('shrink_t', k) for k in range(6)]}, expected player 2")
    g.set8("cpu_n", 0, 4)
    cpu_calm(g)


def rematch(g, label):
    """From the results screen: Start begins the race again with the computer karts held to the most; the race's countdown is run
    and all four computer karts are set racing, as the checks after it expect."""
    g.run(RESULTS_WAIT)
    g.press(0, START)
    g.wait_state(ST_COUNTDOWN, 30)
    g.countdown_from = g.f
    check(g.u8("cpu_n") == CPU_FIT, f"{label}: the rematch has {g.u8('cpu_n')} computer karts, expected {CPU_FIT}")
    countdown(g)
    g.set8("cpu_n", 0, 4)
    g.run(2)


def cpu_timeout_checks(g, label):
    """A computer kart getting home starts no timer: the race runs on past 10 s with no player home. The first player to finish
    then starts the 10 s, wins, and the results come 10 s later with the places as they were. A rematch then starts with the
    computer karts held to the most again."""
    cpu_calm(g)
    for k in range(6):
        g.set8("finished", k, 0)
    set_order(g, [1, 0, 3, 4, 5, 2])
    for k, (lap, cp) in enumerate(((1, NCP - 1), (2, NCP - 1), (3, NCP - 1), (1, 2), (1, 2), (1, 2))):
        g.set8("lap", k, lap)  # kart 2 is about to finish; player 2 is a lap further on than player 1, the other computer karts far behind
        g.set8("cp", k, cp)
    g.set8("done_count", 0, 0)
    g.set16("end_timer", 0, 0)
    g.set8("winner", 0, 0)
    cross(g, 2, 0)
    check(g.u8("finished", 2) and g.u8("done_count") == 1 and not g.u8("finished", 0) and not g.u8("finished", 1),
          f"{label}: computer kart 2 finished: {g.u8('finished', 2)}, done {g.u8('done_count')}")
    check(g.u16("end_timer") == 0, f"{label}: a computer kart's finish set the results timer to {g.u16('end_timer')}")
    g.run(8)
    check([g.u8("place", k) for k in (0, 1, 2)] == [3, 2, 1], f"{label}: places of the karts 0 to 2 are {[g.u8('place', k) for k in (0, 1, 2)]}, expected [3, 2, 1]")
    g.run(AFTER_FIRST + 120)  # well over the 10 s: the race goes on
    check(g.state() == ST_RACE and g.u16("end_timer") == 0,
          f"{label}: {AFTER_FIRST + 120} frames after a computer kart finished with no player home, the state is {g.state()} and the timer {g.u16('end_timer')}")
    # player 2 gets home: the 10 s start now, it wins, and the results come 10 s after its finish
    g.set8("lap", 1, 3)
    g.set8("cp", 1, NCP - 1)
    cross(g, 1, 0)
    check(g.u8("finished", 1) and g.u8("winner") == 1 and AFTER_FIRST - 25 <= g.u16("end_timer") <= AFTER_FIRST,
          f"{label}: player 2 finished: winner {g.u8('winner')}, results timer {g.u16('end_timer')}")
    g.set8("cpu_n", 0, CPU_FIT)  # the game races at most CPU_FIT: its results list that many (kart 5 sat out, last)
    since = g.u16("race_time") - g.u16("finish_time", 1) + g.wait_state(ST_RESULTS, AFTER_FIRST + 60)
    check(abs(since - AFTER_FIRST) <= 2, f"{label}: the results came {since} frames after the first player finished, expected {AFTER_FIRST}")
    g.run(5)
    check(g.u8("winner") == 1, f"{label}: the results came with player {g.u8('winner') + 1} the winner, expected player 2, the first home")
    cpu_results_checks(g, label, [2, 1, 0])
    rematch(g, label)


def at_checkpoint(g, k, c):
    """Kart k on lap 1 in the middle of checkpoint c, as set_order puts it (without the frames it then runs)."""
    x, y, dx, dy = tracks.point_at(trk(g)["route"], (c + 0.5) / NCP)
    g.set8("lap", k, 1)
    g.set8("cp", k, c)
    g.set8("frac", k, 12)
    g.place(k, x, y, heading(dx, dy))


def cpu_final_frame_checks(g, label):
    """rank_all() works out one kart in four a frame with computer karts, and a computer kart's progress is read in its own turn
    (kart 2 + race_time & 3), so a place can lag the progress by a few frames. However late in the race one computer kart passes
    another, the results show each kart in a place of its own that agrees with the progress. Player 1 is home; on the race's last
    frame (race_time set so that it is the turn of kart 2, 3 or 4) that kart's progress moves it past the kart ahead of it, and
    the places are read off the results screen: a row each, no two karts in one row."""
    for q, new_cp in ((0, 22), (1, 19), (2, 16)):  # kart 2 + q passes the kart ahead of it (karts 1, 2, 3 sit at checkpoints 21, 18, 15)
        cpu_calm(g)
        for k in range(6):
            g.set8("finished", k, 0)
        g.set8("cpu_n", 0, CPU_FIT)
        set_order(g, [0, 1, 2, 3, 4, 5])
        g.set8("lap", 0, 3)
        g.set8("cp", 0, NCP - 1)
        g.set8("done_count", 0, 0)
        cross(g, 0, 0)  # player 1 is home, so the timer runs; the other karts race on
        check(g.u8("finished", 0), f"{label}: player 1 did not finish")
        g.run(8)
        check([g.u8("place", k) for k in range(5)] == [1, 2, 3, 4, 5], f"{label}: places before the pass {[g.u8('place', k) for k in range(5)]}")
        at_checkpoint(g, 2 + q, new_cp)
        g.set16("end_timer", 0, 1)  # the next frame is the last
        g.set16("race_time", 0, (g.u16("race_time") & ~3) + 4 + ((q - 1) & 3))  # which becomes kart 2 + q's turn when the clock steps
        g.wait_state(ST_RESULTS, 6)
        n_karts = 2 + g.u8("cpu_n")
        prog = [g.u16("prog", k) for k in range(n_karts)]
        places = [g.u8("place", k) for k in range(n_karts)]
        fin = [g.u8("finished", k) for k in range(n_karts)]
        want = [places[k] if fin[k] else 1 + sum(1 for j in range(n_karts) if prog[j] > prog[k] or (prog[j] == prog[k] and j < k))
                for k in range(n_karts)]
        check(prog[2 + q] > prog[1 + q] and places == want,
              f"{label}, kart {2 + q} passing on the last frame: places {places} with progress {prog}, expected {want}")
        g.run(5)
        rows = [g.map_text(7, 9 + 3 * r, 3) for r in range(n_karts)]
        check(rows == PLACE_TEXT[:n_karts], f"{label}, kart {2 + q} passing: the results rows read {rows}")
        names = sorted(g.map_text(11, 9 + 3 * r + 1, 10).strip() for r in range(n_karts))
        check(names == sorted(driver_label(k) for k in range(n_karts)),
              f"{label}, kart {2 + q} passing: the rows name {names}, one for each kart expected")
        check(g.u8("winner") == 0, f"{label}: the winner is player {g.u8('winner') + 1}, expected player 1, the one home")
        rematch(g, label)
    g.set8("cpu_n", 0, 4)


def cpu_finish_checks(g, label):
    """A computer kart finishing takes first place and starts no timer; the players finish second and third, the first of
    them to cross is the winner and starts the 10 s; the race ends 1.5 s after both players are home, and the results show the places."""
    cpu_calm(g)
    for k in range(6):
        g.set8("finished", k, 0)
    set_order(g, [0, 1, 2, 3, 4, 5])
    for k in range(6):  # lap 3, on the last checkpoint
        g.set8("lap", k, 3)
        g.set8("cp", k, NCP - 1)
    g.set8("done_count", 0, 0)
    g.set8("winner", 0, 0)
    g.set16("end_timer", 0, 0)
    cross(g, 2, 0)
    check(g.u8("finished", 2) and g.u8("place", 2) == 1 and g.u8("done_count") == 1, f"{label}: computer kart 2 crossed the line on the last lap: finished {g.u8('finished', 2)}, place {g.u8('place', 2)}, done {g.u8('done_count')}")
    check(g.u16("end_timer") == 0, f"{label}: the first finisher, a computer kart, set the results timer to {g.u16('end_timer')}")
    place_ = [g.u8("place", k) for k in range(6)]
    check(place_[2] == 1 and sorted(place_) == [1, 2, 3, 4, 5, 6], f"{label}: places after a computer kart finished: {place_}")
    cross(g, 1, 0)
    check(g.u8("finished", 1) and g.u8("place", 1) == 2 and g.u8("winner") == 1, f"{label}: player 2 finished second: place {g.u8('place', 1)}, winner {g.u8('winner')}")
    check(AFTER_BOTH < g.u16("end_timer") <= AFTER_FIRST, f"{label}: the results timer is {g.u16('end_timer')} with one player home, expected the 10 s from its finish")
    cross(g, 0, 0)
    check(g.u8("finished", 0) and g.u8("place", 0) == 3 and g.u8("winner") == 1, f"{label}: player 1 finished third: place {g.u8('place', 0)}, winner {g.u8('winner')}")
    check(g.u16("end_timer") <= AFTER_BOTH, f"{label}: both players are home and the results timer is {g.u16('end_timer')}")
    others = [g.u8("place", k) for k in (3, 4, 5)]
    check(sorted(others) == [4, 5, 6], f"{label}: the computer karts still racing are placed {others} after the three finishers")
    g.set8("cpu_n", 0, CPU_FIT)  # the game races at most CPU_FIT: its results list that many (kart 5 sat out, last)
    g.wait_state(ST_RESULTS, AFTER_BOTH + 30)
    g.run(5)
    cpu_results_checks(g, label, [2, 1, 0])
    g.shot("results-5-rows")
    check(not [s for s in range(2, SLOTS) if g.oam(s)[1] != 224], f"{label}: sprites left on the results screen: {[s for s in range(2, SLOTS) if g.oam(s)[1] != 224]}")


# ---------------------------------------------------------------- the leader shot and computer karts' items

def line_surfaces(g, x0, y0, x1, y1):
    """The surfaces under the straight line from (x0, y0) to (x1, y1) on the track raced, a sample every 4 px."""
    surf = open(os.path.join(ROOT, "game", "res", f"trk{g.u8('track_no')}.surf"), "rb").read()
    n = max(1, int(math.hypot(x1 - x0, y1 - y0) // 4))
    return [surf[(int(y0 + (y1 - y0) * i / n) // 8) * 128 + int(x0 + (x1 - x0) * i / n) // 8] for i in range(n + 1)]


def lineup(g, ranking, top=17):
    """The karts in `ranking` (first to last) one checkpoint apart (about 70 px) on the oval's bottom straight, where the race
    runs east, standing still: first at checkpoint `top`, so all six are on the straight."""
    set_order(g, ranking, top=top, step=1)


def shot_index(g):
    for i in range(4):
        if g.u8("shot_on", i):
            return i
    raise TestFailure("no shot is in flight where one was fired")


def leader_flight(g, holder, target, limit=140):
    """Holder fires a leader shot (set as its item, X pressed); returns (frames until it ended, the largest step it made on
    either axis in one frame, px). The shot must be a leader shot for `target`."""
    use(g, holder, LEADER, ())
    i = shot_index(g)
    check(g.u8("shot_on", i) == 2 + target, f"leader shot: shot_on {g.u8('shot_on', i)}, expected a shot for kart {target} ({2 + target})")
    fastest, last = 0, (sh16(g, "shot_x", i), sh16(g, "shot_y", i))
    for f in range(limit):
        g.run(1)
        if not g.u8("shot_on", i):
            return f + 1, fastest / 16, i
        now = (sh16(g, "shot_x", i), sh16(g, "shot_y", i))
        fastest = max(fastest, abs(now[0] - last[0]), abs(now[1] - last[1]))
        last = now
    return limit, fastest / 16, i


def leader_picture_checks(g, label):
    """The leader shot's frames are in the tiles the countdown's "O" held, and its HUD picture shows for a player who holds it."""
    check(g.u8("leader_ready"), f"{label}: the leader shot's picture was never loaded")
    v = g.vram()
    for r in range(4):
        a = 0xC000 + (LEADER_TILES[0] + 16 * r) * 32
        check(v[a:a + 128] == LEADER_PIC[r * 128:(r + 1) * 128], f"{label}: tile row {r} of the leader shot's picture is not in video memory")
    calm(g)
    g.set8("roll_item", 0, LEADER)
    g.set8("roll", 0, 2)
    g.run(4)
    check(g.u8("item", 0) == LEADER and hud_picture(g, 0) == LEADER and g.oam(ITEM_SLOT(0))[1] != 224,
          f"{label}: a player holding the leader shot: item {g.u8('item', 0)}, HUD picture {hud_picture(g, 0)}, sprite line {g.oam(ITEM_SLOT(0))[1]}")
    g.shot("leader-hud")
    calm(g)


def leader_checks(g, label):
    """The leader shot flies at the kart in first place across the infield's grass at more than a homing shot's speed and spins it;
    a shield blocks it and a star ignores it; a kart in the air is passed under and hit on landing; a holder in first sends it to
    second place; it is drawn with its own tiles and hidden when it ends."""
    cpu_calm(g)
    leader_picture_checks(g, label)
    # far behind, across grass: player 1 last in the middle of the infield, kart 2 first on the bottom straight
    lineup(g, [2, 3, 4, 5, 1, 0])
    tx, ty = g.kart(2)[:2]
    g.place(0, 512, 512, heading(tx - 512, ty - 512))
    check(math.hypot(tx - 512, ty - 512) > 250 and tracks.S_GRASS in line_surfaces(g, 512, 512, tx, ty), f"{label}: the leader shot's path is not a long run over grass")
    hits = g.u16("hits", 2)
    use(g, 0, LEADER, ())
    i = shot_index(g)
    check(g.u8("shot_on", i) == 4 and g.u8("shot_home", i) == 0, f"{label}: a leader shot from last place is for {g.u8('shot_on', i) - 2} (home {g.u8('shot_home', i)}), expected kart 2")
    seen = None
    for f in range(12):
        g.run(1)
    for s in SHOT_SLOTS[0]:
        if g.oam(s)[1] != 224:
            seen = g.oam(s)
    check(seen is not None and seen[2] in LEADER_TILES and (seen[3] >> 1) & 7 == 5 and not seen[4] and seen[0] < 256,
          f"{label}: the leader shot in flight shows {seen}, expected one of the tiles {LEADER_TILES} in palette 5")
    g.shot("leader-shot-in-flight")
    fastest, last = 0, (sh16(g, "shot_x", i), sh16(g, "shot_y", i))
    frames = 12
    for f in range(160):
        if not g.u8("shot_on", i):
            break
        g.run(1)
        frames += 1
        now = (sh16(g, "shot_x", i), sh16(g, "shot_y", i))
        fastest = max(fastest, abs(now[0] - last[0]), abs(now[1] - last[1]))
        last = now
    check(not g.u8("shot_on", i) and g.u8("spin_t", 2) > 0 and g.u16("hits", 2) == hits + 1,
          f"{label}: the leader shot from {math.hypot(tx - 512, ty - 512):.0f} px away did not spin the first kart: on {g.u8('shot_on', i)}, spin {g.u8('spin_t', 2)}, hits {g.u16('hits', 2) - hits}")
    check(fastest / 16 > 4.5, f"{label}: the leader shot's fastest step was {fastest / 16:.1f} px a frame on one axis, a homing shot's is 4")
    check(all(g.u8("spin_t", k) == 0 for k in (0, 1, 3, 4, 5)), f"{label}: a kart other than the leader spun: {[g.u8('spin_t', k) for k in range(6)]}")
    g.run(3)
    check(all(g.oam(s)[1] == 224 for s in list(SHOT_SLOTS[0]) + list(SHOT_SLOTS[1])), f"{label}: the leader shot's sprite stays after it ended")
    g.set8("coins", 2, 0)
    # a shield blocks it, a star ignores it
    for what, name in (("shield", "shield_t"), ("star", "star_t")):
        cpu_calm(g)
        lineup(g, [2, 3, 4, 5, 1, 0])
        g.place(0, 512, 512, heading(tx - 512, ty - 512))
        g.set16(name, 2, 400)
        hits = g.u16("hits", 2)
        leader_flight(g, 0, 2)
        g.run(2)
        check(g.u8("spin_t", 2) == 0 and g.u16("hits", 2) == hits, f"{label}: a kart with a {what} was spun by the leader shot")
        if what == "shield":
            check(g.u16("shield_t", 2) == 0, f"{label}: the leader shot did not use up the shield: {g.u16('shield_t', 2)} frames left")
        else:
            check(g.u16("star_t", 2) > 300, f"{label}: the star ran down: {g.u16('star_t', 2)} frames left")
    # a kart in the air is passed under: the shot waits over it and hits when it lands
    cpu_calm(g)
    lineup(g, [2, 3, 4, 5, 1, 0])
    g.place(0, 512, 512, heading(tx - 512, ty - 512))
    g.set8("air_t", 2, 110)
    g.set8("air_len", 2, 110)
    use(g, 0, LEADER, ())
    i = shot_index(g)
    g.run(80)
    check(g.u8("shot_on", i) and g.u8("air_t", 2) > 0 and g.u8("spin_t", 2) == 0,
          f"{label}: the leader shot at a kart in the air: on {g.u8('shot_on', i)}, air {g.u8('air_t', 2)}, spin {g.u8('spin_t', 2)}, expected it waiting over the kart")
    for f in range(60):
        g.run(1)
        if g.u8("spin_t", 2):
            break
    check(not g.u8("shot_on", i) and g.u8("spin_t", 2) > 0, f"{label}: the leader shot did not hit the kart once it landed: on {g.u8('shot_on', i)}, spin {g.u8('spin_t', 2)}")
    # a holder in first place sends it to second place
    cpu_calm(g)
    lineup(g, [0, 2, 3, 4, 1, 5])
    hits = g.u16("hits", 2)
    frames, fastest, i = leader_flight(g, 0, 2)
    g.run(1)
    check(g.u8("spin_t", 2) > 0 and g.u16("hits", 2) == hits + 1 and g.u8("spin_t", 0) == 0,
          f"{label}: the leader's own leader shot did not spin second place: spin {[g.u8('spin_t', k) for k in range(6)]}")
    cpu_calm(g)


def leader_water_checks(g, label):
    """On a track with water (the Moon Harbour): the leader shot crosses the bay to the kart in first place, which a straight
    shot cannot do (it bounces off the shore)."""
    cpu_calm(g)
    d = TRK[g.u8("track_no")]
    xs, ys, s, L = d["route"]
    best = None
    for i in range(0, len(xs), 6):
        for j in range(i + 40, min(len(xs), i + 200), 6):
            dist = math.hypot(xs[j] - xs[i], ys[j] - ys[i])
            if 150 <= dist <= 320:
                wet = line_surfaces(g, xs[i], ys[i], xs[j], ys[j]).count(tracks.S_FALL)
                if wet >= 8 and (best is None or wet > best[0]):
                    best = (wet, i, j)
    check(best, f"{label}: no pair of route points with water between them to fly a leader shot over")
    _, i, j = best
    set_order(g, [2, 3, 4, 5, 1, 0])
    g.place(2, xs[j], ys[j], WEST)
    g.place(0, xs[i], ys[i], heading(xs[j] - xs[i], ys[j] - ys[i]))
    hits = g.u16("hits", 2)
    frames, fastest, k = leader_flight(g, 0, 2)
    g.run(1)
    check(g.u8("spin_t", 2) > 0 and g.u16("hits", 2) == hits + 1, f"{label}: the leader shot did not cross the water to the first kart: spin {g.u8('spin_t', 2)}, after {frames} frames")
    cpu_calm(g)


def cpu_give(g, k, it):
    """Computer kart k holds `it` as if its roll had just ended, and its decision countdown is about to run out."""
    g.set8("roll", k, 0)
    g.set8("item", k, it)
    g.set8("uses", k, 3)
    g.set16("cpu_age", k, 0)
    g.set8("cpu_use_t", k, 1)


def cpu_used_after(g, k, limit):
    """Frames until computer kart k has used an item (cpu_used rises), or None."""
    n0 = g.u8("cpu_used", k)
    for f in range(limit):
        g.run(1)
        if g.u8("cpu_used", k) != n0:
            return f + 1
    return None


def hud_state(g):
    """Everything of the two players' HUDs a computer kart's item must leave alone: their sprite slots (letters, place, item box,
    coin counter, sparks) and the item pictures in video memory."""
    return ([g.oam(s) for s in list(range(4, 24)) + list(range(48, 64))], hud_picture(g, 0), hud_picture(g, 1),
            [g.u8("hud_pic", p) for p in (0, 1)], [g.u8("hud_shown", p) for p in (0, 1)])


def cpu_use_checks(g, label):
    """A computer kart's item decisions, kind by kind, on the oval's bottom straight with player 1 in front of computer kart 2
    and computer kart 3 behind it: the effect lands on the player (a shot spins it, a shrink shrinks it, a steal takes its item
    and empties its HUD box); each rule waits for what it needs and falls back after 5 s; the HUDs are never written."""
    cpu_calm(g)
    lineup(g, [0, 2, 3, 4, 1, 5])
    hud0 = hud_state(g)
    # at once: coins, a star, a shield
    for it, done in ((COINS, lambda: g.u8("coins", 2) == 2), (STAR, lambda: g.u16("star_t", 2) > 0), (SHIELD, lambda: g.u16("shield_t", 2) > 0)):
        cpu_give(g, 2, it)
        n = cpu_used_after(g, 2, 6)
        check(n is not None and n <= 3 and done() and g.u8("item", 2) == 0, f"{label}: item {it} not used at once by computer kart 2 (after {n} frames)")
        g.set8("coins", 2, 0)
        g.set16("star_t", 2, 0)
        g.set16("shield_t", 2, 0)
    # a boost on a free stretch, at once; on a tight stretch not until it leaves it (or 5 s)
    cpu_calm(g)
    lineup(g, [0, 2, 3, 4, 1, 5])
    cpu_give(g, 2, BOOST)
    n = cpu_used_after(g, 2, 6)
    check(n is not None and g.u8("boost_t", 2) > 0, f"{label}: a boost on a free stretch was not used: {n}")
    d = TRK[g.u8("track_no")]
    xs, ys, _, _ = d["route"]
    runs = cpu_stretches(d, label)
    tight, free = runs[1], runs[0]
    for what, i, want in (("tight", tight, False), ("free", free, True)):
        cpu_calm(g)
        lineup(g, [0, 2, 3, 4, 1, 5])
        b = int(d["steer"][int(ys[i]) // 16, int(xs[i]) // 16])
        g.place(2, xs[i], ys[i], (b & 127) << 8)
        cpu_give(g, 2, BOOST3)
        n = cpu_used_after(g, 2, 100)
        check((n is not None) == want, f"{label}: a boost on a {what} stretch was used after {n} frames")
        if not want:  # carried to a free stretch, the held boost is used at the next look, within CPU_RECHECK frames
            j = free
            bj = int(d["steer"][int(ys[j]) // 16, int(xs[j]) // 16])
            g.place(2, xs[j], ys[j], (bj & 127) << 8)
            n = cpu_used_after(g, 2, CPU_RECHECK + 3)
            check(n is not None, f"{label}: a held boost carried to a free stretch was not used within {CPU_RECHECK + 3} frames")
    # a triple boost is used three times, 45 frames apart, then gone
    cpu_calm(g)
    lineup(g, [0, 2, 3, 4, 1, 5])
    cpu_give(g, 2, BOOST3)
    times = []
    for u in range(3):
        times.append(cpu_used_after(g, 2, 80))
        g.set8("boost_t", 2, 0)
    check(None not in times and times[1] >= 40 and times[2] >= 40 and g.u8("item", 2) == 0 and g.u8("cpu_used", 2) >= 3,
          f"{label}: a triple boost was used after {times} frames, item {g.u8('item', 2)}")
    # a computer kart that spins or sinks uses nothing until it is back
    cpu_calm(g)
    lineup(g, [0, 2, 3, 4, 1, 5])
    g.set8("spin_t", 2, 40)
    cpu_give(g, 2, COINS)
    n = cpu_used_after(g, 2, 24)
    check(n is None, f"{label}: a spinning computer kart used its item after {n} frames")
    n = cpu_used_after(g, 2, 40)
    check(n is not None and g.u8("coins", 2) == 2, f"{label}: the computer kart did not use its item once the spin was over: {n}")
    g.set8("coins", 2, 0)
    # a shot: only with a kart ahead in line; the shot spins the player in front
    for it in (SHOT, SHOT3):
        cpu_calm(g)
        lineup(g, [0, 2, 3, 4, 1, 5])
        hits = g.u16("hits", 0)
        cpu_give(g, 2, it)
        n = cpu_used_after(g, 2, 6)
        check(n is not None and n <= 3 and g.u8("shot_owner", shot_index(g)) == 2, f"{label}: computer kart 2 did not fire item {it} at the player ahead: {n}")
        g.run(40)
        check(g.u8("spin_t", 0) > 0 and g.u16("hits", 0) == hits + 1, f"{label}: a computer kart's shot did not spin the player ahead: spin {g.u8('spin_t', 0)}, hits {g.u16('hits', 0) - hits}")
    g.shot("cpu-shot-hits-player")
    # no kart ahead: held for a while, then fired anyway after 5 s
    cpu_calm(g)
    lineup(g, [2, 3, 4, 5, 1, 0])
    cpu_give(g, 2, SHOT)
    n = cpu_used_after(g, 2, 120)
    check(n is None, f"{label}: a computer kart in front of everyone fired a shot at nobody after {n} frames")
    n = cpu_used_after(g, 2, CPU_PATIENCE + 40)
    check(n is not None and n + 120 <= CPU_PATIENCE + 8 + 8, f"{label}: the held shot was used after {120 + (n or 0)} frames, expected by 5 s ({CPU_PATIENCE})")
    # slime and the fake panel: only with a kart behind; none ahead of it is no reason
    for it, kind in ((PEEL, CELL_PEEL), (PEEL3, CELL_PEEL), (FAKE, CELL_FAKE)):
        cpu_calm(g)
        lineup(g, [0, 2, 3, 4, 1, 5])
        before = len(cells_of(g, kind))
        cpu_give(g, 2, it)
        n = cpu_used_after(g, 2, 6)
        check(n is not None and len(cells_of(g, kind)) == before + 1, f"{label}: computer kart 2 did not drop item {it} with a kart behind it: {n}")
        for c in cells_of(g, kind):
            g.set8("cells", c, 0)
    for it, kind in ((PEEL, CELL_PEEL), (FAKE, CELL_FAKE)):  # the last kart has nobody behind: held, then used anyway after 5 s
        cpu_calm(g)
        lineup(g, [0, 1, 3, 4, 5, 2], top=18)
        cpu_give(g, 2, it)
        n = cpu_used_after(g, 2, 120)
        check(n is None, f"{label}: the last kart dropped item {it} with nobody behind it after {n} frames")
        n = cpu_used_after(g, 2, CPU_PATIENCE + 40)
        check(n is not None and n + 120 <= CPU_PATIENCE + 8 + 8, f"{label}: the held item {it} was used after {120 + (n or 0)} frames, expected by 5 s")
        for c in cells_of(g, kind):
            g.set8("cells", c, 0)
    # a jump: with no water or oil ahead, held until 5 s
    cpu_calm(g)
    lineup(g, [0, 2, 3, 4, 1, 5])
    cpu_give(g, 2, JUMP)
    n = cpu_used_after(g, 2, 120)
    check(n is None and not g.u8("air_t", 2), f"{label}: a computer kart jumped on a plain straight after {n} frames")
    n = cpu_used_after(g, 2, CPU_PATIENCE + 40)
    check(n is not None and g.u8("air_t", 2) > 0, f"{label}: the held jump was never used: {n}")
    # a homing shot, a leader shot, a shrink and a steal wait 0.5 to 2 s, then land on the player in front
    for it in (HOMING, LEADER, SHRINK, STEAL):
        delays = []
        for trial in range(2):
            cpu_calm(g)
            lineup(g, [0, 2, 3, 4, 1, 5])
            g.set16("rng", 0, 0x1234 * (trial + 1) + 7 * it)
            hits = g.u16("hits", 0)
            if it == STEAL:
                g.set8("roll_item", 0, SHOT)
                g.set8("roll", 0, 2)
                g.run(4)
                check(g.u8("item", 0) == SHOT and g.oam(ITEM_SLOT(0))[1] != 224, f"{label}: the player did not get the item to steal")
            cpu_give(g, 2, it)
            n = cpu_used_after(g, 2, 140)
            check(n is not None and 30 <= n <= 125, f"{label}: item {it} was used by computer kart 2 after {n} frames, expected 30 to 125")
            delays.append(n)
            if it == HOMING:
                check(g.u8("shot_home", shot_index(g)) == 1 + 0, f"{label}: the computer kart's homing shot chases {g.u8('shot_home', shot_index(g)) - 1}, expected the player ahead")
            if it == LEADER:
                check(g.u8("shot_on", shot_index(g)) == 2 + 0, f"{label}: the computer kart's leader shot is for kart {g.u8('shot_on', shot_index(g)) - 2}, expected the player in first place")
            if it in (HOMING, LEADER):
                g.run(60)
                check(g.u8("spin_t", 0) > 0 and g.u16("hits", 0) == hits + 1, f"{label}: a computer kart's item {it} did not spin the player: spin {g.u8('spin_t', 0)}")
            if it == SHRINK:
                check(g.u8("shrink_t", 0) > 0 and g.u8("shrink_t", 3) == 0, f"{label}: the computer kart's shrink hit {[g.u8('shrink_t', k) for k in range(6)]}, expected only player 1")
            if it == STEAL:
                check(g.u8("item", 0) == 0 and g.u8("item", 2) == SHOT, f"{label}: the computer kart's steal left items {g.u8('item', 0)} / {g.u8('item', 2)}, expected the player's shot taken")
                g.run(2)
                check(g.oam(ITEM_SLOT(0))[1] == 224 and hud_picture(g, 0) == SHOT, f"{label}: the player's item box did not empty after the steal: sprite line {g.oam(ITEM_SLOT(0))[1]}")
                n2 = cpu_used_after(g, 2, 70)
                check(n2 is not None and g.u8("shot_owner", shot_index(g)) == 2, f"{label}: computer kart 2 did not use the shot it stole: {n2}")
        check(delays[0] != delays[1] or it == STEAL, f"{label}: item {it} waited {delays} frames both times: not random")
    # a steal with nothing to take is kept
    cpu_calm(g)
    lineup(g, [0, 2, 3, 4, 1, 5])
    cpu_give(g, 2, STEAL)
    n = cpu_used_after(g, 2, 160)
    check(n is None and g.u8("item", 2) == STEAL, f"{label}: a steal with nothing to take was used or dropped early: {n}, item {g.u8('item', 2)}")
    n = cpu_used_after(g, 2, 200)  # held for 5 s without a use, it is dropped, so the kart can take a panel again
    check(n is None and g.u8("item", 2) == 0, f"{label}: a steal with nothing to take was not dropped after 5 s: used {n}, item {g.u8('item', 2)}")
    # a computer kart's item decisions and the roll that came before them never write a player's HUD
    cpu_calm(g)
    lineup(g, [0, 2, 3, 4, 1, 5])
    hud0 = hud_state(g)
    pc = cell_no(TRK[0]["panels"][0])
    px, py = cell_mid(TRK[0]["panels"][0])
    drawn = set()
    for n, it in enumerate((None, BOOST, SHOT, PEEL, FAKE, SHIELD, STAR, JUMP, HOMING, LEADER, SHRINK, COINS, BOOST3)):
        cpu_calm(g)
        lineup(g, [0, 2, 3, 4, 1, 5])
        if it is None:  # the roll: a panel taken, 60 frames of spinning, an item
            g.set16("rng", 0, 0x20)
            g.set8("cells", pc, CELL_PANEL)
            g.set8("panel_wait", 0, 0)
            g.place(2, px, py, WEST)
            g.run(2)
            check(g.u8("roll", 2) > 0, f"{label}: computer kart 2 took no panel")
            g.run(ROLL_FRAMES + 4)
            check(g.u8("roll", 2) == 0 and (g.u8("item", 2) != 0 or g.u8("cpu_used", 2) > 0),
                  f"{label}: computer kart 2's roll never ended with an item: roll {g.u8('roll', 2)}, item {g.u8('item', 2)}, used {g.u8('cpu_used', 2)}")
            drawn.add(g.u8("last_roll", 2))
        else:
            cpu_give(g, 2, it)
            g.run(135)
        if hud_state(g) != hud0:
            was, now = hud0[0], hud_state(g)[0]
            diff = [4 + s for s, (a, b) in enumerate(zip(was, now)) if a != b]
            raise TestFailure(f"{label}: computer kart 2's item {it} changed the players' HUDs (slots {diff[:6]}, pictures {hud_state(g)[1:3]})")
    cpu_calm(g)


def cpu_finished_checks(g, label):
    """A computer kart that has finished takes no panel and uses no item, and an item aimed at another kart (a shrink, a
    homing shot) or the leader shot never aims at a kart that has finished: it takes the next one that has not (further ahead,
    or further back for the leader); when every one has, the kart directly ahead or behind as before. Each case is also run
    with the kart still racing, so the checks can fail."""
    pc = cell_no(TRK[0]["panels"][0])
    px, py = cell_mid(TRK[0]["panels"][0])
    for done in (0, 1):
        cpu_calm(g)
        set_order(g, [2, 3, 0, 4, 1, 5])
        g.set8("finished", 2, done)
        # a panel under it
        g.set8("cells", pc, CELL_PANEL)
        g.set8("panel_wait", 0, 0)
        g.place(2, px, py, WEST)
        g.run(2)
        took = g.u8("roll", 2) > 0
        check(took == (not done) and g.u8("cells", pc) == (CELL_PANEL if done else 0),
              f"{label}: a computer kart with finished {done} over a panel: roll {g.u8('roll', 2)}, cell {g.u8('cells', pc)}")
        set_order(g, [2, 3, 0, 4, 1, 5])
        cpu_calm(g)
        g.set8("finished", 2, done)
        # an item in its hand
        cpu_give(g, 2, COINS)
        n = cpu_used_after(g, 2, 8)
        check((n is not None) == (not done) and g.u8("coins", 2) == (0 if done else 2),
              f"{label}: a computer kart with finished {done} and coins in hand used it after {n} frames (coins {g.u8('coins', 2)})")
        g.set8("coins", 2, 0)
        g.set8("finished", 2, 0)
    cpu_calm(g)
    set_order(g, [2, 3, 0, 4, 1, 5])
    # player 1 is third: the kart directly ahead is kart 3 (second); finished, kart 2 (first) is the next one ahead
    for fin, want in (((), 3), ((3,), 2), ((3, 2), 3)):
        cpu_calm(g)
        set_order(g, [2, 3, 0, 4, 1, 5])
        for k in fin:
            g.set8("finished", k, 1)
        use(g, 0, SHRINK, ())
        got = [k for k in range(6) if g.u8("shrink_t", k)]
        check(got == [want], f"{label}: with karts {list(fin)} finished, player 1's shrink hit {got}, expected kart {want}")
        use(g, 0, HOMING, ())
        i = shot_index(g)
        check(g.u8("shot_home", i) == 1 + want, f"{label}: with karts {list(fin)} finished, the homing shot chases {g.u8('shot_home', i) - 1}, expected kart {want}")
        g.set8("shot_on", i, 0)
        for k in fin:
            g.set8("finished", k, 0)
    # the leader shot goes to first place; finished, to the next place back; the leader's own goes to second place, then the one behind it
    for order, fin, want in (([2, 3, 0, 4, 1, 5], (), 2), ([2, 3, 0, 4, 1, 5], (2,), 3), ([2, 3, 0, 4, 1, 5], (2, 3), 4),
                             ([0, 2, 3, 4, 1, 5], (), 2), ([0, 2, 3, 4, 1, 5], (2,), 3)):
        cpu_calm(g)
        set_order(g, order)
        for k in fin:
            g.set8("finished", k, 1)
        use(g, 0, LEADER, ())
        i = shot_index(g)
        check(g.u8("shot_on", i) == 2 + want, f"{label}: order {order} with karts {list(fin)} finished, player 1's leader shot flies to kart {g.u8('shot_on', i) - 2}, expected {want}")
        g.set8("shot_on", i, 0)
        for k in fin:
            g.set8("finished", k, 0)
    cpu_calm(g)


def cpu_decision_cost(g, label, items):
    """A computer kart's item decision costs 10 to 40 lines in C, so it runs only on a frame that has used fewer than CPU_GATE
    lines by the end of its work (race_frame). On a quiet frame every kind runs (the dearest, slime, in the budget); on the
    finish scene (the other kart, 4 homing shots, 2 obstacles and three driving computer karts in view) it waits; and no frame
    that carried a decision goes over the budget in either. Returns nothing; the figures go into `items`."""
    worst = {}
    for scene in ("a quiet frame", "the busy finish"):
        decided = deferred = 0
        top = 0
        for it in (COINS, SHOT, PEEL, FAKE, HOMING, SHRINK, STEAL, LEADER, JUMP, BOOST):
            cpu_calm(g)
            lineup(g, [0, 2, 3, 4, 1, 5])
            if scene != "a quiet frame":
                g.set8("cpu_hold", 0, 0)
                g.set8("cpu_alt", 0, CPU_ALT)
                busy_scene(g, 0)
                x, y, dx, dy = tracks.checkpoint_at(trk(g), 0)
                g.place(0, x - 4 * dx, y - 4 * dy, heading(dx, dy))
                g.run(6)
            for rep_ in range(3):
                cpu_give(g, 2, it)
                g.set16("cpu_age", 2, 5)  # past a delay or a wait: the decision uses the item
                if it == STEAL:
                    g.set8("item", 0, SHOT)
                g.set16("max_lines", 0, 0)
                g.run(1)
                lines = g.u16("max_lines")
                if g.u8("cpu_due") & 4:
                    deferred += 1
                else:
                    decided += 1
                    top = max(top, lines)
                    check(lines <= MAX_LINES, f"{label}: {scene}: a decision about item {it} took the frame to {lines} lines, budget {MAX_LINES}")
                g.set8("cpu_due", 0, 0)
        worst[scene] = (top, decided, deferred)
    quiet, busy = worst["a quiet frame"], worst["the busy finish"]
    check(quiet[1] >= 24, f"{label}: on a quiet frame {quiet[1]} decisions ran and {quiet[2]} waited, expected nearly all to run (30 on the real ROM; the probes of the --phases build add 10 lines, so a few wait there)")
    check(busy[2] > 0, f"{label}: on the busy finish no decision waited ({busy[1]} ran, {busy[2]} waited): the gate does not hold them back")
    cpu_calm(g)
    items["heaviest frame with an item decision (quiet, busy finish), decisions run and deferred"] = (quiet[0], busy[0], quiet[1:], busy[1:])


def cpu_jump_rule_checks(g, label):
    """Before water or oil a computer kart jumps at once; with none within 64 px ahead it does not (on a track that has some).
    The places are found on the track's surface map: a point of plain road and one of eight headings."""
    surf = open(os.path.join(ROOT, "game", "res", f"trk{g.u8('track_no')}.surf"), "rb").read()
    hazard = (tracks.S_FALL, tracks.S_OIL)
    at = lambda x, y: surf[(int(y) // 8) * 128 + int(x) // 8] if 0 <= x < 1024 and 0 <= y < 1024 else tracks.S_GRASS  # noqa: E731
    near = clear = None
    for ty in range(4, 124):
        for tx in range(4, 124):
            if surf[ty * 128 + tx] != tracks.S_ROAD:
                continue
            x, y = tx * 8 + 4, ty * 8 + 4
            for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                ahead = [at(x + dx * a, y + dy * a) for a in (24, 48)]
                if near is None and any(a in hazard for a in ahead):
                    near = (x, y, dx, dy)
                if clear is None and all(a == tracks.S_ROAD for a in at_range(at, x, y, dx, dy)):
                    clear = (x, y, dx, dy)
    check(near and clear, f"{label}: no place to test the jump rule from: near {near}, clear {clear}")
    for what, (x, y, dx, dy), want in (("hazard ahead", near, True), ("clear road", clear, False)):
        cpu_calm(g)
        g.place(2, x, y, heading(dx, dy))
        cpu_give(g, 2, JUMP)
        n = cpu_used_after(g, 2, 60)
        check((n is not None) == want, f"{label}: a computer kart with {what} at ({x},{y}) heading ({dx},{dy}) used its jump after {n} frames (expected {'at once' if want else 'not within 60 frames'})")
    cpu_calm(g)


def at_range(at, x, y, dx, dy):
    """The surfaces 0 to 64 px ahead of (x, y) along (dx, dy), every 8 px."""
    return [at(x + dx * a, y + dy * a) for a in range(0, 65, 8)]


def cpu_busy(g, n, label, alt=0):
    """The busiest frame with n computer karts: the finish (the other kart, 4 homing shots and 2 obstacles in view and the
    banner) with the computer karts ahead of both players, played four times with the finish a frame later each time, since
    a computer kart's progress and the places are worked out on every 4th frame, and with alt each half's karts on alternate
    frames. The computer karts are in their costly states, not only on plain road: the first on the grass beside the road,
    the second spinning, the third boosting (the fourth plain), and the first one's item decision (a shot, looked at and fired
    at a kart ahead) lands on every frame, so on the measured one. Returns (the most lines the logic needed in any of them, the
    most sprites and the most 8-pixel tiles on one screen line); every one of the n karts must be drawn in both halves."""
    best, worst = 0, (0, 0)
    g.worst_detail = {}
    for phase in range(4):
        cpu_calm(g)
        g.set8("cpu_n", 0, n)
        g.set8("cpu_alt", 0, alt)
        g.set8("cpu_hold", 0, 0)  # the computer karts drive in the busiest frame
        p = 0
        for k in range(6):
            g.set8("finished", k, 0)
            g.set8("lap", k, 1)
            g.set8("cp", k, 5)
        g.set8("lap", p, 3)
        g.set8("cp", p, NCP - 1)
        g.set8("done_count", 0, 0)
        g.set16("end_timer", 0, 0)
        for h in (0, 1):
            g.set8("banner_left", h, 0)
            g.set8("banner_t", h, 0)
            for i in range(16):
                g.set8("oamMemory", (BANNER_SLOT(h) + i) * 4 + 1, 224)
        busy_scene(g, p)
        x, y, dx, dy = tracks.checkpoint_at(trk(g), 0)
        nx, ny = -dy, dx
        for k, (ahead, side) in zip(range(2, 2 + n), ((90, -12), (130, 12), (170, -12), (255, 12))):  # on the road, clear of the shots and obstacles
            if k == 2:  # the first one on the grass beside the road, the second (spinning) in front of it in line, so its shot is fired
                side = next(sd for sd in (-46, 46, -54, 54, -62, 62) if d_surface(g, int(x + ahead * dx + sd * nx), int(y + ahead * dy + sd * ny)) == tracks.S_GRASS)
                grass_side = side
            if k == 3:
                side = grass_side
            g.place(k, x + ahead * dx + side * nx, y + ahead * dy + side * ny, heading(dx, dy))
        g.place(p, x - 24 * dx, y - 24 * dy, heading(dx, dy))
        g.run(8 + phase)  # the places settle (and their HUD redraws are done) before the measured crossing
        if n >= 2:
            g.set8("spin_t", 3, 255)  # spinning
        if n >= 3:
            g.set8("boost_t", 4, 255)  # boosting
        g.set16("max_lines", 0, 0)
        decided = deferred = 0
        for step in range(20):
            d = -24 + 2 * step
            g.place(p, x + d * dx, y + d * dy, heading(dx, dy))
            for name in ("fall_t", "air_t", "spin_t"):
                g.set8(name, p, 0)
            if n >= 1:
                cpu_give(g, 2, SHOT)  # its item decision is due this frame
            g.run(1)
            if n >= 1:
                if not g.u8("cpu_due") & 4:  # the decision ran: the bit is cleared when cpu_items() takes it
                    decided += 1
                else:
                    deferred += 1
            if step >= 3:
                g.run(1)  # each half's computer karts may be projected on alternate frames: look after two
                inview = [(v, k) for v in (0, 1) for k in range(2, 2 + n) if g.oam(CPU_SLOT_OF(v, k))[1] != 224]
                check(len(inview) == 2 * n, f"{label}: only {inview} of the {2 * n} computer kart sprites are drawn in the busy scene")
            ld = line_load(g)
            if ld[1] > worst[1]:
                g.worst_detail = {l: v for l, v in g.line_detail.items() if len(v) >= ld[0] - 1}
            worst = (max(worst[0], ld[0]), max(worst[1], ld[1]))
        g.run(2)
        lines = g.u16("max_lines")  # not g.lines(): these scenes are not the busiest of the other checks
        if n >= 1:
            g.cpu_decisions[(n, alt)] = (deferred, decided)
        if lines > best:
            best = lines
            g.cpu_tables[(n, alt)] = (lines, g.phase_table())
            if n == CPU_FIT and not alt:
                g.shot("busy-computer-karts")
    g.set16("max_lines", 0, 0)
    for k in range(6):  # the player that crossed the line is racing again
        g.set8("finished", k, 0)
        g.set8("lap", k, 1)
        g.set8("cp", k, 5)
    g.set8("done_count", 0, 0)
    g.set16("end_timer", 0, 0)
    g.set8("cpu_n", 0, 4)
    g.set8("cpu_alt", 0, CPU_ALT)
    cpu_calm(g)
    return best, worst


def cpu_race_checks(g, stats, budget, items):
    """The computer-kart race on the Clover Oval: six on the grid (read from the ROM for every track), hidden until their
    frames are loaded, drawn in both halves, hit and bumped, ranked 1 to 6, items aimed, finishing, and the busiest frame."""
    check(g.u8("track_no") == 0 and g.u8("cpu_n") == CPU_FIT,
          f"computer karts: track {g.u8('track_no')}, cpu_n {g.u8('cpu_n')} after asking for 9 (the most is {CPU_FIT})")
    check(g.u8("cpu_alt") == CPU_ALT, f"computer karts: cpu_alt is {g.u8('cpu_alt')} at the start, expected {CPU_ALT}")
    cpu_start_checks(g, "computer karts at the start")
    cpu_hidden_before_ready(g)
    for _ in range(300):
        if g.state() == ST_RACE and g.u8("cpu_gfx_ready"):
            break
        g.run(1)
    check(g.u8("cpu_gfx_ready"), "computer karts: the frames were never loaded")
    g.run(2)
    for k in range(2, 6):  # parked: nothing moved them since the start
        check(g.kart(k)[2] == 0, f"computer kart {k} drives at speed {g.kart(k)[2]}")
    grid_checks(g, "start grids")
    # the busiest frame with 0 to 4 computer karts in view of both players: the budget holds for CPU_FIT of them
    # with each half's karts projected on alternate frames (cpu_alt, the default); the others and every frame are reported
    lines_by_n, alt_by_n = {}, {}
    for n in range(0, 5):
        lines, worst = cpu_busy(g, n, f"busiest frame with {n} computer karts")
        lines_by_n[n] = lines
        check(worst[0] <= SPRITE_LINE_LIMITS[0] and worst[1] <= SPRITE_LINE_LIMITS[1],
              f"busiest frame with {n} computer karts: a screen line carries {worst[0]} sprites and {worst[1]} tiles, limits {SPRITE_LINE_LIMITS} {g.worst_detail}")
        items[f"{n} computer karts: sprites, tiles per line"] = worst
        alt_by_n[n] = cpu_busy(g, n, f"busiest frame with {n} computer karts on alternate frames", alt=1)[0]
    check(VBLANK_LINES < alt_by_n[CPU_FIT] <= MAX_LINES,
          f"logic used {alt_by_n[CPU_FIT]} of 262 lines at the finish with {CPU_FIT} computer karts in view and driving, each half's on alternate frames "
          f"(budget {MAX_LINES})")
    cpu_draw_checks(g, "computer karts drawn")
    cpu_alt_checks(g, "computer karts on alternate frames")
    lag = (cpu_lag(g, 0), cpu_lag(g, 1))
    check(lag[0] <= 3, f"computer karts drawn every frame are {lag[0]} px off the camera while turning (alternate frames: {lag[1]})")
    items["computer kart sprite lag in px while turning (every frame, alternate frames)"] = lag
    cpu_bump_checks(g, "computer karts bumped")
    cpu_hud_checks(g, "computer kart HUD")
    cpu_hit_checks(g, "computer karts hit")
    cpu_place_checks(g, "computer kart places")
    cpu_item_checks(g, "computer kart items")
    cpu_finished_checks(g, "finished computer karts")
    leader_checks(g, "leader shot")
    cpu_use_checks(g, "computer karts use items")
    cpu_decision_cost(g, "computer kart decisions", items)
    cpu_timeout_checks(g, "computer kart timeout")
    cpu_final_frame_checks(g, "computer kart places on the last frame")
    budget["Computer karts"] = alt_by_n[CPU_FIT]
    items["busiest frame by computer karts"] = lines_by_n
    items["... on alternate frames"] = alt_by_n
    cpu_finish_checks(g, "computer kart finish")
    g.set8("cpu_n", 0, 0)



# ---------------------------------------------------------------- computer karts drive

CPU_TOPS = [row[1] for row in tracks.kart_types()]  # light, medium, heavy: top speed on the road, 1/16 px a frame (main.c kart_types)
CPU_SLOW = 30        # speed a computer kart holds in a tight stretch (proj.asm CPU_SLOW)
CPU_TIME_MAX = 1.6   # a computer kart's race time is at most this times the route's 3 laps at its type's top speed (measured on four tracks, three types: 0.96 to 1.20 before the computer karts used items, 0.96 to 1.35 after: the karts spin each other with shots and slime, 4 to 17 spins a race; the kart also starts from rest, bumps, spins in oil and under rolling obstacles, and slows in tight stretches)
CPU_TIME_MIN = 0.85  # and at least this much: a kart that beats its own top speed by more than the shortcuts and pads allow is cheating
CPU_OFF_MAX = 0.08   # at most this share of a computer kart's race frames off the road, ramp and pad (oil, sand and grass count; measured 0 to 4.2 percent, 6.0 in one build with the probes: a boost carries a kart wide in a bend, a spin can end on the verge)
CPU_RACE_LIMIT = 9000
# the two computer animals of each track's race (A drives karts 2 and 4, B kart 3): all three types are raced
CPU_ANIMALS = [("OTTER", "GOAT"), ("T-REX", "OTTER"), ("GOAT", "T-REX"), ("OTTER", "T-REX")]


def cpu_rng(g, a, b):
    """The rng that makes choose_cpu() pick animals a and b (names) when the players hold their picks."""
    free = [i for i in range(len(CAST)) if i not in (g.u8("pick", 0), g.u8("pick", 1))]
    ia = free.index(NAMES.index(a))
    ib = [i for i in free if i != NAMES.index(a)].index(NAMES.index(b))
    return ia | ib << 8


def steer_checks(g, label):
    """The steering map in the ROM for the track raced: cur_steer points at it, it is the generator's, and on the road its
    headings point along the race direction (a few cells at each of 16 checkpoints, in the middle and 12 px to either side)."""
    n = g.u8("track_no")
    d = TRK[n]
    ram = g.r.wram()
    o = g.off("cur_steer")
    ptr = ram[o] | ram[o + 1] << 8 | ram[o + 2] << 16
    check((ptr & 0x7FFFFF) == (g.syms[f"trk{n}_steer"] & 0x7FFFFF), f"{label}: cur_steer is {ptr:06X}, expected track {n}'s map at {g.syms[f'trk{n}_steer']:06X}")
    rom = g.rom_bytes(f"trk{n}_steer", 4096)
    check(bytes(rom) == d["steer"].tobytes(), f"{label}: the steering map in the ROM is not the generator's")
    bad = []
    for j in range(0, NCP, 2):
        for lat in (0, -12, 12):
            x, y, dx, dy = tracks.point_at(d["route"], (j + 0.5) / NCP, lat)
            b = rom[(int(y) // 16) * 64 + int(x) // 16]
            a = (b & 127) * 2 * math.pi / 128
            cos = math.sin(a) * dx - math.cos(a) * dy
            if cos < 0.5:
                bad.append((j, lat, round(math.degrees(math.acos(max(-1, min(1, cos)))))))
    check(not bad, f"{label}: steering headings more than 60 degrees off the race direction on the road: (checkpoint, sideways, degrees) {bad[:6]}")
    flagged = sum(1 for b in rom if b & 128)
    check(0 < flagged < 4096 // 2, f"{label}: {flagged} of 4096 steering cells are marked tight")


def cpu_run_to(g, ks, limit, label, until=None):
    """Runs frames (holding the results off) until `until()` or the limit; returns the frames run."""
    for i in range(limit):
        g.set16("end_timer", 0, 600)
        g.run(1)
        if until():
            return i + 1
    return limit


def cpu_prepare(g, k, lap, cp, x, y, angle, speed=0):
    """Computer kart k, alone in the race (cpu_n 1 makes it kart 2), on lap `lap` with checkpoint `cp` reached, placed and
    clear of every timer."""
    for name in ("boost_t", "spin_t", "spin_off", "hop_t", "wheelspin_t", "drift", "charge", "air_t", "trick", "trick_t", "fall_t",
                 "kart_lift", "shrink_t", "roll", "item", "uses", "wrong", "finished", "cpu_use_t"):
        g.set8(name, k, 0)
    g.set8("coins", k, 0)
    g.set8("lap", k, lap)
    g.set8("cp", k, cp)
    g.set8("done_count", 0, 0)
    g.place(k, x, y, angle, speed)
    g.set16("end_timer", 0, 600)


def cpu_drive_race(g, n, items):
    """A race on track n with CPU_FIT computer karts (the two players parked off the route): they stay parked with
    cpu_hold, start without a rocket start, and all finish 3 laps within the time bound, off the road under CPU_OFF_MAX of
    their frames, and never faster than their type allows."""
    label = f"computer karts drive on {TRACK_NAMES[n]}"
    d = TRK[n]
    ks = list(range(2, 2 + CPU_FIT))
    check(g.u8("track_no") == n and g.u8("cpu_n") == CPU_FIT, f"{label}: track {g.u8('track_no')} with {g.u8('cpu_n')} computer karts")
    a, b = CPU_ANIMALS[n]
    check((g.u8("cpu_pick", 0), g.u8("cpu_pick", 1)) == (NAMES.index(a), NAMES.index(b)), f"{label}: the computer animals are {g.u8('cpu_pick', 0), g.u8('cpu_pick', 1)}, expected {a} and {b}")
    steer_checks(g, label)
    cpu_parked_checks(g, n, label, ks, items)
    g.set8("cpu_hold", 0, 1)  # held: nothing moves, and nothing changes in the karts
    g.run(1)
    held = [g.kart(k) for k in ks]
    g.run(60)
    check([g.kart(k) for k in ks] == held, f"{label}: with cpu_hold 1 a computer kart moved: {[g.kart(k) for k in ks]} from {held}")
    g.set8("cpu_hold", 0, 0)
    g.run(2)
    check(all(g.kart(k) != held[i] for i, k in enumerate(ks)), f"{label}: with cpu_hold 0 again a computer kart did not move")
    types = [g.u8("kart_type", k) for k in ks]
    check(sorted(set(types)) == sorted({CAST[NAMES.index(a)]["type"], CAST[NAMES.index(b)]["type"]}), f"{label}: kart types {types}")
    surf = open(os.path.join(ROOT, "game", "res", f"trk{n}.surf"), "rb").read()
    frames, off, done, over, last_boost, coin_hist = ({k: v for k in ks} for v in (0, 0, 0, -99, 99, None))
    coin_hist = {k: [0] * 16 for k in ks}
    fell, spun = {k: 0 for k in ks}, {k: 0 for k in ks}
    t0 = g.u16("race_time")
    for i in range(CPU_RACE_LIMIT):
        g.set16("end_timer", 0, 600)  # the race runs on until every computer kart is home
        g.run(1)
        ram = g.r.wram()
        for k in ks:
            if done[k]:
                continue
            x, y, sp, an = struct.unpack_from("<hhhH", ram, g.off("karts", k * 12))
            x, y = x >> 4, y >> 4
            if ram[g.off("finished", k)]:
                done[k] = struct.unpack_from("<H", ram, g.off("finish_time", 2 * k))[0]
                continue
            frames[k] += 1
            air = ram[g.off("air_t", k)]
            if not air and not (0 <= x < 1024 and 0 <= y < 1024 and surf[(y // 8) * 128 + x // 8] in (tracks.S_ROAD, tracks.S_PAD, tracks.S_RAMP)):
                off[k] += 1
            last_boost[k] = 0 if ram[g.off("boost_t", k)] or ram[g.off("shrink_t", k)] or air else last_boost[k] + 1  # in the air the speed is kept, a boost from before the jump with it
            coin_hist[k] = coin_hist[k][1:] + [ram[g.off("coins", k)]]
            if last_boost[k] > 12:
                over[k] = max(over[k], sp - (CPU_TOPS[types[k - 2]] + (min(max(coin_hist[k]), 10) >> 1) + 1))
            fell[k] += ram[g.off("fall_t", k)] == 1
            spun[k] += ram[g.off("spin_t", k)] == SPIN_FRAMES
        if len(done) and all(done[k] for k in ks):
            break
    check(all(done[k] for k in ks), f"{label}: computer karts {[k for k in ks if not done[k]]} did not finish 3 laps in {i + 1} frames (laps {[g.u8('lap', k) for k in ks]}, checkpoints {[g.u8('cp', k) for k in ks]})")
    L = d["length"]
    times, factors, shares = [], [], []
    for k, t in zip(ks, types):
        ideal = 3 * L / (CPU_TOPS[t] / 16)  # frames for 3 laps of the route at top speed
        times.append(done[k])
        factors.append(float(round(done[k] / ideal, 2)))
        shares.append(float(round(100 * off[k] / frames[k], 2)))
        check(CPU_TIME_MIN <= done[k] / ideal <= CPU_TIME_MAX,
              f"{label}: computer kart {k} (type {t}) took {done[k]} frames, {done[k] / ideal:.2f} times the {ideal:.0f} of its top speed; allowed {CPU_TIME_MIN} to {CPU_TIME_MAX}")
        check(off[k] <= CPU_OFF_MAX * frames[k], f"{label}: computer kart {k} was off the road for {off[k]} of {frames[k]} frames ({100 * off[k] / frames[k]:.1f}%), allowed {100 * CPU_OFF_MAX:.0f}%")
        check(over[k] <= 0, f"{label}: computer kart {k} (type {t}) went {over[k]} faster than its top speed and coins allow, with no boost")
    items[f"{TRACK_NAMES[n]}: computer kart race frames (karts 2-4), time over 3 laps at top speed, off-road %, falls, spins"] = (times, factors, shares, [fell[k] for k in ks], [spun[k] for k in ks])
    used = [g.u8("cpu_used", k) for k in ks]
    check(all(u >= 1 for u in used), f"{label}: computer karts used {used} items in the race, each should have used at least one")
    items[f"{TRACK_NAMES[n]}: items each computer kart used"] = used


PUSH_MAX = 4        # px: how far a parked kart may be shoved by a computer kart that drives into it
PASS_FRAMES = 180   # 3 s: every computer kart is past a parked kart by then


def cpu_parked_checks(g, n, label, ks, items):
    """GO with player 2 left on the grid and no button pressed (the grid puts no computer kart in a player's line, but the
    karts' own lane bias takes one of them into it), player 1 parked off the route: 12 frames on, no computer kart has had a
    rocket start or spun its wheels and each is at speed 1 to 18; then every computer kart must be past player 2 within
    PASS_FRAMES, and player 2 may be shoved at most PUSH_MAX px. Ends with both players parked off the route."""
    d = TRK[n]
    _, _, sdx, sdy = tracks.point_at(d["route"], 0.0)
    for name in ("boost_t", "wheelspin_t", "drift", "charge", "spin_t"):  # the countdown held B to the last frame
        g.set8(name, 1, 0)
    g.place(1, *d["grid"][1], d["angle"], 0)
    park(g, 0)
    start = g.kart(1)[:2]
    g.run(12)
    check(all(g.u8("boost_t", k) == 0 and g.u8("wheelspin_t", k) == 0 for k in ks), f"{label}: a computer kart got a rocket start or spun its wheels")
    check(all(0 < g.kart(k)[2] <= 18 for k in ks), f"{label}: computer kart speeds 12 frames after GO are {[g.kart(k)[2] for k in ks]}")
    passed, push = None, 0
    for t in range(13, 241):
        g.run(1)
        x, y = g.kart(1)[:2]
        push = max(push, abs(x - start[0]), abs(y - start[1]))
        if passed is None and all((g.kart(k)[0] - x) * sdx + (g.kart(k)[1] - y) * sdy > 12 for k in ks):
            passed = t
    check(passed is not None and passed <= PASS_FRAMES,
          f"{label}: with player 2 parked on the grid the computer karts were all past it after {passed} frames, expected at most {PASS_FRAMES} (karts {[g.kart(k)[:3] for k in ks]}, player 2 {g.kart(1)[:2]})")
    check(push <= PUSH_MAX, f"{label}: parked player 2 was shoved {push} px by the computer karts, expected at most {PUSH_MAX}")
    items[f"{TRACK_NAMES[n]}: parked player 2 on the grid: frames until every computer kart is past, most px it was shoved"] = (passed, push)
    for p in (0, 1):
        park(g, p)


def cpu_blocked_checks(g, n, items):
    """On track n, computer kart 2 alone drives at 30 straight at a kart standing still in the middle of the road on the start
    straight (kart 0, no button pressed): it goes round, is past it within 150 frames, shoves it at most PUSH_MAX px, and
    120 frames later is still driving (speed 20 or more) on the road, well beyond it."""
    label = f"computer kart round a stopped kart on {TRACK_NAMES[n]}"
    d = TRK[n]
    g.set8("cpu_n", 0, 1)
    park(g, 1)
    x, y, dx, dy = tracks.point_at(d["route"], 0.0)
    ang = heading(dx, dy)
    cpu_prepare(g, 2, 2, NCP - 1, x - 50 * dx, y - 50 * dy, ang, 30)
    for name in ("boost_t", "wheelspin_t", "drift", "charge", "spin_t", "fall_t", "air_t"):
        g.set8(name, 0, 0)
    bx, by = x + 90 * dx, y + 90 * dy
    g.place(0, bx, by, ang, 0)
    g.set8("cpu_hold", 0, 0)
    passed, push = None, 0
    for t in range(1, 151):
        g.run(1)
        kx, ky = g.kart(2)[:2]
        push = max(push, abs(g.kart(0)[0] - bx), abs(g.kart(0)[1] - by))
        if passed is None and (kx - bx) * dx + (ky - by) * dy > 12:
            passed = t
    check(passed is not None, f"{label}: the kart is at {g.kart(2)[:3]} after 150 frames, the stopped kart at ({bx:.0f}, {by:.0f})")
    check(push <= PUSH_MAX, f"{label}: the stopped kart was shoved {push:.1f} px, expected at most {PUSH_MAX}")
    g.run(120)
    kx, ky, sp, _ = g.kart(2)
    check((kx - bx) * dx + (ky - by) * dy > 150 and sp >= 20 and d_surface(g, kx, ky) in (tracks.S_ROAD, tracks.S_PAD, tracks.S_RAMP),
          f"{label}: 120 frames after passing it the kart is at ({kx}, {ky}) speed {sp} on surface {d_surface(g, kx, ky)}, the stopped kart at ({bx:.0f}, {by:.0f})")
    items[f"{TRACK_NAMES[n]}: computer kart round a stopped kart: frames until past, most px the stopped kart was shoved"] = (passed, push)
    g.set8("cpu_n", 0, CPU_FIT)


CPU_BIAS = [-3, 3, 0, 0]  # each computer kart's own heading bias, steps of 128 to the turn (proj.asm cpu_bias, karts 2 to 5)


def cpu_stretches(d, label):
    """The longest stretch of route samples (2 px apart) with the tight mark set and the longest without it, as the
    samples to start from (the middle of each, 8 samples early)."""
    st = d["steer"]
    xs, ys, s, L = d["route"]
    cells = [st[int(y) // 16, int(x) // 16] >> 7 for x, y in zip(xs, ys)]
    best = {0: (0, 0), 1: (0, 0)}  # (length, first sample)
    i = 0
    while i < len(cells):
        j = i
        while j < len(cells) and cells[j] == cells[i]:
            j += 1
        best[cells[i]] = max(best[cells[i]], (j - i, i))
        i = j
    check(best[0][0] >= 40 and best[1][0] >= 40, f"{label}: no stretch of 80 px both tight and free: {best}")
    return {f: best[f][1] + best[f][0] // 2 - 8 for f in (0, 1)}


def cpu_lift_checks(g, label):
    """Tight stretches: a computer kart placed at speed 40 where the steering map marks a tight stretch is down to about
    CPU_SLOW within 14 frames; at the same speed on a free stretch it holds its top speed."""
    d = TRK[g.u8("track_no")]
    st = d["steer"]
    xs, ys, s, L = d["route"]
    runs = cpu_stretches(d, label)
    for i in (0, 1):
        g.set8("ob_on", i, 0)
    g.set8("cpu_n", 0, 1)
    top = CPU_TOPS[g.u8("kart_type", 2)]
    out = {}
    for tight in (1, 0):
        i = runs[tight]
        b = st[int(ys[i]) // 16, int(xs[i]) // 16]
        cpu_prepare(g, 2, 1, g.u8("cp", 2), xs[i], ys[i], (b & 127) << 8, 40)
        g.run(14)
        out[tight] = g.kart(2)[2]
    check(CPU_SLOW - 5 <= out[1] <= CPU_SLOW + 3, f"{label}: a computer kart in a tight stretch is at speed {out[1]} after 14 frames, expected about {CPU_SLOW}")
    check(out[0] >= top - 3, f"{label}: a computer kart on a free stretch is at speed {out[0]} after 14 frames, expected about {top}")
    g.set8("cpu_n", 0, CPU_FIT)


def cpu_steer_checks(g, label):
    """A computer kart turns towards the heading its cell's steering byte gives plus its own bias: not at all when it is within
    one step of it, by the type's turn a frame when it is two or more off, to the right when the target is larger (clockwise)
    and to the left when it is smaller. Three karts, one frame each, on a free stretch."""
    d = TRK[g.u8("track_no")]
    st = d["steer"]
    xs, ys, s, L = d["route"]
    start = cpu_stretches(d, label)[0]
    for i in (0, 1):
        g.set8("ob_on", i, 0)
    g.set8("cpu_n", 0, 3)
    for diff, want in ((0, 0), (1, 0), (-1, 0), (2, 1), (-2, -1), (5, 1), (-5, -1), (40, 1), (-40, -1)):
        angles = {}
        for idx, k in enumerate((2, 3, 4)):
            i = start + 12 * idx
            b = int(st[int(ys[i]) // 16, int(xs[i]) // 16])
            target = ((b & 127) + CPU_BIAS[k - 2]) & 127
            angles[k] = (((target - diff) & 127) << 8) | 0x40
            cpu_prepare(g, k, 1, g.u8("cp", k), xs[i], ys[i], angles[k], 30)
        g.run(1)
        for k in (2, 3, 4):
            turn = tracks.kart_types()[g.u8("kart_type", k)][2]
            got = (g.kart(k)[3] - angles[k] + 32768) % 65536 - 32768
            check(got == want * turn, f"{label}: computer kart {k} {diff} steps off its target turned by {got}, expected {want * turn}")
    g.set8("cpu_n", 0, CPU_FIT)


def cpu_cap_checks(g, label):
    """On the oval's top straight a computer kart with 20 coins (10 count) tops out at its type's speed plus 5 steps, and
    on the grass beside the road its speed stays at the grass speed."""
    g.set8("cpu_n", 0, 1)
    for i in (0, 1):
        g.set8("ob_on", i, 0)
    top = CPU_TOPS[g.u8("kart_type", 2)]
    cpu_prepare(g, 2, 1, g.u8("cp", 2), 700, 240, WEST, top)
    g.set8("coins", 2, 20)
    g.run(70)
    check(g.kart(2)[2] == top + 5, f"{label}: a computer kart with 20 coins is at speed {g.kart(2)[2]}, expected {top} and 5 steps (10 coins count)")
    cpu_prepare(g, 2, 1, g.u8("cp", 2), 700, 150, WEST, 0)  # grass above the top straight, heading along the road
    fast = 0
    for _ in range(40):
        g.run(1)
        x, y = g.kart(2)[:2]
        if d_surface(g, x, y) == tracks.S_GRASS:
            fast = max(fast, g.kart(2)[2])
    check(0 < fast <= MAX_GRASS, f"{label}: a computer kart on the grass reached speed {fast}, expected up to {MAX_GRASS}")
    g.set8("cpu_n", 0, CPU_FIT)


def d_surface(g, x, y):
    """The surface under map pixel (x, y) of the track raced."""
    surf = open(os.path.join(ROOT, "game", "res", f"trk{g.u8('track_no')}.surf"), "rb").read()
    return surf[(y // 8) * 128 + x // 8]


def cpu_scene_finish(g, label, limit=2500):
    """Runs until computer kart 2 has finished; returns the frames it took."""
    n = cpu_run_to(g, [2], limit, label, until=lambda: g.u8("finished", 2))
    check(g.u8("finished", 2), f"{label}: computer kart 2 did not finish within {limit} frames (lap {g.u8('lap', 2)}, checkpoint {g.u8('cp', 2)}, at {g.kart(2)[:3]})")
    return n


def cpu_recover_checks(g, n, items):
    """On track n, computer kart 2 alone: a hit, being put off the road facing backwards, oil, a crevasse or the water, and in
    each case it recovers and finishes the race (cpu_n 1: kart 2 is the only one racing)."""
    d = TRK[n]
    g.set8("cpu_n", 0, 1)
    label = f"computer kart recovery on {TRACK_NAMES[n]}"
    if n == 0:
        j = NCP - 10
        x, y, dx, dy = tracks.checkpoint_at(d, j)
        cpu_prepare(g, 2, 3, j - 1, x, y, heading(dx, dy), 30)
        g.run(30)
        check(g.kart(2)[2] >= 36, f"{label}: the kart is at speed {g.kart(2)[2]} before the hit")
        g.set8("coins", 2, 6)
        g.set8("shot_struck", 2, 1)  # the hit a shot or obstacle makes
        g.run(2)
        check(g.u8("spin_t", 2) > 0 and g.u8("coins", 2) == 6 - COIN_LOSS, f"{label}: the hit did not spin the kart: spin {g.u8('spin_t', 2)}, coins {g.u8('coins', 2)}")
        g.run(30)
        check(g.kart(2)[2] <= 4, f"{label}: a spinning computer kart is at speed {g.kart(2)[2]} 30 frames into the spin")
        t = cpu_scene_finish(g, f"{label}, after a hit")
        items["recovery frames: after a hit"] = t
        # off the road, facing back along it
        j = NCP - 8
        px, py = off_track_near(d, j)
        x, y, dx, dy = tracks.checkpoint_at(d, j)
        cpu_prepare(g, 2, 3, j - 1, px, py, heading(-dx, -dy), 0)
        g.run(2)
        check(d["prog"][int(py) // 16, int(px) // 16] == tracks.OFF, f"{label}: the backwards kart's start is not off the track")
        t = cpu_scene_finish(g, f"{label}, off the road facing backwards")
        items["recovery frames: off the road facing backwards"] = t
    elif n == 1:
        t_ = tracks.TRACKS[1]
        frac, lat = t_["oil"][0]
        x, y, dx, dy = tracks.point_at(d["route"], frac, lat)
        j = int(frac * NCP)
        cpu_prepare(g, 2, 3, j, x, y, heading(dx, dy), 32)
        for _ in range(6):
            g.run(1)
            if g.u8("spin_t", 2):
                break
        check(g.u8("spin_t", 2) > 0, f"{label}: a computer kart placed on the oil at speed 32 did not spin")
        t = cpu_scene_finish(g, f"{label}, after the oil")
        items["recovery frames: after oil"] = t
    elif n == 2:
        far, dd, gap = d["falls"][0]
        x, y = far[0] + dd[0] * gap / 2, far[1] + dd[1] * gap / 2
        j = int(0.965 * NCP) - 1
        cpu_prepare(g, 2, 3, j, x, y, heading(-dd[0], -dd[1]), 0)
        r0 = g.u16("rescues", 2)
        for _ in range(4):
            g.run(1)
        check(g.u8("fall_t", 2) > 0, f"{label}: a computer kart placed in the crevasse did not fall")
        t = cpu_scene_finish(g, f"{label}, after the crevasse")
        check(g.u16("rescues", 2) == r0 + 1, f"{label}: the kart in the crevasse was rescued {g.u16('rescues', 2) - r0} times, expected once")
        items["recovery frames: after the crevasse"] = t
    else:
        surf = open(os.path.join(ROOT, "game", "res", "trk3.surf"), "rb").read()
        x, y, dx, dy = tracks.point_at(d["route"], 0.62)
        _, tx, ty = min(((tx * 8 + 4 - x) ** 2 + (ty * 8 + 4 - y) ** 2, tx, ty) for ty in range(128) for tx in range(128)
                        if surf[ty * 128 + tx] == S_FALL and abs(tx * 8 - x) < 160 and abs(ty * 8 - y) < 160)
        j = int(0.62 * NCP) - 1
        cpu_prepare(g, 2, 3, j, tx * 8 + 4, ty * 8 + 4, heading(dx, dy), 0)
        r0 = g.u16("rescues", 2)
        g.run(4)
        check(g.u8("fall_t", 2) > 0, f"{label}: a computer kart placed in the water did not fall")
        t = cpu_scene_finish(g, f"{label}, after the water")
        check(g.u16("rescues", 2) == r0 + 1, f"{label}: the kart in the water was rescued {g.u16('rescues', 2) - r0} times, expected once")
        items["recovery frames: after the water"] = t
    cpu_lift_checks(g, label)
    if n == 0:
        cpu_steer_checks(g, label)
        cpu_cap_checks(g, label)
    g.set8("cpu_n", 0, CPU_FIT)


def cpu_drive_block(g, n, items):
    """Menu to a race on track n with the computer karts, then their checks; ends at the results screen."""
    g.press(0, SELECT)
    g.wait_state(ST_SELECT, 30)
    g.run(SELECT_WAIT)
    pick(g, 0, NAMES.index("RED PANDA"))
    pick(g, 1, NAMES.index("TRICERATOPS"))
    g.wait_state(ST_TRACKS, START_WAIT + 10)
    g.run(SELECT_WAIT + 2)
    g.set8("cpu_hold", 0, 0)  # the computer karts are free from the start: the countdown must hold them
    choose(g, 0, n + 1, rng=cpu_rng(g, *CPU_ANIMALS[n]))
    countdown(g)
    cpu_drive_race(g, n, items)
    cpu_recover_checks(g, n, items)
    cpu_blocked_checks(g, n, items)
    if n == 3:
        leader_water_checks(g, f"leader shot on {TRACK_NAMES[n]}")
    if n in (1, 3):
        cpu_jump_rule_checks(g, f"computer karts jump on {TRACK_NAMES[n]}")
    # the busiest frame on this track: CPU_FIT computer karts in their costly states at the finish line, each half's on alternate frames
    lines, worst = cpu_busy(g, CPU_FIT, f"busiest frame on {TRACK_NAMES[n]} with {CPU_FIT} computer karts", alt=1)
    check(VBLANK_LINES < lines <= MAX_LINES, f"{TRACK_NAMES[n]}: logic used {lines} of 262 lines at the finish with {CPU_FIT} computer karts (budget {MAX_LINES})")
    check(worst[0] <= SPRITE_LINE_LIMITS[0] and worst[1] <= SPRITE_LINE_LIMITS[1],
          f"{TRACK_NAMES[n]}: a screen line carries {worst[0]} sprites and {worst[1]} tiles with {CPU_FIT} computer karts, limits {SPRITE_LINE_LIMITS}")
    items[f"{TRACK_NAMES[n]}: busiest frame with {CPU_FIT} computer karts (alternate frames)"] = lines
    g.set8("cpu_n", 0, CPU_FIT)
    g.set8("finished", 0, 1)  # a player is home: with no time left the results come
    g.set8("done_count", 0, 1)
    g.set16("end_timer", 0, 0)
    g.wait_state(ST_RESULTS, 60)
    g.run(RESULTS_WAIT + 5)
    g.set8("cpu_hold", 0, 1)


# ---------------------------------------------------------------- one real race to the results

def autopilot(g, p):
    """The buttons that drive player p along the track the way the computer karts do (proj.asm cpu_frame): the pedal, steering
    towards the heading the track's steering map gives for the cell under the kart, and the brake in a tight stretch above
    CPU_SLOW. It reads only where the kart is and how it points."""
    x, y, speed, angle = g.kart(p)
    b = int(trk(g)["steer"][min(max(y // 16, 0), 63), min(max(x // 16, 0), 63)])
    diff = ((b & 127) - ((angle >> 8) & 127)) & 127
    keys = []
    if 2 <= diff <= 63:
        keys.append(RIGHT)
    elif 64 <= diff <= 126:
        keys.append(LEFT)
    keys.append(Y if b & 128 and speed > CPU_SLOW else B)
    return tuple(keys)


def cpu_real_race(g, items):
    """A whole race on the Clover Oval from the menu: both players drive by the autopilot (no kart is moved by the test) and three
    computer karts drive and use items, to a real finish and the results screen. The places, the times and the results rows agree:
    finished karts are placed in the order of their finish times, the others behind them by progress, the winner is the first
    player home, and the results come 10 s after the first player's finish or 1.5 s after both."""
    label = "a real race with computer karts"
    g.press(0, SELECT)
    g.wait_state(ST_SELECT, 30)
    g.run(SELECT_WAIT)
    pick(g, 0, NAMES.index("RED PANDA"))
    pick(g, 1, NAMES.index("TRICERATOPS"))
    g.wait_state(ST_TRACKS, START_WAIT + 10)
    g.run(SELECT_WAIT + 2)
    g.set8("cpu_hold", 0, 0)
    choose(g, 0, 1, rng=cpu_rng(g, *CPU_ANIMALS[0]))
    countdown(g)
    check(g.u8("cpu_n") == CPU_FIT and g.u8("track_no") == 0, f"{label}: {g.u8('cpu_n')} computer karts on track {g.u8('track_no')}")
    t0 = g.f
    for i in range(CPU_RACE_LIMIT):
        if g.state() != ST_RACE:
            break
        g.run(1, autopilot(g, 0), autopilot(g, 1))
    check(g.state() == ST_RESULTS, f"{label}: state {g.state()} after {g.f - t0} frames (laps {[g.u8('lap', k) for k in range(5)]})")
    g.run(5)
    g.shot("real-race-results")
    n = 2 + g.u8("cpu_n")
    fin = [g.u8("finished", k) for k in range(n)]
    ft = [g.u16("finish_time", k) for k in range(n)]
    place_ = [g.u8("place", k) for k in range(n)]
    players = [k for k in (0, 1) if fin[k]]
    check(players, f"{label}: neither player finished in {g.f - t0} frames (laps {[g.u8('lap', k) for k in range(n)]}, finished {fin})")
    done = sorted((ft[k], k) for k in range(n) if fin[k])
    check(all(ft[k] > 0 for k in range(n) if fin[k]), f"{label}: a finished kart has time 0: {ft}")
    check([place_[k] for _, k in done] == list(range(1, len(done) + 1)),
          f"{label}: finish order {[k for _, k in done]} (times {[t for t, _ in done]}) but places {[place_[k] for _, k in done]}")
    check(all(place_[k] > len(done) for k in range(n) if not fin[k]), f"{label}: a kart that did not finish is placed {place_} among the {len(done)} that did")
    first_player = min((ft[k], k) for k in players)[1]
    check(g.u8("winner") == first_player, f"{label}: winner {g.u8('winner')}, expected the first player home, kart {first_player} (times {ft})")
    first_home = min(ft[k] for k in players)
    last_home = max(ft[k] for k in players)
    since = g.u16("race_time") - (last_home if len(players) == 2 else first_home)  # the clock stops with the race
    want = AFTER_BOTH if len(players) == 2 else AFTER_FIRST
    check(abs(since - want) <= 3, f"{label}: the results came {since} frames after the {'second' if len(players) == 2 else 'first'} player finished, expected {want}")
    ranking = cpu_results_checks(g, label, [])
    check(ranking == sorted(range(n), key=lambda k: place_[k]), f"{label}: the results rows are in order {ranking}, places {place_}")
    used = [g.u8("cpu_used", k) for k in range(2, n)]
    check(sum(used) >= 1, f"{label}: the computer karts used {used} items in the whole race")
    items["real race: finish times, items the computer karts used"] = (ft, used)
    g.run(RESULTS_WAIT)
    g.set8("cpu_hold", 0, 1)


# ---------------------------------------------------------------- a cup with computer karts

# Each race's finishers in order; every other kart racing does not finish and is placed by progress. Kart 2 and 4 drive
# animal A, kart 3 animal B. The totals are 23 for kart 2, 22 for karts 3 and 0, 15 for kart 4 and 7 for kart 1. Kart 2 leads
# although it was 5th in the last race (the points count before the place), and karts 3 and 0 tie on 22 with kart 3 better placed
# in the last race (2nd against 3rd), so the podium is computer kart 2, computer kart 3 and player 1.
CUP_PLAN = [[2, 0, 3, 1, 4], [3, 2, 4, 0], [0, 2, 1, 3], [4, 3, 0, 1, 2]]
PODIUM_BLOCKS = [(12, 15, 176, (232, 184, 40)), (1, 18, 177, (200, 204, 216)), (23, 20, 178, (205, 127, 50))]  # column, top row, tile, colour
PODIUM_POINTS_X = (13, 2, 24)  # where each block's points text starts


def driver_label(k):
    """What the podium and the results call the driver of kart k: a computer kart is numbered by its kart number."""
    return f"COMPUTER {k - 1}" if k > 1 else f"PLAYER {k + 1}"


def cpu_cup_podium_checks(g, order, pts):
    """The podium of a cup with computer karts: the top three by points on the gold, silver and bronze blocks, each with its
    animal's portrait on it, its place and its points; the winner's animal in big letters."""
    g.wait_state(ST_PODIUM, 30)
    g.run(5)
    check(g.u8("cup_winner") == order[0], f"podium: cup winner kart {g.u8('cup_winner')}, expected {order[0]}")
    v = g.vram()
    check(v[0xC000:0xC000 + 384 * 32] == open(os.path.join(ROOT, "game", "res", "select_obj.pic"), "rb").read(),
          "podium: the portraits are not in the sprite tiles")
    for i, (col, row, tile, rgb) in enumerate(PODIUM_BLOCKS):
        k = order[i]
        a = animal_of(g, k)
        x, y, t, attr, large = g.oam(i)
        skin = CAST[a]["palette"][characters.ch_portrait_slot(CAST[a])]
        check(shows(box_colours(g, x, y, 32), skin), f"podium: block {i + 1}'s portrait lacks {NAMES[a]}'s colour {skin}")
        check((x, y, t, (attr >> 1) & 7, large) == (col * 8 + 16, row * 8 - 32, BUST_TILE(a), a // 3, 1),
              f"podium: block {i + 1}'s portrait {(x, y, t, (attr >> 1) & 7, large)}, expected animal {NAMES[a]} at ({col * 8 + 16},{row * 8 - 32})")
        who = driver_label(k)
        cells = [v[(UI_MAP + r * 32 + c) * 2] for r in range(row, 23) for c in range(col, col + 8)
                 if not (r == row + 1 and col + 2 <= c <= col + 4) and not (r == row + 2 and col + 4 - len(who) // 2 <= c < col + 4 - len(who) // 2 + len(who))]
        check(all(t == tile for t in cells), f"podium: block {i + 1} is not solid tile {tile}: {sorted(set(cells))}")
        check(v[(UI_MAP + (row - 1) * 32 + col) * 2] == 0 and v[(UI_MAP + row * 32 + col - 1) * 2] == 0,
              f"podium: block {i + 1} is bigger than its size")
        check(shows(box_colours(g, col * 8 + 1, row * 8 + 10, 4), rgb), f"podium: block {i + 1} is not drawn in its colour {rgb}")
        label = ("1ST", "2ND", "3RD")[i]
        check(g.map_text(col + 2, row + 1, 3) == label, f"podium: block {i + 1} reads {g.map_text(col + 2, row + 1, 3)!r}, expected {label!r}")
        txt = f"{pts[k]} PTS"
        tx = PODIUM_POINTS_X[i]
        check(g.map_text(tx, 23, len(txt)) == txt, f"podium: block {i + 1} points read {g.map_text(tx, 23, len(txt))!r}, expected {txt!r}")
        got = g.map_text(col + 4 - len(who) // 2, row + 2, len(who))  # under the animal: who drives it, on the block
        check(got == who, f"podium: block {i + 1} (kart {k}) names its driver {got!r}, expected {who!r}")
    spans = sorted((PODIUM_POINTS_X[i], PODIUM_POINTS_X[i] + len(f"{pts[order[i]]} PTS")) for i in range(3))
    check(all(b[0] - a[1] >= 2 for a, b in zip(spans, spans[1:])), f"podium: the points texts {spans} are less than two blank columns apart")
    row = [" "] * 32
    for i in range(3):
        for j, ch in enumerate(f"{pts[order[i]]} PTS"):
            row[PODIUM_POINTS_X[i] + j] = ch
    check(g.map_text(0, 23, 32) == "".join(row), f"podium: the points row reads {g.map_text(0, 23, 32)!r}, expected {''.join(row)!r}")
    name = NAMES[animal_of(g, order[0])]
    check(big_line(g, name) == name, f"podium: the big heading reads {big_line(g, name)!r}, expected {name!r}")
    g.shot("podium-computer")


def cpu_cup_checks(g, items):
    """The menu keeps three computer karts through a race and a battle, then a cup of four races with them: each race's
    results list the karts in place order with their points by place (cup_points), the computer karts keep their animals
    for the whole cup, a kart that did not finish scores nothing, and the podium shows the top three."""
    label = "cup with computer karts"
    check(list(g.rom_bytes("cup_points", 11)) == CUP_POINTS + [0, 0, 0] + CUP_POINTS_CPU + [1],
          f"{label}: the points table reads {list(g.rom_bytes('cup_points', 11))}, expected {CUP_POINTS + [0, 0, 0] + CUP_POINTS_CPU + [1]} (places 1 to 6 of a cup with computer karts)")
    g.press(0, SELECT)
    g.wait_state(ST_SELECT, 30)
    g.run(SELECT_WAIT)
    pick(g, 0, NAMES.index("RED PANDA"))
    pick(g, 1, NAMES.index("TRICERATOPS"))
    g.wait_state(ST_TRACKS, START_WAIT + 10)
    g.run(SELECT_WAIT + 2)
    cpu_row_check(g, CPU_FIT)
    g.set8("cpu_hold", 0, 1)
    g.set16("rng", 0, 0xACE1)  # the earlier checks leave it at 0, where it stays: a new pick of the animals would be the same
    choose(g, 0, 0)
    check(g.u8("cpu_n") == CPU_FIT, f"{label}: {g.u8('cpu_n')} computer karts race")
    total = [0] * 6
    animals = None
    for n, order in enumerate(CUP_PLAN):
        countdown(g)
        got = (g.u8("cpu_pick", 0), g.u8("cpu_pick", 1))
        if animals is None:
            animals = got
        check(got == animals, f"{label}, race {n + 1}: the computer animals are {got}, they were {animals} in race 1")
        check(g.u8("track_no") == n and g.u8("cpu_n") == CPU_FIT, f"{label}, race {n + 1}: track {g.u8('track_no')}, {g.u8('cpu_n')} computer karts")
        cpu_calm(g)
        rest = [k for k in range(CPU_FIT + 2) if k not in order]
        set_order(g, order + rest + [5])
        for k in order:
            g.set8("lap", k, 3)
            g.set8("cp", k, NCP - 1)
        for k in order:
            cross(g, k, 0)
            check(g.u8("finished", k), f"{label}, race {n + 1}: kart {k} did not finish")
        for k in rest:
            check(not g.u8("finished", k), f"{label}, race {n + 1}: kart {k} finished without driving")
        g.wait_state(ST_RESULTS, AFTER_FIRST + 120)
        g.run(5)
        for r, k in enumerate(order):
            total[k] += CUP_POINTS_CPU[r]
        got = [g.u8("points", k) for k in range(6)]
        check(got == total, f"{label}, race {n + 1}: points {got}, expected {total}")
        head = g.map_text(9, 2, 15)
        check(head == f"CUP RACE {n + 1} OF 4", f"{label}, race {n + 1}: heading {head!r}")
        cpu_results_checks(g, f"{label}, results {n + 1}", order, total)
        g.shot(f"cup-computer-{n + 1}")
        g.run(RESULTS_WAIT)
        g.press(0, START)
        if n < 3:
            g.wait_state(ST_COUNTDOWN, 30)
            g.countdown_from = g.f
    pts = total
    order = sorted(range(CPU_FIT + 2), key=lambda k: (-pts[k], g.u8("place", k)))
    check(order[:3] == [2, 3, 0] and pts[3] == pts[0] and pts[2] > pts[3] and g.u8("place", 2) > g.u8("place", 3),
          f"{label}: the plan's totals {pts} (last places {[g.u8('place', k) for k in range(5)]}) do not tie kart 3 and kart 0 behind kart 2, which was placed worse in the last race")
    cpu_cup_podium_checks(g, order, pts)
    check(g.u8("cpu_menu") == CPU_FIT, f"{label}: {g.u8('cpu_menu')} computer karts chosen after the cup, expected {CPU_FIT}")
    # the podium's Start begins a new cup: the points start again
    g.run(60)
    g.press(0, START)
    g.wait_state(ST_COUNTDOWN, 30)
    check([g.u8("points", k) for k in range(6)] == [0] * 6 and g.u8("cpu_n") == CPU_FIT, f"{label}: the new cup's points {[g.u8('points', k) for k in range(6)]}")
    g.countdown_from = g.f
    countdown(g)
    g.set8("cpu_hold", 0, 1)


def run(core, syms, rom, shots):
    g = Game(core, syms, shots)
    g.rom = rom
    g.busiest = (0, [], 0)
    g.cpu_tables = {}
    g.cpu_decisions = {}
    g.stats = kart_stats(g)
    stats = {"match": 1.0, "frames": 0, "done": 0, "laps": []}
    measured = {}
    # the triceratops's name needs two lines on the results screen, the frog's one
    frog, trike, red_panda = NAMES.index("FROG"), NAMES.index("TRICERATOPS"), NAMES.index("RED PANDA")

    g.run(20)
    check(g.state() == ST_TITLE, f"boot: state {g.state()}, expected the title")
    check((g.u8("pick", 0), g.u8("pick", 1)) == (0, 1), "boot: the picks are not the otter and the T-Rex")
    title_checks(g)
    g.shot("title")

    # the select screen: player 1 takes the frog, player 2 is refused it and takes the triceratops
    to_select(g, 1)
    for key, want in ((LEFT, 5), (RIGHT, 0), (UP, 12), (DOWN, 0), (DOWN, 6), (DOWN, 12)):  # wraps round the grid
        g.press(0, key)
        check(g.u8("cursor", 0) == want, f"select: player 1 cursor {g.u8('cursor', 0)} after a press, expected {want}")
        cursor_check(g, 0)
    pick(g, 0, frog)
    move(g, 1, (LEFT, DOWN, DOWN))
    pick(g, 1, frog, taken=True)
    move(g, 1, (UP, RIGHT, RIGHT, RIGHT, RIGHT))
    g.shot("select")
    pick(g, 1, trike)
    g.run(START_WAIT - 10)
    check(g.state() == ST_SELECT, f"the track menu came less than {START_WAIT - 4} frames after the second pick")
    menu_checks(g)
    g.shot("track-menu")
    choose(g, 0, 1, rng=17 | 16 << 8)  # fixes the computer animals the race picks (expect_cpu): the 2nd and the 2nd of the rest
    check((g.u8("pick", 0), g.u8("pick", 1)) == (frog, trike), "race 1 does not race the frog and the triceratops")

    # race 1, a single race on the Clover Oval: player 1 wins, player 2 does not finish
    countdown(g)
    race_loads_picks(g, "race 1")
    expect_cpu(g, 17 | 16 << 8, "race 1")
    record_checks(g)
    race_loads_track(g, 0, "race 1")
    minimap_checks(g)
    drive_checks(g, stats)
    cpu_checks(g, "race 1")
    physics_checks(g)
    view_checks(g)
    items = {}
    proj_checks(g, items)
    coin_checks(g, items)
    panel_checks(g, items)
    boost_checks(g, items)
    shot_checks(g, items)
    peel_checks(g, items)
    pad_checks(g, items)
    drift_checks(g, items)
    wrong_way_checks(g, items)
    second_set_checks(g, items)
    hits = g.u16("hits", 0) + g.u16("hits", 1)  # balloons only pop in a balloon battle: hits in a race leave it running
    check(hits >= 3 and not g.u8("done_count") and (g.u16("pops", 0), g.u16("pops", 1)) == (0, 0),
          f"race 1: {hits} hits ended the race or popped balloons: done {g.u8('done_count')}, pops {g.u16('pops', 0)} {g.u16('pops', 1)}")
    calm(g)
    type_checks(g, 0, measured)
    type_checks(g, 1, measured)
    park(g, 1)
    race_from, fd_from = g.f, g.u16("frames_done")
    skip_checks(g, 0)
    full_laps(g, 0, stats)
    check(g.u8("winner") == 0 and g.u8("place", 0) == 1 and g.u16("finish_time", 0) > 0,
          f"race 1: winner {g.u8('winner')}, player 1 place {g.u8('place', 0)} time {g.u16('finish_time', 0)}")
    g.run(30)
    g.shot("finish-banner")
    since = g.u16("race_time") - g.u16("finish_time", 0)
    g.run(AFTER_FIRST - since - 10)
    check(g.state() == ST_RACE, "race 1: results came before 10 seconds had passed")
    stats["frames"] += g.f - race_from
    stats["done"] += (g.u16("frames_done") - fd_from) & 0xFFFF
    since = g.u16("race_time") - g.u16("finish_time", 0) + g.wait_state(ST_RESULTS, 20)
    check(abs(since - AFTER_FIRST) <= 2, f"race 1: results {since} frames after player 1 finished, expected {AFTER_FIRST}")
    check(not g.u8("finished", 1), "race 1: player 2 finished without driving")
    g.run(5)
    results_checks(g, "results 1")
    check(g.map_text(11, 2, 11) == "CLOVER OVAL", f"results 1: heading {g.map_text(11, 2, 11)!r}, expected the track's name")
    g.shot("results-1")
    g.press(0, START)
    check(g.state() == ST_RESULTS, "a Start pressed as the results appear skipped them")
    g.run(RESULTS_WAIT)

    # race 2, a rematch from the results screen on player 1's pad: player 2 wins, both finish. The rng is set
    # so that the computer karts' draws land on a player's own pick: they must go to the next free animal
    low = min(frog, trike)
    start_race(g, 0, rng=low | low << 8)
    for k, want in [(k, CELL_COIN) for k in TRK[0]["coins"]] + [(k, CELL_PANEL) for k in TRK[0]["panels"]]:
        c = cell_no(k)  # the rematch puts back what race 1 took
        check(g.u8("cells", c) == want and g.cell_tiles(c) == floor_set(g, want),
              f"rematch: cell {k} holds {g.u8('cells', c)} with tiles {g.cell_tiles(c)}")
    rocket_countdown(g)
    check((g.u8("pick", 0), g.u8("pick", 1)) == (frog, trike), "the rematch changed the animals")
    race_loads_picks(g, "race 2")
    expect_cpu(g, low | low << 8, "race 2")
    cpu_load_cost(g)
    cpu_checks(g, "race 2")
    race_from, fd_from = g.f, g.u16("frames_done")
    position_checks(g)
    park(g, 0)
    full_laps(g, 1, stats)
    park(g, 1)
    finish_second(g, 0, stats)  # within the 10 s after the first finish: its laps were counted in race 1
    stats["frames"] += g.f - race_from
    stats["done"] += (g.u16("frames_done") - fd_from) & 0xFFFF
    since = g.u16("race_time") - g.u16("finish_time", 0) + g.wait_state(ST_RESULTS, AFTER_BOTH + 10)
    check(abs(since - AFTER_BOTH) <= 2, f"race 2: results {since} frames after both finished, expected {AFTER_BOTH}")
    t0, t1 = g.u16("finish_time", 0), g.u16("finish_time", 1)
    check(g.u8("winner") == 1 and g.u8("place", 1) == 1 and g.u8("place", 0) == 2 and 0 < t1 < t0,
          f"race 2: winner {g.u8('winner')}, places {g.u8('place', 0)}/{g.u8('place', 1)}, times {t0}/{t1}")
    g.run(RESULTS_WAIT + 5)
    results_checks(g, "results 2")
    g.shot("results-2")

    # Select goes back to the select screen; a cup with the red panda (medium) against the triceratops
    g.press(1, SELECT)
    g.wait_state(ST_SELECT, 30)
    g.run(SELECT_WAIT)
    check(g.u8("cursor", 0) == frog and g.u8("cursor", 1) == trike, "back on the select screen, the cursors left the last picks")
    pick(g, 1, trike)  # this time player 2 picks first, and player 1 is refused the same animal
    move(g, 0, (UP, RIGHT, RIGHT, RIGHT, RIGHT))
    pick(g, 0, trike, taken=True)
    move(g, 0, (LEFT, LEFT, LEFT, LEFT))
    # Y undoes player 2's pick; both then press B on the red panda on the same frame: player 1 gets it
    g.press(1, Y)
    check(not g.u8("locked", 1), "select: Y did not undo player 2's pick")
    cursor_check(g, 1)
    move(g, 1, (LEFT, LEFT, LEFT, LEFT))
    check(g.u8("cursor", 1) == red_panda, f"select: player 2 cursor on {NAMES[g.u8('cursor', 1)]}")
    g.run(3, (B,), (B,))
    g.run(3)
    check(g.u8("locked", 0) and g.u8("pick", 0) == red_panda and not g.u8("locked", 1),
          f"select: both pressed B on the red panda: locked {g.u8('locked', 0)}/{g.u8('locked', 1)}, pick {g.u8('pick', 0)}")
    flash_check(g, 1)
    move(g, 1, (RIGHT, RIGHT, RIGHT, RIGHT))
    pick(g, 1, trike)
    # both locked: Y still undoes until the track menu opens
    g.run(START_WAIT // 2)
    g.press(0, Y)
    check(not g.u8("locked", 0), "select: Y during the wait did not undo player 1's pick")
    g.run(START_WAIT)
    check(g.state() == ST_SELECT, "select: the track menu opened after player 1 undid the pick")
    pick(g, 0, red_panda)
    g.wait_state(ST_TRACKS, START_WAIT + 10)
    g.run(SELECT_WAIT + 2)
    choose(g, 1, 0)

    # the cup: the winners alternate; player 2 does not finish race 1 and player 1 not race 4, so the
    # points tie (3 + 1 + 3 + 0 against 0 + 3 + 1 + 3) and the last race's winner, player 2, takes the cup
    budget = {"races 1-2": g.lines()}  # the oval's checks, with both dropping slime in the busiest scene
    check(VBLANK_LINES < budget["races 1-2"] <= MAX_LINES, f"races 1-2: logic used {budget['races 1-2']} of 262 lines")
    plan = [(0, False, [3, 0]), (1, True, [4, 3]), (0, True, [7, 4]), (1, False, [7, 7])]
    for n, (win, second, pts) in enumerate(plan):
        cup_race(g, n, win, second, stats, measured, items, budget)
        check(g.u8("winner") == win and g.u8("finished", 1 - win) == second,
              f"cup race {n + 1}: winner {g.u8('winner') + 1}, other finished {g.u8('finished', 1 - win)}")
        results_cup_checks(g, f"cup results {n + 1}", pts)
        g.shot(f"cup-results-{n + 1}")
        g.press(0, START)
        if n < 3:
            g.wait_state(ST_COUNTDOWN, 30)
            g.countdown_from = g.f
    podium_checks(g, 1, [7, 7])
    stats["budget"] = budget

    # from the podium, Select and the same animals: a single race on the Moon Harbour
    g.run(60)
    g.press(0, SELECT)
    g.wait_state(ST_SELECT, 30)
    g.run(SELECT_WAIT)
    pick(g, 0, red_panda)
    pick(g, 1, trike)
    g.wait_state(ST_TRACKS, START_WAIT + 10)
    g.run(SELECT_WAIT + 2)
    choose(g, 0, 4)
    countdown(g)
    race_loads_track(g, 3, "single race on the Moon Harbour")
    drive_from_grid(g, stats)
    g.shot("moon-harbour")
    finish_second(g, 0, stats)
    finish_second(g, 1, stats)
    g.wait_state(ST_RESULTS, AFTER_BOTH + 30)
    g.run(RESULTS_WAIT + 5)

    # battles on the arena, picked from the track menu after Select
    for pos, check_battle in ((5, balloon_battle_checks), (6, coin_battle_checks)):
        g.press(0, SELECT)
        g.wait_state(ST_SELECT, 30)
        g.run(SELECT_WAIT)
        pick(g, 0, red_panda)
        pick(g, 1, trike)
        g.wait_state(ST_TRACKS, START_WAIT + 10)
        g.run(SELECT_WAIT + 2)
        if pos == 5:  # three computer karts chosen: a battle has none, and the choice stays
            for _ in range(CPU_FIT):
                g.press(0, RIGHT)
            cpu_row_check(g, CPU_FIT)
        choose(g, 0, pos)
        check(g.u8("cpu_n") == 0 and g.u8("cpu_menu") == CPU_FIT, f"battle {pos - 4}: {g.u8('cpu_n')} computer karts race in a battle, {g.u8('cpu_menu')} chosen")
        g.set16("max_lines", 0, 0)
        countdown(g)
        race_loads_track(g, ARENA_NO, "the arena")
        check_battle(g, stats, items)
        budget["Battle " + str(pos - 4)] = g.lines()
        check(VBLANK_LINES < budget["Battle " + str(pos - 4)] <= MAX_LINES, f"battle {pos - 4}: logic used {budget['Battle ' + str(pos - 4)]} of 262 lines")
        g.run(RESULTS_WAIT + 5)

    # a race on the Clover Oval with four computer karts, parked on the grid: drawn, hit, bumped, placed, finishing
    g.press(0, SELECT)
    g.wait_state(ST_SELECT, 30)
    g.run(SELECT_WAIT)
    pick(g, 0, red_panda)
    pick(g, 1, trike)
    g.wait_state(ST_TRACKS, START_WAIT + 10)
    g.run(SELECT_WAIT + 2)
    check(g.u8("cpu_menu") == CPU_FIT, f"the battles left {g.u8('cpu_menu')} computer karts chosen, expected {CPU_FIT}")
    g.set8("cpu_menu", 0, 9)  # more than the most: the race start holds it to CPU_FIT
    choose(g, 0, 1)
    g.set8("cpu_menu", 0, CPU_FIT)
    countdown(g)
    race_loads_track(g, 0, "the computer kart race")
    cpu_race_checks(g, stats, budget, items)
    g.run(RESULTS_WAIT + 5)
    for n in range(4):  # the computer karts drive: three of them race each track
        cpu_drive_block(g, n, items)
    cpu_real_race(g, items)

    cpu_cup_checks(g, items)

    lines = max([g.lines()] + list(budget.values()))
    stats["busiest"] = g.busiest
    check(VBLANK_LINES < lines <= MAX_LINES, f"logic used {lines} of 262 lines (budget {MAX_LINES})")
    check(stats["done"] == stats["frames"], f"dropped frames: loop ran {stats['done']} of {stats['frames']} race frames")
    check(stats["match"] >= MATCH, f"floor matches the reference on {stats['match']:.1%} of pixels")
    stats["types"] = measured
    stats["items"] = items
    stats["cpu_tables"] = g.cpu_tables
    return stats, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="directory for screenshots of each step")
    ap.add_argument("--core", action="append", help="emulator(s) to run; default all three")
    ap.add_argument("--phases", action="store_true",
                    help="run on a copy of the ROM built with PROBES 1 and print what each phase of the busiest frame cost "
                         "(the probes add about 7 lines, so the totals are higher than the real ROM's)")
    a = ap.parse_args()
    global ROM, SYM, MAX_LINES
    if not os.path.exists(ROM):
        sys.exit("FAIL: no ROM; build first with make -C game")
    if a.phases:
        d = tempfile.mkdtemp(prefix="probe_rom_")
        for sub in ("game", "tools"):
            shutil.copytree(os.path.join(ROOT, sub), os.path.join(d, sub), ignore=shutil.ignore_patterns("__pycache__"))
        f = os.path.join(d, "game", "main.c")
        src = open(f).read()
        assert src.count("#define PROBES 0") == 1
        open(f, "w").write(src.replace("#define PROBES 0", "#define PROBES 1"))
        subprocess.run(["make", "-C", os.path.join(d, "game")], capture_output=True)
        log = os.path.join(d, "game", "couchkart.log")
        if "Build finished successfully" not in (open(log).read() if os.path.exists(log) else ""):
            sys.exit("FAIL: the ROM with probes did not build")
        MAX_LINES = 10 ** 6  # the probes add lines: measure them, whatever the budget
        ROM, SYM = os.path.join(d, "game", "couchkart.sfc"), os.path.join(d, "game", "couchkart.sym")
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
    syms, rom = rr.load_syms(SYM), open(ROM, "rb").read()
    failed = False
    for core in a.core or CORES:
        try:
            stats, lines = run(core, syms, rom, a.shots)
            types = ", ".join(f"{characters.TYPE_NAMES[k].lower()} {f} frames to top {t}, turn {r}"
                              for k, (f, t, r) in sorted(stats["types"].items()))
            pl, pn = stats["items"]["projection"]
            print(f"PASS {core}: loop ran {stats['done']} of {stats['frames']} race frames, logic used {lines} of 262 lines "
                  f"(per track at the finish: {', '.join(f'{k.title()} {v}' for k, v in stats['budget'].items())}), "
                  f"floor matches reference {stats['match']:.1%}, lap counts {stats['laps']}; {types}; "
                  f"projection {pl} lines for {pn} things ({pl / pn:.1f} each); "
                  + ", ".join(f"{k} {v}" for k, v in stats["items"].items() if k != "projection"))
            m, ph, start = stats["busiest"]
            if ph:
                print(f"  busiest frame on {core}: {m} lines (the loop starts {start} lines after vblank began); lines per phase:")
                for n, v in zip(PHASES, ph):
                    print(f"    {v:4d}  {n}")
                print(f"    {sum(ph):4d}  sum of the phases")
            tabs = stats.get("cpu_tables", {})
            for n, alt in ((1, 0), (1, 1), (3, 1), (4, 0), (4, 1)):
                if (n, alt) in tabs and tabs[(n, alt)][1][0]:
                    m, (ph, start) = tabs[(n, alt)]
                    print(f"  computer-kart busiest frame on {core}, {n} karts, cpu_alt {alt}: {m} lines (the loop starts {start} lines after vblank began); lines per phase:")
                    for nm, v in zip(PHASES, ph):
                        print(f"    {v:4d}  {nm}")
                    print(f"    {sum(ph):4d}  sum of the phases")
        except TestFailure as e:
            failed = True
            print(f"FAIL {core}: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
