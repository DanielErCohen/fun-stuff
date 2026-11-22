"""Breaks each rule once, in its own copy of the repo, and reports whether the ROM tests catch it.

Every rule the tests guard should make them fail when broken; a rule whose break still passes is
untested. Each entry is (rule, file, text to find, text to put instead); the text must occur once. A rule
guarded in two places gives lists of texts for both (every one must occur once and is replaced).
Usage: python3 tools/break_rules.py [N ...]   (no numbers: every rule; 4 run at once; each rule builds and tests its own copy, so a full run is slow)
Copies go to a temporary folder that is removed afterwards; the repo itself is never touched."""
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys

import tempfile

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="break_rules_")

C, A, T = "game/main.c", "game/proj.asm", "tools/tracks.py"
M = [
    ('coin leaves the map', C, '        cells[c] = 0;\n        queue_cell(c, floor_set[FLOOR_ROAD]);\n        if (coins[p] < (battle == 2 ? BATTLE_COINS : MAX_COINS))', '        cells[c] = 0;\n        if (coins[p] < (battle == 2 ? BATTLE_COINS : MAX_COINS))'),
    ('coin taken once', C, '        cells[c] = 0;\n        queue_cell(c, floor_set[FLOOR_ROAD]);\n        if (coins[p] < (battle == 2 ? BATTLE_COINS : MAX_COINS))', '        queue_cell(c, floor_set[FLOOR_ROAD]);\n        if (coins[p] < (battle == 2 ? BATTLE_COINS : MAX_COINS))'),
    ('coins raise top speed', A, '+   lsr a\n    sta.w dr_cb', '+   lda #0\n    sta.w dr_cb'),
    ("coin counter in the HUD", C, "        glyph_at(s, COIN_X + 14, y, coins[p], PAL_YELLOW);", "        glyph_at(s, COIN_X + 14, y, coins[p] + 1, PAL_YELLOW);"),
    ("panel comes back", C, "    cells[panel_cell[i]] = CELL_PANEL;\n", ""),
    ("panel leaves the map", C, "        cells[c] = 0;\n        queue_cell(c, floor_set[FLOOR_ROAD]);\n        for (i = 0;", "        cells[c] = 0;\n        for (i = 0;"),
    ("better odds behind", C, "odds[(place[p] == 1 ? 0 : (place[p] == 2 ? 16 : 32)) + last_roll[p]]", "odds[last_roll[p]]"),
    ("panel gives the item", C, "    if (!--roll[p])\n    {\n        item[p] = roll_item[p];", "    if (!--roll[p])\n    {\n        item[p] = 0;"),
    ("item picture spins", C, "    else if (!(roll[p] & 3))\n        hud_item(p, ((roll[p] >> 2) & 3) + 1);", ""),
    ("item picture shows the item", C, "        hud_pic[p] = it;", "        hud_pic[p] = 1;"),
    ("boost lifts the cap", A, '.DEFINE BOOST_EXTRA 16', '.DEFINE BOOST_EXTRA 0'),
    ("boost works on grass", A, '    adc #BOOST_EXTRA\n    sta.w dr_top\n    sta.w karts+4,y', '    adc #BOOST_EXTRA\n    sta.w dr_top\n    sta.w karts+4,y\n    lda.w dr_road\n    bne +\n    lda #MAX_GRASS\n    sta.w dr_top\n    sta.w karts+4,y\n+'),
    ("boost lasts its time", C, "#define BOOST_FRAMES 120", "#define BOOST_FRAMES 60"),
    ("boost flame inside the half", C, "        spr(FX_SLOT(p), 100, y, odd", "        spr(FX_SLOT(p), 100, y + 6, odd"),
    ('shot travels', C, '    shot_dx[i] = shot_step[idx];', '    shot_dx[i] = shot_step[idx] / 16;'),
    ("shot bounces", A, "    lda.b <ms_road\n    beq _ms_yok", "    bra _ms_yok"),
    ('shot spins the kart it hits', C, "                    if (!air_t[p])\n                        if (!fall_t[p])\n                            hit(p);", "                    if (0)\n                        if (!fall_t[p])\n                            hit(p);"),
    ("hit drops coins", C, "#define COIN_LOSS 2", "#define COIN_LOSS 0"),
    ("slime is painted", C, "    queue_cell(c, floor_set[set]);\n    return 1;", "    return 1;"),
    ('slime stays', C, '    i = race_time & 3;\n    if (!panel_wait[i]', '    i = race_time & 3;\n    if (peel_on[0] && race_time > 600)\n        remove_peel(peel_cell[0]);\n    if (!panel_wait[i]'),
    ("slime spins the kart", C, "        remove_peel(c);\n        hit(p);", "        remove_peel(c);"),
    ("rocket start rewards", C, "#define ROCKET_WINDOW 20", "#define ROCKET_WINDOW 5"),
    ("early pedal spins the wheels", C, "    else\n        wheelspin_t[p] = WHEELSPIN;", ""),
    ("boost pad boosts", A, '    cmp #SURF_PAD\n    bne +', '    cmp #4\n    bne +'),
    ("drift boost fires", C, "        if (charge[p] >= DRIFT_CHARGE && boost_t[p] < DRIFT_FRAMES)\n            boost_t[p] = DRIFT_FRAMES;", ""),
    ("drift needs charge", C, "#define DRIFT_CHARGE 40", "#define DRIFT_CHARGE 4"),
    ("drift sparks", C, "        spr(FX_SLOT(p), 102, y + 2, odd ? TILE_SPARK1 : TILE_SPARK0, PAL_ITEMS, 0, 0);\n        spr(FX_SLOT(p) + 1, 138, y + 2, odd ? TILE_SPARK0 : TILE_SPARK1, PAL_ITEMS, 0, 0);",
     "        hide_range(FX_SLOT(p), 2);"),
    ("hop lifts the kart", C, "const u8 hop_lift[HOP_FRAMES + 1] = {0, 1, 3, 5, 6, 6, 5, 3, 1};", "const u8 hop_lift[HOP_FRAMES + 1] = {0, 0, 0, 0, 0, 0, 0, 0, 0};"),
    ("spin turns through the views", A, ".DEFINE SPIN_STEP 8", ".DEFINE SPIN_STEP 0"),
    ("spin lasts about a second", C, "#define SPIN_FRAMES 64", "#define SPIN_FRAMES 16"),
    ("projection costs at most 5 lines", A, "_project:\n", "_project:\n.REPT 200\n    nop\n.ENDR\n"),
    ("rematch puts coins back", C, "    for (i = 0; i < 4096; i++)\n        cells[i] = cur_cells[i];", ""),
    ("rematch redraws the floor", C, "    dmaCopyVram7(cur_map, 0, 0x4000, VRAM_INCLOW | VRAM_ADRSTINC_1, 0x1800);", ""),
    ("refused pick flashes", C, "                refuse_t[p] = REFUSE_FRAMES;", "                refuse_t[p] = 0;"),
    ("Y undoes a pick", C, "        if (locked[p] && (padsDown(p) & KEY_Y))", "        if (locked[p] && (padsDown(p) & KEY_SELECT))"),
    ("same-frame tie goes to player 1", C, "    for (p = 0; p < 2; p++)\n    {\n        if (locked[p])\n            continue;",
     "    for (p = 1; p < 2; p--)\n    {\n        if (locked[p])\n            continue;"),
]

M2 = [
    ("rocket window ends at 20", C, "#define ROCKET_WINDOW 20", "#define ROCKET_WINDOW 100"),
    ("a hit ends the boost", C, "    spin_t[p] = SPIN_FRAMES;\n    boost_t[p] = 0;", "    spin_t[p] = SPIN_FRAMES;"),
    ('no panel while holding an item', C, '        if (item[p])\n            return;\n        if (roll[p])', '        if (roll[p])'),
    ("fifth slime removes the oldest", C, "    if (peel_on[i])\n        remove_peel(peel_cell[i]);", ""),
    ("no item while spinning", C, "item[p] && !spin_t[p] && !fall_t[p])", "item[p] && !fall_t[p])"),
    ("shot bounces across x", A, "    lda.b <ms_road\n    beq _ms_xok", "    bra _ms_xok"),
    ("slime not on an occupied cell", C, "    if (cells[c])\n        return 0;\n    addr = ", "    addr = "),
    ('coin cap', C, '        if (coins[p] < (battle == 2 ? BATTLE_COINS : MAX_COINS))\n        {\n            coins[p]++;', '        if (1)\n        {\n            coins[p]++;'),
    ("drift steering into the turn", A, '    lda.w dr_turn           ; steered into the drift\n    lsr a\n    clc\n    adc.w dr_turn\n    sta.w dr_turn', '    lda.w dr_turn           ; steered into the drift'),
    ("drift steering out of the turn", A, '    lsr.w dr_turn           ; steered out of it', '    nop'),
    ("player 2 sees player 1 large", A, "          .db $80, $00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0", "          .db $00, $00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0"),
    ("shot from the map edge stays on the map", C, "    if (shot_x[i] < 0)\n        shot_x[i] = 0;", ""),
    ("own kart frame ends above the half", "tools/gen_assets.py", "        near[31] = [0] * 32", "        pass"),
    ("shot turns with the road at a corner", A, "    jsr ms_turn_x\n    bcs _ms_tx", "    clc\n    bcs _ms_tx"),
    ("boost flames beside the kart", C, "        spr(FX_SLOT(p), 100, y, odd", "        spr(FX_SLOT(p), 120, y, odd"),
    ("spin shows to the other player", A, "    clc\n    adc.w spin_off,y", "    clc\n    adc #0"),
]
M += M2

