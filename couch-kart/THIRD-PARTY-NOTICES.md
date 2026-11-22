# Third-party notices

Couch Kart's own code, tools, art and names are original and are released under the MIT license (`../LICENSE`). Nothing in it comes from Nintendo. "Super Nintendo" names the console the game file format targets.

## Inside the game file

The game file `couch-kart.sfc` contains library code from PVSnesLib. Four library objects are linked into it: `crt0_snes.obj`, `libc.obj`, `libm.obj` and `libtcc.obj`. They come with the PVSnesLib release. Their upstream licenses are not confirmed.

**PVSnesLib 4.7.0**
- Copyright (C) 2012-2026 Alekmaul.
- License: the permissive terms below, in the style of the zlib license. They are quoted from `pvsneslib/pvsneslib_license.txt` in the PVSnesLib 4.7.0 release (version file: `pvsneslib_version.txt`, "4.7.0").
- Source: https://github.com/alekmaul/pvsneslib

```
Copyright (C) 2012-2026
 Alekmaul

This software is provided 'as-is', without any express or implied
warranty.  In no event will the authors be held liable for any
damages arising from the use of this software.

Permission is granted to anyone to use this software for any
purpose, including commercial applications, and to alter it and
redistribute it freely, subject to the following restrictions:

1. The origin of this software must not be misrepresented; you
   must not claim that you wrote the original software. If you use
   this software in a product, an acknowledgment in the product
   documentation would be appreciated but is not required.
2. Altered source versions must be plainly marked as such, and
   must not be misrepresented as being the original software.
3. This notice may not be removed or altered from any source
   distribution.
```

This game was built with PVSnesLib. Thank you to Alekmaul and the PVSnesLib contributors.

## Fetched by `scripts/setup.sh`

`scripts/setup.sh` downloads these into `~/opt/snesdev`. This folder ships none of them. The compiler, assembler, linker, emulators and numpy are tools only. The game file contains the PVSnesLib library code covered above.

| Item | What it is used for | License |
|---|---|---|
| PVSnesLib 4.7.0 release zip (github.com) | The build kit: the library above and the tools below | See above |
| 816-tcc, in the PVSnesLib zip | C compiler for the 65816 | Not confirmed. The binary names "Tiny C Compiler, Copyright (C) 2001-2006 Fabrice Bellard" and "WDC 65816 ASM code generator, Copyright (C) 2007 Ulrich Hecht"; no license file came with it |
| WLA DX (`wla-65816`, `wlalink`), in the PVSnesLib zip | Assembler and linker | Not confirmed; no license file came with it |
| snes9x2002, snes9x2005, snes9x (buildbot.libretro.com) | Emulator cores the tests run | Not confirmed; no license file came with them |
| bsnes (buildbot.libretro.com) | Emulator core for accurate screenshots | The binary reports "GPLv3 or later"; no license file came with it |
| numpy (PyPI, through pip) | Draws the karts and tracks | BSD, from the package metadata of numpy 2.3.5 on the author's machine |

Check each project's own license before you redistribute any of these.
