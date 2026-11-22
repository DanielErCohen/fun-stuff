#!/usr/bin/env python3
"""Reference renderer: predicts the Mode 7 floor from the game's HDMA tables in
work RAM and the ROM tables, with the hardware formula (as in bsnes). Comparing
it with an emulator screenshot tells a maths bug from an HDMA bug.

Usage: m7_model.py --rom game.sfc --sym game.sym --frames N --out model.png
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retro_run as rr  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "game", "res")


def s16(lo, hi):
    v = lo | hi << 8
    return v - 65536 if v & 0x8000 else v


def s13(v):
    v &= 0x1FFF
    return v - 0x2000 if v & 0x1000 else v


def clip(n):
    return (n | ~1023) if n & 0x2000 else (n & 1023)


def rom_read(rom, bank, addr):
    assert addr >= 0x8000, f"table address {addr:04X} is outside LoROM space"
    return rom[(bank & 0x7F) * 0x8000 + (addr - 0x8000)]  # LoROM


def expand_indirect(rom, tbl, bank):
    """Per-line 16-bit values from an indirect HDMA table."""
    out, i = [], 0
    while tbl[i]:
        cnt, ptr = tbl[i], tbl[i + 1] | tbl[i + 2] << 8
        i += 3
        if cnt & 0x80:
            for k in range(cnt & 0x7F):
                out.append(s16(rom_read(rom, bank, ptr + 2 * k), rom_read(rom, bank, ptr + 2 * k + 1)))
        else:
            out += [s16(rom_read(rom, bank, ptr), rom_read(rom, bank, ptr + 1))] * cnt
    return out


def expand_direct4(tbl):
    out, i = [], 0
    while tbl[i]:
        out += [(s16(tbl[i + 1], tbl[i + 2]), s16(tbl[i + 3], tbl[i + 4]))] * tbl[i]
        i += 5
    return out


def line_params(ram, syms, rom):
    """Per screen line: (A, B, C, D, HOFS, VOFS, centre X, centre Y) as the HDMA tables in `ram` set them."""
    def ram_bytes(name, n):
        o = rr.wram_offset(syms[name])
        return ram[o:o + n]
    sbank, tbank = ram_bytes("s_bank", 1)[0], ram_bytes("t_bank", 1)[0]
    A = expand_indirect(rom, ram_bytes("hdma_a", 13), sbank)
    B = expand_indirect(rom, ram_bytes("hdma_b", 13), tbank)
    C = expand_indirect(rom, ram_bytes("hdma_c", 13), sbank)
    D = expand_indirect(rom, ram_bytes("hdma_d", 13), tbank)
    SC = expand_direct4(ram_bytes("hdma_scroll", 11))
    CE = expand_direct4(ram_bytes("hdma_center", 21))
    return [(A[y], B[y], C[y], D[y], s13(SC[y][0]), s13(SC[y][1]), s13(CE[y][0]), s13(CE[y][1]))
            for y in range(224)]


def map_point(params, x, y):
    """The map pixel the hardware shows at screen pixel (x, y)."""
    a, b, c, d, hofs, vofs, hc, vc = params[y]
    psx = ((a * clip(hofs - hc)) & ~63) + ((b * clip(vofs - vc)) & ~63) + ((b * y) & ~63) + (hc << 8)
    psy = ((c * clip(hofs - hc)) & ~63) + ((d * clip(vofs - vc)) & ~63) + ((d * y) & ~63) + (vc << 8)
    return (psx + a * x) >> 8, (psy + c * x) >> 8


def predict(ram, syms, rom, vram=None):
    """RGB bytes (256x224) of the floor and sky the HDMA tables in `ram` describe; sprites are not drawn.
    With `vram`, the map and tiles are the ones in video memory (the low and high byte of each word), so
    coins taken and slime dropped show as the game drew them; otherwise the track's starting map."""
    params = line_params(ram, syms, rom)
    n = ram[rr.wram_offset(syms["track_no"])]  # the track raced: its colours (CGRAM is not readable)
    tiles = vram[1:0x8000:2] if vram else open(os.path.join(RES, f"trk{n}.pc7"), "rb").read()
    tmap = vram[0:0x8000:2] if vram else open(os.path.join(RES, f"trk{n}.mp7"), "rb").read()
    pal = open(os.path.join(RES, f"trk{n}.pal"), "rb").read()
    colors = []
    for i in range(256):
        v = pal[i * 2] | pal[i * 2 + 1] << 8
        colors.append(bytes(((v & 31) << 3, (v >> 5 & 31) << 3, (v >> 10 & 31) << 3)))

    img = bytearray()
    for y in range(224):
        for x in range(256):
            X, Y = map_point(params, x, y)
            t = tmap[(Y >> 3) * 128 + (X >> 3)] if 0 <= X < 1024 and 0 <= Y < 1024 else 0
            img += colors[tiles[t * 64 + (Y & 7) * 8 + (X & 7)]]
    return bytes(img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="snes9x")
    ap.add_argument("--rom", required=True)
    ap.add_argument("--sym", required=True)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    r = rr.Runner(args.core, args.rom)
    for _ in range(args.frames):
        r.run_frame()
    img = predict(r.wram(), rr.load_syms(args.sym), open(args.rom, "rb").read())
    rr.write_png(args.out, 256, 224, img)
    print(f"model written: {args.out}")


if __name__ == "__main__":
    main()