T, G = "tools/tracks.py", "tools/gen_assets.py"
M4 = [  # tracks, their features and the cup
    ("a checkpoint counts only after the one before", A, '    lda.w cp,x\n    inc a\n    and #NCP-1\n    cmp.w pg_c\n    bne _pg_frac', '    lda.w pg_c\n    cmp.w cp,x\n    beq _pg_frac\n    lda.w pg_c'),
    ("off the track nothing counts", A, '    cmp #OFF_TRACK\n    bne +', '    cmp #OFF_TRACK\n    bra +'),
    ("laps count through the shortcut", T, "        best = np.where(use, sc_fine[np.maximum(sn, 0)], best)", "        pass"),
    ("final-lap banner shows", C, '    if (lap[p] == LAPS && p < 2)\n        final_lap(p);', ''),
    ("final-lap banner goes", A, "    sta.w banner_t,x\n    bne _cs_bn", "    sta.w banner_t,x\n    bra _cs_bn"),
    ("final-lap banner shows once", C, '    if (lap[p] == LAPS && p < 2)\n        final_lap(p);', '    if (lap[p] >= LAPS - 1)\n        final_lap(p);'),
    ("wrong-way sign shows", A, '    cmp #WRONG_STEPS\n    bcc +', '    cmp #WRONG_STEPS\n    bra +'),
    ("wrong-way sign goes", A, '    lda #0\n    sta.w wrong,x\n_pg_cp:', '_pg_cp:'),
    ("ramp lifts longer at speed", A, "+   cmp #AIR_MIN\n    bcs +", "+   lda #30\n    cmp #AIR_MIN\n    bcs +"),
    ("ramp lifts the kart", A, "    lsr a\n    lsr a\n    lsr a\n    lsr a\n    cmp #41", "    lda #0\n    cmp #41"),
    ("speed kept in the air", A, '    beq +\n    jmp _dr_turn            ; in the air the kart keeps its speed', '    bra +\n    jmp _dr_turn            ; in the air the kart keeps its speed'),
    ("ramp trick boosts", A, "    lda #TRICK_FRAMES\n    sta.w boost_t,x\n_gr_notrick:", "_gr_notrick:"),
    ("ramp trick needs L or R", C, ["        if ((down & (KEY_L | KEY_R)) && !trick[p])", "    if (down & (KEY_L | KEY_R))\n        busy = 1;"], ["        if (!trick[p])", "    busy = 1;"]),  # two guards: tricks() checks the buttons itself, and kart_frame() calls it only when one is down
    ("oil spins", A, "+   lda #SPIN_FRAMES\n    sta.w spin_t,x", "+   lda #0\n    sta.w spin_t,x"),
    ("oil costs no coins", A, "    stz.w hop_t,x\n    jmp _gr_next\n_gr_notoil:", "    stz.w hop_t,x\n    stz.w coins,x\n    jmp _gr_next\n_gr_notoil:"),
    ("sand slows", A, '    cmp #SURF_SAND\n    bne ++', '    cmp #SURF_SAND\n    bra ++'),
    ("water and pits swallow karts", A, "    cmp #SURF_FALL\n    beq +\n    jmp _gr_next", "    cmp #SURF_FALL\n    jmp _gr_next"),
    ("rescue to the last checkpoint", C, "    r = &trk_rescue[(track_no * NCP + cp[p]) * 3];", "    r = &trk_rescue[(track_no * NCP + ((cp[p] + 1) & (NCP - 1))) * 3];"),
    ("rescue costs coins", C, "    coins[p] = coins[p] > COIN_LOSS ? coins[p] - COIN_LOSS : 0;\n    hud_coins(p);\n    rescues[p]++;", "    rescues[p]++;"),
    ("a falling kart sinks from view", C, "        else\n            hide(p);\n        return;", "        else\n            spr(p, 120, p * HALF + KART_LINE - 10, FAR_FRAME(p, 0), p, 0, 0);\n        return;"),
    ("obstacle spins the kart", C, "                    if (!air_t[p] && !fall_t[p])\n                        hit(p);\n                }", "                }"),
    ("obstacle rolls back", A, "    inc a\n    cmp.w ob_len,y\n    bcc +", "    inc a\n    bra +"),
    ("obstacle is drawn", A, "_obst:\n    sbc #10                 ; carry is set\n", "_obst:\n    jmp _hide\n"),
    ("minimap dots where the karts are", A, "    lsr a                       ; x / 16 / 32: map pixels on the minimap\n    clc\n    adc #MINI_X-7", "    lsr a                       ; x / 16 / 32: map pixels on the minimap\n    clc\n    adc #MINI_X"),
    ("minimap is the track's", C, "        dmaCopyVram(trk_mini[t] + (i << 7), 0x6000 + ((TILE_MINIMAP + (i << 4)) << 4), 128);", ""),
    ("track tiles load", C, "    dmaCopyVram7(trk_tiles[t], 0, trk_tiles_size[t], VRAM_INCHIGH | VRAM_ADRSTINC_1, 0x1900);", ""),
    ('the menu picks the track', C, '        track_no = cup_on ? 0 : (battle ? ARENA : menu_pos - 1);', '        track_no = cup_on ? 0 : (battle ? ARENA : 0);'),
    ('menu cursor wraps', C, '            menu_pos = menu_pos ? menu_pos - 1 : MENU_LAST;', '            menu_pos = menu_pos ? menu_pos - 1 : 0;'),
    ("the cup goes on to the next track", C, "                track_no = ++cup_race;", "                ++cup_race;"),
    ("points for first", C, "{3, 1, 0, 0, 0, 9, 6, 4, 3, 2, 1}", "{2, 1, 0, 0, 0, 9, 6, 4, 3, 2, 1}"),
    ("second scores only when it finishes", C, "            if (finished[1 - winner])\n                points[1 - winner] += cup_points[1];",
     "            points[1 - winner] += cup_points[1];"),
    ("a tied cup goes to the last race's winner", C, "key = ((u16)points[k] << 3) + 8 - place[k];", "key = ((u16)points[k] << 3) + 8 - k;"),
    ("podium after the fourth race", C, "        if (cup_on && cup_race == CUP_RACES - 1)\n            show_podium();", "        if (0)\n            show_podium();"),
    ("the other kart in the air is drawn higher", A, "    lda.w kart_lift,y\n    and #$00ff\n    beq _nolift", "    lda.w kart_lift,y\n    and #$0000\n    beq _nolift"),
    ("karts start facing along the road", T, '        "angle": heading(sdx, sdy),', '        "angle": heading(odx, ody) if obstacles else heading(sdx, sdy),'),
    ("the other half does not draw a falling kart", A, "    lda.w fall_t,y\n    and #$00ff\n    beq +\n    jmp _hide", "    lda.w fall_t,y\n    and #$0000\n    beq +\n    jmp _hide"),
    ("rescue before the ramp", T, "                sr = (s0 - RUNUP) % L", "                pass"),
    ("shots bounce off this track's edges", A, "    sta.b <ms_sp+2\n    ldx #0\n_ms_loop:", "    sta.b <ms_sp+2\n    lda.b <ms_sp\n    clc\n    adc #$4000\n    sta.b <ms_sp\n    ldx #0\n_ms_loop:"),
]
M += M4

M5 = [  # battles
    ("a hit pops a balloon", C, "    hits[p]++;\n    pop(p);", "    hits[p]++;"),
    ("a fall pops a balloon", C, "    rescues[p]++;\n    pop(p);", "    rescues[p]++;"),
    ("no balloons left loses", C, "    if (!balloons[p])\n        battle_over(1 - p);", ""),
    ("balloons start at 3", C, "#define BALLOONS 3", "#define BALLOONS 2"),
    ("balloons show over the own kart", C, "        if (balloons[h] && !fall_t[h])", "        if (0)"),
    ("the other kart's balloons show", C, "        spr(BAL_SLOT(h) + 1, x, y - 12, bal_tile(1 - h, balloons[1 - h]), PAL_MINI, 0, 0);", "        hide(BAL_SLOT(h) + 1);"),
    ("no lap letters in a battle", C, "    if (!battle)\n    {\n        glyph_at(s, 8, y, G_L, PAL_WHITE);", "    if (1)\n    {\n        glyph_at(s, 8, y, G_L, PAL_WHITE);"),
    ("the most coins win", C, "battle_over(coins[0] > coins[1] ? 0 : (coins[1] > coins[0] ? 1 : lead_p));", "battle_over(lead_p);"),
    ("a coin tie goes to the lead", C, "(coins[1] > coins[0] ? 1 : lead_p));", "(coins[1] > coins[0] ? 1 : 0));"),
    ("the lead needs more coins", C, "    if (coins[p] > coins[1 - p])\n        lead_p = p;", "    if (coins[p] >= coins[1 - p])\n        lead_p = p;"),
    ("coins count past 10 in a coin battle", C, "        if (coins[p] < (battle == 2 ? BATTLE_COINS : MAX_COINS))", "        if (coins[p] < MAX_COINS)"),
    ("coin speed counts only to 10", A, "    cmp #11\n    bcc +\n    lda #10\n+   lsr a\n    sta.w dr_cb", "    lsr a\n    sta.w dr_cb"),
    ("taken coins come back", C, "            cells[c] = CELL_COIN;\n            queue_cell(c, floor_set[FLOOR_COIN]);\n            return;", "            return;"),
    ("the coin clock runs", C, "        hud_clock();\n    }", "    }"),
    ("the menu picks a battle", C, "        battle = menu_pos == 5 ? 1 : (menu_pos == 6 ? 2 : 0);", "        battle = menu_pos == 5 ? 1 : 0;"),
    ("hits pop balloons only in a balloon battle", C, "    if (battle != 1) // separate ifs", "    if (0) // separate ifs"),
]
M += M5

