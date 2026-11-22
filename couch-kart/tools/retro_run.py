#!/usr/bin/env python3
"""Headless SNES runner: loads a libretro core and a ROM, plays a scripted input
sequence, saves screenshots and reads work RAM. Used by the tests and for
screenshots you can look at, so no display or sound is needed.

Usage:
  retro_run.py --core snes9x2005 --rom game.sfc --frames 300 \
      --hold "60-240:p0=up,p1=up+right" --shot 120:out.png --shot 300:out2.png \
      --read wram_sym=frames_done --sym game.sym
"""
import argparse
import ctypes as C
import os
import struct
import sys
import zlib

CORE_DIR = os.environ.get("SNES_CORES", os.path.expanduser("~/opt/snesdev/cores"))

# libretro constants
ENV_GET_CAN_DUPE = 3
ENV_SET_PIXEL_FORMAT = 10
ENV_GET_SYSTEM_DIRECTORY = 9
ENV_GET_SAVE_DIRECTORY = 31
ENV_GET_VARIABLE = 15
ENV_GET_VARIABLE_UPDATE = 17
PIX_0RGB1555, PIX_XRGB8888, PIX_RGB565 = 0, 1, 2
MEM_SYSTEM_RAM = 2

# RetroPad button ids
BUTTONS = {"b": 0, "y": 1, "select": 2, "start": 3, "up": 4, "down": 5, "left": 6,
           "right": 7, "a": 8, "x": 9, "l": 10, "r": 11}


class GameInfo(C.Structure):
    _fields_ = [("path", C.c_char_p), ("data", C.c_void_p), ("size", C.c_size_t), ("meta", C.c_char_p)]


class Variable(C.Structure):
    _fields_ = [("key", C.c_char_p), ("value", C.c_char_p)]


ENV_CB = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VIDEO_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AUDIO_CB = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
AUDIO_BATCH_CB = C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t)
POLL_CB = C.CFUNCTYPE(None)
STATE_CB = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)


def write_png(path, w, h, rgb):
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


class Runner:
    def __init__(self, core, rom):
        path = core if os.path.isfile(core) else os.path.join(CORE_DIR, f"{core}_libretro.so")
        self.lib = C.CDLL(path)
        self.pixfmt = PIX_0RGB1555
        self._raw = None
        self._frame = None
        self.pressed = {0: set(), 1: set()}
        self._sysdir = C.c_char_p(os.path.dirname(path).encode())
        self._cbs = [ENV_CB(self._env), VIDEO_CB(self._video), AUDIO_CB(lambda l, r: None),
                     AUDIO_BATCH_CB(lambda d, n: n), POLL_CB(lambda: None), STATE_CB(self._state)]
        L = self.lib
        L.retro_set_environment(self._cbs[0])
        L.retro_set_video_refresh(self._cbs[1])
        L.retro_set_audio_sample(self._cbs[2])
        L.retro_set_audio_sample_batch(self._cbs[3])
        L.retro_set_input_poll(self._cbs[4])
        L.retro_set_input_state(self._cbs[5])
        L.retro_init()
        data = open(rom, "rb").read()
        self._rom = C.create_string_buffer(data, len(data))
        info = GameInfo(os.path.abspath(rom).encode(), C.cast(self._rom, C.c_void_p), len(data), None)
        L.retro_load_game.restype = C.c_bool
        if not L.retro_load_game(C.byref(info)):
            raise SystemExit(f"core refused the ROM: {rom}")
        L.retro_get_memory_data.restype = C.c_void_p
        L.retro_get_memory_size.restype = C.c_size_t

    def _env(self, cmd, data):
        cmd &= 0xFFFF
        if cmd == ENV_SET_PIXEL_FORMAT:
            self.pixfmt = C.cast(data, C.POINTER(C.c_uint))[0]
            return True
        if cmd in (ENV_GET_SYSTEM_DIRECTORY, ENV_GET_SAVE_DIRECTORY):
            C.cast(data, C.POINTER(C.c_char_p))[0] = self._sysdir
            return True
        if cmd == ENV_GET_CAN_DUPE:
            C.cast(data, C.POINTER(C.c_bool))[0] = True
            return True
        if cmd == ENV_GET_VARIABLE:
            C.cast(data, C.POINTER(Variable))[0].value = None
            return False
        if cmd == ENV_GET_VARIABLE_UPDATE:
            C.cast(data, C.POINTER(C.c_bool))[0] = False
            return True
        return False

    def _video(self, data, w, h, pitch):
        if not data:  # duped frame: keep the last one
            return
        self._raw = (C.string_at(data, pitch * h), w, h, pitch, self.pixfmt)
        self._frame = None

    @property
    def frame(self):
        """(w, h, rgb bytes) of the last picture, converted on first use: most frames are never looked at."""
        if self._frame is None and self._raw:
            buf, w, h, pitch, fmt = self._raw
            out = bytearray(w * h * 3)
            o = 0
            for y in range(h):
                row = buf[y * pitch:y * pitch + w * (4 if fmt == PIX_XRGB8888 else 2)]
                if fmt == PIX_XRGB8888:
                    for x in range(w):
                        b, g, r = row[x * 4], row[x * 4 + 1], row[x * 4 + 2]
                        out[o:o + 3] = bytes((r, g, b)); o += 3
                else:
                    for (v,) in struct.iter_unpack("<H", row):
                        if fmt == PIX_RGB565:
                            r, g, b = (v >> 11) << 3, ((v >> 5) & 63) << 2, (v & 31) << 3
                        else:
                            r, g, b = ((v >> 10) & 31) << 3, ((v >> 5) & 31) << 3, (v & 31) << 3
                        out[o:o + 3] = bytes((r, g, b)); o += 3
            self._frame = (w, h, bytes(out))
        return self._frame

    def _state(self, port, device, index, bid):
        return 1 if bid in self.pressed.get(port, ()) else 0

    def run_frame(self):
        self.lib.retro_run()

    def wram(self):
        p = self.lib.retro_get_memory_data(MEM_SYSTEM_RAM)
        n = self.lib.retro_get_memory_size(MEM_SYSTEM_RAM)
        return C.string_at(p, n) if p else b""

    def poke(self, offset, data):
        """Writes bytes into work RAM at `offset` (see wram_offset); libretro's memory pointer is the live RAM."""
        p = self.lib.retro_get_memory_data(MEM_SYSTEM_RAM)
        n = self.lib.retro_get_memory_size(MEM_SYSTEM_RAM)
        if not p or offset + len(data) > n:
            raise SystemExit(f"cannot write {len(data)} bytes at {offset:#x}: work RAM is {n} bytes")
        C.memmove(p + offset, bytes(data), len(data))

    def shot(self, path):
        if self.frame:
            write_png(path, *self.frame)


