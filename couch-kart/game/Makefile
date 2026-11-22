PVSNESLIB_HOME ?= $(HOME)/opt/snesdev/pvsneslib
export PVSNESLIB_HOME

# ROMNAME is used in snes_rules file
export ROMNAME := couchkart
# FastROM: code and tables in ROM read at 3.58 MHz instead of 2.68, about a quarter more logic per frame
export FASTROM := 1
# 512 KB: four tracks need about 200 KB of tiles, maps and surfaces
export ROMSIZE := 09
export ROMBANKS := 16

include ${PVSNESLIB_HOME}/devkitsnes/snes_rules

.PHONY: all assets cleanLogs

all: cleanLogs buildWithSummary

buildActual: assets $(OBJS) $(ROMNAME).sfc

assets:
	python3 ../tools/gen_assets.py

# data.asm only .incbin's the generated files, so name them or a changed asset never reaches the ROM
data.obj: assets res/persp_s.bin res/persp_t.bin res/tracks.asm $(wildcard res/trk*.*) \
	res/shared.pic res/shared.pal res/cast.pal res/cast.asm $(wildcard res/cast_*.pic) res/select_obj.pic \
	res/select_obj.pal res/select_bg.pic res/select_bg.map res/select_bg.pal res/ui.pic res/ui.pal res/sin.bin res/proj.bin res/obj_frames.bin res/cam.bin res/items.pic res/battle.pic res/leader.pic res/step.bin

# main.c includes the generated cast tables
main.obj: res/cast.h res/layout.h res/tracks.h

proj.obj: res/layout.inc

clean: cleanBuildRes cleanRom cleanGfx cleanLogs
	rm -rf res