M6 = [  # the second item set
    ("a homing shot steers", A, "    lda #HOME_TURN\n    bra _st_turn", "    lda #0\n    bra _st_turn"),
    ("a homing shot turns towards the kart", A, "    beq _st_minus\n    bmi _st_minus\n    lda #HOME_TURN", "    beq _st_minus\n    bpl _st_minus\n    lda #HOME_TURN"),
    ("a homing shot takes its heading after a bounce", A, "    jsr _st_heads\n    bcc +\n    jmp _st_ok\n+   ldx.w st_i2", "    jsr _st_heads\n    jmp _st_ok\n+   ldx.w st_i2"),
    ("a triple lasts three uses", C, "        if (--uses[p] > 1)\n            return;", "        if (0)\n            return;"),
    ("a drawn triple has three uses", C, "        uses[p] = 3;\n        hud_item(p, item[p]);", "        uses[p] = 2;\n        hud_item(p, item[p]);"),
    ("a triple shot throws shots", C, "    if (it == ITEM_SHOT3)\n        base = ITEM_SHOT;\n    if (it == ITEM_PEEL3)\n        base = ITEM_PEEL;\n    o = target_of(p);", "    if (it == ITEM_PEEL3)\n        base = ITEM_PEEL;\n    o = target_of(p);"),
    ("a triple slime drops slime", C, "    if (it == ITEM_PEEL3)\n        base = ITEM_PEEL;\n    o = target_of(p);", "    o = target_of(p);"),
    ("the shield blocks a hit", C, "    if (shield_t[p])\n    {\n        shield_off(p);\n        return;\n    }\n    spin_out(p);", "    spin_out(p);"),
    ("the shield's picture stays", C, "        hud_item(p, ITEM_SHIELD);", "        hud_item(p, 0);"),
    ("the shield runs out", A, "    dec a\n    sta.w shield_t,y\n", "    sta.w shield_t,y\n"),
    ("a shielded kart takes no panel", C, "        if (shield_t[p])\n            return; // the shield's picture holds the item box\n", ""),
    ("the shield takes a shrink", C, "    if (shield_t[o])\n    {\n        shield_off(o);\n        return;\n    }\n    shrink_t[o]", "    shrink_t[o]"),
    ("a star kart takes no hit", C, "    if (star_t[p])\n        return;\n    if (shield_t[p])", "    if (shield_t[p])"),
    ("the star boosts", A, "    lda #2\n    sta.w boost_t,x\n_kt_next:", "    lda #0\n    sta.w boost_t,x\n_kt_next:"),
    ("the star spins the kart it touches", C, "    m = bump_all();\n    if (m)\n        for (p = 0, b = 1; p < NK_MAX; p++, b <<= 1)\n            if (m & b)\n                hit(p);\n    keep_all();", "    m = bump_all();\n    keep_all();"),
    ("the star flashes the kart", C, "        pal = PAL_YELLOW;", "        pal = p;"),
    ("the jump lifts the kart", C, "        air_t[p] = JUMP_FRAMES;\n        air_len[p] = JUMP_FRAMES;", "        air_len[p] = JUMP_FRAMES;"),
    ("a shot does not hurt a jumping kart", C, "                    if (!air_t[p])\n                        if (!fall_t[p])", "                    if (1)\n                        if (!fall_t[p])"),
    ("a jumping kart flies over the other", A, "    lda.w air_t+\\1\n    ora.w fall_t+\\1\n", "    lda.w fall_t+\\1\n"),
    ("a shrunk kart is slow, boosting or not", A, "    lda #SHRINK_TOP\n    sta.w dr_top\n    lda.w karts+4,y\n    bmi ++\n    cmp #SHRINK_OVER\n    bcc ++\n    lda #SHRINK_TOP\n    sta.w karts+4,y\n", ""),
    ("a shrunk kart looks small to its player", C, "    if (shrink_t[p])\n        spr(p, 120,", "    if (0)\n        spr(p, 120,"),
    ("a shrunk kart looks small to the other", A, "    lda.w shrink_t,y\n    and #$00ff\n    beq +", "    lda #0\n    beq +"),
    ("the shrink ends", A, "    lda.w shrink_t,x        ; a shrunk kart counts down (main.c used to, in a loop of its own)\n    beq +\n    dec a\n    sta.w shrink_t,x\n", ""),
    ("steal takes the item", C, "        item[o] = 0;\n        hud_item(o, 0);", "        hud_item(o, 0);"),
    ("steal with nothing to take is kept", C, "        if (!item[o])\n            return; // nothing to take: keep it\n", ""),
    ("the fake panel looks like a panel", C, "    if (kind == CELL_FAKE)\n        set = FLOOR_PANEL;\n", ""),
    ("the fake panel spins the kart", C, "    else\n    {\n        remove_peel(c);\n        hit(p);", "    else if (v == CELL_PEEL)\n    {\n        remove_peel(c);\n        hit(p);"),
    ("the slipstream boosts", A, "    lda #SLIP_FRAMES\n    sta.w boost_t,x\n", ""),
    ("the slipstream needs the kart's line", A, "    cmp #SLIP_SPAN\n    bcs _sl_miss\n    lda.w karts+4,y", "    lda.w karts+4,y"),
    ("the slipstream takes a second", A, ".DEFINE SLIP_TICKS 15", ".DEFINE SLIP_TICKS 5"),
    ("battle places come from the battle", C, "    if (battle)\n    {\n        battle_places();\n        return;\n    }\n", ""),
    ("the kart with fewer balloons or coins is behind", C, "    place[0] = a > b ? 1 : 2;", "    place[0] = 1;"),
    ("battle results show the counts when it was decided", C, "        points_text(22, row + 1, final_count[p], \"COINS\");", "        points_text(22, row + 1, coins[p], \"COINS\");"),
    ("a hit can take the coin lead away", C, "    if (coins[1 - p] > coins[p])\n        lead_p = 1 - p; // a hit took the lead away\n", ""),
    ("a battle starts with no coin lead", C, "    lead_p = 0; // after the coin counters", "    // after the coin counters"),
    ("a shot does not hurt a sinking kart", C, "                        if (!fall_t[p])\n                            hit(p);", "                        if (1)\n                            hit(p);"),
    ("a sinking kart is not touched", A, "    lda.w air_t+\\1\n    ora.w fall_t+\\1\n", "    lda.w air_t+\\1\n"),
    ("the coin clock rounds up", C, "(battle_time + 59) / 60", "battle_time / 60"),
    ("the coin clock shows in the countdown", C, "    if (battle == 2)\n        hud_clock(); // the clock shows", "    if (0)\n        hud_clock(); // the clock shows"),
    ("every item can be drawn", C, "1, 2, 5, 6, 7, 10, 12, 6, 1, 13, 7, 10, 12, 5, 11, 9,", "1, 2, 5, 6, 7, 1, 12, 6, 1, 13, 7, 2, 12, 5, 11, 9,"),
]
M += M6