def load_syms(path):
    """WLA-DX .sym file ("007e2082 name" or "7e:2082 name") -> {name: 24-bit address}."""
    syms = {}
    for line in open(path, errors="ignore"):
        parts = line.split()
        if len(parts) != 2 or line.startswith((";", "[")):
            continue
        addr, name = parts
        try:
            if ":" in addr:
                bank, off = addr.split(":")
                syms[name] = (int(bank, 16) << 16) | int(off, 16)
            else:
                syms[name] = int(addr, 16) & 0xFFFFFF
        except ValueError:
            continue
    return syms


def wram_offset(addr24):
    bank, off = addr24 >> 16, addr24 & 0xFFFF
    if bank in (0x7E, 0x7F):
        return ((bank - 0x7E) << 16) | off
    if off < 0x2000:  # low RAM mirror in banks $00-$3F/$80-$BF
        return off
    raise ValueError(f"{addr24:06X} is not in work RAM")


def parse_hold(spec):
    """'60-240:p0=up+right,p1=a' -> (60, 240, {0: {...}, 1: {...}})"""
    rng, keys = spec.split(":", 1)
    a, b = (int(x) for x in rng.split("-"))
    held = {}
    for part in keys.split(","):
        port, names = part.split("=")
        held[int(port[1:])] = {BUTTONS[n] for n in names.split("+") if n}
    return a, b, held


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", required=True)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--frames", type=int, default=300)
    ap.add_argument("--hold", action="append", default=[])
    ap.add_argument("--shot", action="append", default=[], help="FRAME:path.png")
    ap.add_argument("--sym", help="WLA-DX .sym file for --read")
    ap.add_argument("--read", action="append", default=[], help="symbol[:bytes] read at the end")
    a = ap.parse_args()

    r = Runner(a.core, a.rom)
    holds = [parse_hold(h) for h in a.hold]
    shots = {}
    for s in a.shot:
        f, p = s.split(":", 1)
        shots.setdefault(int(f), []).append(p)
    for f in range(1, a.frames + 1):
        r.pressed = {0: set(), 1: set()}
        for lo, hi, held in holds:
            if lo <= f <= hi:
                for port, ids in held.items():
                    r.pressed.setdefault(port, set()).update(ids)
        r.run_frame()
        for p in shots.get(f, []):
            r.shot(p)
    if a.read:
        syms = load_syms(a.sym)
        ram = r.wram()
        for spec in a.read:
            name, _, n = spec.partition(":")
            n = int(n or 2)
            off = wram_offset(syms[name])
            print(f"{name}={int.from_bytes(ram[off:off + n], 'little')}")


if __name__ == "__main__":
    sys.exit(main())
