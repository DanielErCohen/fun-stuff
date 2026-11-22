#!/bin/sh
# Installs the toolchain into ~/opt/snesdev (Linux x86_64): PVSnesLib 4.7.0 and
# the libretro SNES emulators the tests run, plus bsnes for accurate screenshots, and numpy, which
# tools/characters.py uses to draw the karts. Safe to run again.
# `sh scripts/setup.sh --check` only reports whether everything is there.
set -eu
DIR="${SNESDEV:-$HOME/opt/snesdev}"
PVSNESLIB_VERSION=4.7.0
CORES="snes9x2002 snes9x2005 snes9x bsnes"

missing=""
[ -x "$DIR/pvsneslib/devkitsnes/bin/816-tcc" ] || missing="$missing pvsneslib"
for c in $CORES; do
  [ -f "$DIR/cores/${c}_libretro.so" ] || missing="$missing $c"
done
python3 -c "import numpy" 2>/dev/null || missing="$missing numpy"

if [ "${1:-}" = "--check" ]; then
  if [ -n "$missing" ]; then
    echo "missing:$missing; run sh scripts/setup.sh" >&2
    exit 1
  fi
  echo "toolchain present in $DIR"
  exit 0
fi

mkdir -p "$DIR/cores"
if [ ! -x "$DIR/pvsneslib/devkitsnes/bin/816-tcc" ]; then
  curl -fsSL -o "$DIR/pvsneslib.zip" \
    "https://github.com/alekmaul/pvsneslib/releases/download/$PVSNESLIB_VERSION/pvsneslib_$(echo $PVSNESLIB_VERSION | tr -d .)_64b_linux_release.zip"
  unzip -q -o "$DIR/pvsneslib.zip" -d "$DIR"
  rm "$DIR/pvsneslib.zip"
fi
for c in $CORES; do
  if [ ! -f "$DIR/cores/${c}_libretro.so" ]; then
    curl -fsSL -o "$DIR/cores/$c.zip" "https://buildbot.libretro.com/nightly/linux/x86_64/latest/${c}_libretro.so.zip"
    unzip -q -o "$DIR/cores/$c.zip" -d "$DIR/cores"
    rm "$DIR/cores/$c.zip"
  fi
done
python3 -c "import numpy" 2>/dev/null || python3 -m pip install --user numpy
echo "toolchain installed in $DIR"