M7 = [  # the countdowns, the floor's work and the pickup scan loop over every kart in proj.asm
    ("the shield's picture goes when it runs out", A, "    lda.w kt_mask\n    ora.w kt_bit\n    sta.w kt_mask\n", ""),
    ("a spin ends", A, "    dec a\n    sta.w spin_t,x\n    beq _kt_spin0", "    sta.w spin_t,x\n    beq _kt_spin0"),
    ("the trick's turn ends", A, "    dec a\n    sta.w trick_t,x\n    beq _kt_trick0", "    sta.w trick_t,x\n    beq _kt_trick0"),
    ("the trick turns the kart", A, "    dec a\n    sta.w trick_t,x\n    beq _kt_trick0\n    lda.w spin_off,x\n    clc\n    adc #SPIN_STEP", "    dec a\n    sta.w trick_t,x\n    beq _kt_trick0\n    lda.w spin_off,x\n    clc\n    adc #0"),
    ("spinning wheels stop", A, "    dec a\n    sta.w wheelspin_t,x", "    sta.w wheelspin_t,x"),
    ("the timers run for the second kart", A, "    cpx.w nk_n\n    beq +\n    jmp _kt_loop", "    cpx #1\n    beq +\n    jmp _kt_loop"),
    ("the floor works on the second kart", A, "    cpx.w nk_n\n    beq +\n    jmp _gr_loop", "    cpx #1\n    beq +\n    jmp _gr_loop"),
    ("the pickup scan sees the second kart", A, "    cpx.w nk_n\n    bne _fs_loop", "    cpx #1\n    bne _fs_loop"),
    ("the pickup scan names the kart", A, "_fs_next:\n    rep #$20\n    asl.w fs_bit", "_fs_next:\n    rep #$20\n    nop"),
    ("a kart in the air takes nothing from the floor", A, "    lda.w air_t,x\n    ora.w fall_t,x\n    bne _fs_next", "    lda.w air_t,x\n    ora.w fall_t,x\n    bra _fs_go\n_fs_go:"),
    ("the pickup scan reads the kart's row", A, "    ora.w fs_c\n    phy", "    phy"),
    ("the rescue names the kart", A, "    asl.w gr_bit\n    inx\n    tya", "    nop\n    inx\n    tya"),
    ("a jump ends", A, "    dec a\n    sta.w air_t,x\n    bne _gr_lift", "    sta.w air_t,x\n    bne _gr_lift"),
    ("a fall takes a second", A, ".DEFINE FALL_FRAMES 60", ".DEFINE FALL_FRAMES 20"),
    ("a ramp needs speed", A, "+   cmp #3                  ; speed over 2", "+   cmp #0                  ; speed over 2"),
    ("a spin from oil lasts about a second", A, ".DEFINE SPIN_FRAMES 64", ".DEFINE SPIN_FRAMES 16"),
    ("a hop lifts the kart", A, "    lda.l hop_lift,x\n    plx", "    lda #0\n    plx"),
    ("the ramp trick's boost lasts its time", A, ".DEFINE TRICK_FRAMES 40", ".DEFINE TRICK_FRAMES 10"),
]
M += M7


M8 = [  # bumps, the map edge, homing shots and places loop over every kart in proj.asm
    ("the star kart's touch hits the second kart", A, "    beq +\n    lda.w bm_j\n    asl a\n    tax\n    lda.l kart_bit,x", "    bra +\n    lda.w bm_j\n    asl a\n    tax\n    lda.l kart_bit,x"),
    ("the second kart's star hits the first", A, "    beq +\n    lda.w bm_i\n    asl a", "    bra +\n    lda.w bm_i\n    asl a"),
    ("the hit names its kart", A, "kart_bit: .dw 1, 2,", "kart_bit: .dw 1, 1,"),
    ("bumps reach the second kart", A, "    BM_PAIR 0, 1\n_bm_r2_0:", "_bm_r2_0:"),
    ("touching karts are pushed apart along x", A, "    sbc.w bm_ax\n    asl a\n    asl a\n    asl a", "    sbc.w bm_ax\n    asl a"),
    ("touching karts are pushed apart along y", A, "    sbc.w bm_ay\n    asl a\n    asl a\n    asl a", "    sbc.w bm_ay\n    asl a"),
    ("a push along x goes the right way", A, "    bit.w bm_dx\n    bpl +\n    eor #$ffff\n    inc a", "    bit.w bm_dx"),
    ("a push along y goes the right way", A, "    bit.w bm_dy\n    bpl +\n    eor #$ffff\n    inc a", "    bit.w bm_dy"),
    ("a tie on both axes pushes along x", A, "    lda.w bm_ax\n    cmp.w bm_ay\n    bcc _bm_pushy", "    lda.w bm_ay\n    cmp.w bm_ax\n    bcs _bm_pushy"),
    ("the first kart loses a quarter of its speed", A, "    sbc.w bm_t\n    sta.w karts+4,y", "    sbc #0\n    sta.w karts+4,y"),
    ("the second kart loses a quarter of its speed", A, "    sbc.w bm_t\n    sta.w karts+4,x", "    sbc #0\n    sta.w karts+4,x"),
    ("every touch is counted", A, "    inc.w bumps\n", ""),
    ("the second kart in the air touches nothing", A, "    lda.w air_t,x\n    ora.w fall_t,x\n    rep #$20\n    beq +\n    rts", "    lda.w fall_t,x\n    rep #$20\n    beq +\n    rts"),
    ("the second kart sinking touches nothing", A, "    lda.w air_t,x\n    ora.w fall_t,x\n    rep #$20\n    beq +\n    rts", "    lda.w air_t,x\n    rep #$20\n    beq +\n    rts"),
    ("the map edge holds the second kart", A, "    cpy.w nk_off\n    bne _kp_loop", "    cpy #12\n    bne _kp_loop"),
    ("the map edge slows a kart", A, ".DEFINE EDGE_SPEED 3", ".DEFINE EDGE_SPEED 30"),
    ("the map's west edge holds", A, "    lda #0\n    sta.w karts,y\n    inx", "    sta.w karts,y\n    inx"),
    ("the map's east edge holds", A, "    lda #16383\n    sta.w karts,y\n", "    sta.w karts,y\n"),
    ("the map's north edge holds", A, "    lda #0\n    sta.w karts+2,y\n    inx", "    sta.w karts+2,y\n    inx"),
    ("the map's south edge holds", A, "    lda #16383\n    sta.w karts+2,y\n", "    sta.w karts+2,y\n"),
    ("a homing shot turns left", A, "    lda #$10000-HOME_TURN", "    lda #HOME_TURN"),
    ("a homing shot turns right", A, "    lda #HOME_TURN\n    bra _st_turn", "    lda #$10000-HOME_TURN\n    bra _st_turn"),
    ("a homing shot chases the second kart", A, "kart_off: .dw 0, 12,", "kart_off: .dw 0, 0,"),
    ("a homing shot takes its step from its heading", A, "    lda.w shot_step,y\n    sta.w shot_dx,x", "    lda.w shot_step,y\n    sta.w shot_dx,x\n    lda.w shot_dx,x\n    clc\n    adc #1\n    sta.w shot_dx,x"),
    ("places rank by progress", A, "    bcc _rk_no              ; behind kart i", "    bra _rk_no              ; behind kart i"),
    ("places count the karts ahead", A, "    bne _rk_yes             ; ahead of it", "    bra _rk_no              ; ahead of it"),
    ("player 1 is ahead on a tie", A, "    cpx.w rk_y\n    bcs _rk_no", "    cpx.w rk_y\n    bra _rk_no"),
    ("the second kart gets its place", A, "    sta.w rk_i\n    cmp.w nk_n\n    bcs +", "    sta.w rk_i\n    cmp #1\n    bcs +"),
    ("every kart is ranked against the first", A, "    cpx.w nk_w\n    bne _rk_j", "    cpx #2\n    bne _rk_j"),
    ("a changed place is named", A, "    lda.l kart_bit,x\n    ora.w rk_mask", "    lda #0\n    ora.w rk_mask"),
    ("the HUD shows the new place of player 2", C, "    if (lead & 2)\n        hud_place(1);", ""),
    ("the HUD shows the new place of player 1", C, "    if (lead & 1)\n        hud_place(0);", ""),
    ("L or R starts a hop", C, "    if (down & (KEY_L | KEY_R))\n        busy = 1;\n", ""),
    ("a drift ends when L or R is let go", C, "    busy = hop_t[p] | drift[p];", "    busy = hop_t[p];"),
    ("a hop runs out", C, "    busy = hop_t[p] | drift[p];", "    busy = drift[p];"),
    ("the item picture rolls", C, "    if (roll[p])\n        roll_step(p);", "    if (0)\n        roll_step(p);"),
]
M += M8

G = "tools/gen_assets.py"
M9 = [  # pictures and palettes for computer karts
    ("the R glyph is drawn", G, '    art["gR"] = draw_glyph("R", 2, 16, 16, 1, 1, 2, 3, 1)\n', '    art["gR"] = [[0] * 16 for _ in range(16)]\n'),
    ("the computer dot has its dark ring", G, '"dot3": {1: MINI_FIRST}}', '"dot3": {}}'),
    ("computer frames wait for the countdown", C, "    if (!cpu_gfx_ready && game_state == ST_RACE && !timer && !battle)", "    if (!cpu_gfx_ready && game_state == ST_RACE && !battle)"),
    ("each computer animal has its own band", C, "(CPU_BASE + (cpu_loaded << 5) + cpu_dst[i])", "(CPU_BASE + cpu_dst[i])"),
    ("computer frames come from the computer animal", C, "cast_gfx[cpu_pick[cpu_loaded]]", "cast_gfx[pick[cpu_loaded]]"),
    ("a computer animal is not a player's", C, "        ok = (i != pick[0]) & (i != pick[1]) & (i != skip);", "        ok = (i != skip);"),
    ("the computer animals differ", C, "        ok = (i != pick[0]) & (i != pick[1]) & (i != skip);", "        ok = (i != pick[0]) & (i != pick[1]);"),
    ("the first computer animal is drawn from the free ones", C, "(rng & 255) % (CAST - 2)", "(rng & 255) % CAST"),
    ("the second computer animal is drawn from the free ones", C, "((rng >> 8) & 255) % (CAST - 3)", "((rng >> 8) & 255) % CAST"),
    ("one computer animal a frame", C, "        cpu_gfx_ready = cpu_loaded == 2;\n", "        cpu_gfx_ready = cpu_loaded == 2;\n        if (!cpu_gfx_ready)\n            load_cpu_gfx();\n"),
    ("palette 7 holds the second computer animal", C, "    dmaCopyCGram(&cast_pal + (cpu_pick[1] << 5), CGRAM_CPU(1), 32);", "    dmaCopyCGram(&cast_pal + (cpu_pick[0] << 5), CGRAM_CPU(1), 32);"),
    ("the obstacle's colours load into palette 2", C, "    dmaCopyCGram(trk_obpal[t], CGRAM_OB, 10);", "    dmaCopyCGram(trk_obpal[t], CGRAM_OB + 1, 10);"),
    ("the balloons keep their colours", G, "3: MINI_FIRST + 2, 4: MINI_FIRST + 3}", "3: MINI_FIRST + 3, 4: MINI_FIRST + 2}"),
    ("the minimap keeps its colours", G, "(232, 232, 240), (96, 184, 255), (255, 112, 80)]\nMINI_MAP", "(232, 232, 200), (96, 184, 255), (255, 112, 80)]\nMINI_MAP"),
    ("the minimap dots use palette 2", A, "(($30 | (2 << 1) | (TILE_DOT1 >> 8)) << 8)", "(($30 | (6 << 1) | (TILE_DOT1 >> 8)) << 8)"),
    ("a kart is a record with a view flag", A, "    lda.l obj_frames+4,x\n    and #$00ff\n    beq _nolift", "    lda.l obj_frames+4,x\n    and #$00ff\n    bra _nolift"),
    ("computer kart records are karts", G, "0x30 | (pal << 1), 0x40, 0]", "0x30 | (pal << 1), 0, 0]"),
    ("computer karts show their far views", G, "CPU_FAR_VIEW = [5, 5, 6, 7, 7]", "CPU_FAR_VIEW = [5, 5, 5, 7, 7]"),
]
M += M9


