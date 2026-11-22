; Hand-written hot paths, called from main.c with the tcc-816 convention: arguments on the stack
; from 4,s (u8 one byte, u16 two), A, X and Y 16 bits on entry and exit, registers free to use.
; tcc-816 needs about 5 lines for one sprite write and 26 for one projected thing in C
; (measured); these need about 1 and 3.
;
; Work RAM globals sit in bank $7E, so the data bank is set to $7E; I/O registers are reached
; with long addresses, ROM tables with long indexed reads (there is no long,Y mode).

.include "hdr.asm"
.include "res/layout.inc"       ; sprite tile numbers, from tools/gen_assets.py

.DEFINE MINI_X 8                ; the minimap's corner in each half (main.c MINI_X, MINI_Y)
.DEFINE MINI_Y 76
.DEFINE OB_REACH 12             ; an obstacle hits a kart closer than this on both axes, map pixels (main.c)
.DEFINE MAX_GRASS 16            ; top speed off the road and on sand for every kart, 1/16 px a frame
.DEFINE PAD_FRAMES 30           ; a boost pad's boost, frames
.DEFINE BOOST_EXTRA 16          ; a boost lifts the top speed by this, 1/16 px a frame
.DEFINE SURF_GRASS 0            ; surfaces (main.c SURF_*)
.DEFINE SURF_ROAD 1
.DEFINE SURF_PAD 2
.DEFINE SURF_SAND 5
.DEFINE ST_RACE 2                ; game_state of a race (main.c ST_RACE)
.DEFINE KEY_B $8000             ; pad bits (PVSnesLib input.h)
.DEFINE KEY_Y $4000
.DEFINE KEY_DOWN $0400
.DEFINE KEY_LEFT $0200
.DEFINE KEY_RIGHT $0100
.DEFINE KEY_A $0080
.DEFINE NCP 32                  ; checkpoints a lap (res/tracks.h)
.DEFINE OFF_TRACK 255           ; lap progress off the track (main.c)
.DEFINE SHRINK_TOP 26           ; a shrunk kart's top speed (main.c shrink)
.DEFINE SHRINK_OVER 27          ; (SHRINK_TOP + 1)
.DEFINE SLIP_BOX 12             ; slipstream: the other kart within 12 px of the point 24 px ahead (both axes),
.DEFINE SLIP_SPAN 25            ; (2 * SLIP_BOX + 1)
.DEFINE SLIP_MIN 24             ; at this speed or more,
.DEFINE SLIP_TICKS 15           ; for 15 ticks of 4 frames (1 s), gives a boost of
.DEFINE SLIP_FRAMES 40          ; this many frames
.DEFINE NKARTS 6                ; karts in the data: the two players, then four computer karts (12-byte records in karts)
.DEFINE SPIN_FRAMES 64          ; a hit or oil spins the kart this long (main.c)
.DEFINE SPIN_STEP 8             ; and turns its shown heading this much a frame
.DEFINE FALL_FRAMES 60          ; a kart in water or a pit is put back after this many frames
.DEFINE AIR_MIN 8               ; a ramp lifts the kart one frame per speed step, between these (main.c)
.DEFINE AIR_MAX 56
.DEFINE TRICK_FRAMES 40         ; the ramp trick's boost on landing
.DEFINE SURF_RAMP 3
.DEFINE SURF_OIL 4
.DEFINE OIL_SPEED 24             ; oil spins a kart at this speed or more, 1/16 px a frame
.DEFINE SURF_FALL 6
.DEFINE AV_T 30                 ; a computer kart that touched another kart steers round it for this many frames
.DEFINE AV_R 14                 ; and aims this many of 128 heading steps to the right of the steering map's heading
.DEFINE AV_L $FFF2              ; or to the left (-14)
.DEFINE BUMP 10                 ; karts closer than this on both axes touch, map pixels (main.c)
.DEFINE EDGE_SPEED 3            ; speed left after touching the map edge (main.c)
.DEFINE HOME_TURN 4             ; a homing shot turns this many of 128 steps every 4 frames (main.c)
.DEFINE CPU_FAR 360               ; computer karts are drawn up to this far ahead of the camera, map pixels (their tops stay off the HUD)
.DEFINE PAL_YELLOW 3             ; sprite palettes of the banner's words (main.c)
.DEFINE PAL_GREEN 4
.DEFINE ST_COUNTDOWN 1          ; game_state of the countdown (main.c)
.DEFINE LAPS 3                  ; laps in a race (main.c)
.DEFINE AFTER_FIRST 600         ; frames to the results after the first kart finishes (main.c)
.DEFINE AFTER_BOTH 90           ; and after both players have
.DEFINE DRIFT_CHARGE 40         ; a drift this charged shows sparks (main.c DRIFT_CHARGE)
.DEFINE WRONG_STEPS 3           ; the wrong-way sign shows after this many steps backwards (main.c)
.DEFINE LEADER_STEP 96          ; the leader shot's step on each axis, 1/16 px a frame (6 px; a homing shot goes 4)
.DEFINE CPU_SLOW 30             ; in a tight stretch (the steering map's bit 7) a computer kart brakes above this speed and drives at it

.RAMSECTION ".proj_bss" BANK $7e SLOT 2
sp_t      dsb 2
cm_i      dsb 2   ; camera: the angle times 2, the player times 2 and times 8, a row offset
cm_p2     dsb 2
cm_p8     dsb 2
cm_t      dsb 2
mk_i      dsb 2   ; move_kart: the heading's row in mk_tab, the speed's column, a value and the remainder of a split
mk_m      dsb 2
mk_t      dsb 2
mk_t2     dsb 2
mk_r      dsb 2
dr_p      dsb 2   ; drive: the player, the pad, the kart's offset in karts, its type record's offset,
dr_pad    dsb 2   ; the floor under it, the coin bonus, its top speed this frame, its turn, a value
dr_k      dsb 2
dr_kt     dsb 2
dr_road   dsb 2
dr_cb     dsb 2
dr_top    dsb 2
dr_turn   dsb 2
dr_t      dsb 2
pg_p      dsb 2   ; progress: the player, the progress under the kart, its checkpoint, the result
pg_v      dsb 2
pg_c      dsb 2
pg_e      dsb 2
sl_p      dsb 2   ; slipstream: the player, its kart's offset in karts, the other's, its heading times 2, a value
sl_k      dsb 2
sl_o      dsb 2
sl_i      dsb 2
sl_t      dsb 2
kt_mask   dsb 2   ; kart_timers: the karts whose shield ran out, and the bit of the kart now
kt_bit    dsb 2
bn_p      dsb 2   ; banner_step: the half, glyphs left to write this call, the glyph, its slot, the kind, a value
bn_n      dsb 2
bn_i      dsb 2
bn_s      dsb 2
bn_k      dsb 2
bn_o      dsb 2
bn_t      dsb 2
ln_r      dsb 2   ; lap_next: the result and a value
ln_t      dsb 2
cs_p      dsb 2   ; clock_step: the player
pp_r      dsb 2   ; progress_players: player 1's result
bf_r      dsb 2   ; busy_flags: the result
gr_mask   dsb 2   ; ground_all: the karts to rescue, the kart's bit, a value, the floor column
gr_bit    dsb 2
gr_t      dsb 2
gr_cb     dsb 2
fs_mask   dsb 2   ; floor_scan: the karts over something, the kart's bit, the cell
fs_bit    dsb 2
fs_c      dsb 2
bm_mask   dsb 2   ; bump_all: the karts a star touched, kart i and j and their offsets in karts, the
bm_i      dsb 2   ; centres' distances and their absolute values, a value
bm_j      dsb 2
bm_ik     dsb 2
bm_jk     dsb 2
bm_dx     dsb 2
bm_dy     dsb 2
bm_ax     dsb 2
bm_ay     dsb 2
bm_t      dsb 2
st_i      dsb 2   ; steer_fast: the shot and its word offset, its heading times 2, the vector to the kart,
st_i2     dsb 2   ; two products and a value; smul's operand and sign
st_a2     dsb 2
st_rx     dsb 2
st_ry     dsb 2
st_c      dsb 2
st_t      dsb 2
st_u      dsb 2
st_sgn    dsb 2
rk_s      dsb 2   ; rank_all: the step from one kart to the next
rk_mask   dsb 2   ; rank_all: the karts whose place changed, kart i, its word index, its place
rk_i      dsb 2
rk_y      dsb 2
rk_r      dsb 2
nk_n      dsb 2   ; karts racing now: 2 + cpu_n, twice that, and its offset in karts (LOAD_NK)
nk_w      dsb 2
nk_off    dsb 2
pc_mask   dsb 2   ; progress_cpu: the result, a kart's bit, the kart's result
pc_b      dsb 2
pc_t      dsb 2
ms_mask   dsb 2   ; move_shots and move_obstacles: the karts something has hit (shot_struck, ob_struck set), a bit each
mo_k      dsb 2   ; move_obstacles: the kart's word index, and the obstacle's index
mo_x      dsb 2
mn_n      dsb 2   ; minimap: the computer dots left to place and the next one
mn_i      dsb 2
cf_k      dsb 2   ; cpu_frame: the kart, its steering byte, its heading, the pad it presses
cf_b      dsb 2
cf_h      dsb 2
cf_pad    dsb 2
cf_y      dsb 2   ; and the kart's offset in karts
cf_av     dsb 8   ; per computer kart (2 to 5, a word each): frames left of steering round a kart it touched
cf_sd     dsb 8   ; and the heading step it adds meanwhile (AV_R or AV_L)
bm_a      dsb 2   ; _bm_swerve: the computer kart, the other kart's offset from it, a product's factors and sign, a sum
bm_rx     dsb 2
bm_ry     dsb 2
bm_ma     dsb 2
bm_mb     dsb 2
bm_ms     dsb 2
bm_c      dsb 2
bm_o      dsb 2
bm_ta     dsb 2
bm_tb     dsb 2
bm_fx     dsb 2
bm_ft     dsb 2
.ENDS

; draw_objects points the direct page here, so its variables take one byte to address
.RAMSECTION ".proj_dp" BANK 0 SLOT 1 ALIGN 256
pj_base   dsb 0
pj_t0     dsb 2   ; line when draw_objects started
pj_p      dsb 2   ; view: 0 player 1's half, 1 player 2's
pj_half   dsb 2   ; 0 or 112, the half's first screen line
pj_j      dsb 2   ; thing: 0 to 5 the karts (the kart's number), 6 to 9 the shots, 10 and 11 the obstacles
pj_k      dsb 2   ; p * 12 + j, the row in the slot tables
pj_kn     dsb 2   ; karts drawn: 2, or 2 + cpu_n once the computer animals' frames are loaded
pj_o      dsb 2   ; OAM offset of the thing's sprite in this view
pj_cx     dsb 2   ; camera, map pixels
pj_cy     dsb 2
pj_idx    dsb 2   ; camera angle, table steps 0-127
pj_sa8    dsb 2   ; |sin| / 2 in the high byte, for a 16-bit write to the multiplier; its sign mask
pj_sm     dsb 2
pj_ca8    dsb 2   ; |cos| / 2 likewise
pj_cm     dsb 2
pj_ox     dsb 2   ; thing position, 1/16 map pixel
pj_oy     dsb 2
pj_dir    dsb 2   ; thing heading, table steps (karts only)
pj_kind   dsb 2   ; offset of the kind's near frame record: 0 player 1's kart, 48 player 2's, 96 a shot, 144 an obstacle,
                  ; 192, 240, 288 and 336 the four computer karts (a record with a view flag, byte 4, is a kart)
pj_sz     dsb 2   ; size class times 16: 0 near, 16 mid, 32 far
pj_rxa    dsb 2   ; |dx| / 2 from the camera and its sign mask
pj_rxm    dsb 2
pj_rya    dsb 2
pj_rym    dsb 2
pj_m      dsb 2
pj_tmp    dsb 2
pj_lat    dsb 2   ; sideways and ahead of the camera: x32 while summing, then map pixels
pj_fwd    dsb 2
pj_la     dsb 2   ; |lat| and its sign mask
pj_latm   dsb 2
pj_gl     dsb 2   ; ground line in the half
pj_off    dsb 2   ; sideways offset on screen, pixels
pj_rec    dsb 2   ; offset of the frame record in obj_frames
pj_box    dsb 2
pj_left   dsb 2
pj_top    dsb 2
pj_flip   dsb 2
pj_tile   dsb 2
ms_i      dsb 2   ; move_shots: the shot, its word offset, position now and next, road under it
ms_w      dsb 2
ms_x      dsb 2
ms_y      dsb 2
ms_nx     dsb 2
ms_ny     dsb 2
ms_road   dsb 2
ms_t      dsb 2
ms_a      dsb 2   ; turning at a corner: the speed, half of it, and the side with road (1 south or east, 2 north or west)
ms_t2     dsb 2
ms_s      dsb 2
bm_xa     dsb 2   ; bump_all: the kart's position plus BUMP px
bm_ya     dsb 2
ms_ax     dsb 2   ; the shot's position less 159: the test against each kart is one subtraction and compare
ms_ay     dsb 2
ms_sp     dsb 4   ; the track's surface map (main.c cur_surf), a long pointer
cf_sp     dsb 4   ; cpu_frame: the track's steering map (main.c cur_steer), a long pointer
.ENDS

.SECTION ".proj_text" SUPERFREE

; Sets nk_n to the karts racing (2 + cpu_n), nk_w to twice that and nk_off to their offset in karts: the
; loops over karts visit these, so a race with no computer karts costs what the two-player race did.
.MACRO LOAD_NK
    lda.w cpu_n
    and #$00ff
    inc a
    inc a
    sta.w nk_n
    asl a
    sta.w nk_w
    tax
    lda.l kart_off,x
    sta.w nk_off
.ENDM

.accu 16
.index 16
.16bit

; Per view p and thing j (row k = p * 12 + j): OAM offset ($FFFF: the view's own kart, drawn
; elsewhere), and for the other player's kart the offset of its byte in the high OAM table, the mask that
; keeps the other sprites' bits there, and its large-size bit (the computer karts, shots and obstacles are
; always small with x below 256, so their high bits stay 0). Slots: 2 and 3 the other player's kart,
; 76-79 and 80-83 the computer karts, 40-43 and 44-47 the shots, 60-61 and 62-63 the obstacles.
pj_slots: .dw $FFFF, 2*4, 76*4, 77*4, 78*4, 79*4, 40*4, 41*4, 42*4, 43*4, 60*4, 61*4
          .dw 3*4, $FFFF, 80*4, 81*4, 82*4, 83*4, 44*4, 45*4, 46*4, 47*4, 62*4, 63*4
pj_hi:    .dw 0, 512, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
          .dw 512, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
pj_keep:  .db $FF, $CF, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
          .db $3F, $FF, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
pj_large: .db $00, $20, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
          .db $80, $00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
; the offset of each kart's near frame record in obj_frames, by kart
pj_kinds: .dw 0, 48, 192, 240, 288, 336
; heading seen along the line of sight, in eighths: view offset into the 5 tiles (x2) and the
; mirror bit in the attribute byte (high byte)
pj_view:  .dw 0, 2, 4, 6, 8, 6, 4, 2
pj_mirror: .dw 0, 0, 0, 0, 0, $4000, $4000, $4000

;---------------------------------------------------------------------------------
; void spr(u8 slot, s16 x, u8 y, u16 tile, u8 pal, u8 flip, u8 large)
; Writes one sprite into the library's OAM copy, which its vblank code sends to the PPU.
; After php and phb: slot 6, x 7-8, y 9, tile 10-11, pal 12, flip 13, large 14.
spr:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda 6,s
    and #$00ff
    asl a
    asl a
    tax
    sep #$20
    lda 7,s
    sta oamMemory,x
    lda 9,s
    sta oamMemory+1,x
    lda 10,s
    sta oamMemory+2,x
    lda 12,s
    asl a
    ora #$30
    sta sp_t
    lda 13,s
    beq +
    lda #$40
    tsb sp_t
+   lda 11,s
    and #$01
    ora sp_t
    sta oamMemory+3,x
    ; high table: two bits per sprite (x bit 8, large), four sprites a byte
    lda 6,s
    and #$03
    asl a
    asl a
    sta sp_t
    lda 8,s
    and #$01
    ora sp_t
    sta sp_t
    lda 14,s
    beq +
    lda #$02
    tsb sp_t
+   rep #$20
    lda 6,s
    and #$00fc
    lsr a
    lsr a
    tay
    lda sp_t
    and #$000f
    tax
    lsr a
    lsr a
    sta sp_t+0
    sep #$20
    lda.l hi_bits,x
    sta sp_t+1
    rep #$20
    lda sp_t
    and #$0003
    tax
    sep #$20
    lda.l hi_keep,x
    and oamMemory+512,y
    ora sp_t+1
    sta oamMemory+512,y
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; The screen line now, 0-261, in A (direct page at pj_base).
pj_line:
    sep #$20
    lda.l $00213F           ; resets the counter read order
    lda.l $002137           ; latches the counters
    lda.l $00213D
    sta.b <pj_tmp
    lda.l $00213D
    and #$01
    sta.b <pj_tmp+1
    rep #$20
    lda.b <pj_tmp
    rts

; |A| in A, its sign mask in Y
.MACRO ABS_MASK
    ldy #0
    cmp #$8000
    bcc +
    eor #$ffff
    inc a
    ldy #$ffff
+
.ENDM

; the same, right after an instruction that set N from A
.MACRO ABS_MASK_N
    bmi ++
    ldy #0
    bra +
++  eor #$ffff
    inc a
    ldy #$ffff
+
.ENDM

; A = (A ^ mask) - mask: A, or -A when the mask is $FFFF
.MACRO SIGNED
    eor.b <\1
    sec
    sbc.b <\1
.ENDM

;---------------------------------------------------------------------------------
; void draw_objects(void)
; Projects the other player's kart, the computer karts, the 4 shots and the 2 obstacles into each player's half with that player's camera, as
; the floor is drawn: the ground line and size from the distance ahead, the screen column from the
; sideways offset, and for a kart one of 5 views (and its mirror) from its heading against the line
; of sight. Writes each sprite or hides it, and leaves the lines used in pj_lines and the count in
; pj_count, so the test can measure the cost per thing.
; Products use the 8 x 8 bit multiplier at $4202: a 16-bit write sets both factors and starts it,
; and the result at $4216 is ready 8 cycles later, which the sign work in between covers.
draw_objects:
    php
    phb
    phd
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda #pj_base
    tcd
    jsr pj_line
    sta.b <pj_t0
    lda.w cpu_gfx_ready     ; the computer karts show once their frames are in video memory
    and #$00ff
    beq +
    lda.w cpu_n
    and #$00ff
+   clc
    adc #2
    sta.b <pj_kn
    stz.b <pj_p
_view:
    lda.b <pj_p
    asl a
    tax
    lda.w pend_cx,x
    sta.b <pj_cx
    lda.w pend_cy,x
    sta.b <pj_cy
    lda.b <pj_p
    beq +
    lda #12
+   tax
    lda.w karts+6,x
    xba
    and #$007f
    sta.b <pj_idx
    asl a
    tax
    lda.l sin_table,x
    ABS_MASK
    lsr a
    xba
    sta.b <pj_sa8
    sty.b <pj_sm
    lda.b <pj_idx
    clc
    adc #32
    and #$007f
    asl a
    tax
    lda.l sin_table,x
    ABS_MASK
    lsr a
    xba
    sta.b <pj_ca8
    sty.b <pj_cm
    lda.b <pj_p
    beq +
    lda #112
+   sta.b <pj_half
    stz.b <pj_j
    lda.b <pj_p
    beq +
    lda #12
+   sta.b <pj_k

_obj:
    lda.b <pj_k
    asl a
    tax
    lda.l pj_slots,x
    bpl +
    jmp _next
+   sta.b <pj_o
    lda.b <pj_j
    cmp #6
    bcs _shot
    ; a kart: position, and its heading plus the spin it shows; a kart that fell in is not drawn. A computer
    ; kart beyond the ones racing, or before their frames are loaded, is skipped with its sprite left as it was
    cmp.b <pj_kn
    bcc +
    jmp _next
+   cmp #2
    bcc _kart_go
    lda.w cpu_alt           ; with cpu_alt set, each half's computer karts are projected on alternate frames
    and #$00ff
    beq _kart_alt
    lda.w race_time
    eor.b <pj_p
    lsr a
    bcc _kart_alt
    jmp _next
_kart_alt:
    lda.b <pj_j
_kart_go:
    tay
    lda.w fall_t,y
    and #$00ff
    beq +
    jmp _hide
+   tya
    asl a
    tax
    lda.l pj_kinds,x
    sta.b <pj_kind
    lda.l kart_off,x
    tax
    lda.w karts,x
    sta.b <pj_ox
    lda.w karts+2,x
    sta.b <pj_oy
    lda.w karts+6,x
    xba
    sep #$20
    clc
    adc.w spin_off,y
    rep #$20
    and #$007f
    sta.b <pj_dir
    bra _project
_shot:
    cmp #10
    bcs _obst
    sec
    sbc #6
    tax
    lda.w shot_on,x
    and #$00ff
    bne +
    jmp _hide
+   ldy #96                  ; a shot, or (shot_on 2 and more) a leader shot's comet
    cmp #2
    bcc +
    ldy #384
+   sty.b <pj_kind
    txa
    asl a
    tax
    lda.w shot_x,x
    sta.b <pj_ox
    lda.w shot_y,x
    sta.b <pj_oy
    bra _project
_obst:
    sbc #10                 ; carry is set
    tax
    lda.w ob_on,x
    and #$00ff
    bne +
    jmp _hide
+   txa
    asl a
    tax
    lda.w ob_x,x
    sta.b <pj_ox
    lda.w ob_y,x
    sta.b <pj_oy
    lda #144
    sta.b <pj_kind

_project:
    ; offset from the camera, halved, as magnitude and sign: within 511 map pixels or hidden
    lda.b <pj_ox
    lsr a
    lsr a
    lsr a
    lsr a
    sec
    sbc.b <pj_cx
    ABS_MASK_N
    cmp #512
    bcc +
    jmp _hide
+   lsr a
    sta.b <pj_rxa
    sty.b <pj_rxm
    lda.b <pj_oy
    lsr a
    lsr a
    lsr a
    lsr a
    sec
    sbc.b <pj_cy
    ABS_MASK_N
    cmp #512
    bcc +
    jmp _hide
+   lsr a
    sta.b <pj_rya
    sty.b <pj_rym

    ; fwd = dx sin - dy cos first, so a thing behind costs two products; then lat = dx cos + dy sin.
    ; Each product / 2 so the sums fit: x32 map pixels
    lda.b <pj_rxa
    ora.b <pj_sa8
    sta.l $004202
    lda.b <pj_rxm
    eor.b <pj_sm
    sta.b <pj_m
    lda.l $004216
    lsr a
    SIGNED pj_m
    sta.b <pj_fwd

    lda.b <pj_rya
    ora.b <pj_ca8
    sta.l $004202
    lda.b <pj_rym
    eor.b <pj_cm
    eor #$ffff
    sta.b <pj_m
    lda.l $004216
    lsr a
    SIGNED pj_m
    clc
    adc.b <pj_fwd
    bpl +
    jmp _hide
+   cmp #56*32
    bcs +
    jmp _hide
+   sta.b <pj_fwd

    lda.b <pj_rxa
    ora.b <pj_ca8
    sta.l $004202
    lda.b <pj_rxm
    eor.b <pj_cm
    sta.b <pj_m
    lda.l $004216
    lsr a
    SIGNED pj_m
    sta.b <pj_lat

    lda.b <pj_rya
    ora.b <pj_sa8
    sta.l $004202
    lda.b <pj_rym
    eor.b <pj_sm
    sta.b <pj_m
    lda.l $004216
    lsr a
    SIGNED pj_m
    clc
    adc.b <pj_lat
    sta.b <pj_lat

    ; 56 to 511 map pixels ahead, and within the 90 degree view
    lda.b <pj_fwd
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    cmp #512
    bcc +
    jmp _hide
+   sta.b <pj_fwd
    ldx.b <pj_kind          ; a computer kart farther than CPU_FAR would stand on the HUD lines: not drawn
    cpx #192
    bcc +
    cpx #384                ; (the leader shot's comet is small and shows at any distance)
    bcs +
    cmp #CPU_FAR
    bcc +
    jmp _hide
+   lda.b <pj_lat
    ABS_MASK
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta.b <pj_la
    sty.b <pj_latm
    cmp.b <pj_fwd
    bcc +
    beq +
    jmp _hide

    ; column offset = |lat| * 128 / distance = |lat| * 64 / (distance / 2), on the hardware divider
    ; (16 / 8 bits, ready 16 cycles after the divisor is written); the frame record work covers the wait
+   lda.b <pj_la
    asl a
    asl a
    asl a
    asl a
    asl a
    asl a
    sta.l $004204
    lda.b <pj_fwd
    and #$fffe
    tax
    lsr a
    sep #$20
    sta.l $004206
    rep #$20

    ; by distance / 2: the ground line, and the size's record offset in the high byte
    lda.l proj_sl,x
    sta.b <pj_gl
    xba
    and #$00ff
    sta.b <pj_sz
    ; a shrunk kart is drawn one size smaller (main.c shrink_t); a kart is a record with a view flag
    ldx.b <pj_kind
    lda.l obj_frames+4,x
    and #$00ff
    beq +
    ldy.b <pj_j
    lda.w shrink_t,y
    and #$00ff
    beq +
    lda.b <pj_sz
    cmp #32
    bcs +
    adc #16                 ; carry is clear
    sta.b <pj_sz
+   lda.b <pj_sz
    clc
    adc.b <pj_kind
    sta.b <pj_rec
    tax
    lda.l obj_frames+1,x
    and #$00ff
    eor #$ffff
    sec
    adc.b <pj_gl
    and #$00ff              ; ground line - ground row of the frame (below 0 wraps above 112)
    sta.b <pj_top
    ; a kart in the air (a hop or a ramp) is drawn higher: its lift, halved for each size step further away
    lda.l obj_frames+4,x
    and #$00ff
    beq _nolift
    ldy.b <pj_j
    lda.w kart_lift,y
    and #$00ff
    beq _nolift
    ldy.b <pj_sz
    cpy #16
    bcc +
    lsr a
    cpy #32
    bcc +
    lsr a
+   eor #$ffff
    sec
    adc.b <pj_top
    and #$00ff
    sta.b <pj_top
_nolift:
    lda.l obj_frames,x
    and #$00ff
    sta.b <pj_box
    clc
    adc.b <pj_top
    cmp #113
    bcc +
    jmp _hide
+   lda.l $004214
    sta.b <pj_off
    SIGNED pj_latm
    clc
    adc #128                ; screen column of the centre
    sta.b <pj_tmp
    lda.b <pj_box
    lsr a
    eor #$ffff
    sec
    adc.b <pj_tmp           ; centre - box / 2
    bpl +
    jmp _hide
+   sta.b <pj_left
    clc
    adc.b <pj_box
    cmp #257
    bcc +
    jmp _hide

    ; a kart's view: its heading against the camera's and the bearing of the line of sight
+   lda.l obj_frames+4,x
    and #$00ff
    beq _noview
    ldx.b <pj_off
    lda.l proj_bear,x
    and #$00ff
    SIGNED pj_latm
    eor #$ffff
    sec
    adc.b <pj_dir
    sec
    sbc.b <pj_idx
    clc
    adc #8
    lsr a
    lsr a
    lsr a
    lsr a
    and #$0007
    asl a
    tax
    lda.l pj_mirror,x
    sta.b <pj_flip
    lda.l pj_view,x
    bra _tile
_noview:
    stz.b <pj_flip
_tile:
    clc
    adc.b <pj_rec
    tax
    lda.l obj_frames+6,x
    sta.b <pj_tile

    ; the sprite: x and line, then tile and attributes (palette, mirror, tile bit 8)
    ldx.b <pj_rec
    lda.l obj_frames+2,x    ; the attribute base (palette) is the record's high byte here
    and #$ff00
    ora.b <pj_flip
    ora.b <pj_tile          ; tile bit 8 lands on attribute bit 0
    ldx.b <pj_o
    sta.w oamMemory+2,x
    lda.b <pj_top
    clc
    adc.b <pj_half
    xba
    ora.b <pj_left
    sta.w oamMemory,x
    lda.b <pj_kind
    cmp #96
    bcc +
    jmp _next               ; a shot is always small with x below 256: its high bits stay 0
+   lda.b <pj_k
    asl a
    tax
    lda.l pj_hi,x
    tay
    ldx.b <pj_k
    sep #$20
    lda.l pj_keep,x
    and.w oamMemory,y
    sta.b <pj_tmp
    ldx.b <pj_rec
    lda.l obj_frames+2,x
    beq +
    ldx.b <pj_k
    lda.l pj_large,x
    ora.b <pj_tmp
    sta.b <pj_tmp
+   lda.b <pj_tmp
    sta.w oamMemory,y
    rep #$20
    bra _next

_hide:
    sep #$20
    ldx.b <pj_o
    lda #224
    sta.w oamMemory+1,x
    rep #$20

_next:
    inc.b <pj_k
    inc.b <pj_j
    lda.b <pj_j
    cmp #12
    bcs +
    jmp _obj
+   inc.b <pj_p
    lda.b <pj_p
    cmp #2
    bcs +
    jmp _view
+   jsr pj_line
    sec
    sbc.b <pj_t0
    bpl +
    clc
    adc #262
+   sta.l pj_lines
    lda.b <pj_kn            ; both views: the other kart, the 4 shots and the 2 obstacles, and the computer karts
    sec
    sbc #2
    asl a
    clc
    adc #14
    sta.l pj_count
    pld
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; Surface under (A = x, X = y), both in 1/16 map pixels within the map (main.c SURF_*), read from the
; track's surface map through ms_sp. Returns it in A with the zero flag set for grass; uses Y.
ms_surface:
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta.b <ms_t
    txa
    and #$3f80
    ora.b <ms_t
    tay
    lda [<ms_sp],y
    and #$00ff
    rts

; Does shot ms_i touch kart Y (0 to 5)? A kart is not hit by its own shot during its grace frames.
; On a hit: marks shot_struck[Y] for main.c to spin the kart, ends the shot and returns carry set.
ms_try:
    ldx.b <ms_i
    sep #$20
    lda.w shot_grace,x
    beq +
    tya
    cmp.w shot_owner,x
    bne +
    rep #$20
    clc
    rts
+   rep #$20
    tya
    asl a
    tax
    lda.l kart_off,x
    tax
    lda.w karts,x
    sec
    sbc.b <ms_nx
    clc
    adc #159                ; a shot hits a kart closer than 10 px (160) on both axes: dx + 159 is 0 to 318
    cmp #319
    bcs _ms_miss
    lda.w karts+2,x
    sec
    sbc.b <ms_ny
    clc
    adc #159
    cmp #319
    bcs _ms_miss
    sep #$20
    lda #1
    sta.w shot_struck,y
    ldx.b <ms_i
    lda #0
    sta.w shot_on,x
    rep #$20
    sec
    rts
_ms_miss:
    clc
    rts

;---------------------------------------------------------------------------------
; A shot flying mostly along x (|dy| < |dx| / 2) has met grass: at a corner, where the road goes on
; 8 px to one side only, it turns that way at the same speed instead of flying back at its thrower.
; Returns carry set when it turned; otherwise the caller bounces it straight back.
ms_turn_x:
    ldy.b <ms_w
    lda.w shot_dx,y
    bpl +
    eor #$ffff
    inc a
+   sta.b <ms_a
    lsr a
    sta.b <ms_t2
    lda.w shot_dy,y
    bpl +
    eor #$ffff
    inc a
+   cmp.b <ms_t2
    bcs _mt_no
    stz.b <ms_s
    lda.b <ms_y             ; road 8 px south?
    clc
    adc #128
    cmp #$4000
    bcs +
    tax
    lda.b <ms_x
    jsr ms_surface
    beq +
    inc.b <ms_s
+   lda.b <ms_y             ; road 8 px north?
    sec
    sbc #128
    bcc +
    tax
    lda.b <ms_x
    jsr ms_surface
    beq +
    lda.b <ms_s
    bne _mt_no              ; road both ways: a wall straight across
    lda #2
    sta.b <ms_s
+   lda.b <ms_s
    beq _mt_no
    ldy.b <ms_w
    lda.b <ms_a
    ldx.b <ms_s
    cpx #1
    beq +
    eor #$ffff
    inc a
+   sta.w shot_dy,y
    lda #0
    sta.w shot_dx,y
    sec
    rts
_mt_no:
    clc
    rts

; The same for a shot flying mostly along y: it turns east or west.
ms_turn_y:
    ldy.b <ms_w
    lda.w shot_dy,y
    bpl +
    eor #$ffff
    inc a
+   sta.b <ms_a
    lsr a
    sta.b <ms_t2
    lda.w shot_dx,y
    bpl +
    eor #$ffff
    inc a
+   cmp.b <ms_t2
    bcs _mt_no
    stz.b <ms_s
    lda.b <ms_nx            ; road 8 px east?
    clc
    adc #128
    cmp #$4000
    bcs +
    ldx.b <ms_y
    jsr ms_surface
    beq +
    inc.b <ms_s
+   lda.b <ms_nx            ; road 8 px west?
    sec
    sbc #128
    bcc +
    ldx.b <ms_y
    jsr ms_surface
    beq +
    lda.b <ms_s
    bne _mt_no
    lda #2
    sta.b <ms_s
+   lda.b <ms_s
    beq _mt_no
    ldy.b <ms_w
    lda.b <ms_a
    ldx.b <ms_s
    cpx #1
    beq +
    eor #$ffff
    inc a
+   sta.w shot_dx,y
    lda #0
    sta.w shot_dy,y
    sec
    rts

; One kart of the fast test: the shot touches it when its distance is under 10 px (160) on both axes,
; (kart - (shot - 159)) is 0 to 318. A hit jumps to _ms_hit with Y the kart.
.MACRO MS_KART
    lda.w karts+\1*12
    sec
    sbc.b <ms_ax
    cmp #319
    bcs +
    lda.w karts+\1*12+2
    sec
    sbc.b <ms_ay
    cmp #319
    bcs +
    ldy #\1
    jmp _ms_hit
+
.ENDM

;---------------------------------------------------------------------------------
; A distance in A (signed, within 16383), limited to LEADER_STEP either way.
.MACRO CLAMP_STEP
    bmi ++
    cmp #LEADER_STEP+1
    bcc +++
    lda #LEADER_STEP
    bra +++
++  cmp #$10000-LEADER_STEP
    bcs +++
    lda #$10000-LEADER_STEP
+++
.ENDM

;---------------------------------------------------------------------------------
; u8 move_shots(void)
; Shots fly straight and bounce off the track edge, where road meets grass, or turn with the road at a
; corner (a shot thrown from the grass flies on until it reaches road), and bounce off the map edge; each ends on the first kart it
; touches or after its life. Returns in tcc__r0 a bit per kart a shot hit (shot_struck[] says which).
move_shots:
    php
    phb
    phd
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda #pj_base
    tcd
    LOAD_NK
    stz.w ms_mask
    lda.w cur_surf
    sta.b <ms_sp
    lda.w cur_surf+2
    sta.b <ms_sp+2
    ldx #0
_ms_loop:
    stx.b <ms_i
    lda.w shot_on,x
    and #$00ff
    bne +
    jmp _ms_next
+   cmp #2
    bcc +
    jmp _ms_lead            ; a leader shot
+   txa
    asl a
    sta.b <ms_w
    tay
    lda.w shot_x,y
    sta.b <ms_x
    lda.w shot_y,y
    sta.b <ms_y
    tax
    lda.b <ms_x
    jsr ms_surface
    sta.b <ms_road
    ldy.b <ms_w
    lda.b <ms_x
    clc
    adc.w shot_dx,y
    cmp #$4000
    bcs _ms_bx
    sta.b <ms_nx
    lda.b <ms_road
    beq _ms_xok
    ldx.b <ms_y
    lda.b <ms_nx
    jsr ms_surface
    bne _ms_xok
    jsr ms_turn_x
    bcs _ms_tx
_ms_bx:
    ldy.b <ms_w
    lda #0
    sec
    sbc.w shot_dx,y
    sta.w shot_dx,y
_ms_tx:
    lda.b <ms_x
    sta.b <ms_nx
_ms_xok:
    ldy.b <ms_w
    lda.b <ms_y
    clc
    adc.w shot_dy,y
    cmp #$4000
    bcs _ms_by
    sta.b <ms_ny
    lda.b <ms_road
    beq _ms_yok
    ldx.b <ms_ny
    lda.b <ms_nx
    jsr ms_surface
    bne _ms_yok
    jsr ms_turn_y
    bcs _ms_ty
_ms_by:
    ldy.b <ms_w
    lda #0
    sec
    sbc.w shot_dy,y
    sta.w shot_dy,y
_ms_ty:
    lda.b <ms_y
    sta.b <ms_ny
_ms_yok:
    ldy.b <ms_w
    lda.b <ms_nx
    sta.w shot_x,y
    lda.b <ms_ny
    sta.w shot_y,y
    ldx.b <ms_i
    sep #$20
    lda.w shot_grace,x
    rep #$20
    beq _ms_fast
    ldy #0                  ; its thrower is spared while the grace frames last: the slow way
_ms_k:
    jsr ms_try
    bcc +
    jmp _ms_kdone
+   iny
    cpy.w nk_n
    bcc _ms_k
    jmp _ms_kdone
_ms_fast:
    lda.b <ms_nx
    sec
    sbc #159
    sta.b <ms_ax
    lda.b <ms_ny
    sec
    sbc #159
    sta.b <ms_ay
    MS_KART 0
    MS_KART 1
    ldx.w nk_n
    cpx #3
    bcs +
    jmp _ms_kdone
+
    MS_KART 2
    cpx #4
    bcs +
    jmp _ms_kdone
+
    MS_KART 3
    cpx #5
    bcs +
    jmp _ms_kdone
+
    MS_KART 4
    cpx #6
    bcs +
    jmp _ms_kdone
+
    MS_KART 5
    jmp _ms_kdone
; A leader shot (shot_on is 2 + its target kart): it flies at the target on each axis by LEADER_STEP at most, over any
; floor and walls, and hits it when within 10 px on both axes, like a shot. A target in the air or sinking is passed
; under: the shot waits over it, and hits when it lands (main.c turns shot_struck into hit() unless the kart is in the
; air or sinking, which it still is not by then).
_ms_lead:
    and #$00ff
    dec a
    dec a
    sta.b <ms_s             ; the target kart
    txa
    asl a
    sta.b <ms_w
    lda.b <ms_s
    asl a
    tax
    lda.l kart_off,x
    tax                     ; X: the target's offset in karts
    ldy.b <ms_w
    lda.w karts,x
    sec
    sbc.w shot_x,y
    sta.b <ms_t             ; the distance to go on each axis
    lda.w karts+2,x
    sec
    sbc.w shot_y,y
    sta.b <ms_t2
    lda.b <ms_t
    clc
    adc #159
    cmp #319
    bcs _ml_move
    lda.b <ms_t2
    clc
    adc #159
    cmp #319
    bcs _ml_move
    ldx.b <ms_s             ; it is there
    sep #$20
    lda.w air_t,x
    ora.w fall_t,x
    rep #$20
    beq +
    jmp _ms_kdone           ; in the air or sinking: wait
+   sep #$20
    lda #1
    sta.w shot_struck,x
    ldx.b <ms_i
    lda #0
    sta.w shot_on,x
    rep #$20
    jmp _ms_kdone
_ml_move:
    lda.b <ms_t
    CLAMP_STEP
    clc
    adc.w shot_x,y
    sta.w shot_x,y
    lda.b <ms_t2
    CLAMP_STEP
    clc
    adc.w shot_y,y
    sta.w shot_y,y
    jmp _ms_kdone
_ms_hit:                    ; Y is the kart: marks it, ends the shot
    sep #$20
    lda #1
    sta.w shot_struck,y
    ldx.b <ms_i
    lda #0
    sta.w shot_on,x
    rep #$20
_ms_kdone:
    ldx.b <ms_i
    sep #$20
    lda.w shot_grace,x
    beq +
    dec a
    sta.w shot_grace,x
+   rep #$20
    ldy.b <ms_w
    lda.w shot_life,y
    dec a
    sta.w shot_life,y
    bne _ms_next
    sep #$20
    lda #0
    sta.w shot_on,x
    rep #$20
_ms_next:
    ldx.b <ms_i
    inx
    cpx #4
    bcs +
    jmp _ms_loop
+   stz.w ms_mask           ; the karts with shot_struck set, a bit each (the tests set it too)
    lda.w shot_struck       ; nothing set: nothing to scan
    ora.w shot_struck+2
    ora.w shot_struck+4
    beq _ms_ret
    ldx #0
_ms_sc:
    sep #$20
    lda.w shot_struck,x
    rep #$20
    beq +
    phx
    txa
    asl a
    tax
    lda.l kart_bit,x
    ora.w ms_mask
    sta.w ms_mask
    plx
+   inx
    cpx.w nk_n
    bne _ms_sc
_ms_ret:
    lda.w ms_mask
    sta.l tcc__r0
    pld
    plb
    plp
    rtl

; One kart of an obstacle's test: it is hit when the kart is within the reach on both axes.
.MACRO MO_KART
    lda.w karts+\1*12
    sec
    sbc.b <ms_ax
    cmp #OB_REACH*32-1
    bcs +
    lda.w karts+\1*12+2
    sec
    sbc.b <ms_ay
    cmp #OB_REACH*32-1
    bcs +
    sep #$20
    lda #1
    sta.w ob_struck+\1
    rep #$20
+
.ENDM

;---------------------------------------------------------------------------------
; u8 move_obstacles(void)
; Each obstacle that is on rolls ob_dx, ob_dy (1/16 px) a frame and turns back after ob_len frames, so
; it rolls across the road and back; one closer than OB_REACH map pixels on both axes to a kart sets
; ob_struck for that kart (and its bit in the result, tcc__r0), which main.c turns into a hit.
move_obstacles:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    LOAD_NK
    stz.w ms_mask
    ldx #0
_mo_loop:
    lda.w ob_on,x
    and #$00ff
    bne +
    jmp _mo_next
+   txa
    asl a
    tay
    lda.w ob_x,y
    clc
    adc.w ob_dx,y
    sta.w ob_x,y
    lda.w ob_y,y
    clc
    adc.w ob_dy,y
    sta.w ob_y,y
    lda.w ob_t,y
    inc a
    cmp.w ob_len,y
    bcc +
    lda #0
    sec
    sbc.w ob_dx,y
    sta.w ob_dx,y
    lda #0
    sec
    sbc.w ob_dy,y
    sta.w ob_dy,y
    lda #0
+   sta.w ob_t,y
    ; each kart in turn: the obstacle's position less (reach - 1), then kart - that is 0 to 2 * reach - 2 when they touch
    stx.w mo_x
    lda.w ob_x,y
    sec
    sbc #OB_REACH*16-1
    sta.b <ms_ax
    lda.w ob_y,y
    sec
    sbc #OB_REACH*16-1
    sta.b <ms_ay
    MO_KART 0
    MO_KART 1
    lda.w nk_n
    cmp #3
    bcs +
    jmp _mo_kd
+   MO_KART 2
    lda.w nk_n
    cmp #4
    bcs +
    jmp _mo_kd
+   MO_KART 3
    lda.w nk_n
    cmp #5
    bcs +
    jmp _mo_kd
+   MO_KART 4
    lda.w nk_n
    cmp #6
    bcs +
    jmp _mo_kd
+   MO_KART 5
_mo_kd:
    ldx.w mo_x
_mo_next:
    inx
    cpx #2
    bcs +
    jmp _mo_loop
+   stz.w ms_mask           ; the karts with ob_struck set, a bit each (the tests set it too)
    lda.w ob_struck
    ora.w ob_struck+2
    ora.w ob_struck+4
    beq _mo_ret
    ldx #0
_mo_sc:
    sep #$20
    lda.w ob_struck,x
    rep #$20
    beq +
    phx
    txa
    asl a
    tax
    lda.l kart_bit,x
    ora.w ms_mask
    sta.w ms_mask
    plx
+   inx
    cpx.w nk_n
    bne _mo_sc
_mo_ret:
    lda.w ms_mask
    sta.l tcc__r0
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; void minimap(void)
; The karts' dots on each half's 32x32 minimap of the 1024x1024 map: player 1's in slots 64 (top half)
; and 66 (bottom half), player 2's in 65 and 67, the computer karts' in 84 to 87 (top half) and 88 to 91
; (bottom half). A dot sprite is 16x16 with the dot at its middle, so it
; sits 7 pixels up and left of the kart's place on the minimap.
.MACRO MINI_DOT                  ; \1 offset of the kart in karts, \2 its top-half slot
    lda.w karts+\1
    xba
    and #$00ff
    lsr a                       ; x / 16 / 32: map pixels on the minimap
    clc
    adc #MINI_X-7
    sep #$20
    sta.w oamMemory+\2*4
    sta.w oamMemory+(\2+2)*4
    rep #$20
    lda.w karts+\1+2
    xba
    and #$00ff
    lsr a
    clc
    adc #MINI_Y-7
    sep #$20
    sta.w oamMemory+\2*4+1
    clc
    adc #112
    sta.w oamMemory+(\2+2)*4+1
    rep #$20
.ENDM

minimap:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    MINI_DOT 0, 64
    MINI_DOT 12, 65
    ; tile and attributes: palette 2 (the white text palette, which holds the minimap colours) above the floor, tile bit 8 in attribute bit 0
    lda #(TILE_DOT1 & $ff) | (($30 | (2 << 1) | (TILE_DOT1 >> 8)) << 8)
    sta.w oamMemory+64*4+2
    sta.w oamMemory+66*4+2
    lda #(TILE_DOT2 & $ff) | (($30 | (2 << 1) | (TILE_DOT2 >> 8)) << 8)
    sta.w oamMemory+65*4+2
    sta.w oamMemory+67*4+2
    ; the computer karts' dots: kart 2 + i in slot 84 + i (top half) and 88 + i (bottom half). During the race one
    ; dot is placed a frame (race_time & 3), each every 4 frames; before it, all of them
    lda.w cpu_n
    and #$00ff
    beq _mn_out
    sta.w mn_n
    stz.w mn_i
    lda.w game_state
    and #$00ff
    cmp #ST_RACE
    bne _mn_loop
    lda.w race_time
    and #3
    cmp.w mn_n
    bcs _mn_out
    sta.w mn_i
    lda #1
    sta.w mn_n
_mn_loop:
    lda.w mn_i
    inc a
    inc a
    asl a
    tax
    lda.l kart_off,x
    tay
    lda.w mn_i
    asl a
    asl a
    tax
    lda.w karts,y
    xba
    and #$00ff
    lsr a
    clc
    adc #MINI_X-7
    sep #$20
    sta.w oamMemory+84*4,x
    sta.w oamMemory+88*4,x
    rep #$20
    lda.w karts+2,y
    xba
    and #$00ff
    lsr a
    clc
    adc #MINI_Y-7
    sep #$20
    sta.w oamMemory+84*4+1,x
    clc
    adc #112
    sta.w oamMemory+88*4+1,x
    rep #$20
    lda #(TILE_DOT3 & $ff) | (($30 | (2 << 1) | (TILE_DOT3 >> 8)) << 8)
    sta.w oamMemory+84*4+2,x
    sta.w oamMemory+88*4+2,x
    inc.w mn_i
    dec.w mn_n
    bne _mn_loop
_mn_out:
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; void move_kart(u8 p)
; Kart p one frame along its heading: forward is (sin, -cos) of its angle, times its speed (1/16 px a
; frame), added to the remainders accx and accy in 1/256 px; their whole pixels move the kart and the
; rest stays, so slow and slanted moves stay exact. The C did the same with two software multiplies
; and a division each way; this reads sin x speed from a table (mk_tab, speed 0 to 62, |sin| 0 to 256)
; and splits as C's division does, rounding towards zero.
move_kart:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda 6,s
    and #$00ff
    asl a
    tax
    lda.l kart_off,x
    tay
    jsr mk_move
    plb
    plp
    rtl

; The kart at offset Y in karts one frame on (data bank $7E, 16-bit registers). The step on each axis is read from
; mk_tab: row = the heading (the angle's high byte, 0 to 127), column = the speed (0 to 63), the word sin x speed in
; 1/256 px; the y axis reads the row a quarter turn on (cos) and moves the other way.
mk_move:
    lda.w karts+4,y
    cmp #64                 ; no kart is faster than 62: the table stops at 63
    bcc +
    lda #63
+   asl a
    sta.w mk_m              ; the speed's column
    lda.w karts+6,y
    and #$7f00
    lsr a
    sta.w mk_i              ; the heading's row, 128 bytes each
    ora.w mk_m
    tax
    lda.l mk_tab,x
    clc
    adc.w karts+8,y
    jsr mk_split
    clc
    adc.w karts,y
    sta.w karts,y
    lda.w mk_r
    sta.w karts+8,y
    lda.w mk_i
    clc
    adc #$1000
    and #$3f80
    ora.w mk_m
    tax
    lda.l mk_tab,x
    sta.w mk_t2
    lda.w karts+10,y
    sec
    sbc.w mk_t2
    jsr mk_split
    clc
    adc.w karts+2,y
    sta.w karts+2,y
    lda.w mk_r
    sta.w karts+10,y
    rts

; A (1/256 px) split as C's A / 256 and A % 256: whole pixels in A, the remainder in mk_r.
mk_split:
    cmp #$8000
    bcs +
    sta.w mk_t
    and #$00ff
    sta.w mk_r
    lda.w mk_t
    xba
    and #$00ff
    rts
+   eor #$ffff
    inc a
    sta.w mk_t
    and #$00ff
    eor #$ffff
    inc a
    sta.w mk_r
    lda.w mk_t
    xba
    and #$00ff
    eor #$ffff
    inc a
    rts

;---------------------------------------------------------------------------------
; void drive(u8 p, u16 pad)
; Kart p for one frame, as main.c's C did it (about 10 lines a kart there): the top speed is the kart
; type's plus a step for every two coins, or MAX_GRASS off the road and on sand; a boost pad starts a
; short boost; a falling kart stands; a spinning kart or spinning wheels take no pedal, and a spinning
; kart slows; a boost holds the kart BOOST_EXTRA above its top speed, also off the road. In the air the
; speed is kept. Otherwise the pedal gains the type's acceleration (in 1/16 of a step, carried in
; accel_frac) up to the top speed, no pedal rolls a step slower, the brake takes 3, and above the top
; speed the kart loses 2. Above speed 2 it steers by the type's turn, or in a drift always turns the
; drift's way: half as much again when steered into it, which charges twice as fast, half when steered
; out. Then move_kart. After php, phb and phd: p at 8,s, pad at 9,s.
drive:
    php
    phb
    phd
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda #pj_base
    tcd
    lda.w cur_surf
    sta.b <ms_sp
    lda.w cur_surf+2
    sta.b <ms_sp+2
    lda 8,s
    and #$00ff
    sta.w dr_p
    lda 9,s
    sta.w dr_pad
    jsr dr_run
    pld
    plb
    plp
    rtl

; The work of drive for kart dr_p with the pad dr_pad (data bank $7E, direct page at pj_base, ms_sp the surface map,
; 16-bit registers): cpu_frame calls it for each computer kart.
dr_run:
    lda.w dr_p
    asl a
    tax
    lda.l kart_off,x
    tay
    sty.w dr_k
    ldx.w dr_p
    lda.w kart_type,x
    and #$00ff
    sta.w dr_t
    asl a
    clc
    adc.w dr_t
    asl a                   ; the type's record: accel, top, turn (6 bytes)
    sta.w dr_kt
    ; the floor under the kart, or road in the air
    lda.w air_t,x
    and #$00ff
    beq +
    lda #SURF_ROAD
    bra ++
+   lda.w karts,y
    tax
    lda.w karts+2,y
    sta.w dr_t
    txa
    jsr dr_surface
++  sta.w dr_road
    ldx.w dr_p
    cmp #SURF_PAD
    bne +
    lda.w boost_t,x
    and #$00ff
    cmp #PAD_FRAMES
    bcs +
    sep #$20
    lda #PAD_FRAMES
    sta.w boost_t,x
    rep #$20
+   lda.w coins,x           ; a step for every two coins, counting at most 10 (a coin battle counts more)
    and #$00ff
    cmp #11
    bcc +
    lda #10
+   lsr a
    sta.w dr_cb
    ldx.w dr_kt
    lda.l kart_types+2,x
    clc
    adc.w dr_cb
    sta.w dr_top
    lda.w dr_road
    beq +
    cmp #SURF_SAND
    bne ++
+   lda #MAX_GRASS
    sta.w dr_top
++  ldx.w dr_p
    ldy.w dr_k
    lda.w fall_t,x
    and #$00ff
    beq +
    stz.w dr_pad
    lda #0
    sta.w karts+4,y
+   lda.w spin_t,x
    and #$00ff
    beq +
    stz.w dr_pad
    lda.w karts+4,y
    bmi ++
    cmp #2
    bcc ++
    sec
    sbc #2
    sta.w karts+4,y
    bra ++
+   lda.w wheelspin_t,x
    and #$00ff
    beq ++
    stz.w dr_pad
++  lda.w boost_t,x
    and #$00ff
    beq +
    dec a
    sep #$20
    sta.w boost_t,x
    rep #$20
    ldx.w dr_kt
    lda.l kart_types+2,x
    clc
    adc.w dr_cb
    clc
    adc #BOOST_EXTRA
    sta.w dr_top
    sta.w karts+4,y
    ldx.w dr_p
+   lda.w shrink_t,x        ; a shrunk kart: top speed SHRINK_TOP, boosting or not (main.c shrink)
    and #$00ff
    beq ++
    lda #SHRINK_TOP
    sta.w dr_top
    lda.w karts+4,y
    bmi ++
    cmp #SHRINK_OVER
    bcc ++
    lda #SHRINK_TOP
    sta.w karts+4,y
++  lda.w air_t,x
    and #$00ff
    beq +
    jmp _dr_turn            ; in the air the kart keeps its speed
+   lda.w dr_pad
    and #KEY_B|KEY_A
    beq _dr_roll
    lda.w karts+4,y
    cmp.w dr_top
    bcs _dr_caps
    ldx.w dr_kt
    lda.l kart_types,x
    sta.w dr_t
    ldx.w dr_p
    lda.w accel_frac,x
    and #$00ff
    clc
    adc.w dr_t
    sta.w dr_t
    and #$000f
    sep #$20
    sta.w accel_frac,x
    rep #$20
    lda.w dr_t
    lsr a
    lsr a
    lsr a
    lsr a
    clc
    adc.w karts+4,y
    cmp.w dr_top
    bcc +
    lda.w dr_top
+   sta.w karts+4,y
    bra _dr_caps
_dr_roll:
    lda.w karts+4,y
    beq _dr_caps
    dec a
    sta.w karts+4,y
_dr_caps:
    lda.w dr_pad
    and #KEY_Y|KEY_DOWN
    beq +
    lda.w karts+4,y
    sec
    sbc #3
    sta.w karts+4,y
+   lda.w karts+4,y
    bmi _dr_zero
    cmp.w dr_top
    beq _dr_turn
    bcc _dr_turn
    sec
    sbc #2
    sta.w karts+4,y
    bra _dr_turn
_dr_zero:
    lda #0
    sta.w karts+4,y

_dr_turn:
    ldy.w dr_k
    lda.w karts+4,y
    bmi +
    cmp #3
    bcs ++
+   jmp _dr_move            ; below speed 3 a kart does not steer
++  ldx.w dr_kt
    lda.l kart_types+4,x
    sta.w dr_turn
    ldx.w dr_p
    lda.w drift,x
    and #$00ff
    beq _dr_plain
    cmp #$0080              ; drift is -1 (left) or 1 (right)
    bcs +
    lda #KEY_RIGHT
    bra ++
+   lda #KEY_LEFT
++  and.w dr_pad
    beq +
    lda.w dr_turn           ; steered into the drift
    lsr a
    clc
    adc.w dr_turn
    sta.w dr_turn
    lda.w charge,x
    and #$00ff
    clc
    adc #2
    bra ++
+   lda.w dr_pad
    and #KEY_LEFT|KEY_RIGHT
    beq +
    lsr.w dr_turn           ; steered out of it
+   lda.w charge,x
    and #$00ff
    inc a
++  cmp #201
    bcc +
    lda #200
+   sep #$20
    sta.w charge,x
    rep #$20
    lda.w drift,x
    and #$00ff
    cmp #$0080
    bcs _dr_left
    bra _dr_right
_dr_plain:
    lda.w dr_pad
    and #KEY_LEFT
    beq +
    lda.w karts+6,y
    sec
    sbc.w dr_turn
    sta.w karts+6,y
+   lda.w dr_pad
    and #KEY_RIGHT
    beq _dr_move
_dr_right:
    lda.w karts+6,y
    clc
    adc.w dr_turn
    sta.w karts+6,y
    bra _dr_move
_dr_left:
    lda.w karts+6,y
    sec
    sbc.w dr_turn
    sta.w karts+6,y
_dr_move:
    ldy.w dr_k
    jsr mk_move
    rts

; The surface under (A = x, dr_t = y), both in 1/16 map pixels (main.c surface_at), through ms_sp.
dr_surface:
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta.w dr_cb
    lda.w dr_t
    and #$3f80
    ora.w dr_cb
    tay
    lda [<ms_sp],y
    and #$00ff
    rts

;---------------------------------------------------------------------------------
; void cpu_frame(void)
; Every racing computer kart drives one frame: its floor cell's byte in the steering map gives the heading to aim at
; (bits 0-6, in the game's angle units, plus the kart's own small bias so the karts do not follow one line); the kart
; steers left or right when it is more than one step off, holds the pedal unless bit 7 marks a tight stretch and it is
; above CPU_SLOW, when it brakes, and then drives as a player does (dr_run, the kart's own type, no speed bonus). Nothing runs before GO
; or while cpu_hold is 1.
cpu_frame:
    php
    phb
    phd
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda.w game_state
    and #$00ff
    cmp #ST_RACE
    beq +
    stz.w cf_av             ; before GO no kart is steering round another
    stz.w cf_av+2
    stz.w cf_av+4
    stz.w cf_av+6
    jmp _cf_out
+   lda.w cpu_hold
    and #$00ff
    beq +
    jmp _cf_out
+   lda #pj_base
    tcd
    lda.w cur_surf
    sta.b <ms_sp
    lda.w cur_surf+2
    sta.b <ms_sp+2
    lda.w cur_steer
    sta.b <cf_sp
    lda.w cur_steer+2
    sta.b <cf_sp+2
    LOAD_NK
    lda #2
    sta.w cf_k
    lda #24                 ; kart 2's offset in karts
    sta.w cf_y
_cf_loop:
    ldy.w cf_y
    lda.w karts+2,y         ; the steering map's cell = (y >> 8) * 64 + (x >> 8), as progress reads it
    and #$ff00
    lsr a
    lsr a
    sta.w cf_h
    lda.w karts,y
    xba
    and #$00ff
    ora.w cf_h
    tay
    lda [<cf_sp],y
    and #$00ff
    sta.w cf_b
    ldy.w cf_y
    lda.w karts+6,y         ; the heading, 0-127
    xba
    and #$007f
    sta.w cf_h
    lda.w cf_k
    asl a
    tax
    lda.w cf_av-4,x         ; steering round a kart it touched: the heading it aims at moves to one side for AV_T frames
    beq +
    lda.w cf_av-4,x
    dec a
    sta.w cf_av-4,x
    lda.w cf_b
    and #$007f
    clc
    adc.w cf_sd-4,x
    clc
    adc.l cpu_bias-4,x
    bra ++
+   lda.w cf_b
    and #$007f
    clc
    adc.l cpu_bias-4,x
++  sec
    sbc.w cf_h
    and #$007f              ; target less heading, modulo 128: 2 to 63 turn right, 64 to 126 left
    ldx #0
    cmp #2
    bcc +
    cmp #127
    bcs +
    ldx #KEY_RIGHT
    cmp #64
    bcc +
    ldx #KEY_LEFT
+   stx.w cf_pad
    lda.w cf_b
    bit #$0080
    beq +                   ; in a tight stretch it brakes above CPU_SLOW and presses the pedal below it
    lda.w karts+4,y
    cmp #CPU_SLOW+1
    bcc +
    lda.w cf_pad
    ora #KEY_Y
    bra ++
+   lda.w cf_pad
    ora #KEY_B
++  sta.w cf_pad
    ; a plain kart (no timer running, on the road) takes the short path below: the same rules as dr_run for that case
    ldx.w cf_k
    sep #$20
    lda.w spin_t,x
    ora.w fall_t,x
    ora.w wheelspin_t,x
    ora.w boost_t,x
    ora.w shrink_t,x
    ora.w air_t,x
    ora.w drift,x
    rep #$20
    beq +
    jmp _cf_slow
+   lda.w karts,y           ; the surface under the kart (main.c surface_at): (y & $3f80) | (x >> 7)
    asl a
    xba
    and #$00ff
    sta.w cf_h
    lda.w karts+2,y
    and #$3f80
    ora.w cf_h
    tay
    lda [<ms_sp],y
    and #$00ff
    cmp #SURF_ROAD
    beq +
    jmp _cf_slow
+   ldx.w cf_k
    lda.w kart_type,x       ; top speed: the type's plus a step for every two coins (at most 10 count)
    and #$00ff
    sta.w dr_t
    asl a
    clc
    adc.w dr_t
    asl a
    sta.w dr_kt
    lda.w coins,x
    and #$00ff
    cmp #11
    bcc +
    lda #10
+   lsr a
    ldx.w dr_kt
    clc
    adc.l kart_types+2,x
    sta.w dr_top
    ldy.w cf_y
    lda.w cf_pad
    and #KEY_B
    beq _cf_roll
    lda.w karts+4,y
    cmp.w dr_top
    bcs _cf_caps
    lda.l kart_types,x      ; the pedal gains the type's acceleration (1/16 of a step, carried in accel_frac)
    sta.w dr_t
    ldx.w cf_k
    lda.w accel_frac,x
    and #$00ff
    clc
    adc.w dr_t
    sta.w dr_t
    and #$000f
    sep #$20
    sta.w accel_frac,x
    rep #$20
    lda.w dr_t
    lsr a
    lsr a
    lsr a
    lsr a
    clc
    adc.w karts+4,y
    cmp.w dr_top
    bcc +
    lda.w dr_top
+   sta.w karts+4,y
    bra _cf_caps
_cf_roll:
    lda.w karts+4,y         ; no pedal: a step slower
    beq _cf_caps
    dec a
    sta.w karts+4,y
_cf_caps:
    lda.w cf_pad
    and #KEY_Y
    beq +
    lda.w karts+4,y         ; the brake takes 3
    sec
    sbc #3
    sta.w karts+4,y
+   lda.w karts+4,y
    bmi _cf_zero
    cmp.w dr_top
    beq _cf_turn
    bcc _cf_turn
    sec
    sbc #2                  ; above the top speed the kart loses 2
    sta.w karts+4,y
    bra _cf_turn
_cf_zero:
    lda #0
    sta.w karts+4,y
_cf_turn:
    lda.w karts+4,y         ; below speed 3 a kart does not steer
    bmi _cf_move
    cmp #3
    bcc _cf_move
    lda.w cf_pad
    and #KEY_LEFT|KEY_RIGHT
    beq _cf_move
    ldx.w dr_kt
    cmp #KEY_LEFT
    beq +
    lda.l kart_types+4,x    ; right: the angle grows by the type's turn
    clc
    adc.w karts+6,y
    bra ++
+   lda.l kart_types+4,x    ; left: it shrinks
    eor #$ffff
    sec
    adc.w karts+6,y
++  sta.w karts+6,y
_cf_move:
    jsr mk_move
    bra _cf_next
_cf_slow:
    lda.w cf_k              ; anything else (a spin, a fall, a boost, the air, off the road) goes through drive's own code
    sta.w dr_p
    lda.w cf_pad
    sta.w dr_pad
    jsr dr_run
_cf_next:
    inc.w cf_k
    lda.w cf_y
    clc
    adc #12
    sta.w cf_y
    lda.w cf_k
    cmp.w nk_n
    bcs _cf_out
    jmp _cf_loop
_cf_out:
    pld
    plb
    plp
    rtl

cpu_bias: .dw $FFFD, 3, 0, 0    ; each computer kart's own heading bias in steps of 128 to the turn (karts 2 to 5): about 2 px sideways a step

;---------------------------------------------------------------------------------
; u8 progress(u8 p)
; Lap progress for kart p (main.c track_progress): the cell under the kart holds 0-254 round the lap or
; OFF_TRACK. On the track: a step back of up to 15 counts towards the wrong-way sign, a step forward
; clears it; the checkpoint (progress / 8) moves on only to the next one and never once finished, and
; frac is 8-15 inside the checkpoint or 0-7 in the one before; prog = (lap * 32 + checkpoint) * 8 +
; frac. Returns bit 0 when checkpoint 0 was reached (a lap: main.c counts it) and bit 1 when the
; wrong-way sign should change, in tcc__r0 as tcc-816 expects. After php, phb and phd: p at 8,s.
progress:
    php
    phb
    phd
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda #pj_base
    tcd
    lda.w cur_prog
    sta.b <ms_sp
    lda.w cur_prog+2
    sta.b <ms_sp+2
    lda 8,s
    and #$00ff
    sta.w pg_p
    jsr pg_kart
    pld
    sta.l tcc__r0           ; tcc-816 takes a function's result from tcc__r0, not from A
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; u8 progress_players(void)
; progress() for both players in one call: bits 0 and 1 are player 1's (a lap, the wrong-way sign changes), bits 2
; and 3 player 2's.
progress_players:
    php
    phb
    phd
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda #pj_base
    tcd
    lda.w cur_prog
    sta.b <ms_sp
    lda.w cur_prog+2
    sta.b <ms_sp+2
    stz.w pg_p
    jsr pg_kart
    sta.w pp_r
    lda #1
    sta.w pg_p
    jsr pg_kart
    asl a
    asl a
    ora.w pp_r
    pld
    sta.l tcc__r0
    plb
    plp
    rtl

; The work of progress for kart pg_p (the track's progress map is at ms_sp, the direct page at pj_base):
; returns bit 0 and bit 1 in A.
pg_kart:
    stz.w pg_e
    lda.w pg_p
    asl a
    tax
    lda.l kart_off,x
    tay
    ldx.w pg_p
    lda.w karts+2,y         ; cell = (y >> 8) * 64 + (x >> 8), positions in 1/16 px
    and #$ff00
    lsr a
    lsr a
    sta.w pg_c
    lda.w karts,y
    xba
    and #$00ff
    ora.w pg_c
    tay
    lda [<ms_sp],y
    and #$00ff
    cmp #OFF_TRACK
    bne +
    jmp _pg_prog
+   sta.w pg_v
    sep #$20
    sec
    sbc.w fine,x            ; d = v - fine, as a signed byte
    pha
    lda.w pg_v
    sta.w fine,x
    pla
    beq _pg_cp
    bpl +
    cmp #$f1                ; -15 to -1: a step back
    bcc _pg_cp
    lda.w wrong,x
    inc a
    beq _pg_cp              ; stays at 255
    sta.w wrong,x
    bra _pg_cp
+   cmp #16                 ; 1 to 15: a step forward
    bcs _pg_cp
    lda #0
    sta.w wrong,x
_pg_cp:
    rep #$20
    lda.w pg_v
    lsr a
    lsr a
    lsr a
    sta.w pg_c
    lda.w finished,x
    and #$00ff
    bne _pg_frac
    lda.w cp,x
    inc a
    and #NCP-1
    cmp.w pg_c
    bne _pg_frac
    sep #$20
    sta.w cp,x
    rep #$20
    and #$00ff
    bne _pg_frac
    lda #1
    sta.w pg_e
_pg_frac:
    lda.w cp,x
    and #$00ff
    cmp.w pg_c
    bne +
    lda.w pg_v
    and #$0007
    ora #$0008
    bra ++
+   dec a
    and #NCP-1
    cmp.w pg_c
    bne _pg_prog
    lda.w pg_v
    and #$0007
++  sep #$20
    sta.w frac,x
    rep #$20
_pg_prog:
    lda.w lap,x             ; prog = ((lap * 32 + cp) * 8) + frac
    and #$00ff
    asl a
    asl a
    asl a
    asl a
    asl a
    sta.w pg_c
    lda.w cp,x
    and #$00ff
    clc
    adc.w pg_c
    asl a
    asl a
    asl a
    sta.w pg_c
    lda.w frac,x
    and #$00ff
    clc
    adc.w pg_c
    pha
    txa
    asl a
    tay
    pla
    sta.w prog,y
    ; the wrong-way sign: on from WRONG_STEPS steps back until finished
    lda.w finished,x
    and #$00ff
    bne +
    lda.w wrong,x
    and #$00ff
    cmp #WRONG_STEPS
    bcc +
    lda #1
    bra ++
+   lda #0
++  sta.w pg_c
    lda.w wrong_shown,x
    and #$00ff
    cmp.w pg_c
    beq +
    lda.w pg_e
    ora #2
    sta.w pg_e
+   lda.w pg_e
    rts

;---------------------------------------------------------------------------------
; u16 progress_cpu(void)
; progress for one computer kart a frame, in turn (2 + race_time & 3: each every 4 frames, as a kart moves less
; than a checkpoint in that time): the low byte of the result has the kart's bit when it reached checkpoint 0 (a
; lap), the high byte its bit when its wrong-way sign should change.
progress_cpu:
    php
    phb
    phd
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda #pj_base
    tcd
    LOAD_NK
    stz.w pc_mask
    lda.w race_time
    and #3
    inc a
    inc a
    sta.w pg_p
    cmp.w nk_n
    bcs _pc_done
    lda.w cur_prog
    sta.b <ms_sp
    lda.w cur_prog+2
    sta.b <ms_sp+2
    jsr pg_kart
    beq _pc_done
    sta.w pc_t
    lda.w pg_p
    asl a
    tax
    lda.l kart_bit,x
    sta.w pc_b
    lda.w pc_t
    lsr a
    bcc +
    pha
    lda.w pc_b
    ora.w pc_mask
    sta.w pc_mask
    pla
+   lsr a
    bcc _pc_done
    lda.w pc_b
    xba
    ora.w pc_mask
    sta.w pc_mask
_pc_done:
    lda.w pc_mask
    pld
    sta.l tcc__r0
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; void camera(u8 p)
; The camera D0 map pixels behind kart p (pend_cx, pend_cy) and the perspective table rows for its
; angle (pend_row[p]: s at the angle, t at the angle - 90 degrees, s at - 90, t at + 180), which
; init_hdma hands to HDMA next frame. cam_d holds D0 * sin / 256 per angle and row_off the angle's row
; offset (tools/gen_assets.py cam_tables), so there is no multiply. After php and phb: p at 6,s.
camera_both:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda #0
    jsr cm_one
    lda #1
    jsr cm_one
    plb
    plp
    rtl

camera:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda 6,s
    jsr cm_one
    plb
    plp
    rtl

; The camera of player A (0 or 1), data bank $7E, 16-bit registers.
cm_one:
    and #$0001
    asl a
    sta.w cm_p2
    asl a
    asl a
    sta.w cm_p8
    ldy #0
    lda.w cm_p2
    beq +
    ldy #12                 ; karts[1]
+   lda.w karts+6,y
    xba
    and #$007f
    asl a
    sta.w cm_i
    tax
    lda.w karts,y           ; x >> 4: map pixels (the map edge keeps it 0 or more)
    lsr a
    lsr a
    lsr a
    lsr a
    sec
    sbc.l cam_d,x
    ldx.w cm_p2
    sta.w pend_cx,x
    lda.w cm_i              ; cos = sin 90 degrees on
    clc
    adc #64
    and #$00fe
    tax
    lda.w karts+2,y
    lsr a
    lsr a
    lsr a
    lsr a
    clc
    adc.l cam_d,x
    ldx.w cm_p2
    sta.w pend_cy,x
    ldx.w cm_i
    lda.l row_off,x
    clc
    adc.w s_addr
    ldx.w cm_p8
    sta.w pend_row,x
    lda.w cm_i
    sec
    sbc #64
    and #$00fe
    tax
    lda.l row_off,x
    sta.w cm_t
    clc
    adc.w t_addr
    ldx.w cm_p8
    sta.w pend_row+2,x
    lda.w cm_t
    clc
    adc.w s_addr
    sta.w pend_row+4,x
    lda.w cm_i
    clc
    adc #128
    and #$00fe
    tax
    lda.l row_off,x
    clc
    adc.w t_addr
    ldx.w cm_p8
    sta.w pend_row+6,x
    rts

;---------------------------------------------------------------------------------
; void init_hdma(void)
; Called every race frame right after vblank starts, because the library's vblank code undoes the
; HDMA set-up (docs/engine.md): writes the camera values computed last frame into the six HDMA
; tables, then points channels 2 to 7 at them. The tables never change while HDMA reads them.

; an indirect table: sky lines read the zero word before the rows, floor lines one row each
.MACRO IND_TABLE                 ; \1 table, \2 its zero word, \3 row number 0-3
    sep #$20
    lda #24
    sta.w \1
    sta.w \1+6
    lda #$80|88
    sta.w \1+3
    sta.w \1+9
    stz.w \1+12
    rep #$20
    lda.w \2
    sta.w \1+1
    sta.w \1+7
    lda.w pend_row+2*\3
    sta.w \1+4
    lda.w pend_row+8+2*\3
    sta.w \1+10
.ENDM

; channel \1: mode \2 to register $21\3 from table \4, indirect rows in bank \5
.MACRO HDMA_CH
    lda #(\3 << 8) | \2
    sta.l $004300 + (\1 << 4)
    lda #(\4 & $ffff)
    sta.l $004302 + (\1 << 4)
    sep #$20
    lda #$7e
    sta.l $004304 + (\1 << 4)
    lda.w \5
    sta.l $004307 + (\1 << 4)
    rep #$20
.ENDM

init_hdma:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    IND_TABLE hdma_a, s_zero, 0
    IND_TABLE hdma_b, t_zero, 1
    IND_TABLE hdma_c, s_zero, 2
    IND_TABLE hdma_d, t_zero, 3
    ; scroll: HOFS = centre - 128 (screen column 128 is the camera); VOFS puts floor line 0 at w = 64
    sep #$20
    lda #112
    sta.w hdma_scroll
    sta.w hdma_scroll+5
    stz.w hdma_scroll+10
    lda #24
    sta.w hdma_center
    sta.w hdma_center+10
    lda #88
    sta.w hdma_center+5
    sta.w hdma_center+15
    stz.w hdma_center+20
    rep #$20
    lda.w pend_cx
    sta.w hdma_center+6
    sec
    sbc #128
    sta.w hdma_scroll+1
    lda.w pend_cy
    sta.w hdma_center+8
    clc
    adc #40
    sta.w hdma_scroll+3
    lda.w pend_cx+2
    sta.w hdma_center+16
    sec
    sbc #128
    sta.w hdma_scroll+6
    lda.w pend_cy+2
    sta.w hdma_center+18
    sec
    sbc #72
    sta.w hdma_scroll+8
    lda #1020                   ; the sky tile's centre (main.c SKY_X, SKY_Y)
    sta.w hdma_center+1
    sta.w hdma_center+3
    sta.w hdma_center+11
    sta.w hdma_center+13
    sep #$20
    lda #0
    sta.l $00420C
    rep #$20
    HDMA_CH 2, $42, $1B, hdma_a, s_bank     ; M7A, indirect, write twice
    HDMA_CH 3, $42, $1C, hdma_b, t_bank     ; M7B
    HDMA_CH 4, $42, $1D, hdma_c, s_bank     ; M7C
    HDMA_CH 5, $42, $1E, hdma_d, t_bank     ; M7D
    HDMA_CH 6, $03, $0D, hdma_scroll, s_bank ; M7HOFS, M7VOFS (direct: the bank byte is unused)
    HDMA_CH 7, $03, $1F, hdma_center, s_bank ; M7X, M7Y
    sep #$20
    lda #$FC
    sta.l $00420C
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; void slipstream(void)
; Every other frame one kart (bit 1 of race_time picks it), so each kart every 4 frames: close behind the
; other kart (within SLIP_BOX px of the point 24 px ahead, from the slime drop's table drop_d), at SLIP_MIN
; or more, for SLIP_TICKS ticks in a row gives a boost of SLIP_FRAMES (main.c slip and boost_t).
slipstream:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda.w race_time
    lsr a
    bcc +
    jmp _sl_out             ; odd frames: neither kart
+   and #$0001
    sta.w sl_p
    ldy #0
    ldx #12
    lsr a
    bcc +
    ldy #12
    ldx #0
+   sty.w sl_k
    stx.w sl_o
    lda.w karts+6,y
    xba
    and #$007f
    asl a
    sta.w sl_i
    ; the other kart's x offset from the point ahead, in px: (other x - x) / 16 - drop_d[heading]
    lda.w karts,x
    sec
    sbc.w karts,y
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    ldx.w sl_i
    sec
    sbc.l drop_d,x
    clc
    adc #SLIP_BOX
    cmp #SLIP_SPAN
    bcs _sl_miss
    ; and its y offset: (other y - y) / 16 + drop_d[heading + 32]
    ldx.w sl_o
    lda.w karts+2,x
    sec
    sbc.w karts+2,y
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    sta.w sl_t
    lda.w sl_i
    clc
    adc #64
    and #$00fe
    tax
    lda.l drop_d,x
    clc
    adc.w sl_t
    clc
    adc #SLIP_BOX
    cmp #SLIP_SPAN
    bcs _sl_miss
    lda.w karts+4,y
    bmi _sl_miss
    cmp #SLIP_MIN
    bcc _sl_miss
    ldx.w sl_p
    sep #$20
    lda.w slip,x
    inc a
    cmp #SLIP_TICKS
    bcc +
    lda.w boost_t,x
    cmp #SLIP_FRAMES
    bcs ++
    lda #SLIP_FRAMES
    sta.w boost_t,x
++  lda #0
+   sta.w slip,x
    rep #$20
    bra _sl_out
_sl_miss:
    ldx.w sl_p
    sep #$20
    stz.w slip,x
    rep #$20
_sl_out:
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; u8 kart_timers(void)
; The plain countdowns of every kart, once a race frame (main.c kart_frame did them per kart): a spin
; and a trick turn the shown heading while they run, the wheelspin counts down, the shield counts down
; and the star counts down while keeping the boost at 2 or more. A computer kart's decision countdown (cpu_use_t)
; counts down too, and at 0 sets the kart's bit in cpu_due, which race_frame turns into its item decision. Returns in
; tcc__r0 a bit per kart whose shield ran out this frame (bit k for kart k), for the C to take the shield picture away.
kart_timers:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    LOAD_NK
    stz.w kt_mask
    lda #1
    sta.w kt_bit
    ldx #0
_kt_loop:
    sep #$20
    lda.w spin_t,x
    beq _kt_trick
    dec a
    sta.w spin_t,x
    beq _kt_spin0
    lda.w spin_off,x
    clc
    adc #SPIN_STEP
    and #127
    bra _kt_spin1
_kt_spin0:
    lda #0
_kt_spin1:
    sta.w spin_off,x
_kt_trick:
    lda.w trick_t,x
    beq _kt_wheel
    dec a
    sta.w trick_t,x
    beq _kt_trick0
    lda.w spin_off,x
    clc
    adc #SPIN_STEP
    and #127
    bra _kt_trick1
_kt_trick0:
    lda #0
_kt_trick1:
    sta.w spin_off,x
_kt_wheel:
    lda.w wheelspin_t,x
    beq _kt_shield
    dec a
    sta.w wheelspin_t,x
_kt_shield:
    rep #$20
    txa
    asl a
    tay
    lda.w shield_t,y
    beq _kt_star
    dec a
    sta.w shield_t,y
    bne _kt_star
    lda.w kt_mask
    ora.w kt_bit
    sta.w kt_mask
_kt_star:
    lda.w star_t,y
    beq _kt_next
    dec a
    sta.w star_t,y
    sep #$20
    lda.w boost_t,x
    cmp #2
    bcs _kt_next
    lda #2
    sta.w boost_t,x
_kt_next:
    sep #$20
    lda.w cpu_use_t,x       ; a computer kart's countdown to its item decision: at 0 its bit goes into cpu_due
    beq _kt_nx
    dec a
    sta.w cpu_use_t,x
    bne _kt_nx
    lda.w cpu_due
    ora.w kt_bit
    sta.w cpu_due
_kt_nx:
    rep #$20
    asl.w kt_bit
    inx
    cpx.w nk_n
    beq +
    jmp _kt_loop
+   lda.w kt_mask
    sta.l tcc__r0
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; u8 ground_all(void)
; What the floor does to each kart after it moved (main.c ground() did it per kart): a falling kart
; counts down to its rescue; a kart in the air counts down, rises and falls by t * (length - t) / 16
; (at most 40) and on landing gets the ramp trick's boost; otherwise it sits at its hop's height and
; the surface under it decides: a ramp over speed 2 lifts it for one frame per speed step (AIR_MIN
; to AIR_MAX), oil spins it (no coins lost), water or a pit starts its fall. Returns in tcc__r0 a bit
; per kart whose fall just ended, for the C to rescue (that moves it and costs coins). After php, phb
; and phd.
ground_all:
    php
    phb
    phd
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda #pj_base
    tcd
    lda.w cur_surf
    sta.b <ms_sp
    lda.w cur_surf+2
    sta.b <ms_sp+2
    LOAD_NK
    stz.w gr_mask
    lda #1
    sta.w gr_bit
    ldx #0
    ldy #0
_gr_loop:
    sep #$20
    lda.w fall_t,x
    beq _gr_nofall
    dec a
    sta.w fall_t,x
    beq +
    jmp _gr_next
+   rep #$20
    lda.w gr_mask
    ora.w gr_bit
    sta.w gr_mask
    jmp _gr_next
_gr_nofall:
    sep #$20                ; (tells the assembler: the code before this label left it in 16 bits)
    lda.w air_t,x
    beq _gr_floor
    dec a
    sta.w air_t,x
    bne _gr_lift
    lda.w trick,x           ; landed: the trick's boost
    beq _gr_notrick
    lda.w boost_t,x
    cmp #TRICK_FRAMES
    bcs _gr_notrick
    lda #TRICK_FRAMES
    sta.w boost_t,x
_gr_notrick:
    stz.w trick,x
    bra _gr_floor
_gr_lift:
    sta.w gr_t              ; t frames left: lift = t * (length - t) / 16
    sta.l $004202
    lda.w air_len,x
    sec
    sbc.w gr_t
    sta.l $004203
    nop                     ; the product is ready 8 cycles after the second factor
    nop
    nop
    nop
    rep #$20
    lda.l $004216
    lsr a
    lsr a
    lsr a
    lsr a
    cmp #41
    bcc +
    lda #40
+   sep #$20
    sta.w kart_lift,x
    jmp _gr_next
_gr_floor:
    lda.w hop_t,x           ; the hop's height (main.c hop_lift)
    bne _gr_hop
    stz.w kart_lift,x
    bra _gr_surf
_gr_hop:
    rep #$20
    and #$00ff
    phx
    tax
    sep #$20
    lda.l hop_lift,x
    plx
    sta.w kart_lift,x
_gr_surf:
    rep #$20
    lda.w karts,y           ; the surface under the kart (main.c surface_at)
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    sta.w gr_cb
    lda.w karts+2,y
    and #$3f80
    ora.w gr_cb
    phy
    tay
    lda [<ms_sp],y
    ply
    and #$00ff
    cmp #SURF_RAMP
    bne _gr_notramp
    lda.w karts+4,y
    bpl +
    jmp _gr_next
+   cmp #3                  ; speed over 2
    bcs +
    jmp _gr_next
+   cmp #AIR_MIN
    bcs +
    lda #AIR_MIN
+   cmp #AIR_MAX+1
    bcc +
    lda #AIR_MAX
+   sep #$20
    sta.w air_t,x
    sta.w air_len,x
    stz.w trick,x
    stz.w hop_t,x
    jmp _gr_next
_gr_notramp:
    rep #$20                ; the assembler thinks 8 bits here, the code that gets here is in 16
    cmp #SURF_OIL
    bne _gr_notoil
    sep #$20
    lda.w spin_t,x          ; oil spins the kart unless it spins already, or crawls out below OIL_SPEED (a kart that
    beq _gr_oilgo           ; spun to a halt on the patch would otherwise spin again each time its spin ended)
    jmp _gr_next
_gr_oilgo:
    rep #$20
    lda.w karts+4,y
    cmp #OIL_SPEED
    sep #$20
    bcs +
    jmp _gr_next
+   lda #SPIN_FRAMES
    sta.w spin_t,x
    stz.w boost_t,x
    stz.w drift,x
    stz.w charge,x
    stz.w hop_t,x
    jmp _gr_next
_gr_notoil:
    rep #$20
    cmp #SURF_FALL
    beq +
    jmp _gr_next
+   sep #$20
    lda #FALL_FRAMES
    sta.w fall_t,x
    stz.w spin_t,x
    stz.w spin_off,x
    stz.w boost_t,x
    stz.w drift,x
    stz.w charge,x
    stz.w hop_t,x
    stz.w kart_lift,x
    rep #$20
    lda #0
    sta.w karts+4,y
_gr_next:
    sep #$20
    lda.w shrink_t,x        ; a shrunk kart counts down (main.c used to, in a loop of its own)
    beq +
    dec a
    sta.w shrink_t,x
+   rep #$20
    asl.w gr_bit
    inx
    tya
    clc
    adc #12
    tay
    cpx.w nk_n
    beq +
    jmp _gr_loop
+   lda.w gr_mask
    pld
    sta.l tcc__r0
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; u8 floor_scan(void)
; Which karts drive over something: a bit per kart that is on the ground and whose 16x16 floor cell
; (main.c cell_of) holds a coin, a panel or slime (a computer kart that has finished is skipped). Returns it in tcc__r0; the C picks up what is there
; for those karts only, so the usual frame costs a few instructions a kart.
floor_scan:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    LOAD_NK
    stz.w fs_mask
    lda #1
    sta.w fs_bit
    ldx #0
    ldy #0
_fs_loop:
    sep #$20
    lda.w air_t,x
    ora.w fall_t,x
    bne _fs_next
    cpx #2
    bcc +
    lda.w finished,x        ; a computer kart that has finished takes nothing
    bne _fs_next
+
    rep #$20
    lda.w karts+2,y
    and #$ff00
    lsr a
    lsr a
    sta.w fs_c
    lda.w karts,y
    xba
    and #$00ff
    ora.w fs_c
    phy
    tay
    sep #$20
    lda.w cells,y
    ply
    cmp #0
    beq _fs_next
    rep #$20
    lda.w fs_mask
    ora.w fs_bit
    sta.w fs_mask
_fs_next:
    rep #$20
    asl.w fs_bit
    inx
    tya
    clc
    adc #12
    tay
    cpx.w nk_n
    bne _fs_loop
    lda.w fs_mask
    sta.l tcc__r0
    plb
    plp
    rtl

; Byte offset of kart k in karts (12 bytes each), and the bit of kart k, indexed by k * 2.
kart_off: .dw 0, 12, 24, 36, 48, 60, 72
kart_bit: .dw 1, 2, 4, 8, 16, 32

.MACRO ASR1                     ; A = A >> 1, keeping the sign
    cmp #$8000
    ror a
.ENDM

;---------------------------------------------------------------------------------
; u8 bump_all(void)
; Karts whose centres are closer than BUMP px on both axes touch (main.c bump did it for two): a pair is
; pushed apart along the axis it overlaps least on (the x axis on a tie), half the overlap each, and both
; lose a quarter of their speed; bumps counts each touch. A kart in the air or sinking out of sight touches
; none. Every pair is visited (kart i against each later kart j), later pairs see the pushed positions.
; Returns in tcc__r0 a bit per kart that a star kart touched, for the C to hit().
bump_all:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    LOAD_NK
    stz.w bm_mask
    lda.w nk_n
    cmp #4
    bcs +
    cmp #3
    bcs _bm_to3
    jmp _bm_n2
_bm_to3:
    jmp _bm_n3
+   beq _bm_to4
    cmp #6
    bcs _bm_to6
    jmp _bm_n5
_bm_to4:
    jmp _bm_n4
_bm_to6:
    jmp _bm_n6

; One pair test: kart i with kart j (j after i): close on both axes (under BUMP px, a little wide) goes to the slow
; path. The first axis is one subtraction and compare against kart i's position plus BUMP px (bm_xa, bm_ya).
.MACRO BM_PAIR
    lda.w bm_xa
    sec
    sbc.w karts+\2*12
    cmp #BUMP*32
    bcs +
    lda.w bm_ya
    sec
    sbc.w karts+\2*12+2
    cmp #BUMP*32
    bcs +
    lda #\1
    sta.w bm_i
    lda #\2
    sta.w bm_j
    ldy #\1*12
    ldx #\2*12
    jsr _bm_slow
    BM_LOAD \1
+
.ENDM

; Kart i's position plus BUMP px, kept for its pairs (a pair that pushes the karts apart reloads it).
.MACRO BM_LOAD
    lda.w karts+\1*12
    clc
    adc #BUMP*16
    sta.w bm_xa
    lda.w karts+\1*12+2
    clc
    adc #BUMP*16
    sta.w bm_ya
.ENDM

; The start of kart i's pairs: a kart in the air or sinking touches nothing, so its row is skipped (\2 is the label after it).
.MACRO BM_ROW
    sep #$20
    lda.w air_t+\1
    ora.w fall_t+\1
    rep #$20
    beq +
    jmp \2
+   BM_LOAD \1
.ENDM

_bm_n2:
    BM_ROW 0, _bm_r2_0
    BM_PAIR 0, 1
_bm_r2_0:
    jmp _bm_end

_bm_n3:
    BM_ROW 0, _bm_r3_0
    BM_PAIR 0, 1
    BM_PAIR 0, 2
_bm_r3_0:
    BM_ROW 1, _bm_r3_1
    BM_PAIR 1, 2
_bm_r3_1:
    jmp _bm_end

_bm_n4:
    BM_ROW 0, _bm_r4_0
    BM_PAIR 0, 1
    BM_PAIR 0, 2
    BM_PAIR 0, 3
_bm_r4_0:
    BM_ROW 1, _bm_r4_1
    BM_PAIR 1, 2
    BM_PAIR 1, 3
_bm_r4_1:
    BM_ROW 2, _bm_r4_2
    BM_PAIR 2, 3
_bm_r4_2:
    jmp _bm_end

_bm_n5:
    BM_ROW 0, _bm_r5_0
    BM_PAIR 0, 1
    BM_PAIR 0, 2
    BM_PAIR 0, 3
    BM_PAIR 0, 4
_bm_r5_0:
    BM_ROW 1, _bm_r5_1
    BM_PAIR 1, 2
    BM_PAIR 1, 3
    BM_PAIR 1, 4
_bm_r5_1:
    BM_ROW 2, _bm_r5_2
    BM_PAIR 2, 3
    BM_PAIR 2, 4
_bm_r5_2:
    BM_ROW 3, _bm_r5_3
    BM_PAIR 3, 4
_bm_r5_3:
    jmp _bm_end

_bm_n6:
    BM_ROW 0, _bm_r6_0
    BM_PAIR 0, 1
    BM_PAIR 0, 2
    BM_PAIR 0, 3
    BM_PAIR 0, 4
    BM_PAIR 0, 5
_bm_r6_0:
    BM_ROW 1, _bm_r6_1
    BM_PAIR 1, 2
    BM_PAIR 1, 3
    BM_PAIR 1, 4
    BM_PAIR 1, 5
_bm_r6_1:
    BM_ROW 2, _bm_r6_2
    BM_PAIR 2, 3
    BM_PAIR 2, 4
    BM_PAIR 2, 5
_bm_r6_2:
    BM_ROW 3, _bm_r6_3
    BM_PAIR 3, 4
    BM_PAIR 3, 5
_bm_r6_3:
    BM_ROW 4, _bm_r6_4
    BM_PAIR 4, 5
_bm_r6_4:
    jmp _bm_end

_bm_end:
    lda.w bm_mask
    sta.l tcc__r0
    plb
    plp
    rtl

_bm_slow:                   ; the pair is close: Y is kart i's offset in karts, X kart j's, bm_i and bm_j the numbers
    stx.w bm_jk             ; one in the air or sinking touches nothing
    ldx.w bm_j
    sep #$20
    lda.w air_t,x
    ora.w fall_t,x
    rep #$20
    beq +
    rts
+   ldx.w bm_jk
    lda.w karts,y
    sec
    sbc.w karts,x
    ASR1
    ASR1
    ASR1
    ASR1
    sta.w bm_dx
    bpl +
    eor #$ffff
    inc a
+   cmp #BUMP
    bcc +
    rts
+   sta.w bm_ax
    lda.w karts+2,y
    sec
    sbc.w karts+2,x
    ASR1
    ASR1
    ASR1
    ASR1
    sta.w bm_dy
    bpl +
    eor #$ffff
    inc a
+   cmp #BUMP
    bcc +
    rts
+   sta.w bm_ay
    lda.w bm_i              ; a computer kart that touches another kart steers round it
    cmp #2
    bcc _bm_swj
    sta.w bm_a
    lda.w bm_dx             ; the other kart's offset from it
    eor #$ffff
    inc a
    sta.w bm_rx
    lda.w bm_dy
    eor #$ffff
    inc a
    sta.w bm_ry
    lda.w bm_jk
    sta.w bm_o
    jsr _bm_swerve
_bm_swj:
    lda.w bm_j
    cmp #2
    bcc _bm_swe
    sta.w bm_a
    lda.w bm_dx
    sta.w bm_rx
    lda.w bm_dy
    sta.w bm_ry
    tya
    sta.w bm_o
    jsr _bm_swerve
_bm_swe:
    lda.w bm_ax
    cmp.w bm_ay
    bcc _bm_pushy
    lda #BUMP               ; x axis: push = (BUMP - |dx|) * 8, towards the side kart i is on
    sec
    sbc.w bm_ax
    asl a
    asl a
    asl a
    bit.w bm_dx
    bpl +
    eor #$ffff
    inc a
+   sta.w bm_t
    jsr _bm_share
    lda.w karts,y
    clc
    adc.w bm_ta
    sta.w karts,y
    lda.w karts,x
    sec
    sbc.w bm_tb
    sta.w karts,x
    bra _bm_speed
_bm_pushy:
    lda #BUMP
    sec
    sbc.w bm_ay
    asl a
    asl a
    asl a
    bit.w bm_dy
    bpl +
    eor #$ffff
    inc a
+   sta.w bm_t
    jsr _bm_share
    lda.w karts+2,y
    clc
    adc.w bm_ta
    sta.w karts+2,y
    lda.w karts+2,x
    sec
    sbc.w bm_tb
    sta.w karts+2,x
_bm_speed:
    lda.w karts+4,y         ; speed -= speed >> 2, both karts
    ASR1
    ASR1
    sta.w bm_t
    lda.w karts+4,y
    sec
    sbc.w bm_t
    sta.w karts+4,y
    lda.w karts+4,x
    ASR1
    ASR1
    sta.w bm_t
    lda.w karts+4,x
    sec
    sbc.w bm_t
    sta.w karts+4,x
    inc.w bumps
    lda.w bm_i              ; a star kart hits the kart it touches
    asl a
    tax
    lda.w star_t,x
    beq +
    lda.w bm_j
    asl a
    tax
    lda.l kart_bit,x
    ora.w bm_mask
    sta.w bm_mask
+   lda.w bm_j
    asl a
    tax
    lda.w star_t,x
    beq +
    lda.w bm_i
    asl a
    tax
    lda.l kart_bit,x
    ora.w bm_mask
    sta.w bm_mask
+   rts

; The push bm_t is split between the two karts (Y and X): half each, except that a kart standing still (speed under 3, as
; slow as a kart that cannot steer) is not shoved and the other kart takes all of it. Returns bm_ta for kart Y, bm_tb for kart X.
_bm_share:
    lda.w bm_t
    sta.w bm_ta
    sta.w bm_tb
    lda.w karts+4,y
    cmp #3
    bcs _bm_sh1
    lda.w karts+4,x
    cmp #3
    bcc _bm_sh2             ; both stand still: half each
    stz.w bm_ta             ; kart Y stands still: kart X takes it all
    lda.w bm_t
    asl a
    sta.w bm_tb
    rts
_bm_sh1:
    lda.w karts+4,x
    cmp #3
    bcs _bm_sh2
    stz.w bm_tb             ; kart X stands still: kart Y takes it all
    lda.w bm_t
    asl a
    sta.w bm_ta
_bm_sh2:
    rts

; Computer kart bm_a touched the kart at offset bm_o in karts, which lies (bm_rx, bm_ry) px from it: for AV_T frames it aims to
; one side of the steering map's heading (cpu_frame adds cf_sd to it). The side is the one with road: the surface 2 steps
; of its forward step (about 30 px) to the right of the other kart, and the same to its left; when both or neither are road, the
; side away from it (the sign of the cross product of the kart's forward step, two words of mk_tab at speed 15, with the
; offset). A kart that is already steering round keeps its side and only gets its time back.
_bm_swerve:
    phx
    phy
    phd
    lda.w bm_a
    asl a
    sta.w bm_t
    tax
    lda.w cf_av-4,x
    beq +
    jmp _bm_swt
+   lda.l kart_off,x
    tay
    lda.w karts+6,y
    and #$7f00
    lsr a
    ora #30
    tax
    lda.l mk_tab,x          ; the step along x
    sta.w bm_fx
    lda.w karts+6,y
    and #$7f00
    lsr a
    ora #30
    clc
    adc #$1000
    and #$3fff
    tax
    lda.l mk_tab,x          ; the step along y is its negative
    sta.w bm_ft
    lda #pj_base
    tcd
    lda.w cur_surf
    sta.b <ms_sp
    lda.w cur_surf+2
    sta.b <ms_sp+2
    ldx.w bm_o
    lda.w bm_ft             ; the right of the heading is (bm_ft, bm_fx)
    asl a
    clc
    adc.w karts,x
    pha
    lda.w bm_fx
    asl a
    clc
    adc.w karts+2,x
    sta.w dr_t
    pla
    jsr dr_surface
    ldy #0
    cmp #SURF_ROAD
    bne +
    ldy #1
+   sty.w bm_c
    ldx.w bm_o
    lda.w karts,x
    sec
    sbc.w bm_ft
    sec
    sbc.w bm_ft
    pha
    lda.w karts+2,x
    sec
    sbc.w bm_fx
    sec
    sbc.w bm_fx
    sta.w dr_t
    pla
    jsr dr_surface
    ldy #0
    cmp #SURF_ROAD
    bne +
    ldy #1
+   lda.w bm_c
    cpy.w bm_c
    beq _bm_swx             ; both or neither: away from the other kart
    cmp #0
    beq _bm_swl
    bra _bm_swr
_bm_swx:
    lda.w bm_fx
    sta.w bm_ma
    lda.w bm_ry
    sta.w bm_mb
    jsr _bm_mul
    sta.w bm_c
    lda.w bm_ft
    sta.w bm_ma
    lda.w bm_rx
    sta.w bm_mb
    jsr _bm_mul
    clc
    adc.w bm_c              ; above 0: the other kart is on its right
    bmi _bm_swr
    beq _bm_swr
_bm_swl:
    ldx.w bm_t
    lda #AV_L
    bra _bm_sws
_bm_swr:
    ldx.w bm_t
    lda #AV_R
_bm_sws:
    sta.w cf_sd-4,x
    xba                     ; and it turns that far at once, since a kart held up by the other kart is too slow to steer clear
    and #$ff00
    pha
    lda.l kart_off,x
    tay
    pla
    clc
    adc.w karts+6,y
    sta.w karts+6,y
_bm_swt:
    ldx.w bm_t
    lda #AV_T
    sta.w cf_av-4,x
    pld
    ply
    plx
    rts

; A = bm_ma * bm_mb, both signed and under 256 in size (the 8 x 8 multiplier at $4202).
_bm_mul:
    lda.w bm_ma
    eor.w bm_mb
    sta.w bm_ms
    lda.w bm_ma
    bpl +
    eor #$ffff
    inc a
+   and #$00ff
    sta.w bm_ma
    lda.w bm_mb
    bpl +
    eor #$ffff
    inc a
+   xba
    and #$ff00
    ora.w bm_ma
    sta.l $004202
    nop
    nop
    lda.w bm_ms
    lda.l $004216
    bit.w bm_ms
    bpl +
    eor #$ffff
    inc a
+   rts

;---------------------------------------------------------------------------------
; void keep_all(void)
; Every kart is held on the map (0 to 16383 on both axes); one that touched an edge keeps at most
; EDGE_SPEED, enough to steer away (main.c keep_on_map did it for one kart).
keep_all:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    LOAD_NK
    ldy #0
_kp_loop:
    ldx #0                  ; x set when the kart touched an edge
    lda.w karts,y
    bpl _kp_x1
    lda #0
    sta.w karts,y
    inx
    bra _kp_y
_kp_x1:
    cmp #16384
    bcc _kp_y
    lda #16383
    sta.w karts,y
    inx
_kp_y:
    lda.w karts+2,y
    bpl _kp_y1
    lda #0
    sta.w karts+2,y
    inx
    bra _kp_speed
_kp_y1:
    cmp #16384
    bcc _kp_speed
    lda #16383
    sta.w karts+2,y
    inx
_kp_speed:
    cpx #0
    beq _kp_next
    lda.w karts+4,y
    sec
    sbc #EDGE_SPEED+1
    bmi _kp_next
    lda #EDGE_SPEED
    sta.w karts+4,y
_kp_next:
    tya
    clc
    adc #12
    tay
    cpy.w nk_off
    bne _kp_loop
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; A = a * Y, both signed with |a| and |Y| at most 255, by the 8 x 8 multiplier (the result is ready 8
; cycles after the write, which the two nops cover).
smul:
    sta.w st_u
    tya
    eor.w st_u
    sta.w st_sgn            ; bit 15 is the sign of the product
    lda.w st_u
    bpl +
    eor #$ffff
    inc a
+   sta.w st_u
    tya
    bpl +
    eor #$ffff
    inc a
+   xba                     ; |Y| to the high byte, |a| in the low one
    ora.w st_u
    sta.l $004202
    nop
    nop
    lda.l $004216
    bit.w st_sgn
    bpl +
    eor #$ffff
    inc a
+   rts

;---------------------------------------------------------------------------------
; u8 steer_fast(void)
; One homing shot a frame (race_time & 3 picks it, so each every 4 frames) turns HOME_TURN of 128 steps
; towards the side the kart it chases is on: the sign of the cross product of its step and the vector to
; the kart (main.c steer_shot did it with two software multiplies). Returns in tcc__r0 0, or the shot's
; number plus 1 when its step does not match its heading (it bounced or turned at a corner), for
; main.c steer_slow() to put right.
steer_fast:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda #0
    sta.l tcc__r0
    lda.w race_time
    and #3
    sta.w st_i
    tax
    sep #$20
    lda.w shot_on,x
    bne +
    jmp _st_out
+   lda.w shot_home,x
    bne +
    jmp _st_out
+    lda.w shot_ang,x
    rep #$20
    and #$00ff
    asl a
    sta.w st_a2
    lda.w st_i
    asl a
    sta.w st_i2
    ldx.w st_i2
    ldy.w st_a2
    lda.w shot_dx,x         ; the step must be the one the heading gives
    cmp.w shot_step,y
    beq +
    jmp _st_slow
+
    tya
    clc
    adc #64
    and #$00fe
    tay
    lda.w shot_step,y
    eor #$ffff
    inc a
    cmp.w shot_dy,x
    beq +
    jmp _st_slow
+
_st_ok:
    ldx.w st_i
    sep #$20
    lda.w shot_home,x
    rep #$20
    and #$00ff
    dec a
    asl a
    tax
    lda.l kart_off,x
    tay                     ; y = the chased kart's offset in karts
    ldx.w st_i2
    lda.w karts,y           ; rx = (kart x - shot x) / 128, ry likewise (8 px steps: the product fits 16 bits)
    sec
    sbc.w shot_x,x
    ASR1
    ASR1
    ASR1
    ASR1
    ASR1
    ASR1
    ASR1
    sta.w st_rx
    lda.w karts+2,y
    sec
    sbc.w shot_y,x
    ASR1
    ASR1
    ASR1
    ASR1
    ASR1
    ASR1
    ASR1
    sta.w st_ry
    lda.w shot_dx,x
    ldy.w st_ry
    jsr smul
    sta.w st_c
    ldx.w st_i2
    lda.w shot_dy,x
    ldy.w st_rx
    jsr smul
    sta.w st_t
    lda.w st_c
    sec
    sbc.w st_t              ; dx * ry - dy * rx
    beq _st_minus
    bmi _st_minus
    lda #HOME_TURN
    bra _st_turn
_st_minus:
    lda #$10000-HOME_TURN
_st_turn:
    sta.w st_t
    ldx.w st_i
    lda.w shot_ang,x
    and #$00ff
    clc
    adc.w st_t
    and #$007f
    sta.w st_a2             ; the new heading
    sep #$20
    sta.w shot_ang,x
    rep #$20
    lda.w st_a2
    asl a
    tay
    ldx.w st_i2
    lda.w shot_step,y
    sta.w shot_dx,x
    tya
    clc
    adc #64
    and #$00fe
    tay
    lda.w shot_step,y
    eor #$ffff
    inc a
    sta.w shot_dy,x
    jmp _st_done
_st_slow:                   ; the step no longer fits the heading (a bounce or a corner turn): find the heading it fits
    lda.w st_a2
    jsr _st_heads
    bcc +
    jmp _st_ok
+   ldx.w st_i2
    lda.w shot_dx,x
    bne _st_dy
    lda.w shot_dy,x         ; no sideways step: straight up or down
    bmi +
    lda #128                ; heading 64 (down), doubled for the word tables
    jmp _st_set
+   lda #0
    jmp _st_set
_st_dy:
    lda.w shot_dy,x
    bne _st_try
    lda.w shot_dx,x         ; no step up or down: straight right or left
    bmi +
    lda #64
    jmp _st_set
+   lda #192
    jmp _st_set
_st_try:                    ; the mirror, the quarter turn back, or the quarter turn on: (128 - a), (64 - a), (a + 64) of 128
    lda #256
    sec
    sbc.w st_a2
    and #$00fe
    sta.w st_t
    jsr _st_heads
    bcc +
    lda.w st_t
    jmp _st_set
+   lda #128
    sec
    sbc.w st_a2
    and #$00fe
    sta.w st_t
    jsr _st_heads
    bcc +
    lda.w st_t
    jmp _st_set
+   lda.w st_a2
    clc
    adc #128
    and #$00fe
    sta.w st_t
    jsr _st_heads
    bcc +
    lda.w st_t
    jmp _st_set
+   sep #$20                ; it fits no heading: it flies straight
    ldx.w st_i
    lda #0
    sta.w shot_home,x
    rep #$20
    jmp _st_out
_st_set:                    ; A is the heading, doubled: it becomes the shot's heading, and the turn goes on from it
    sta.w st_a2
    lsr a
    sep #$20
    ldx.w st_i
    sta.w shot_ang,x
    rep #$20
    jmp _st_ok

; Does shot st_i2 / 2 step as heading A / 2 says? Carry set when both its steps match.
_st_heads:
    tay
    ldx.w st_i2
    lda.w shot_dx,x
    cmp.w shot_step,y
    bne _sh_no
    tya
    clc
    adc #64
    and #$00fe
    tay
    lda.w shot_step,y
    eor #$ffff
    inc a
    cmp.w shot_dy,x
    bne _sh_no
    sec
    rts
_sh_no:
    clc
    rts

_st_out:
    rep #$20
_st_done:
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; u8 rank_all(void)
; (every kart every frame in a two-player race; with computer karts one kart in four a frame: karts 0 and 4 on frames
; where race_time & 3 is 0, 1 and 5 on 1, kart 2 on 2, kart 3 on 3, so each is worked out every 4th frame; main.c sets rk_full
; to 1 for one call before the results are drawn, which works out every kart)
; Each kart's place from its lap progress: 1 plus the karts ahead of it (more progress, or equal progress
; and a lower number: on a tie player 1 is ahead). Writes place[] and returns in tcc__r0 a bit per kart
; whose place changed, for the C to redraw its HUD.
rank_all:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    LOAD_NK
    stz.w rk_mask
    lda #1                  ; two players: every kart every frame
    sta.w rk_s
    stz.w rk_i
    lda.w cpu_n             ; with computer karts one kart in four every frame: karts r, r + 4 on frame r
    and #$00ff
    beq _rk_i
    lda.w rk_full           ; unless the results are about to be drawn: every kart
    and #$00ff
    bne _rk_i
    lda #4
    sta.w rk_s
    lda.w race_time
    and #3
    sta.w rk_i
    cmp.w nk_n
    bcc _rk_i
    jmp _rk_out
_rk_i:
    ldx.w rk_i
    sep #$20
    lda.w finished,x
    rep #$20
    beq +
    jmp _rk_same            ; a finished kart keeps the place it finished in
+   txa
    asl a
    sta.w rk_y              ; the word index of kart i
    tay
    lda #1
    sta.w rk_r
    ldx #0
_rk_j:
    lda.w prog,x
    cmp.w prog,y
    bcc _rk_no              ; behind kart i
    bne _rk_yes             ; ahead of it
    cpx.w rk_y
    bcs _rk_no              ; level: only a lower number counts (and not kart i itself)
_rk_yes:
    inc.w rk_r
_rk_no:
    inx
    inx
    cpx.w nk_w
    bne _rk_j
    ldx.w rk_i
    lda.w rk_r
    sep #$20
    cmp.w place,x
    beq _rk_same
    sta.w place,x
    rep #$20
    ldx.w rk_y
    lda.l kart_bit,x
    ora.w rk_mask
    sta.w rk_mask
_rk_same:
    rep #$20
    lda.w rk_i
    clc
    adc.w rk_s
    sta.w rk_i
    cmp.w nk_n
    bcs +
    jmp _rk_i
+
_rk_out:
    lda.w rk_mask
    sta.l tcc__r0
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; u8 busy_flags(void)
; Which per-player jobs of the frame have anything to do, so the usual frame skips the C calls: bit p own_kart(p)
; (a hop, spin, wheelspin, flight, trick, fall, star or shrink, or the sprite shown last frame still to put back),
; bit 2 + p effects(p) (sparks, a flame, or the slots still showing one), bit 4 + p banner_step(p) (glyphs left to
; write). The C functions still decide what to draw; this only says when they cannot do anything.
.MACRO BF_PLAYER
    sep #$20
    lda.w own_was+\1
    ora.w spin_t+\1
    ora.w hop_t+\1
    ora.w wheelspin_t+\1
    ora.w air_t+\1
    ora.w trick_t+\1
    ora.w fall_t+\1
    ora.w shrink_t+\1
    rep #$20
    and #$00ff
    ora.w star_t+\1*2
    beq +
    lda.w bf_r
    ora #1<<\1
    sta.w bf_r
+   sep #$20
    lda.w fx_was+\1
    ora.w boost_t+\1
    bne ++
    lda.w drift+\1
    beq +++
    lda.w charge+\1
    cmp #DRIFT_CHARGE
    bcc +++
++  rep #$20
    lda.w bf_r
    ora #4<<\1
    sta.w bf_r
+++ rep #$20
    sep #$20
    lda.w banner_left+\1
    rep #$20
    and #$00ff
    beq +
    lda.w bf_r
    ora #16<<\1
    sta.w bf_r
+
.ENDM

busy_flags:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    stz.w bf_r
    BF_PLAYER 0
    BF_PLAYER 1
    lda.w bf_r
    sta.l tcc__r0
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; void banner_step(u8 p)
; "FINISH" between two flags, or "FINAL LAP" in green: writes the next 2 glyph sprites of half p's banner (banner_left
; says how many of the 8 are still to write, banner_kind which words), 2 a frame because a whole banner at once costs
; as much as the rest of the frame's logic. After php and phb: p at 6,s. Glyph numbers as main.c G_*: F 18, I 19, N 16,
; S 14, H 20, flag 21, A 12, L 11, P 13.
; Each glyph of each banner as 4 OAM bytes: x, the line in half 0 (40), tile (low byte), attributes (palette, tile bit 8).
.MACRO BN_GLYPH                 ; \1 x, \2 tile, \3 palette
    .db \1, 40, <\2, ((\3<<1)|$30|(>\2&1))
.ENDM
bn_gl:    BN_GLYPH 92, GLYPH_18, PAL_YELLOW
          BN_GLYPH 104, GLYPH_19, PAL_YELLOW
          BN_GLYPH 116, GLYPH_16, PAL_YELLOW
          BN_GLYPH 128, GLYPH_19, PAL_YELLOW
          BN_GLYPH 140, GLYPH_14, PAL_YELLOW
          BN_GLYPH 152, GLYPH_20, PAL_YELLOW
          BN_GLYPH 70, GLYPH_21, PAL_YELLOW
          BN_GLYPH 170, GLYPH_21, PAL_YELLOW
          BN_GLYPH 74, GLYPH_18, PAL_GREEN
          BN_GLYPH 86, GLYPH_19, PAL_GREEN
          BN_GLYPH 98, GLYPH_16, PAL_GREEN
          BN_GLYPH 110, GLYPH_12, PAL_GREEN
          BN_GLYPH 122, GLYPH_11, PAL_GREEN
          BN_GLYPH 146, GLYPH_11, PAL_GREEN
          BN_GLYPH 158, GLYPH_12, PAL_GREEN
          BN_GLYPH 170, GLYPH_13, PAL_GREEN
bn_keep:  .db $FC, $F3, $CF, $3F    ; the high table's bits of a sprite: x bit 8 and the size, cleared

banner_step:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda 6,s
    and #$00ff
    sta.w bn_p
    lda #2
    sta.w bn_n
_bn_loop:
    ldx.w bn_p
    sep #$20
    lda.w banner_left,x
    bne +
    jmp _bn_out
+   dec a
    sta.w banner_left,x
    rep #$20
    and #$00ff
    sta.w bn_t
    sep #$20
    lda.w banner_kind,x
    rep #$20
    and #$00ff
    asl a
    asl a
    asl a
    sta.w bn_k              ; the kind's row: 8 glyphs
    lda #7                  ; the glyph written now: 8 - the number left before this one = 7 - the number left after it
    sec
    sbc.w bn_t
    sta.w bn_i
    lda.w bn_p              ; slot 24 + 8 p + i
    asl a
    asl a
    asl a
    clc
    adc #24
    clc
    adc.w bn_i
    sta.w bn_s
    asl a
    asl a
    tay                     ; the sprite's offset in oamMemory
    lda.w bn_k
    clc
    adc.w bn_i
    asl a
    asl a
    tax                     ; the glyph's 4 bytes
    lda.l bn_gl,x           ; x and line (half 0)
    ldx.w bn_p
    beq +
    clc
    adc #112*256            ; half 1: 112 lines further down
+   sta.w oamMemory,y
    lda.w bn_k
    clc
    adc.w bn_i
    asl a
    asl a
    tax
    lda.l bn_gl+2,x         ; tile and attributes
    sta.w oamMemory+2,y
    lda.w bn_s              ; the high table: this sprite's bits cleared (small, x under 256)
    lsr a
    lsr a
    tay
    lda.w bn_s
    and #$0003
    tax
    sep #$20
    lda.l bn_keep,x
    and.w oamMemory+512,y
    sta.w oamMemory+512,y
    rep #$20
    dec.w bn_n
    beq _bn_out
    jmp _bn_loop
_bn_out:
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; u8 lap_next(u8 p)
; Kart p reached checkpoint 0 (main.c lap_done): its lap count goes up. Past LAPS it finishes: it takes the next place,
; the first player to finish starts the 10 s to the results (a computer kart's finish starts nothing), the race ends 1.5 s
; after both players have finished, `winner` is the first player to finish, and a player's banner is set to be written (a computer kart has none). Then prog follows
; the lap. Returns 1 in tcc__r0 when the kart finished, 0 when it is still racing (the C draws the lap counter then).
; After php and phb: p at 6,s.
lap_next:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda 6,s
    and #$00ff
    tax                     ; X = the kart
    sep #$20
    lda.w lap,x
    inc a
    sta.w lap,x
    rep #$20
    and #$00ff
    cmp #LAPS+1
    bcs _ln_fin
    stz.w ln_r
    jmp _ln_prog
_ln_fin:
    lda #1
    sta.w ln_r
    sep #$20
    lda #1
    sta.w finished,x
    rep #$20
    txa
    asl a
    tay
    lda.w race_time
    sta.w finish_time,y
    rep #$20
    cpx #2
    bcs _ln_cont            ; a computer kart finishes without starting the 10 s
    txa
    eor #1
    tay
    sep #$20
    lda.w finished,y
    rep #$20
    bne _ln_cont
    lda #AFTER_FIRST        ; the first player home starts the 10 s, and wins
    sta.w end_timer
    txa
    sep #$20
    sta.w winner
_ln_cont:
    sep #$20
    inc.w done_count
    lda.w done_count
    sta.w place,x
    lda.w finished
    beq _ln_noend
    lda.w finished+1
    beq _ln_noend
    rep #$20
    lda.w end_timer
    cmp #AFTER_BOTH+1
    bcc _ln_n2
    lda #AFTER_BOTH
    sta.w end_timer
_ln_n2:
    sep #$20
_ln_noend:
    rep #$20
    cpx #2
    bcs _ln_prog
    txa                     ; a player: its banner slots, hidden (GO may still show), then the finish banner to write
    asl a
    asl a
    asl a
    clc
    adc #24
    asl a
    asl a
    tay
    sep #$20
    lda #224
    sta.w oamMemory+1,y
    sta.w oamMemory+5,y
    lda #0
    sta.w banner_kind,x
    sta.w banner_t,x
    lda #8
    sta.w banner_left,x
    rep #$20
_ln_prog:
    rep #$20
    lda.w lap,x             ; prog = ((lap * 32 + cp) * 8) + frac
    and #$00ff
    asl a
    asl a
    asl a
    asl a
    asl a
    sta.w ln_t
    lda.w cp,x
    and #$00ff
    clc
    adc.w ln_t
    asl a
    asl a
    asl a
    sta.w ln_t
    lda.w frac,x
    and #$00ff
    clc
    adc.w ln_t
    sta.w ln_t
    txa
    asl a
    tay
    lda.w ln_t
    sta.w prog,y
    lda.w ln_r
    sta.l tcc__r0
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; void clock_step(void)
; The start of every frame of a race or countdown (main.c race_frame): the random number steps (a 16-bit shift register
; with taps $B400), and when the countdown is over the race clock counts, the 2-sprite GO banner goes when its time is
; up (unless the player finished, whose banner is then the finish banner), and each player's final-lap banner goes
; after banner_t frames.
clock_step:
    php
    phb
    sep #$20
    lda #$7e
    pha
    plb
    rep #$30
    lda.w rng
    lsr a
    bcc +
    eor #$B400
+   sta.w rng
    sep #$20
    lda.w game_state
    cmp #ST_COUNTDOWN
    rep #$20
    bne +
    jmp _cs_out
+   lda.w race_time
    cmp #$ffff
    beq +
    inc a
    sta.w race_time
+   lda.w timer
    beq _cs_banner
    dec a
    sta.w timer
    bne _cs_banner
    ldx #0                  ; GO has been up long enough: hide its two sprites in a half whose banner is not in use
_cs_go:
    sep #$20
    lda.w finished,x
    ora.w banner_t,x
    rep #$20
    bne +
    txa
    asl a
    asl a
    asl a
    clc
    adc #24
    asl a
    asl a
    tay
    sep #$20
    lda #224
    sta.w oamMemory+1,y
    sta.w oamMemory+5,y
    rep #$20
+   inx
    cpx #2
    bcc _cs_go
_cs_banner:
    stz.w cs_p
_cs_b:
    ldx.w cs_p
    sep #$20
    lda.w banner_t,x
    beq _cs_bn
    dec a
    sta.w banner_t,x
    bne _cs_bn
    rep #$20                ; the final-lap banner's 8 glyphs go
    txa
    asl a
    asl a
    asl a
    clc
    adc #24
    asl a
    asl a
    tay
    ldx #8
    sep #$20
    lda #224
_cs_h:
    sta.w oamMemory+1,y
    iny
    iny
    iny
    iny
    dex
    bne _cs_h
_cs_bn:
    rep #$20
    inc.w cs_p
    lda.w cs_p
    cmp #2
    bcc _cs_b
_cs_out:
    plb
    plp
    rtl

;---------------------------------------------------------------------------------
; u16 frame_lines(void)
; The lines of the frame used so far in tcc__r0, counted as main.c measure() does: the screen line less 225, or plus 37 in
; the lines before it. A computer kart's item decision runs only when this is small enough.
frame_lines:
    php
    sep #$20
    lda.l $00213F           ; resets the counter read order
    lda.l $002137           ; latches the counters
    lda.l $00213D           ; vertical counter, low byte
    xba
    lda.l $00213D           ; then its ninth bit
    and #$01
    xba
    rep #$30
    cmp #225
    bcc +
    sec
    sbc #225
    bra ++
+   clc
    adc #37
++  sta.l tcc__r0
    plp
    rtl

;---------------------------------------------------------------------------------
; void probe(void)
; Stores the line counter (0-261, 9 bits) in the next word of phase_line[], so tools/test_rom.py can show
; what each phase of the busiest frame cost (main.c measure copies the table). Long addresses, no data
; bank change; about 50 cycles a call, 0.2 line.
probe:
    php
    sep #$20
    lda.l $00213F           ; resets the counter read order
    lda.l $002137           ; latches the counters
    lda.l $00213D           ; vertical counter, low byte
    xba
    lda.l $00213D           ; then its ninth bit
    and #$01
    xba
    rep #$30
    pha
    lda.l pv_n
    tax
    inc a
    inc a
    sta.l pv_n
    pla
    sta.l phase_line,x
    plp
    rtl

.ENDS
