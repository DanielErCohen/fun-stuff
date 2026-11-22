.include "hdr.asm"

; Each perspective table is 22 KB and gets a bank to itself, because an
; indirect HDMA channel reads from one bank only.
.section ".persp_s" superfree
persp_s:
.dw 0
.incbin "res/persp_s.bin"
.ends

.section ".persp_t" superfree
persp_t:
.dw 0
.incbin "res/persp_t.bin"
.ends

; The four tracks: each one's tiles, map, surface map, colours, starting floor cells, lap progress,
; minimap and obstacle colours, in sections of their own (res/tracks.asm, from tools/tracks.py).
.include "res/tracks.asm"

; Race sprites: the shared countdown and glyph tiles and the text palettes; each animal's
; 4 KB of race tiles has a section of its own in res/cast.asm, and its palette is in cast_pal.
.section ".shared" superfree
shared_gfx:
.incbin "res/shared.pic"
shared_pal:
.incbin "res/shared.pal"
cast_pal:
.incbin "res/cast.pal"
sin_table:
.incbin "res/sin.bin"
.ends

.include "res/cast.asm"

; Select screen: portrait and cursor sprites, and the background picture.
.section ".select_obj" superfree
select_obj_gfx:
.incbin "res/select_obj.pic"
select_obj_pal:
.incbin "res/select_obj.pal"
.ends

.section ".select_bg" superfree
select_bg_gfx:
.incbin "res/select_bg.pic"
select_bg_gfx_end:
select_bg_map:
.incbin "res/select_bg.map"
select_bg_pal:
.incbin "res/select_bg.pal"
.ends

.section ".ui" superfree
ui_gfx:
.incbin "res/ui.pic"
ui_gfx_end:
ui_pal:
.incbin "res/ui.pal"
.ends

; The items' HUD pictures, 128 bytes each in item-number order (main.c copies one into a player's HUD frame).
.section ".items_pic" superfree
items_pic:
.incbin "res/items.pic"
battle_pic:
.incbin "res/battle.pic"
leader_pic:
.incbin "res/leader.pic"
.ends

; The tables game/proj.asm projects moving things with (see tools/gen_assets.py proj_tables).
.section ".proj_data" superfree
proj_sl:
.incbin "res/proj.bin" skip 0 read 512
proj_bear:
.incbin "res/proj.bin" skip 512 read 256
obj_frames:
.incbin "res/obj_frames.bin"
cam_d:
.incbin "res/cam.bin" skip 0 read 256
row_off:
.incbin "res/cam.bin" skip 256 read 256
drop_d:
.incbin "res/cam.bin" skip 512 read 256
.ends

; A kart's step each frame: sin of 128 headings times 64 speeds as signed 16-bit words, 128 bytes a heading
; (tools/gen_assets.py step_table), read by mk_move in game/proj.asm. 16 KB.
.section ".step_table" superfree
mk_tab:
.incbin "res/step.bin"
.ends