T = "tools/tracks.py"
M10 = [  # computer karts in the race data, drawn, parked
    ("computer karts have rows on the grid", T, "GRID_BACK = (20, 44, 62)", "GRID_BACK = (20, 30, 40)"),
    ("computer karts start on their grid places", C, "        karts[p].x = trk_grid[track_no * 12 + p * 2] << 4;", "        karts[p].x = trk_grid[track_no * 12 + (p & 1) * 2] << 4;"),
    ("the race holds the computer karts to the most", C, "    if (cpu_n > CPU_MAX)\n        cpu_n = CPU_MAX;\n", ""),
    ("a battle has no computer karts", C, "    if (battle)\n        cpu_n = 0; // battles are between the two players\n", ""),
    ("computer karts are drawn in each half's own slots", A, "          .dw 3*4, $FFFF, 80*4, 81*4, 82*4, 83*4,", "          .dw 3*4, $FFFF, 76*4, 77*4, 78*4, 79*4,"),
    ("each computer kart has its own picture", A, "pj_kinds: .dw 0, 48, 192, 240, 288, 336", "pj_kinds: .dw 0, 48, 192, 192, 288, 336"),
    ("computer karts wait for their pictures", A, "    and #$00ff\n    beq +\n    lda.w cpu_n\n    and #$00ff\n+   clc\n    adc #2\n    sta.b <pj_kn", "    and #$00ff\n    lda.w cpu_n\n    and #$00ff\n    clc\n    adc #2\n    sta.b <pj_kn"),
    ("computer karts are drawn up to 360 px", A, ".DEFINE CPU_FAR 360 ", ".DEFINE CPU_FAR 600 "),
    ("computer karts' high OAM bits are cleared", C, "oamMemory[531] = oamMemory[532] = oamMemory[533] = oamMemory[534] = 0;", "oamMemory[531] = oamMemory[532] = oamMemory[533] = oamMemory[534] = 0xFF;"),
    ("alternate frames draw one half at a time", A, "    eor.b <pj_p\n    lsr a\n    bcc _kart_alt", "    eor.b <pj_p\n    lsr a\n    bra _kart_alt"),
    ("the floor works on the computer karts", A, "    cpx.w nk_n\n    beq +\n    jmp _gr_loop", "    cpx #2\n    beq +\n    jmp _gr_loop"),
    ("the timers run for the computer karts", A, "    cpx.w nk_n\n    beq +\n    jmp _kt_loop", "    cpx #2\n    beq +\n    jmp _kt_loop"),
    ("the pickup scan sees the computer karts", A, "    cpx.w nk_n\n    bne _fs_loop", "    cpx #2\n    bne _fs_loop"),
    ("the map edge holds the computer karts", A, "    cpy.w nk_off\n    bne _kp_loop", "    cpy #24\n    bne _kp_loop"),
    ("a shot hits a computer kart", A, "    cpy.w nk_n\n    bcc _ms_k", "    cpy #2\n    bcc _ms_k"),
    ("an obstacle hits a computer kart", A, "    cmp #3\n    bcs +\n    jmp _mo_kd\n+   MO_KART 2", "    cmp #9\n    bcs +\n    jmp _mo_kd\n+   MO_KART 2"),
    ("a player bumps a computer kart", A, "    BM_PAIR 0, 2\n    BM_PAIR 0, 3\n    BM_PAIR 0, 4\n    BM_PAIR 0, 5\n_bm_r6_0:", "    BM_PAIR 0, 3\n    BM_PAIR 0, 4\n    BM_PAIR 0, 5\n_bm_r6_0:"),
    ("places count the computer karts ahead", A, "    cpx.w nk_w\n    bne _rk_j", "    cpx #4\n    bne _rk_j"),
    ("computer karts' progress is read", C, "            lead = progress_cpu();", "            lead = 0;"),
    ("a computer kart's lap is counted", A, "    lsr a\n    bcc +\n    pha\n    lda.w pc_b", "    lsr a\n    bra +\n    pha\n    lda.w pc_b"),
    ("the HUD shows 3RD with an R", C, "        spr(s + 1, 224, y, TILE_GR, PAL_YELLOW, 0, 0);", "        spr(s + 1, 224, y, glyph_tile[G_S], PAL_YELLOW, 0, 0);"),
    ("the HUD shows 4TH to 6TH with an H", C, "n == 1 ? G_T : (n == 2 || n == 3 ? G_D : G_H)", "n == 1 ? G_T : G_D"),
    ("the HUD shows 4TH to 6TH with a T", C, ": (n == 2 ? G_N : G_T), PAL_YELLOW);", ": (n == 2 ? G_N : G_N), PAL_YELLOW);"),
    ("the results name places 3 to 6", C, '{"", "1ST", "2ND", "3RD", "4TH", "5TH", "6TH"}', '{"", "1ST", "2ND", "2ND", "4TH", "5TH", "6TH"}'),
    ("places 3 to 6 draw the third table", C, "odds[(place[p] == 1 ? 0 : (place[p] == 2 ? 16 : 32)) + last_roll[p]]", "odds[(place[p] == 1 ? 0 : 16) + last_roll[p]]"),
    ("an item aims at the kart directly ahead in place", C, "    want = ahead ? place[p] - 1 : 2;", "    want = ahead ? place[p] + 1 : 2;"),
    ("the leader's item aims at the kart directly behind", C, "    want = ahead ? place[p] - 1 : 2;", "    want = ahead ? place[p] - 1 : 3;"),
    ("a homing shot chases the aimed kart", C, "    shot_home[i] = kind == 1 ? 1 + target_of(p) : 0;", "    shot_home[i] = kind == 1 ? 2 - p : 0;"),
    ("the race ends 1.5 s after both players finish", A, "    lda.w finished+1\n    beq _ln_noend\n", ""),
    ("a computer kart finishing starts the 10 s", A, "    cpx #2\n    bcs _ln_cont            ; a computer kart finishes without starting the 10 s\n    txa\n    eor #1", "    txa\n    eor #1"),
    ("the first player home wins", A, "    bne _ln_cont\n    lda #AFTER_FIRST", "    nop\n    lda #AFTER_FIRST"),
    ("a finished kart keeps its finishing place", A, "    beq +\n    jmp _rk_same            ; a finished kart keeps the place it finished in", "    bra +\n    jmp _rk_same            ; a finished kart keeps the place it finished in"),
    ("the results wait for a player to finish", C, "(battle | finished[0] | finished[1])) //", "1) //"),
    ("a computer kart's lap leaves the HUD alone", C, "    if (p > 1)\n        return; // only the players have a HUD\n", ""),
    ("a computer kart's wrong way leaves the HUD alone", C, "    if (p > 1)\n        return; // a computer kart has no sign\n", ""),
    ("a computer kart's coins leave the HUD alone", C, "    if (p > 1)\n        return;\n    s = ITEM_SLOT(p) + 2;", "    s = ITEM_SLOT(p) + 2;"),
    ("computer karts have minimap dots", A, "    beq _mn_out\n    sta.w mn_n", "    bra _mn_out\n    sta.w mn_n"),
    ("computer karts have a dot in the bottom half", A, "    sta.w oamMemory+88*4,x\n    rep #$20\n    lda.w karts+2,y", "    nop\n    rep #$20\n    lda.w karts+2,y"),
    ("the minimap draws behind the computer dots", C, "#define MINI_SLOT(p) (92 + (p))", "#define MINI_SLOT(p) (68 + (p))"),
]
M += M10

