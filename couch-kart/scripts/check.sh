#!/bin/sh
# The local gate: checks the toolchain, builds the game, then plays it in three emulators.
# Prints PASS per step and stops at the first failure. Run it from anywhere: `sh scripts/check.sh`.
# Build runs before test, because the tests play the built game file.
set -eu
cd "$(dirname "$0")/.."

INSTALL_CMD="sh scripts/setup.sh --check"
TEST_CMD="python3 tools/test_rom.py"
# PVSnesLib's make exits 0 even when the link fails, leaving the old game file: the log's last word decides.
BUILD_CMD="make -C game && grep -q 'Build finished successfully' game/couchkart.log"

step() {
  name=$1
  cmd=$2
  if sh -c "$cmd"; then
    echo "PASS $name"
  else
    echo "FAIL $name: $cmd" >&2
    exit 1
  fi
}

step install "$INSTALL_CMD"
step build "$BUILD_CMD"
step test "$TEST_CMD"
echo "All gates passed."