M11 = [  # making room: the shot, obstacle and bump tests per kart, the frame's quick-outs, the lap and banner work in assembly
    ("a shot hits the kart it touches", A, "    ldy #\\1\n    jmp _ms_hit", "    ldy #\\1\n    nop\n    nop\n    nop"),
    ("a shot passes a computer kart that is not racing", A, "    cpx #6\n    bcs +\n    jmp _ms_kdone\n+\n    MS_KART 5", "    cpx #0\n    bcs +\n    jmp _ms_kdone\n+\n    MS_KART 5"),
    ("an obstacle strikes the kart it touches", A, "    sta.w ob_struck+\\1", "    sta.w ob_struck"),
    ("the own kart shows a spin", A, "    ora.w spin_t+\\1\n    ora.w hop_t+\\1\n", "    ora.w hop_t+\\1\n"),
    ("the own kart shows a hop", A, "    ora.w hop_t+\\1\n    ora.w wheelspin_t+\\1\n", "    ora.w wheelspin_t+\\1\n"),
    ("the own kart goes back after a spin", A, "    lda.w own_was+\\1\n    ora.w spin_t+\\1", "    lda.w spin_t+\\1"),
    ("a boosting kart shows its flame", A, "    lda.w fx_was+\\1\n    ora.w boost_t+\\1\n    bne ++", "    lda.w fx_was+\\1\n    bne ++"),
    ("a charged drift shows sparks", A, "    cmp #DRIFT_CHARGE\n    bcc +++", "    cmp #$FF\n    bcc +++"),
    ("the flame goes when the boost ends", A, "    lda.w fx_was+\\1\n    ora.w boost_t+\\1", "    lda.w boost_t+\\1"),
    ("the finish banner is written", A, "    ora #16<<\\1", "    ora #0"),
    ("player 2's lap is counted", A, "    asl a\n    asl a\n    ora.w pp_r", "    ora.w pp_r"),
    ("player 2's progress is read", A, "    lda #1\n    sta.w pg_p\n    jsr pg_kart", "    lda #0\n    sta.w pg_p\n    jsr pg_kart"),
    ("each computer kart's place is worked out", A, "    lda #4\n    sta.w rk_s", "    lda #8\n    sta.w rk_s"),
    ("a computer kart's place is worked out on its own frame", A, "    lda.w race_time\n    and #3\n    sta.w rk_i", "    lda #0\n    sta.w rk_i"),
    ("a shot with no sideways step flies straight up or down", A, "    lda #128                ; heading 64 (down), doubled for the word tables", "    lda #0"),
    ("a shot turned at a corner finds the mirror heading", A, "    lda #256\n    sec\n    sbc.w st_a2", "    lda #386\n    sec\n    sbc.w st_a2"),
    ("a lap counts", A, "    lda.w lap,x\n    inc a\n    sta.w lap,x", "    lda.w lap,x\n    sta.w lap,x"),
    ("a finisher takes the next place", A, "    lda.w done_count\n    sta.w place,x", "    lda #6\n    sta.w place,x"),
    ("progress follows the lap", A, "    sta.w prog,y\n    lda.w ln_r", "    nop\n    nop\n    nop\n    lda.w ln_r"),
    ("a finisher's finish banner is armed", A, "    lda #8\n    sta.w banner_left,x", "    lda #0\n    sta.w banner_left,x"),
    ("the final-lap banner is green", A, "BN_GLYPH 74, GLYPH_18, PAL_GREEN", "BN_GLYPH 74, GLYPH_18, PAL_YELLOW"),
    ("the finish banner spells FINISH", A, "BN_GLYPH 92, GLYPH_18, PAL_YELLOW", "BN_GLYPH 92, GLYPH_19, PAL_YELLOW"),
    ("the banner is written two glyphs a frame", A, "    lda #2\n    sta.w bn_n", "    lda #1\n    sta.w bn_n"),
    ("the second half's banner is lower", A, "    adc #112*256", "    adc #0"),
    ("the race clock counts", A, "    inc a\n    sta.w race_time\n+   lda.w timer", "    nop\n    sta.w race_time\n+   lda.w timer"),
    ("the random number steps", A, "+   sta.w rng\n", "+   nop\n    nop\n    nop\n"),
    ("GO goes after its time", A, "    bne _cs_banner\n    ldx #0", "    bra _cs_banner\n    ldx #0"),
    ("player 2's camera follows player 2", A, "    lda #1\n    jsr cm_one", "    lda #0\n    jsr cm_one"),
    ("the computer karts are projected on alternate frames by default", C, "    cpu_alt = 1; // the computer", "    cpu_alt = 0; // the computer"),
    ("three computer karts race", C, "#define CPU_MAX 3 ", "#define CPU_MAX 2 "),
]
M += M11

M12 = [  # the computer karts drive
    ("the computer karts drive", C, "    if (cpu_n)\n        cpu_frame();", "    if (0)\n        cpu_frame();"),
    ("a computer kart turns right towards its target", A, "    ldx #KEY_RIGHT\n    cmp #64", "    ldx #0\n    cmp #64"),
    ("a computer kart turns left towards its target", A, "    ldx #KEY_LEFT\n+   stx.w cf_pad", "    ldx #0\n+   stx.w cf_pad"),
    ("a computer kart steers only when more than one step off", A, "    cmp #2\n    bcc +\n    cmp #127\n    bcs +\n    ldx #KEY_RIGHT", "    cmp #1\n    bcc +\n    cmp #128\n    bcs +\n    ldx #KEY_RIGHT"),
    ("each computer kart has its own heading bias", A, "cpu_bias: .dw $FFFD, 3, 0, 0", "cpu_bias: .dw 0, 0, 0, 0"),
    ("a computer kart holds the pedal", A, "+   lda.w cf_pad\n    ora #KEY_B\n++  sta.w cf_pad", "+   lda.w cf_pad\n    ora #0\n++  sta.w cf_pad"),
    ("a computer kart brakes in a tight stretch above CPU_SLOW", A, "    ora #KEY_Y\n    bra ++", "    ora #KEY_B\n    bra ++"),
    ("the computer karts wait for GO", A, "    lda.w game_state\n    and #$00ff\n    cmp #ST_RACE\n    beq +\n    stz.w cf_av             ; before GO no kart is steering round another\n    stz.w cf_av+2\n    stz.w cf_av+4\n    stz.w cf_av+6\n    jmp _cf_out\n+   lda.w cpu_hold", "    lda.w cpu_hold"),
    ("cpu_hold parks the computer karts", A, "    beq +\n    jmp _cf_out\n+   lda #pj_base", "    bra +\n    nop\n    nop\n    nop\n+   lda #pj_base"),
    ("a computer kart uses its own type's top speed", A, "    adc.l kart_types+2,x\n    sta.w dr_top\n    ldy.w cf_y", "    adc #45\n    sta.w dr_top\n    ldy.w cf_y"),
    ("a computer kart's coins count only to 10", A, "    cmp #11\n    bcc +\n    lda #10\n+   lsr a\n    ldx.w dr_kt\n    clc\n    adc.l kart_types+2,x\n    sta.w dr_top\n    ldy.w cf_y", "    lsr a\n    ldx.w dr_kt\n    clc\n    adc.l kart_types+2,x\n    sta.w dr_top\n    ldy.w cf_y"),
    ("a spinning computer kart takes no pedal", A, "    lda.w spin_t,x\n    ora.w fall_t,x\n    ora.w wheelspin_t,x\n    ora.w boost_t,x\n    ora.w shrink_t,x", "    lda.w fall_t,x\n    ora.w wheelspin_t,x\n    ora.w boost_t,x\n    ora.w shrink_t,x"),
    ("a computer kart off the road drives at the grass speed", A, "    cmp #SURF_ROAD\n    beq +\n    jmp _cf_slow", "    cmp #SURF_GRASS\n    beq +\n    jmp _cf_slow"),
    ("oil spins only a kart at OIL_SPEED or more", A, "    cmp #OIL_SPEED\n    sep #$20\n    bcs +", "    cmp #0\n    sep #$20\n    bcs +"),
    ("the steering map aims along the race direction", T, "    j = (near + int(round(AIM / STEP))) % n\n", "    j = (near - int(round(AIM / STEP))) % n\n"),
    ("the steering map marks the tight stretches", T, "    lift = (tight[near] < hold_radius()).astype(int)", "    lift = (tight[near] < 0).astype(int)"),
    ("the steering map aims past the oil and the sand", T, "    side = dodge_offsets(t, route)[j] / np.maximum(np.hypot(dx, dy), 1e-9)", "    side = 0 * dodge_offsets(t, route)[j] / np.maximum(np.hypot(dx, dy), 1e-9)"),
]
M += M12

M13 = [  # the third odds table, the leader shot, computer karts use items, the decision gate
    ("the third table holds the leader shot", C, "    6, 1, 10, 5, 12, 1, 6, 15, 10, 5, 6, 15, 10, 1, 5, 12,", "    6, 1, 10, 5, 12, 1, 6, 9, 10, 5, 6, 9, 10, 1, 5, 12,"),
    ("no two places draw the same item at one index", C, "    6, 1, 10, 5, 12, 1, 6, 15, 10, 5, 6, 15, 10, 1, 5, 12,", "    6, 2, 10, 5, 12, 1, 6, 15, 10, 5, 6, 15, 10, 1, 5, 12,"),
    ("the leader shot flies over grass", A, "_ml_move:\n    lda.b <ms_t\n    CLAMP_STEP",
     "_ml_move:\n    ldy.b <ms_w\n    ldx.w shot_y,y\n    lda.w shot_x,y\n    jsr ms_surface\n    bne +\n    ldx.b <ms_i\n    sep #$20\n    lda #0\n    sta.w shot_on,x\n    rep #$20\n    jmp _ms_kdone\n+   ldy.b <ms_w\n    lda.b <ms_t\n    CLAMP_STEP"),
    ("the leader shot is faster than a homing shot", A, ".DEFINE LEADER_STEP 96", ".DEFINE LEADER_STEP 48"),
    ("the leader shot goes to first place", C, "    want = place[p] == 1 ? 2 : 1;", "    want = 2;"),
    ("a leader's own leader shot goes to second place", C, "    want = place[p] == 1 ? 2 : 1;\n    k = unfinished_at(p, want, 0);", "    want = 1;\n    k = unfinished_at(255, want, 0);"),
    ("a kart in the air is passed under by the leader shot", A, "    beq +\n    jmp _ms_kdone           ; in the air or sinking: wait", "    bra +\n    jmp _ms_kdone           ; in the air or sinking: wait"),
    ("the leader shot has its own picture", "tools/gen_assets.py", "                tiles = [leader_tile(sz)] * 5", "                tiles = [shared_tile((\"i_shot\", \"shot_mid\", \"shot_far\")[sz])] * 5"),
    ("the leader shot has a HUD picture", "tools/gen_assets.py", '"i_fake", "i_leader"]', '"i_fake"]'),
    ("the leader shot's picture is copied in", C, "        dmaCopyVram(&leader_pic + (i << 7), 0x6000 + ((TILE_LEADER + (i << 4)) << 4), 128);", "        i = i;"),
    ("a battle loads the leader shot's picture too", C, "    if (battle)\n        ok = 1;\n    if (!ok)", "    if (!ok)"),
    ("the leader shot waits for its picture", C, "        if (!leader_ready)\n            return; // its picture", "        if (0)\n            return; // its picture"),
    ("a computer kart's roll ends", C, "        if (p > 1)\n            cpu_use_t[p] = ROLL_FRAMES;", "        if (p > 1)\n            cpu_use_t[p] = 0;"),
    ("a computer kart's decisions run", C, "        if (frame_lines() < CPU_GATE)\n            cpu_items();", "        if (frame_lines() < 0)\n            cpu_items();"),
    ("a computer kart's decisions wait for a light frame", C, "        if (frame_lines() < CPU_GATE)\n            cpu_items();", "        cpu_items();"),
    ("a computer kart shoots at a kart ahead", C, "        ok = cpu_sees(p, 1, 10240);", "        ok = 1;"),
    ("a computer kart drops slime on a kart behind", C, "    else if (base == ITEM_PEEL)\n        ok = cpu_sees(p, 0, 7680);", "    else if (base == ITEM_PEEL)\n        ok = 1;"),
    ("a computer kart drops a fake panel on a kart behind", C, "    else if (base == ITEM_FAKE)\n        ok = cpu_sees(p, 0, 7680);", "    else if (base == ITEM_FAKE)\n        ok = 1;"),
    ("a computer kart boosts off the tight bends", C, "        ok = !(cur_steer[cell_of(karts[p].x, karts[p].y)] & 128);", "        ok = 1;"),
    ("a computer kart jumps before water or oil", C, "        ok = cpu_wet_ahead(p);", "        ok = 1;"),
    ("a computer kart's homing and leader shots wait", C, "            cpu_age[p] = 30 + d; // the delay, 30 to 120 frames\n            cpu_use_t[p] = 30 + d;", "            cpu_age[p] = 1;\n            cpu_use_t[p] = 1;"),
    ("a computer kart's delay is random", C, "            d = rng & 127;", "            d = 40;"),
    ("a held item is used after 5 s", C, "#define CPU_PATIENCE 300", "#define CPU_PATIENCE 3000"),
    ("a computer kart looks again every 8 frames", C, "#define CPU_RECHECK 8 ", "#define CPU_RECHECK 40"),
    ("the item decision waits at once for nothing", C, "    ok = 1;\n    if (base == ITEM_BOOST)", "    ok = 0;\n    if (base == ITEM_BOOST)"),
    ("a computer kart's item is used through use_item", C, "    u = uses[p];\n    use_item(p);", "    u = uses[p];\n    item[p] = 0;"),
    ("a triple item's next use", C, "    if (item[p])\n        cpu_use_t[p] = 45; // a triple item's next use", "    if (item[p])\n        cpu_use_t[p] = 0; // a triple item's next use"),
    ("a spinning computer kart uses nothing", C, "    if (spin_t[p] | fall_t[p])", "    if (0)"),
    ("a computer kart that could not use its item drops it after 5 s", C, "        if (cpu_age[p] >= CPU_PATIENCE)\n            item[p] = 0;\n        else\n            cpu_use_t[p] = CPU_RECHECK;", "        cpu_use_t[p] = CPU_RECHECK;"),
    ("a computer kart's item leaves the HUD alone", C, "    if (p > 1)\n        return; // a computer kart has no item box\n    if (it)", "    if (it)"),
    ("the countdown reaches the decisions", A, "    dec a\n    sta.w cpu_use_t,x\n    bne _kt_nx", "    dec a\n    sta.w cpu_use_t,x\n    bra _kt_nx"),
    ("kart steps come from the table", A, "    lda.l mk_tab,x\n    clc\n    adc.w karts+8,y", "    lda.l mk_tab,x\n    asl a\n    clc\n    adc.w karts+8,y"),
    ("the kart's y step is the quarter turn on", A, "    adc #$1000\n    and #$3f80", "    adc #$0800\n    and #$3f80"),
]
M += M13

M14 = [  # the screens for computer karts
    ("the menu starts on the most computer karts", C, "    cpu_menu = CPU_MAX; // the track menu starts on the most", "    cpu_menu = 0; // the track menu starts on the most"),
    ("left on the computer karts line wraps round", C, "            cpu_menu = cpu_menu ? cpu_menu - 1 : CPU_MAX;", "            cpu_menu = cpu_menu ? cpu_menu - 1 : 0;"),
    ("right on the computer karts line wraps round", C, "            cpu_menu = cpu_menu < CPU_MAX ? cpu_menu + 1 : 0;", "            cpu_menu = cpu_menu < CPU_MAX ? cpu_menu + 1 : CPU_MAX;"),
    ("left and right leave the choice alone on a battle", C, "    else if ((down & (KEY_LEFT | KEY_RIGHT)) && menu_pos <= ARENA)", "    else if (down & (KEY_LEFT | KEY_RIGHT))"),
    ("a battle under the cursor shows NONE", C, "    if (menu_pos > ARENA)\n    {\n        s = \"NONE\";", "    if (0)\n    {\n        s = \"NONE\";"),
    ("the race has the menu's computer karts", C, "        cpu_n = cpu_menu; // a battle sets it", "        cpu_n = 0; // a battle sets it"),
    ("a cup's computer karts keep their animals", C, "    keep = cup_on;\n", "    keep = 0;\n"),
    ("a kart that did not finish scores nothing in a cup with computer karts", C, "                if (finished[k])\n                    points[k] += cup_points[5 + place[k] - 1];", "                points[k] += cup_points[5 + place[k] - 1];"),
    ("a computer cup's first place scores 9", C, "{3, 1, 0, 0, 0, 9, 6, 4, 3, 2, 1}", "{3, 1, 0, 0, 0, 8, 6, 4, 3, 2, 1}"),
    ("a computer cup's third place scores 4", C, "{3, 1, 0, 0, 0, 9, 6, 4, 3, 2, 1}", "{3, 1, 0, 0, 0, 9, 6, 5, 3, 2, 1}"),
    ("a computer cup's fifth place scores 2", C, "{3, 1, 0, 0, 0, 9, 6, 4, 3, 2, 1}", "{3, 1, 0, 0, 0, 9, 6, 4, 3, 3, 1}"),
    ("the results list the karts in place order", C, "                if (place[k] == r)\n                {\n                    if (r == 1)", "                if (k == r - 1)\n                {\n                    if (r == 1)"),
    ("the results rows are three text rows apart", C, "                    result_row_cpu(k, 6 + 3 * r);", "                    result_row_cpu(k, 6 + 2 * r);"),
    ("a computer kart's row says COMPUTER", C, '    text(11, row + 1, driver_name[k], 0);', '    text(11, row + 1, driver_name[k > 1 ? 2 : k], 0);'),
    ("a kart that did not finish shows NO TIME", C, '    else\n        text(23, row, "NO TIME", 0);\n    if (cup_on)\n        points_text(23, row + 1, points[k], "POINTS");', '    else\n        text(23, row, "-", 0);\n    if (cup_on)\n        points_text(23, row + 1, points[k], "POINTS");'),
    ("the results with computer karts name the first place's animal", C, "                        winner_text(animal_of(k));", "                        winner_text(pick[0]);"),
    ("the podium has a third block with computer karts", C, "    n = cpu_n ? 3 : 2;", "    n = 2;"),
    ("the bronze block has its own tile", C, "podium_block(pod_x[o + i], pod_row[i], 8, 176 + i);", "podium_block(pod_x[o + i], pod_row[i], 8, 176 + (i & 1));"),
    ("the bronze block is bronze", "tools/gen_assets.py", "PODIUM_TILES = [(7, 8), (9, 10), (11, 12)]", "PODIUM_TILES = [(7, 8), (9, 10), (9, 10)]"),
    ("a tie in a computer cup goes to the better place in the last race", C, "key = ((u16)points[k] << 3) + 8 - place[k];", "key = ((u16)points[k] << 3) + place[k];"),
    ("the podium shows the animal of each kart", C, "BIG_TILE(animal_of(k)), animal_of(k) / 3, 0, 1);", "BIG_TILE(pick[0]), pick[0] / 3, 0, 1);"),
    ("the podium loads the portraits", C, "        dmaCopyVram(&select_obj_gfx, 0x6000, 384 * 32); // the portraits", "        i = i; // the portraits"),
    ("the podium loads the portraits' colours", C, "        dmaCopyCGram(&select_obj_pal, 128, 7 * 32);\n    }\n    text_mid(16, 1, \"CUP RESULTS\"", "    }\n    text_mid(16, 1, \"CUP RESULTS\""),
    ("the podium's winner is the top kart", C, "    cup_winner = order[0];", "    cup_winner = order[1];"),
    ("the podium's points are the kart's", C, "        points_text(pod_text[o + i], 23, points[k], cpu_n ? \"PTS\" : \"POINTS\");", "        points_text(pod_text[o + i], 23, points[order[0]], cpu_n ? \"PTS\" : \"POINTS\");"),
]
M += M14

M15 = [  # the finish, the points, the results and the menu texts
    ("a player's finish starts the 10 s", A, "    lda #AFTER_FIRST        ; the first player home starts the 10 s, and wins\n    sta.w end_timer\n", ""),
    ("the podium counts points before the last place", C, "key = ((u16)points[k] << 3) + 8 - place[k];", "key = ((u16)points[k] << 0) + 8 - place[k];"),
    ("a computer cup's second place scores 6", C, "{3, 1, 0, 0, 0, 9, 6, 4, 3, 2, 1}", "{3, 1, 0, 0, 0, 9, 7, 4, 3, 2, 1}"),
    ("a computer cup's fourth place scores 3", C, "{3, 1, 0, 0, 0, 9, 6, 4, 3, 2, 1}", "{3, 1, 0, 0, 0, 9, 6, 4, 4, 2, 1}"),
    ("a computer cup's sixth place scores 1", C, "{3, 1, 0, 0, 0, 9, 6, 4, 3, 2, 1}", "{3, 1, 0, 0, 0, 9, 6, 4, 3, 2, 0}"),
    ("a finished computer kart takes no panels", A, "    lda.w finished,x        ; a computer kart that has finished takes nothing\n    bne _fs_next\n", ""),
    ("a finished computer kart uses no item", C, "    if (finished[p])\n        return; // a kart that has finished uses nothing\n", ""),
    ("an aimed item passes a finished kart", C, "    k = unfinished_at(p, want, ahead);", "    k = 255;"),
    ("the leader shot passes a finished kart", C, "    k = unfinished_at(p, want, 0);", "    k = 255;"),
    ("an aimed item looks on in the right direction", C, "        if (ahead)\n            want--;\n        else\n            want++;", "        want++;"),
    ("an aimed item keeps the kart in front when all have finished", C, "    for (k = 0; k < 2 + cpu_n; k++)\n        if (k != p && place[k] == want)\n            return k;\n    return p == 0 ? 1 : 0;\n}\n\n// The kart the leader shot", "    return p == 0 ? 1 : 0;\n}\n\n// The kart the leader shot"),
    ("the results work out every kart's place", A, "    lda.w rk_full           ; unless the results are about to be drawn: every kart\n    and #$00ff\n    bne _rk_i\n", ""),
    ("the random number steps on every menu frame", C, "            rng = (rng >> 1) ^ ((rng & 1) ? 0xB400 : 0);", "            rng = rng;"),
    ("a player who did not finish shows NO TIME", C, '    else\n        text(23, row, "NO TIME", 0);\n    if (cup_on)\n        points_text(23, row + 1, points[p], "POINTS");', '    else\n        text(23, row, "-", 0);\n    if (cup_on)\n        points_text(23, row + 1, points[p], "POINTS");'),
    ("the track menu says how to change the computer karts", C, '    text(1, 26, "LEFT/RIGHT: COMPUTER KARTS", 0);\n', ""),
    ("the computer karts line is a row above the help line", C, '    text(8, 23, "COMPUTER KARTS:", 0);', '    text(8, 24, "COMPUTER KARTS:", 0);'),
    ("the podium's points texts stand apart", C, "const u8 pod_text[6] = {14, 4, 0, 13, 2, 24};", "const u8 pod_text[6] = {14, 4, 0, 11, 1, 21};"),
    ("the podium names each driver", C, "            text_mid(pod_x[o + i] + 4, pod_row[i] + 2, driver_name[k], 0);", "            k = k;"),
    ("computer karts are numbered by their kart number", C, '"COMPUTER 2", "COMPUTER 3"', '"COMPUTER 1", "COMPUTER 3"'),
    ("a coin battle's count stays off the animal's row", C, '        points_text(22, row + 1, final_count[p], "COINS");', '        points_text(22, row, final_count[p], "COINS");'),
    ("a balloon battle's count stays off the animal's row", C, 'points_text(22, row + 1, final_count[p], final_count[p] == 1 ? "BALLOON" : "BALLOONS");', 'points_text(22, row, final_count[p], final_count[p] == 1 ? "BALLOON" : "BALLOONS");'),
]
M += M15

M16 = [  # a computer kart goes round a kart in its way
    ("a computer kart steers to one side of the map's heading after a touch", A, "    clc\n    adc.w cf_sd-4,x\n    clc\n    adc.l cpu_bias-4,x\n    bra ++", "    clc\n    adc.l cpu_bias-4,x\n    bra ++"),
    ("a touch starts the steering round", A, ["    sta.w bm_o\n    jsr _bm_swerve\n_bm_swj:", "    sta.w bm_o\n    jsr _bm_swerve\n_bm_swe:"], ["    sta.w bm_o\n_bm_swj:", "    sta.w bm_o\n_bm_swe:"]),
    ("a computer kart steers to the side with road", A, "    cmp #0\n    beq _bm_swl\n    bra _bm_swr", "    cmp #0\n    beq _bm_swr\n    bra _bm_swl"),
    ("a kart standing still is not shoved", A, "    cmp #3\n    bcs _bm_sh1\n", "    cmp #3\n    bcs _bm_sh1\n    bra _bm_sh2\n"),
    ("no computer kart starts in a player's line", T, "GRID_SIDES = ((-12, 12), (-18, 18), (0, 18))", "GRID_SIDES = ((-12, 12), (-12, 12), (0, 12))"),
]
M += M16


def run(i):
    name, path, old, new = M[i]
    d = os.path.join(WORK, f"m{i}")
    shutil.rmtree(d, ignore_errors=True)
    for sub in ("game", "tools"):
        shutil.copytree(os.path.join(SRC, sub), os.path.join(d, sub), ignore=shutil.ignore_patterns("__pycache__"))
    f = os.path.join(d, path)
    s = open(f).read()
    for o, n in zip(old, new) if isinstance(old, list) else [(old, new)]:
        if s.count(o) != 1:
            return name, f"PATCH DID NOT APPLY ({s.count(o)} matches)"
        s = s.replace(o, n)
    open(f, "w").write(s)
    b = subprocess.run(["make", "-C", os.path.join(d, "game")], capture_output=True, text=True)
    log = os.path.join(d, "game", "couchkart.log")
    if b.returncode or "Build finished successfully" not in (open(log).read() if os.path.exists(log) else ""):
        g = subprocess.run([sys.executable, os.path.join(d, "tools", "gen_assets.py")], capture_output=True, text=True)
        if "points against the race direction" in g.stdout + g.stderr:  # the track generator's own check stopped the build
            return name, "FAIL (the generator stopped the build): " + (g.stdout + g.stderr).strip().splitlines()[-1][:160]
        return name, "BUILD FAILED: " + (b.stdout + b.stderr)[-300:]
    t = subprocess.run([sys.executable, os.path.join(d, "tools", "test_rom.py"), "--core", "snes9x2002"],
                       capture_output=True, text=True, timeout=600)
    out = [l for l in t.stdout.splitlines() if l.startswith(("PASS", "FAIL"))]
    return name, (out[0] if out else t.stdout[-300:] + t.stderr[-300:])


if __name__ == "__main__":
    idx = [int(a) for a in sys.argv[1:]] or range(len(M))
    missed = 0
    with cf.ThreadPoolExecutor(4) as ex:
        for i, (name, res) in zip(idx, ex.map(run, idx)):
            caught = res.startswith("FAIL")
            missed += not caught
            print(f"{'caught' if caught else 'MISSED'} {i} {name}: {res[:200]}", flush=True)
    shutil.rmtree(WORK, ignore_errors=True)
    print(f"{len(idx) - missed} of {len(idx)} broken rules caught")
    sys.exit(1 if missed else 0)
