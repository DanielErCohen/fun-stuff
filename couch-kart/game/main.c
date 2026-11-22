/*---------------------------------------------------------------------------------
    Couch Kart: two players race three laps on one of four tracks, split screen,
    Mode 7 floor; a single race or a cup of four with points and a podium.

    Each half of the screen is 24 lines of sky and 88 lines of Mode 7 floor.
    HDMA rewrites the Mode 7 matrix on every line from tables precomputed for
    128 steering angles (tools/gen_assets.py), so the CPU only picks table rows
    and moves the karts each frame. Sky lines use a zero matrix centred on a
    sky-blue map tile.

    PVSnesLib quirks, each confirmed in emulators:
    - DMA channels 0 and 1 belong to the library (an HDMA table on channel 1
      hangs the frame loop), so HDMA uses channels 2 to 7.
    - The library's vblank code undoes HDMA set-up, so init_hdma() runs every
      frame; set up once, the floor stays flat.
    - Pointers to globals report bank 0, but the globals sit in bank $7E.
    - Registers are written through constant addresses (a macro), never an
      address computed at run time.
---------------------------------------------------------------------------------*/
#include <snes.h>
#include "res/cast.h"   // the animals: name, kart type and race tiles, from tools/characters.py
#include "res/layout.h" // race sprite tile numbers, from tools/gen_assets.py
#include "res/tracks.h" // the four tracks' data and facts, from tools/tracks.py

extern char persp_s, persp_t, drop_d, items_pic, battle_pic, leader_pic;
extern char shared_gfx, shared_pal, cast_pal, ui_gfx, ui_gfx_end, ui_pal, sin_table;
extern char select_obj_gfx, select_obj_pal, select_bg_gfx, select_bg_gfx_end, select_bg_map, select_bg_pal;

#define SKY_LINES 24
#define FLOOR_LINES 88
#define HALF 112
#define ROW_BYTES (FLOOR_LINES * 2)
#define D0 57         // camera distance behind the kart, map pixels (floor line 84 in the tables)
#define KART_LINE 108 // line in the half where the player's own kart touches the ground
#define NEAR_CONTACT 27 // ground row in a 32x32 kart frame (tools/characters.py NEAR); proj.asm's records hold the others
#define EDGE_SPEED 3  // speed left after hitting the map edge: enough to steer away

#define NK_MAX 6         // karts in the race data: the two players (0 and 1), then up to four computer karts
#define CPU_MAX 3        // computer karts at most. Not the one number to raise: the results screen has rows for 5 karts (a 6th would land on the START line), the busiest frame is measured with 3 (docs/engine.md "Computer karts"), and the race data holds 4
#define LAPS 3
#define COUNT_STEP 60   // frames each countdown number shows (60 Hz)
#define GO_FRAMES 60
#define AFTER_FIRST 600 // results 10 s after the first kart finishes...
#define AFTER_BOTH 90   // ...or 1.5 s after both have, so the second sees its banner
#define BUMP 10         // karts whose centres are closer than this (map pixels) on both axes touch

// Lap counting: each 16x16 cell of a track holds how far round the
// lap it lies, 0-255 (NCP checkpoints of 8 steps), or OFF_TRACK where nothing counts.
#define OFF_TRACK 255
#define WRONG_STEPS 3   // the wrong-way sign shows after this many steps of progress backwards
#define FINAL_FRAMES 90 // the final-lap banner shows 1.5 s

// Surfaces (tools/tracks.py S_*): what driving over an 8x8 tile does.
#define SURF_GRASS 0
#define SURF_ROAD 1
#define SURF_PAD 2
#define SURF_RAMP 3
#define SURF_OIL 4
#define SURF_SAND 5
#define SURF_FALL 6
// the ramp's air time (8 to 56 frames) and the trick's landing boost (40 frames) are constants in proj.asm
#define TRICK_SPIN 16   // the trick turns the kart once round in the air
#define FALL_FRAMES 60  // a kart in water or a pit is put back after 1 s
#define OB_REACH 12     // an obstacle hits a kart closer than this on both axes (map pixels)

#define ST_TITLE 0
#define ST_COUNTDOWN 1
#define ST_RACE 2
#define ST_RESULTS 3
#define ST_SELECT 4
#define ST_TRACKS 5
#define ST_PODIUM 6
#define CUP_RACES 4
#define ARENA 4         // the battle arena is the fifth floor
#define MENU_LAST 6     // the track menu: the cup, four tracks, balloon battle, coin battle
#define BALLOONS 3      // a balloon battle: each kart starts with 3; a hit or a fall pops one
#define COIN_TIME 3600  // a coin battle lasts 60 s
#define COIN_BACK 120   // in a coin battle a taken coin comes back every 2 s, one at a time
#define BATTLE_COINS 99 // a coin battle counts coins to 99; their speed counts only to 10
#define ARENA_COINS 24
// Cup points by place, for a kart that finished:
// the first row is the two-player cup (first 3, second 1), the second row a cup with computer karts (places 1 to 6, so
// a larger CPU_MAX cannot read past the table). A kart that did not finish scores 0.
const u8 cup_points[11] = {3, 1, 0, 0, 0, 9, 6, 4, 3, 2, 1};

// Race sprite VRAM (res/layout.h): player p's animal in tiles 128p to 128p+127, loaded at race
// start from the animal's own block; countdown and glyphs from tile 256.
#define NEAR_FRAME(p, v) (PLAYER_BLOCK(p) + near_off[v])
#define MID_FRAME(p, v) (PLAYER_BLOCK(p) + small_off[v])
#define FAR_FRAME(p, v) (PLAYER_BLOCK(p) + small_off[5 + (v)])
#define COUNT_FRAME(n) count_tile[3 - (n)] // 3, 2, 1; GO is count_tile[3] and [4]
#define GLYPH(g) glyph_tile[g]             // g indexes "0123456789/LAPSTNDFIH", then the flag
// Select screen sprite VRAM: portrait i as a 32x32 frame, four to a band of 4 tile rows, then
// the cursor halves from tile 320: player, locked, bottom half.
#define BIG_TILE(i) ((((i) >> 2) << 6) + (((i)&3) << 2))
#define CURSOR_TILE(p, lock, bottom) (320 + ((p) << 3) + ((lock) << 2) + ((bottom) << 1))
#define PAL_CURSOR 6
#define SEL_X 8   // portrait i sits at SEL_X + 40 * (i % 6), SEL_Y + 56 * (i / 6), as gen_assets.py draws its panel
#define SEL_Y 32
#define SEL_COLS 6
#if CAST % SEL_COLS
#error "the select screen's cursor wraps assume full rows of 6 animals"
#endif
#define START_WAIT 40 // frames between the second pick and the race, so both see their picks locked
#define REFUSE_FRAMES 30 // a refused pick flashes the cursor for half a second
#define G_SLASH 10
#define G_L 11
#define G_A 12
#define G_P 13
#define G_S 14
#define G_T 15
#define G_N 16
#define G_D 17
#define G_F 18
#define G_I 19
#define G_H 20
#define G_FLAG 21
#define PAL_WHITE 2
#define PAL_YELLOW 3
#define PAL_GREEN 4

// Sprite slots: 0-1 own karts, 2-3 the other kart in each half, then each half's HUD and banner,
// 40-47 the shots (four in each half, written by proj.asm), each half's item and coin counter,
// the sparks or flame at each own kart, 60-63 the moving obstacles (proj.asm), 64-67 the minimap
// dots (proj.asm), 70-71 each half's wrong-way sign, 72-75 the balloons, then the
// computer karts (76-79 in player 1's half, 80-83 in player 2's), their minimap dots (84-87, 88-91) and each
// half's minimap (92-93, after every dot so the dots draw on top of it).
// On the select screen: 0-3 the cursors (above the portraits), 4-21 the portraits.
#define HUD_SLOT(p) (4 + (p)*10)
#define BANNER_SLOT(p) (24 + (p)*8)
#define ITEM_SLOT(p) (48 + (p)*4) // then the coin, and the coin count's two digits
#define FX_SLOT(p) (56 + (p)*2)
#define MINI_SLOT(p) (92 + (p)) // behind every dot: a lower slot draws in front
#define WRONG_SLOT(p) (70 + (p))
#define BAL_SLOT(h) (72 + (h)*2) // in half h: the own kart's balloons, then the other kart's
#define SLOTS 94 // 76-79 and 80-83 the computer karts in each half, 84-87 and 88-91 their minimap dots in each half (proj.asm), 92-93 the minimaps
#define PAL_MINI 2 // the white text palette: its entries 6-9 are the minimap's and the balloons' colours, 10-14 the obstacle's
#define CGRAM_OB (128 + 2 * 16 + 10) // where the track's 5 obstacle colours go (colour number in sprite palette 2)
#define CGRAM_CPU(n) (128 + (6 + (n)) * 16) // sprite palettes 6 and 7: the computer animals' colours
#define MINI_X 8  // the minimap's corner in each half (proj.asm places the dots from it)
#define MINI_Y 76
#define WRONG_X 120
#define WRONG_Y 26
#define PAL_ITEMS 5
#define ITEM_X 104
#define COIN_X 128

// Things on the track: coins, item panels and
// dropped slime are painted into the floor map, one 16x16-pixel cell each; cells[] holds what lies
// in each cell, so a kart finds what it drives over with one read.
#define CELL_COIN 1
#define CELL_PANEL 2
#define CELL_PEEL 3
#define CELL_FAKE 4    // a fake item panel: drawn like a panel, it spins the kart that takes it
#define MAX_COINS 10   // each two coins add one step of top speed, so at most 5
#define COIN_LOSS 2    // coins a hit costs
#define ITEM_BOOST 1
#define ITEM_SHOT 2
#define ITEM_PEEL 3
#define ITEM_COINS 4
#define ITEM_HOMING 5  // the second set: a shot that chases the other kart
#define ITEM_BOOST3 6  // three boosts, shots or slimes, used one at a time
#define ITEM_SHOT3 7
#define ITEM_PEEL3 8
#define ITEM_SHIELD 9  // blocks one hit (or a shrink) for up to 10 s
#define ITEM_STAR 10   // 6 s of boost, no hits, spins the kart it touches (oil, water and pits still catch it)
#define ITEM_JUMP 11   // a high jump over slime, shots and water
#define ITEM_SHRINK 12 // the other kart turns small and slow for 4 s
#define ITEM_STEAL 13  // takes the other kart's item
#define ITEM_FAKE 14   // drops a fake item panel
#define ITEM_LEADER 15 // a comet that flies to the kart in first place over any floor (proj.asm move_shots), or to second place when its holder leads
#define CPU_RECHECK 8    // a computer kart with an item it cannot use yet looks again after this many frames
#define CPU_PATIENCE 300 // and uses it anyway after 5 s
#define CPU_GATE 136     // a computer kart's item decision runs only on a frame that has used fewer lines than this by the end of its work: the dearest decision (slime, 40 lines) then still fits the budget of 180
#define SHIELD_FRAMES 600
#define STAR_FRAMES 360
#define JUMP_FRAMES 36
#define SHRINK_FRAMES 240
#define HOME_TURN 4      // a homing shot turns this many of 128 steps every 4 frames
#define ROLL_FRAMES 60   // the item picture spins this long in the HUD
#define PANEL_TICKS 75   // a taken panel comes back after 75 ticks of 4 frames (5 s)
#define BOOST_FRAMES 120 // the boost item: 2 s above top speed, also on the grass
#define DRIFT_FRAMES 40
#define ROCKET_FRAMES 45
#define ROCKET_WINDOW 20 // the pedal goes down at most 20 frames before GO for a rocket start...
#define WHEELSPIN 45     // ...pressed earlier and held, the wheels spin for 45 frames at GO
#define SPIN_FRAMES 64   // a hit spins the kart for about a second, 4 turns
// a spinning kart turns its shown heading 8 of 128 steps a frame (SPIN_STEP in proj.asm)
#define SHOTS 4
#define SHOT_LIFE 360    // a shot flies 6 s at most
#define SHOT_GRACE 20    // frames before a shot can hit the kart that threw it
#define PEELS 4
#define HOP_FRAMES 8
#define DRIFT_MIN 12     // below this speed a drift ends
#define DRIFT_CHARGE 40  // charge for the drift boost: 20 to 40 frames of drifting
#define MQ 20            // floor map writes waiting for vblank: the worst frame queues 14

#define VMAIN (*(vuint8 *)0x2115)
#define VMADDL (*(vuint8 *)0x2116)
#define VMADDH (*(vuint8 *)0x2117)
#define VMDATAL (*(vuint8 *)0x2118)
#define VMDATAH (*(vuint8 *)0x2119)
#define BG1VOFS (*(vuint8 *)0x210E)
#define UI_TILES 0x4000 // Mode 1 data sits above the Mode 7 map and tiles (words 0-0x3FFF), which stay loaded
#define UI_MAP 0x5800

#define REG_SLHV_LATCH (*(vuint8 *)0x2137)
#define REG_OPVCT_READ (*(vuint8 *)0x213D)

// Kart types, read per kart by drive(): light, medium, heavy. Light karts pick up speed fastest
// and turn sharpest, heavy ones reach the highest top speed. The gaps are small: on today's oval a
// clean heavy lap is about 5% quicker than a clean light one, and two trips onto the grass or
// bumps lose that.
typedef struct
{
    s16 accel; // speed gained per frame with the pedal down, in 1/16 of a speed step
    s16 top;   // top speed on the road, 1/16 px per frame
    s16 turn;  // steering per frame, 1/256 of a table step
} KartType;

const KartType kart_types[3] = {
    {20, 39, 176}, // light: top speed in 32 frames
    {16, 40, 160}, // medium: top speed in 40 frames
    {12, 41, 144}, // heavy: top speed in 55 frames
};

typedef struct
{
    s16 x, y;     // position, 1/16 map pixel
    s16 speed;    // 1/16 px per frame
    u16 angle;    // high byte & 127 = table step, 0 = facing up the map
    s16 accx, accy;
} Kart;

Kart karts[NK_MAX]; // 0 and 1 the players, 2 to 5 the computer karts
u8 cpu_alt;      // 1 (the default): each half's computer karts are projected on alternate frames (30 Hz, half the cost, a shake of a few pixels while turning); 0: every frame
u8 cpu_hold;     // 1: the computer karts stay parked (the tests set it; the game never does)
u8 cpu_n;        // computer karts racing, 0 to CPU_MAX (0: the two-player race); battles always use 0
u8 cpu_menu;     // the track menu's choice of computer karts, 0 to CPU_MAX: CPU_MAX at power-on, kept until the power goes off
u8 kart_type[NK_MAX];  // each kart's type, from its animal
u8 accel_frac[NK_MAX]; // speed gained so far towards the next step, 1/16

// The track raced and its data in the ROM, set at race start; read by tools/test_rom.py by symbol name.
u8 track_no;
u8 *cur_map, *cur_surf, *cur_cells, *cur_prog;
u8 *cur_steer;      // the computer karts' steering map: a heading and a lift bit per 16x16 cell (proj.asm cpu_frame)
u8 floor_set[6][4]; // the 4 map tiles of each floor cell picture on this track (FLOOR_*)
u16 panel_cell[PANELS];
u8 tile_grass_dark;
u8 air_t[NK_MAX], air_len[NK_MAX]; // frames left in the air after a ramp, and the jump's length
u8 trick[NK_MAX];             // 1 once L or R was pressed in the air: a boost on landing
u8 trick_t[NK_MAX];           // frames left of the trick's turn in the air
u8 fall_t[NK_MAX];            // frames left before a kart in water or a pit is put back
u8 kart_lift[NK_MAX];         // how high each kart is drawn above the floor, lines (proj.asm reads it)
u16 rescues[NK_MAX];
u8 fine[NK_MAX];              // lap progress of the last cell on the track, 0-255
u8 wrong[NK_MAX];             // steps of progress backwards in a row
u8 wrong_shown[NK_MAX];  // (proj.asm reads it for every kart; only the players show the sign)
u8 banner_kind[2];       // what the banner slots spell: 0 FINISH, 1 FINAL LAP
u8 banner_t[2];          // frames before the final-lap banner goes
u8 finals[2];            // final-lap banners shown this race
// Moving obstacles, moved by proj.asm: position and step (1/16 px), frames each way, frames so far.
u8 ob_on[2];
s16 ob_x[2], ob_y[2], ob_dx[2], ob_dy[2];
u16 ob_len[2], ob_t[2];
u8 ob_struck[NK_MAX]; // set by move_obstacles when one touches that kart
// The cup: single race or cup, the race in the cup, each player's points, the menu cursor.
u8 cup_on, cup_race, menu_pos;
u8 battle;            // 0 a race, 1 a balloon battle, 2 a coin battle
u8 balloons[2];
u16 pops[2];
u16 battle_time;      // a coin battle's frames left
u8 lead_p;            // in a coin battle, the last to take the lead (it wins a tie)
u8 final_count[2];    // balloons or coins when a battle was decided
u16 coin_cell[ARENA_COINS];
u8 coin_cells, coin_next;
u16 coin_wait;
u8 clock_t;           // frames to the coin battle clock's next second
u8 points[NK_MAX];
u8 cup_winner;

// Pickups, items and tricks, read by tools/test_rom.py by symbol name.
u8 cells[4096];  // what lies in each 16x16 floor cell: 0, CELL_COIN, CELL_PANEL or CELL_PEEL
u8 coins[NK_MAX];
u8 item[NK_MAX];      // the item held, 0 for none
u8 roll[NK_MAX];      // frames left of the item picture spinning in the HUD
u8 roll_item[NK_MAX]; // the item it stops on
u8 hud_pic[2];   // the item picture each player's HUD should show, and the one copied into its tiles
u8 hud_shown[2];
u8 last_roll[NK_MAX]; // the draw 0-15 it came from
u8 cpu_use_t[NK_MAX]; // a computer kart's countdown to its next item decision (proj.asm kart_timers sets its bit in cpu_due at 0)
u8 cpu_due;           // the computer karts whose countdown ran out this frame, a bit each (race_frame runs cpu_item for them)
u16 cpu_age[NK_MAX];  // frames a computer kart has held its item without using it (or the random delay it chose)
u8 cpu_used[NK_MAX];  // items a computer kart has used this race (the tests read it)
u8 uses[NK_MAX];      // a triple item's uses left
u16 shield_t[NK_MAX]; // frames of shield left
u16 star_t[NK_MAX];
u8 shrink_t[NK_MAX];  // proj.asm reads it
u8 slip[2];      // ticks spent in the other kart's slipstream
u16 rng;
u8 panel_wait[PANELS]; // ticks until a taken panel comes back
u8 boost_t[NK_MAX];   // frames of boost left
u8 spin_t[NK_MAX];    // frames of spinning left after a hit
u8 spin_off[NK_MAX];  // heading the spinning kart shows, added to its real one (proj.asm reads it)
u8 hop_t[NK_MAX];
u8 wheelspin_t[NK_MAX];
s8 drift[NK_MAX];     // -1 drifting left, 1 right, 0 not
u8 charge[NK_MAX];
u8 press_t[2];   // countdown frames left when the pedal went down, 0 when it is up
u8 own_was[2];   // the own kart sprite showed a hop, spin or wheelspin last frame
u8 fx_was[2];    // what the sparks and flame slots showed last frame
u16 hits[NK_MAX];
u8 shot_on[SHOTS];   // 0 free, 1 a shot, 2 + k a leader shot flying to kart k (proj.asm move_shots, draw_objects)
s16 shot_x[SHOTS], shot_y[SHOTS], shot_dx[SHOTS], shot_dy[SHOTS];
u16 shot_life[SHOTS];
u8 shot_owner[SHOTS], shot_grace[SHOTS];
u8 shot_home[SHOTS]; // 0 a straight shot, else 1 + the kart a homing shot chases
u8 shot_ang[SHOTS];  // a homing shot's heading, 0-127
u8 shot_struck[NK_MAX]; // set by move_shots when a shot hits that kart
u8 next_shot;
u16 peel_cell[PEELS];
u8 peel_on[PEELS];
u8 next_peel;
u16 mq_addr[MQ];
u8 mq_a[MQ], mq_b[MQ];
u8 mq_n;
u16 pj_lines, pj_count; // proj.asm: lines its last call took, and the things it projected

// Panel draws, 16 each: the leader's, the kart behind's (second place) and the rest's (places 3 to 6, only with
// computer karts). Behind gets more boosts and shots, the rest more boosts, homing shots, stars and shrinks and the
// two leader shots; no draw gives two places the same item, so the test sees which table a draw used.
const u8 odds[48] = {
    // leader: 3 slime, 2 coins, 2 fake panels, 2 shields, 2 shots, then a boost, jump, triple slime, steal, homing shot
    3, 4, 3, 14, 9, 2, 1, 4, 3, 14, 9, 2, 11, 8, 13, 5,
    // behind: 2 each of boosts, homing shots, triple boosts, triple shots, stars, shrinks; a shot, steal, jump, shield
    1, 2, 5, 6, 7, 10, 12, 6, 1, 13, 7, 10, 12, 5, 11, 9,
    // places 3 to 6: 3 each of boosts, triple boosts, homing shots and stars, 2 each of shrinks and the leader shot
    6, 1, 10, 5, 12, 1, 6, 15, 10, 5, 6, 15, 10, 1, 5, 12,
};
const u8 hop_lift[HOP_FRAMES + 1] = {0, 1, 3, 5, 6, 6, 5, 3, 1};

// Race state, read by tools/test_rom.py by symbol name.
u8 game_state;
u8 lap[NK_MAX];      // start-line crossings: 1 during the first lap, LAPS + 1 once finished
u8 cp[NK_MAX];       // last checkpoint reached, 0 just past the start line (NCP a lap)
u8 finished[NK_MAX];
u8 rk_full;          // 1 for the one call of rank_all() that works out every kart (before the results are drawn)
u8 place[NK_MAX];
u8 done_count;
u8 winner;
u16 finish_time[NK_MAX]; // frames from GO
u16 race_time;
u16 prog[NK_MAX];
u16 timer;
u16 end_timer;
u16 bumps;
u8 frac[NK_MAX];        // where the kart is round its checkpoint: 8-15 inside it, 0-7 in the one before; kept off the track
u8 banner_left[2]; // finish banner sprites still to write, 2 per frame, so a finish frame stays in budget
u16 input_wait;    // frames before the results or select screen takes a button
u8 pick[2];        // each player's animal, an index into the cast
u8 cpu_pick[2];    // the computer karts' two animals (chosen at race start, or at the first race of a cup; neither a player's pick, different)
u8 cpu_loaded;     // how many of them have their frames in the shared tiles yet
u8 cpu_gfx_ready;  // 1 once both animals' frames are in video memory (the drawing checks it)
u8 leader_ready;   // 1 once the leader shot's picture is in the tiles the countdown's "O" held: the shot cannot be fired before
u8 cursor[2];      // the animal each player's cursor is on in the select screen
u8 locked[2];      // set once that player has picked
u16 start_wait;    // frames left before the race once both have picked
u8 refuse_t[2];    // frames left of a cursor flashing because its pick was refused
u8 hdma_a[13], hdma_b[13], hdma_c[13], hdma_d[13], hdma_scroll[11], hdma_center[21];
u16 pend_row[2][4];
s16 pend_cx[2], pend_cy[2];
u16 s_addr, t_addr, s_zero, t_zero;
u8 s_bank, t_bank;
dmaMemory mem;

// Read back by tools/retro_run.py: logic iterations completed, and the most
// lines of a frame the logic has needed counted from the start of vblank.
u16 frames_done;
u16 max_lines;
// Per-phase cost, read by tools/test_rom.py --phases, which builds the ROM with PROBES 1: probe() in
// proj.asm stores the line counter (0-261) at the boundaries between the phases of a frame in
// phase_line[]; measure() copies the table to phase_best[] when the frame sets a new max_lines, and the
// count of probes to phase_cnt. A probe costs about 0.45 line (7 lines for the 15 of a frame, measured), too much to ship, so PROBES is 0 in the ROM that is released and in the normal test.
#define PROBES 0
u16 phase_line[24];
u16 pv_n;                // bytes of phase_line[] used this frame
u16 phase_best[24];
u16 phase_cnt;
#if PROBES
void probe(void);
#define PROBE() probe()
#else
#define PROBE()
#endif

s16 sin_at(u16 idx)
{
    return ((s16 *)&sin_table)[idx & 127];
}

// Finds the perspective tables: each starts with a zero word, the rows follow.
s16 shot_step[128]; // a shot's step along x for each heading, 4 px a frame: sin / 4 (y is -shot_step[a + 32])

void init_tables(void)
{
    u8 i;
    for (i = 0; i < 128; i++)
        shot_step[i] = sin_at(i) / 4; // a table: tcc-816 divides with a library call
    mem.mem.p = (u8 *)&persp_s;
    s_zero = mem.mem.c.addr;
    s_addr = s_zero + 2;
    s_bank = mem.mem.c.bank;
    mem.mem.p = (u8 *)&persp_t;
    t_zero = mem.mem.c.addr;
    t_addr = t_zero + 2;
    t_bank = mem.mem.c.bank;
}

// High OAM table: two bits per sprite (x bit 8, large size), four sprites per byte.
// Tables, because tcc-816 compiles a shift by a variable as a loop.
const u8 hi_keep[4] = {0xFC, 0xF3, 0xCF, 0x3F};
const u8 hi_bits[16] = {0, 1, 2, 3, 0, 4, 8, 12, 0, 16, 32, 48, 0, 64, 128, 192};

// In proj.asm: a sprite written straight into the library's OAM copy, and the projection of the
// other kart and the shots into each half.
void spr(u8 slot, s16 x, u8 y, u16 tile, u8 pal, u8 flip, u8 large);
void draw_objects(void);
u8 move_shots(void);     // returns a bit per kart with shot_struck set
u8 move_obstacles(void); // likewise for ob_struck
void minimap(void);
void camera_both(void); // both players' cameras
void camera(u8 p); // the camera D0 pixels behind kart p, and the perspective table rows for its angle
void move_kart(u8 p); // kart p a frame along its heading at its speed
void init_hdma(void); // every race frame right after vblank starts: see the quirks at the top

// Line 224 is below the picture, and a sprite up to 32 lines tall there does not wrap to the top.
void hide(u8 slot)
{
    oamMemory[(slot << 2) + 1] = 224;
}

void hide_range(u8 first, u8 count)
{
    while (count--)
        hide(first++);
}

// Surface under a point in 1/16 map pixels (SURF_*).
u8 surface_at(s16 x, s16 y)
{
    return cur_surf[(((u16)y >> 7) << 7) + ((u16)x >> 7)];
}

// drive() is in game/proj.asm (it ran every frame for each kart and cost about 10 lines in C): the
// floor's top speed and the boost pad, spinning and falling, the boost, the pedal and the brake, then
// steering and the drift, then move_kart(). Its constants (MAX_GRASS, PAD_FRAMES, BOOST_EXTRA) are there.
void drive(u8 p, u16 pad);
void cpu_frame(void); // proj.asm: every racing computer kart steers by the steering map and drives one frame
void slipstream(void); // proj.asm: close behind the other kart for 1 s gives a boost; its constants are there

// Karts that touch are pushed apart along the axis they overlap least on, and both lose a quarter of their
// speed. bump_all() in game/proj.asm does it for every pair of karts (NKARTS there) and returns the karts
// a star kart touched, which hit() spins here. keep_all() holds every kart on the map.
void hit(u8 p);
u8 bump_all(void);
void keep_all(void);

void glyph_at(u8 slot, s16 x, u8 y, u8 g, u8 pal)
{
    spr(slot, x, y, GLYPH(g), pal, 0, 0);
}

void hud_lap(u8 p)
{
    u8 shown;
    if (p > 1)
        return; // only the players have a HUD
    if (battle)
        return;
    shown = lap[p] < 1 ? 1 : (lap[p] > LAPS ? LAPS : lap[p]);
    glyph_at(HUD_SLOT(p) + 3, 52, p * HALF + 4, shown, PAL_WHITE);
}

// "1ST", "2ND", "3RD", "4TH", "5TH", "6TH": the R has no HUD letter and is a tile of its own (TILE_GR).
void hud_place(u8 p)
{
    u8 s, y, n;
    if (p > 1)
        return;
    if (battle)
        return;
    s = HUD_SLOT(p) + 6;
    y = p * HALF + 4;
    n = place[p];
    glyph_at(s, 212, y, n, PAL_YELLOW);
    if (n == 3)
        spr(s + 1, 224, y, TILE_GR, PAL_YELLOW, 0, 0);
    else
        glyph_at(s + 1, 224, y, n == 1 ? G_S : (n == 2 ? G_N : G_T), PAL_YELLOW);
    glyph_at(s + 2, 236, y, n == 1 ? G_T : (n == 2 || n == 3 ? G_D : G_H), PAL_YELLOW);
}

void hud_static(u8 p)
{
    u8 s, y;
    s = HUD_SLOT(p);
    y = p * HALF + 4;
    if (!battle)
    {
        glyph_at(s, 8, y, G_L, PAL_WHITE);
        glyph_at(s + 1, 20, y, G_A, PAL_WHITE);
        glyph_at(s + 2, 32, y, G_P, PAL_WHITE);
        glyph_at(s + 4, 64, y, G_SLASH, PAL_WHITE);
        glyph_at(s + 5, 76, y, LAPS, PAL_WHITE);
    }
    spr(s + 9, 190, y, MID_FRAME(p, 4), p, 0, 0); // the player's animal, facing out
    spr(ITEM_SLOT(p) + 1, COIN_X, y, TILE_COIN, PAL_ITEMS, 0, 0);
}

// n = 3, 2 or 1 shows that number in both halves, 0 shows GO.
void banner_count(u8 n)
{
    u8 p, s, y;
    for (p = 0; p < 2; p++)
    {
        s = BANNER_SLOT(p);
        y = p * HALF + 36;
        if (n)
        {
            spr(s, 112, y, COUNT_FRAME(n), PAL_YELLOW, 0, 1);
            hide(s + 1);
        }
        else
        {
            spr(s, 96, y, count_tile[3], PAL_GREEN, 0, 1);
            spr(s + 1, 128, y, count_tile[4], PAL_GREEN, 0, 1);
        }
    }
}

// "FINISH" between two flags, or "FINAL LAP" in green (banner_kind), written 2 sprites a frame from
// banner_left by banner_step() in proj.asm: a whole banner costs about as much as the rest of the frame's logic.
void banner_step(u8 p);

void final_lap(u8 p)
{
    banner_kind[p] = 1;
    banner_left[p] = 8;
    banner_t[p] = FINAL_FRAMES;
    finals[p]++;
}

u16 cell_of(s16 x, s16 y)
{
    return (((u16)y >> 8) << 6) + ((u16)x >> 8);
}

// Laps: progress() in game/proj.asm reads the track's lap progress under the kart every frame (8 steps a
// checkpoint), notes steps backwards for the wrong-way sign and moves the checkpoint on only to the next
// one, so cutting across reaches a later checkpoint out of order and gains nothing; off the track nothing
// counts. It returns 1 when the kart reaches checkpoint 0 (a lap, handled here) and 2 when the wrong-way
// sign should change.
u8 progress(u8 p);
u16 progress_cpu(void); // the same for every computer kart: bit k of the low byte a lap, of the high byte the sign
void wrong_way(u8 p);

// A kart reached checkpoint 0: lap_next() in proj.asm counts the lap and, past LAPS, finishes the kart (see there);
// otherwise the lap counter and the final-lap banner are drawn here.
u8 lap_next(u8 p);

void lap_done(u8 p)
{
    if (lap_next(p))
        return;
    hud_lap(p);
    if (lap[p] == LAPS && p < 2)
        final_lap(p); // the banner is the players' (its arrays hold two)
}

u8 progress_players(void); // both players': bits 0 and 1 a lap and a sign change for player 1, bits 2 and 3 for player 2
void clock_step(void);
u16 frame_lines(void);     // the lines of the frame used so far, as measure() counts them
u8 busy_flags(void);       // bit p own_kart(p) has work, 2 + p effects(p), 4 + p banner_step(p)

// The sign above the kart while it drives the wrong way (progress() says when it changes).
void wrong_way(u8 p)
{
    wrong_shown[p] ^= 1;
    if (p > 1)
        return; // a computer kart has no sign
    if (wrong_shown[p])
        spr(WRONG_SLOT(p), WRONG_X, p * HALF + WRONG_Y, TILE_WRONG_WAY, PAL_ITEMS, 0, 0);
    else
        hide(WRONG_SLOT(p));
}

// In a battle the kart with more balloons or coins leads (both count as behind on a tie), so the panel
// draws give the trailing kart the catch-up items; battle_over() sets the final places.
void battle_places(void)
{
    u8 a, b;
    if (done_count)
        return;
    a = battle == 1 ? balloons[0] : coins[0];
    b = battle == 1 ? balloons[1] : coins[1];
    place[0] = a > b ? 1 : 2;
    place[1] = b > a ? 1 : 2;
}

u8 rank_all(void); // proj.asm: places from progress, the karts whose place changed as bits

// rank_all() also places the karts that have not finished behind the ones that have, by progress.
void positions(void)
{
    u8 lead;
    if (battle)
    {
        battle_places();
        return;
    }
    lead = rank_all();
    if (lead & 1)
        hud_place(0);
    if (lead & 2)
        hud_place(1);
}

// ---------------------------------------------------------------- pickups, items and tricks

// The HUD item picture: its tiles are copied into the player's HUD frame in the next vblank (load_hud).
void hud_item(u8 p, u8 it)
{
    if (p > 1)
        return; // a computer kart has no item box
    if (it)
    {
        hud_pic[p] = it;
        spr(ITEM_SLOT(p), ITEM_X, p * HALF + 4, hud_tile[p], PAL_ITEMS, 0, 0);
    }
    else
        hide(ITEM_SLOT(p));
}

// In vblank: a changed HUD picture's top two tiles, then its bottom two 16 tiles further in the sheet.
void load_hud(void)
{
    u8 p;
    u8 *src;
    u16 dst;
    for (p = 0; p < 2; p++)
    {
        if (hud_pic[p] == hud_shown[p])
            continue;
        hud_shown[p] = hud_pic[p];
        src = &items_pic + ((hud_pic[p] - 1) << 7);
        dst = 0x6000 + (hud_tile[p] << 4);
        dmaCopyVram(src, dst, 64);
        dmaCopyVram(src + 64, dst + 256, 64);
    }
}

// The coin counter: a coin and one or two digits.
void hud_coins(u8 p)
{
    u8 s, y;
    if (p > 1)
        return;
    s = ITEM_SLOT(p) + 2;
    y = p * HALF + 4;
    if (coins[p] > coins[1 - p])
        lead_p = p;
    if (coins[1 - p] > coins[p])
        lead_p = 1 - p; // a hit took the lead away
    if (coins[p] >= 10)
    {
        glyph_at(s, COIN_X + 14, y, coins[p] / 10, PAL_YELLOW);
        glyph_at(s + 1, COIN_X + 26, y, coins[p] % 10, PAL_YELLOW);
    }
    else
    {
        glyph_at(s, COIN_X + 14, y, coins[p], PAL_YELLOW);
        hide(s + 1);
    }
}

// Two map writes per 16x16 cell, done in the next vblank by flush_map(): VRAM takes writes only then.
void queue_cell(u16 c, const u8 *t)
{
    u16 addr;
    if (mq_n > MQ - 2)
        return;
    addr = ((c >> 6) << 8) + ((c & 63) << 1); // tile row 2y, column 2x
    mq_addr[mq_n] = addr;
    mq_a[mq_n] = t[0];
    mq_b[mq_n] = t[1];
    mq_addr[mq_n + 1] = addr + 128;
    mq_a[mq_n + 1] = t[2];
    mq_b[mq_n + 1] = t[3];
    mq_n += 2;
}

// The cell's floor as the track draws it, without a coin or panel: road where one started.
void restore_cell(u16 c)
{
    u16 addr;
    u8 t[4];
    if (cur_cells[c])
    {
        queue_cell(c, floor_set[FLOOR_ROAD]);
        return;
    }
    addr = ((c >> 6) << 8) + ((c & 63) << 1);
    t[0] = cur_map[addr];
    t[1] = cur_map[addr + 1];
    t[2] = cur_map[addr + 128];
    t[3] = cur_map[addr + 129];
    queue_cell(c, t);
}

void flush_map(void)
{
    u8 i;
    VMAIN = 0; // the Mode 7 map is the low byte of each word: step after the low byte
    for (i = 0; i < mq_n; i++)
    {
        VMADDL = mq_addr[i] & 255;
        VMADDH = mq_addr[i] >> 8;
        VMDATAL = mq_a[i];
        VMDATAL = mq_b[i];
    }
    mq_n = 0;
}

void remove_peel(u16 c)
{
    u8 i;
    for (i = 0; i < PEELS; i++)
        if (peel_on[i] && peel_cell[i] == c)
            peel_on[i] = 0;
    cells[c] = 0;
    restore_cell(c);
}

// A battle ends: the winner first, the results 1.5 s later.
void battle_over(u8 w)
{
    if (done_count)
        return;
    final_count[0] = battle == 1 ? balloons[0] : coins[0]; // the results show these, not what the 1.5 s after changes
    final_count[1] = battle == 1 ? balloons[1] : coins[1];
    winner = w;
    place[w] = 1;
    place[1 - w] = 2;
    done_count = 2;
    end_timer = AFTER_BOTH;
}

// In a balloon battle a hit or a fall pops a balloon; the kart with none left loses.
void pop(u8 p)
{
    if (battle != 1) // separate ifs: tcc-816 compiled "battle != 1 || !balloons[p]" to run the body (docs/engine.md)
        return;
    if (!balloons[p])
        return;
    balloons[p]--;
    pops[p]++;
    if (!balloons[p])
        battle_over(1 - p);
}

void shield_off(u8 p)
{
    shield_t[p] = 0;
    hud_item(p, 0);
}

// Oil spins the kart for about a second and ends its tricks.
void spin_out(u8 p)
{
    if (spin_t[p])
        return;
    spin_t[p] = SPIN_FRAMES;
    boost_t[p] = 0;
    drift[p] = 0;
    charge[p] = 0;
    hop_t[p] = 0;
}

// A hit (a shot, slime, an obstacle) spins the kart and also costs it coins.
void hit(u8 p)
{
    if (spin_t[p])
        return;
    if (star_t[p])
        return;
    if (shield_t[p])
    {
        shield_off(p);
        return;
    }
    spin_out(p);
    coins[p] = coins[p] > COIN_LOSS ? coins[p] - COIN_LOSS : 0;
    hud_coins(p);
    hits[p]++;
    pop(p);
}

// A kart in water or a pit is put back in the middle of its last checkpoint, facing on, and loses coins.
void rescue(u8 p)
{
    const s16 *r;
    r = &trk_rescue[(track_no * NCP + cp[p]) * 3];
    karts[p].x = r[0] << 4;
    karts[p].y = r[1] << 4;
    karts[p].angle = r[2];
    karts[p].speed = 0;
    karts[p].accx = 0;
    karts[p].accy = 0;
    coins[p] = coins[p] > COIN_LOSS ? coins[p] - COIN_LOSS : 0;
    hud_coins(p);
    rescues[p]++;
    pop(p);
}

// After the karts have moved, ground_all() in game/proj.asm does the floor's work for every kart: a ramp
// lifts it, one frame per speed step, so faster jumps go further; oil spins it; water and pits swallow it.
// In the air the floor does nothing, and landing ends the jump with the ramp trick's boost when L or R
// was pressed up there. It returns the karts whose fall just ended, which rescue() puts back (this file).
u8 ground_all(void);
u8 kart_timers(void); // proj.asm: the spin, trick, wheelspin, shield and star countdowns; returns the karts whose shield ended
u8 floor_scan(void);  // proj.asm: the karts on the ground over a coin, a panel or slime

// What kart p drives over: a coin, an item panel or slime (called only when floor_scan() found something).
void floor_things(u8 p)
{
    u16 c;
    u8 v, i;
    c = cell_of(karts[p].x, karts[p].y);
    v = cells[c];
    if (!v)
        return; // the other kart on the same cell took it
    if (v == CELL_COIN)
    {
        cells[c] = 0;
        queue_cell(c, floor_set[FLOOR_ROAD]);
        if (coins[p] < (battle == 2 ? BATTLE_COINS : MAX_COINS))
        {
            coins[p]++;
            hud_coins(p);
        }
    }
    else if (v == CELL_PANEL)
    {
        if (item[p])
            return;
        if (roll[p])
            return;
        if (shield_t[p])
            return; // the shield's picture holds the item box
        cells[c] = 0;
        queue_cell(c, floor_set[FLOOR_ROAD]);
        for (i = 0; i < PANELS; i++)
            if (panel_cell[i] == c)
                panel_wait[i] = PANEL_TICKS;
        last_roll[p] = rng & 15;
        roll_item[p] = odds[(place[p] == 1 ? 0 : (place[p] == 2 ? 16 : 32)) + last_roll[p]]; // the leader's table, second place's, or the rest's
        roll[p] = ROLL_FRAMES;
        if (p > 1)
            cpu_use_t[p] = ROLL_FRAMES; // a computer kart's roll ends, and its item decision starts, when this runs out
    }
    else
    {
        remove_peel(c);
        hit(p);
    }
}

// The coin battle's clock in each half where the lap count shows in a race: seconds left.
void hud_clock(void)
{
    u8 p, s;
    s = (battle_time + 59) / 60; // whole seconds left, rounded up: 60 at the start, 1 in the last second
    for (p = 0; p < 2; p++)
    {
        glyph_at(HUD_SLOT(p), 8, p * HALF + 4, s / 10, PAL_WHITE);
        glyph_at(HUD_SLOT(p) + 1, 20, p * HALF + 4, s % 10, PAL_WHITE);
    }
}

// A balloon picture over the lap letters (start_race copies them): player p's n balloons.
u16 bal_tile(u8 p, u8 n)
{
    return glyph_tile[G_L + p * 3 + n - 1];
}

// Balloons over each kart in both halves: the own kart's above its sprite, the other kart's above where
// draw_objects() put it (slot 2 or 3), hidden when it is not in view or the balloons would cross the half.
void balloon_sprites(void)
{
    u8 h, o, y, box;
    s16 x;
    for (h = 0; h < 2; h++)
    {
        if (balloons[h] && !fall_t[h])
            spr(BAL_SLOT(h), 120, h * HALF + KART_LINE - NEAR_CONTACT - kart_lift[h] - 13, bal_tile(h, balloons[h]), PAL_MINI, 0, 0);
        else
            hide(BAL_SLOT(h));
        o = (2 + h) << 2;
        y = oamMemory[o + 1];
        box = (oamMemory[512] >> (((2 + h) << 1) + 1)) & 1 ? 32 : 16;
        if (y == 224)
            y = 0;
        if (!balloons[1 - h])
            y = 0;
        if (y < h * HALF + 12)
        {
            hide(BAL_SLOT(h) + 1);
            continue;
        }
        x = oamMemory[o] + (box >> 1) - 8;
        spr(BAL_SLOT(h) + 1, x, y - 12, bal_tile(1 - h, balloons[1 - h]), PAL_MINI, 0, 0);
    }
}

// Each battle frame: the coin battle's clock and its coins coming back; the balloons.
void battle_frame(void)
{
    u8 i;
    u16 c;
    if (battle == 1)
    {
        balloon_sprites();
        return;
    }
    if (battle_time && !--battle_time)
        battle_over(coins[0] > coins[1] ? 0 : (coins[1] > coins[0] ? 1 : lead_p));
    if (!--clock_t)
    {
        clock_t = 60;
        hud_clock();
    }
    if (--coin_wait)
        return;
    coin_wait = COIN_BACK;
    for (i = 0; i < coin_cells; i++)
    {
        c = coin_cell[coin_next];
        if (++coin_next == coin_cells)
            coin_next = 0;
        if (!cells[c])
        {
            cells[c] = CELL_COIN;
            queue_cell(c, floor_set[FLOOR_COIN]);
            return;
        }
    }
}

// One panel a frame, each every 4 frames: a taken panel comes back once its cell is free.
void panel_tick(void)
{
    u8 i;
    i = race_time & 3;
    if (!panel_wait[i] || --panel_wait[i])
        return;
    if (cells[panel_cell[i]])
    {
        panel_wait[i] = 1;
        return;
    }
    cells[panel_cell[i]] = CELL_PANEL;
    queue_cell(panel_cell[i], floor_set[FLOOR_PANEL]);
}

// The kart of place `want` that has not finished and is not p, searching on from `want` away from p's own place
// (ahead: towards first place, else towards last); 255 when there is none.
u8 unfinished_at(u8 p, u8 want, u8 ahead)
{
    u8 k, i;
    for (i = 0; i < 2 + cpu_n; i++)
    {
        if (want < 1)
            break;
        for (k = 0; k < 2 + cpu_n; k++)
            if (k != p && place[k] == want && !finished[k])
                return k;
        if (ahead)
            want--;
        else
            want++;
    }
    return 255;
}

// The kart an item aimed at another kart (a homing shot, a shrink, a steal) takes for p: the other player in
// a two-player race or a battle; with computer karts racing, the kart directly ahead in place, or the one
// directly behind for the leader. A kart that has finished is passed over for the next one that has not (further
// ahead, or further back for the leader); when every one has finished the choice stays the kart directly ahead or behind.
u8 target_of(u8 p)
{
    u8 k, want, ahead;
    if (!cpu_n)
        return 1 - p;
    ahead = place[p] > 1;
    want = ahead ? place[p] - 1 : 2;
    k = unfinished_at(p, want, ahead);
    if (k != 255)
        return k;
    for (k = 0; k < 2 + cpu_n; k++)
        if (k != p && place[k] == want)
            return k;
    return p == 0 ? 1 : 0;
}

// The kart the leader shot flies to for kart p: the one in first place, or the one in second when p leads; a kart that
// has finished is passed over for the next place back, unless all of them have.
u8 leader_of(u8 p)
{
    u8 k, want;
    want = place[p] == 1 ? 2 : 1;
    k = unfinished_at(p, want, 0);
    if (k != 255)
        return k;
    for (k = 0; k < 2 + cpu_n; k++)
        if (k != p && place[k] == want)
            return k;
    return p == 0 ? 1 : 0;
}

// kind 0 a straight shot, 1 a homing shot, 2 a leader shot (shot_on holds 2 + its target)
void fire_shot(u8 p, u8 kind)
{
    u8 i;
    u16 idx;
    i = next_shot;
    next_shot = (i + 1) & (SHOTS - 1);
    idx = (karts[p].angle >> 8) & 127;
    shot_ang[i] = idx;
    shot_home[i] = kind == 1 ? 1 + target_of(p) : 0;
    shot_dx[i] = shot_step[idx];
    shot_dy[i] = -shot_step[(idx + 32) & 127];
    shot_x[i] = karts[p].x + shot_dx[i] * 5; // 20 px ahead, kept on the map: move_shots bounces off its edge
    shot_y[i] = karts[p].y + shot_dy[i] * 5;
    if (shot_x[i] < 0)
        shot_x[i] = 0;
    if (shot_x[i] > 16383)
        shot_x[i] = 16383;
    if (shot_y[i] < 0)
        shot_y[i] = 0;
    if (shot_y[i] > 16383)
        shot_y[i] = 16383;
    shot_life[i] = SHOT_LIFE;
    shot_owner[i] = p;
    shot_grace[i] = SHOT_GRACE;
    shot_on[i] = kind == 2 ? 2 + leader_of(p) : 1;
}

// Slime drops 24 px behind the kart into a free cell; the oldest of 4 goes when a fifth is dropped.
u8 drop_peel(u8 p, u8 kind)
{
    u16 idx, c, addr;
    s16 bx, by;
    u8 i, t, set;
    idx = (karts[p].angle >> 8) & 127;
    bx = (karts[p].x >> 4) - ((s16 *)&drop_d)[idx]; // 24 * sin / 256, a table: no multiply
    by = (karts[p].y >> 4) + ((s16 *)&drop_d)[(idx + 32) & 127];
    if (bx < 0 || bx > 1023 || by < 0 || by > 1023)
        return 0;
    c = ((by >> 4) << 6) + (bx >> 4);
    if (cells[c])
        return 0;
    addr = ((c >> 6) << 8) + ((c & 63) << 1);
    t = cur_surf[addr];
    if (t != SURF_ROAD && t != SURF_GRASS)
        return 0; // slime lies on road or off-road, not in water, sand, oil or on a ramp
    i = next_peel;
    next_peel = (i + 1) & (PEELS - 1);
    if (peel_on[i])
        remove_peel(peel_cell[i]);
    peel_cell[i] = c;
    peel_on[i] = 1;
    cells[c] = kind;
    t = cur_map[addr];
    set = t == 0 ? FLOOR_SLIME_GRASS : (t == tile_grass_dark ? FLOOR_SLIME_DARK : FLOOR_SLIME_ROAD);
    if (kind == CELL_FAKE)
        set = FLOOR_PANEL;
    queue_cell(c, floor_set[set]);
    return 1;
}

// One homing shot every frame, so each turns every 4 frames: towards the side the other kart is on.
// steer_fast() in proj.asm does it all. A shot whose step no longer matches its heading, because it
// bounced or turned at a corner, takes its new heading first: the mirror, a quarter turn back or on, or
// straight up, down, left or right; one turned some other way flies straight (shot_home 0).
void steer_fast(void);

// The other kart shrinks, unless a star makes it immune or its shield takes the blow.
void shrink(u8 o)
{
    if (star_t[o])
        return;
    if (shield_t[o])
    {
        shield_off(o);
        return;
    }
    shrink_t[o] = SHRINK_FRAMES;
    drift[o] = 0;
    charge[o] = 0;
}

// A shrunk kart counts down in ground_all() (proj.asm); drive() there holds it to SHRINK_TOP, boost or not.

void use_item(u8 p)
{
    u8 it, base, o;
    it = item[p];
    base = it;
    if (it == ITEM_BOOST3)
        base = ITEM_BOOST;
    if (it == ITEM_SHOT3)
        base = ITEM_SHOT;
    if (it == ITEM_PEEL3)
        base = ITEM_PEEL;
    o = target_of(p);
    if (base == ITEM_BOOST)
        boost_t[p] = BOOST_FRAMES;
    else if (base == ITEM_SHOT)
        fire_shot(p, 0);
    else if (base == ITEM_HOMING)
        fire_shot(p, 1);
    else if (base == ITEM_LEADER)
    {
        if (!leader_ready)
            return; // its picture is not in video memory yet (the countdown's "O" still holds the O): keep it
        fire_shot(p, 2);
    }
    else if (base == ITEM_PEEL)
    {
        if (!drop_peel(p, CELL_PEEL))
            return; // no free cell behind: keep it
    }
    else if (base == ITEM_FAKE)
    {
        if (!drop_peel(p, CELL_FAKE))
            return;
    }
    else if (base == ITEM_SHIELD)
    {
        shield_t[p] = SHIELD_FRAMES;
        item[p] = 0;
        hud_item(p, ITEM_SHIELD); // its picture stays while the shield lasts
        return;
    }
    else if (base == ITEM_STAR)
        star_t[p] = STAR_FRAMES;
    else if (base == ITEM_JUMP)
    {
        if (air_t[p])
            return;
        air_t[p] = JUMP_FRAMES;
        air_len[p] = JUMP_FRAMES;
        trick[p] = 0;
        hop_t[p] = 0;
        drift[p] = 0;
        charge[p] = 0;
    }
    else if (base == ITEM_SHRINK)
        shrink(o);
    else if (base == ITEM_STEAL)
    {
        if (!item[o])
            return; // nothing to take: keep it
        item[p] = item[o];
        uses[p] = uses[o];
        item[o] = 0;
        hud_item(o, 0);
        hud_item(p, item[p]);
        return;
    }
    else
    {
        coins[p] += 2;
        if (coins[p] > (battle == 2 ? BATTLE_COINS : MAX_COINS))
            coins[p] = battle == 2 ? BATTLE_COINS : MAX_COINS;
        hud_coins(p);
    }
    if (it != base)
    {
        // a triple keeps its picture for two more uses, then shows the single item for the last
        if (--uses[p] > 1)
            return;
        item[p] = base;
        hud_item(p, base);
        return;
    }
    item[p] = 0;
    hud_item(p, 0);
}

// ---------------------------------------------------------------- computer karts use items

// Does a kart other than p lie within `reach` (64 x px) ahead of kart p (ahead 1) or behind it (ahead 0) and within 24 px
// of its line? Four products a look, so it runs only for a computer kart with a shot or slime to place, every few frames.
u8 cpu_sees(u8 p, u8 ahead, s16 reach)
{
    u8 k, idx;
    s16 dx, dy, hx, hy, fwd, side;
    idx = (karts[p].angle >> 8) & 127;
    hx = shot_step[idx]; // the heading, 64 for a whole step
    hy = -shot_step[(idx + 32) & 127];
    for (k = 0; k < 2 + cpu_n; k++)
    {
        if (k == p)
            continue;
        dx = (karts[k].x >> 4) - (karts[p].x >> 4);
        dy = (karts[k].y >> 4) - (karts[p].y >> 4);
        if (dx > 160)
            continue;
        if (dx < -160)
            continue;
        if (dy > 160)
            continue;
        if (dy < -160)
            continue;
        fwd = dx * hx + dy * hy;
        side = dx * hy - dy * hx;
        if (!ahead)
            fwd = -fwd;
        if (fwd > 0 && fwd < reach && side < 1536 && side > -1536)
            return 1;
    }
    return 0;
}

// Is there water, a pit or oil 24 or 48 px ahead of kart p?
u8 cpu_wet_ahead(u8 p)
{
    u8 idx, i, s;
    s16 x, y;
    idx = (karts[p].angle >> 8) & 127;
    for (i = 6; i <= 12; i += 6)
    {
        x = karts[p].x + shot_step[idx] * i;
        y = karts[p].y - shot_step[(idx + 32) & 127] * i;
        if ((u16)x > 16383)
            continue;
        if ((u16)y > 16383)
            continue;
        s = surface_at(x, y);
        if (s == SURF_OIL)
            return 1;
        if (s == SURF_FALL)
            return 1;
    }
    return 0;
}

// The items a computer kart uses after a short random delay.
u8 cpu_delayed(u8 base)
{
    if (base == ITEM_HOMING)
        return 1;
    if (base == ITEM_LEADER)
        return 1;
    if (base == ITEM_SHRINK)
        return 1;
    if (base == ITEM_STEAL)
        return 1;
    return 0;
}

// Computer kart p's countdown ran out: first its roll ends (no HUD), then it decides whether to use the item it holds:
// boosts off the tight bends, stars, shields and coins at once, shots when a kart lies ahead, slime and the fake panel
// when one lies behind, a jump before water or oil, homing and leader shots, shrinks and steals after a random 0.5 to
// 2 s; one that is not usable yet is looked at again every CPU_RECHECK frames and used anyway after CPU_PATIENCE.
// The use is use_item(p), so the item does what a player's does.
void cpu_item(u8 p)
{
    u8 it, base, ok, u;
    u16 d;
    if (finished[p])
        return; // a kart that has finished uses nothing
    if (roll[p])
    {
        roll[p] = 0;
        item[p] = roll_item[p];
        uses[p] = 3;
        cpu_age[p] = 0;
    }
    it = item[p];
    if (!it)
        return;
    if (spin_t[p] | fall_t[p])
    {
        cpu_use_t[p] = CPU_RECHECK; // a spinning or sinking kart uses nothing
        return;
    }
    base = it;
    if (it == ITEM_BOOST3)
        base = ITEM_BOOST;
    if (it == ITEM_SHOT3)
        base = ITEM_SHOT;
    if (it == ITEM_PEEL3)
        base = ITEM_PEEL;
    ok = 1;
    if (base == ITEM_BOOST)
        ok = !(cur_steer[cell_of(karts[p].x, karts[p].y)] & 128);
    else if (base == ITEM_SHOT)
        ok = cpu_sees(p, 1, 10240);
    else if (base == ITEM_PEEL)
        ok = cpu_sees(p, 0, 7680);
    else if (base == ITEM_FAKE)
        ok = cpu_sees(p, 0, 7680);
    else if (base == ITEM_JUMP)
        ok = cpu_wet_ahead(p);
    else if (cpu_delayed(base))
    {
        if (!cpu_age[p])
        {
            d = rng & 127;
            if (d > 90)
                d -= 91;
            cpu_age[p] = 30 + d; // the delay, 30 to 120 frames
            cpu_use_t[p] = 30 + d;
            return;
        }
    }
    if (!ok)
    {
        cpu_age[p] += CPU_RECHECK;
        if (cpu_age[p] < CPU_PATIENCE)
        {
            cpu_use_t[p] = CPU_RECHECK;
            return;
        }
    }
    u = uses[p];
    use_item(p);
    if (item[p] == it && uses[p] == u)
    {
        // nothing was used (no free cell for slime, nothing to steal, already in the air, the leader shot's picture not loaded): look again, and drop it after CPU_PATIENCE
        cpu_age[p] += CPU_RECHECK;
        if (cpu_age[p] >= CPU_PATIENCE)
            item[p] = 0;
        else
            cpu_use_t[p] = CPU_RECHECK;
        return;
    }
    cpu_used[p]++;
    cpu_age[p] = 0;
    if (item[p])
        cpu_use_t[p] = 45; // a triple item's next use
}

// One of the computer karts whose countdown ran out (kart_timers() in proj.asm sets their bits): the lowest, once a frame.
// race_frame() calls it at the end of the frame, and only when the frame has used fewer than CPU_GATE lines, so a decision
// (10 to 40 lines in C) never lands on a frame that is already busy: it waits for a lighter one.
void cpu_items(void)
{
    u8 p, b;
    for (p = 2, b = 4; p < NK_MAX; p++, b <<= 1)
        if (cpu_due & b)
        {
            cpu_due &= ~b;
            cpu_item(p);
            return;
        }
}

// The item picture spins through the 4 items, then stops on the one drawn.
void roll_step(u8 p)
{
    if (!roll[p])
        return;
    if (!--roll[p])
    {
        item[p] = roll_item[p];
        uses[p] = 3;
        hud_item(p, item[p]);
    }
    else if (!(roll[p] & 3))
        hud_item(p, ((roll[p] >> 2) & 3) + 1);
}

// Hop on L or R; landing with L or R still held and the D-pad pushed starts a drift that way.
// Letting go after enough charge gives a short boost.
void tricks(u8 p, u16 pad, u16 down)
{
    if (spin_t[p])
        return;
    if (fall_t[p])
        return;
    if (air_t[p])
    {
        // the ramp trick: L or R in the air turns the kart once round and boosts it on landing
        if ((down & (KEY_L | KEY_R)) && !trick[p])
        {
            trick[p] = 1;
            trick_t[p] = TRICK_SPIN;
        }
        return;
    }
    if ((down & (KEY_L | KEY_R)) && !hop_t[p] && !drift[p])
        hop_t[p] = HOP_FRAMES;
    if (hop_t[p])
    {
        if (!--hop_t[p] && (pad & (KEY_L | KEY_R)) && (pad & (KEY_LEFT | KEY_RIGHT)) && karts[p].speed >= DRIFT_MIN)
        {
            drift[p] = (pad & KEY_LEFT) ? -1 : 1;
            charge[p] = 0;
        }
    }
    else if (drift[p] && (!(pad & (KEY_L | KEY_R)) || karts[p].speed < DRIFT_MIN))
    {
        if (charge[p] >= DRIFT_CHARGE && boost_t[p] < DRIFT_FRAMES)
            boost_t[p] = DRIFT_FRAMES;
        drift[p] = 0;
        charge[p] = 0;
    }
}

// The own kart: lifted while it hops or flies off a ramp, turning through its views while it spins or does
// the ramp trick, shaking while its wheels spin, and sinking out of sight after falling in.
void own_kart(u8 p)
{
    u8 sector, view, flip, special, pal;
    special = spin_t[p] || hop_t[p] || wheelspin_t[p] || air_t[p] || trick_t[p] || fall_t[p] || star_t[p] || shrink_t[p];
    if (!special && !own_was[p])
        return;
    own_was[p] = special;
    if (fall_t[p])
    {
        if (fall_t[p] > FALL_FRAMES - 16)
            spr(p, 120, p * HALF + KART_LINE - 13, MID_FRAME(p, 0), p, 0, 0);
        else if (fall_t[p] > FALL_FRAMES - 32)
            spr(p, 120, p * HALF + KART_LINE - 10, FAR_FRAME(p, 0), p, 0, 0);
        else
            hide(p);
        return;
    }
    sector = ((spin_off[p] + 8) >> 4) & 7;
    view = sector <= 4 ? sector : 8 - sector;
    flip = sector > 4;
    if (wheelspin_t[p])
        flip = (wheelspin_t[p] >> 2) & 1;
    pal = p;
    if (star_t[p] & 4)
        pal = PAL_YELLOW; // a star flashes the kart
    if (shrink_t[p])
        spr(p, 120, p * HALF + KART_LINE - 13 - kart_lift[p], MID_FRAME(p, view), pal, flip, 0);
    else
        spr(p, 112, p * HALF + KART_LINE - NEAR_CONTACT - kart_lift[p], NEAR_FRAME(p, view), pal, flip, 1);
}

// Sparks at the wheels once a drift has charged, a flame behind a boosting kart.
void effects(u8 p)
{
    u8 now, y, odd;
    now = (drift[p] && charge[p] >= DRIFT_CHARGE) ? 1 : (boost_t[p] ? 2 : 0);
    if (!now && !fx_was[p])
        return;
    fx_was[p] = now;
    y = p * HALF + KART_LINE - 14; // 16 lines ending above the half's last line, at the wheels
    odd = frames_done & 1;
    if (now == 1)
    {
        spr(FX_SLOT(p), 102, y + 2, odd ? TILE_SPARK1 : TILE_SPARK0, PAL_ITEMS, 0, 0);
        spr(FX_SLOT(p) + 1, 138, y + 2, odd ? TILE_SPARK0 : TILE_SPARK1, PAL_ITEMS, 0, 0);
    }
    else if (now == 2)
    {
        // beside the wheels: a flame behind the kart would be hidden by its sprite, which is drawn in front
        spr(FX_SLOT(p), 100, y, odd ? TILE_FLAME1 : TILE_FLAME0, PAL_ITEMS, odd, 0);
        spr(FX_SLOT(p) + 1, 140, y, odd ? TILE_FLAME0 : TILE_FLAME1, PAL_ITEMS, !odd, 0);
    }
    else
        hide_range(FX_SLOT(p), 2);
}

// Each frame of a race for player p: the item roll, using an item, tricks (the countdowns are in kart_timers()).
void kart_frame(u8 p, u16 pad, u16 down)
{
    u8 busy;
    if (roll[p])
        roll_step(p);
    if ((down & KEY_X) && item[p] && !spin_t[p] && !fall_t[p])
        use_item(p);
    busy = hop_t[p] | drift[p]; // tricks() does nothing without a hop, a drift or L or R pressed
    if (down & (KEY_L | KEY_R))
        busy = 1;
    if (busy)
        tricks(p, pad, down);
}

// Before GO: the pedal pressed at most ROCKET_WINDOW frames before GO gives a rocket start; pressed
// earlier and held, the wheels spin.
void countdown_pedal(u8 p)
{
    if (padsCurrent(p) & (KEY_B | KEY_A))
    {
        if (!press_t[p])
            press_t[p] = timer;
    }
    else
        press_t[p] = 0;
}

void rocket_start(u8 p)
{
    if (!press_t[p])
        return;
    if (press_t[p] <= ROCKET_WINDOW)
        boost_t[p] = ROCKET_FRAMES;
    else
        wheelspin_t[p] = WHEELSPIN;
}


void measure(void)
{
    u16 line, used;
    line = REG_STAT78;     // resets the counter read order
    line = REG_SLHV_LATCH; // assigned, because tcc-816 drops a bare read and the latch never fires
    line = REG_OPVCT_READ;
    line |= (REG_OPVCT_READ & 1) << 8;
    used = line >= 225 ? line - 225 : line + 37;
    if (used > max_lines)
    {
        max_lines = used;
#if PROBES
        phase_cnt = pv_n >> 1;
        for (line = 0; line < 24; line++)
            phase_best[line] = phase_line[line];
#endif
    }
    pv_n = 0;
}

// ---------------------------------------------------------------- title and results (Mode 1)

void vram_at(u16 addr)
{
    VMAIN = 0x80;
    VMADDL = addr & 255;
    VMADDH = addr >> 8;
}

// Small letters, palette 0 white or 1 yellow. The screen is off, so VRAM can be written directly.
void text(u8 x, u8 y, const char *str, u8 pal)
{
    vram_at(UI_MAP + (y << 5) + x);
    while (*str)
    {
        VMDATAL = (*str >= 32 && *str < 96) ? *str - 32 : 0;
        VMDATAH = pal << 2;
        str++;
    }
}

u8 big_index(char c)
{
    if (c >= 'A' && c <= 'Z')
        return c - 'A';
    return c == '!' ? 26 : 27;
}

// Big 16x16 letters, two map rows tall.
void big_text(u8 x, u8 y, const char *str)
{
    const char *c;
    u16 t;
    for (c = str; *c; c++, x += 2)
    {
        if (*c == ' ')
            continue;
        t = 64 + (big_index(*c) << 2);
        vram_at(UI_MAP + (y << 5) + x);
        VMDATAL = t;
        VMDATAH = 0;
        VMDATAL = t + 1;
        VMDATAH = 0;
        vram_at(UI_MAP + ((y + 1) << 5) + x);
        VMDATAL = t + 2;
        VMDATAH = 0;
        VMDATAL = t + 3;
        VMDATAH = 0;
    }
}

u8 str_len(const char *str)
{
    u8 n;
    for (n = 0; str[n]; n++)
        ;
    return n;
}

// Small letters centred on column cx.
void text_mid(u8 cx, u8 y, const char *str, u8 pal)
{
    text(cx - (str_len(str) >> 1), y, str, pal);
}

// Screen off, Mode 1 with one background; every sprite hidden.
void mode1_screen(void)
{
    setScreenOff();
    REG_HDMAEN = 0;
    setMode(BG_MODE1, 0);
    bgSetDisable(1);
    bgSetDisable(2);
    bgSetGfxPtr(0, UI_TILES);
    bgSetMapPtr(0, UI_MAP, SC_32x32);
    bgSetScroll(0, 0, 0);
    hide_range(0, SLOTS);
}

// The title and results screens: letters loaded and the map cleared. The race sprites stay loaded.
void ui_screen(void)
{
    u16 i;
    mode1_screen();
    dmaCopyVram(&ui_gfx, UI_TILES, (&ui_gfx_end - &ui_gfx));
    dmaCopyCGram(&ui_pal, 0, 64);
    vram_at(UI_MAP);
    for (i = 0; i < 1024; i++)
    {
        VMDATAL = 0;
        VMDATAH = 0;
    }
}

void show_title(void)
{
    ui_screen();
    big_text(6, 4, "COUCH KART");
    spr(0, 48, 80, NEAR_FRAME(0, 4), 0, 0, 1);
    spr(1, 176, 80, NEAR_FRAME(1, 4), 1, 0, 1);
    text_mid(8, 15, "PLAYER 1", 0);
    text_mid(24, 15, "PLAYER 2", 0);
    text_mid(8, 16, cast_names[pick[0]], 1);
    text_mid(24, 16, cast_names[pick[1]], 1);
    text(10, 21, "PRESS START", 1);
    game_state = ST_TITLE;
    setScreenOn();
}

// "M:SS.CC" from frames at 60 per second.
void time_text(char *buf, u16 f)
{
    u16 m, s, c;
    m = f / 3600;
    if (m > 9)
    {
        m = 9;
        f = 35999;
    }
    f -= m * 3600;
    s = f / 60;
    c = ((f - s * 60) * 100) / 60;
    buf[0] = '0' + m;
    buf[1] = ':';
    buf[2] = '0' + s / 10;
    buf[3] = '0' + s % 10;
    buf[4] = '.';
    buf[5] = '0' + c / 10;
    buf[6] = '0' + c % 10;
    buf[7] = 0;
}

// "12 POINTS"-style number: one or two digits then the word.
void points_text(u8 x, u8 y, u8 n, const char *word)
{
    char buf[12];
    u8 i, k;
    i = 0;
    if (n >= 10)
        buf[i++] = '0' + n / 10;
    buf[i++] = '0' + n % 10;
    buf[i++] = ' ';
    for (k = 0; word[k]; k++)
        buf[i++] = word[k];
    buf[i] = 0;
    text(x, y, buf, 1);
}

const char *const place_name[NK_MAX + 1] = {"", "1ST", "2ND", "3RD", "4TH", "5TH", "6TH"};

// Who drives kart k; a computer kart is numbered by its kart number (kart 2 is COMPUTER 1), the same on every screen.
const char *const driver_name[NK_MAX] = {"PLAYER 1", "PLAYER 2", "COMPUTER 1", "COMPUTER 2", "COMPUTER 3", "COMPUTER 4"};

void result_row(u8 p, u8 row)
{
    char buf[12];
    text(7, row, place_name[place[p]], 1);
    text(11, row, cast_names[pick[p]], 0);
    text(11, row + 1, p ? "PLAYER 2" : "PLAYER 1", 0);
    if (battle == 1)
    {
        if (final_count[p])
            points_text(22, row + 1, final_count[p], final_count[p] == 1 ? "BALLOON" : "BALLOONS"); // on the driver's line: the longest name ends at column 21 on the line above
        else
            text(22, row + 1, "OUT", 0);
    }
    else if (battle == 2)
        points_text(22, row + 1, final_count[p], "COINS");
    else if (finished[p])
    {
        time_text(buf, finish_time[p]);
        text(23, row, buf, 0);
    }
    else
        text(23, row, "NO TIME", 0);
    if (cup_on)
        points_text(23, row + 1, points[p], "POINTS");
    spr(p, 16, row * 8 - 12, NEAR_FRAME(p, 4), p, 0, 1);
}

// The animal of kart k: a player's pick, or one of the two computer animals.
u8 animal_of(u8 k)
{
    return k < 2 ? pick[k] : cpu_pick[(k - 2) & 1];
}

// With computer karts: kart k's place, animal, who drives it, its time or NO TIME, and its cup points, on two text rows.
void result_row_cpu(u8 k, u8 row)
{
    char buf[12];
    text(7, row, place_name[place[k]], 1);
    text(11, row, cast_names[animal_of(k)], 0);
    text(11, row + 1, driver_name[k], 0);
    if (finished[k])
    {
        time_text(buf, finish_time[k]);
        text(23, row, buf, 0);
    }
    else
        text(23, row, "NO TIME", 0);
    if (cup_on)
        points_text(23, row + 1, points[k], "POINTS");
}

// "<NAME> WINS!" in big letters, 16 to a line: on two lines when the name is long.
void winner_text(u8 animal)
{
    const char *name;
    char buf[18];
    u8 n, i;
    name = cast_names[animal];
    n = str_len(name);
    if (n + 6 <= 16)
    {
        for (i = 0; i < n; i++)
            buf[i] = name[i];
        buf[n] = ' ';
        for (i = 0; i < 5; i++)
            buf[n + 1 + i] = "WINS!"[i];
        buf[n + 6] = 0;
        big_text(16 - (n + 6), 5, buf);
    }
    else
    {
        big_text(16 - n, 4, name);
        big_text(11, 6, "WINS!");
    }
}

void show_results(void)
{
    char head[2];
    u8 k, r;
    ui_screen();
    if (cpu_n)
    {
        rk_full = 1; // rank_all() works out one kart in four a frame: every kart now, so no two share a place
        rank_all();
        rk_full = 0;
    }
    if (cup_on)
    {
        // cup points by place for the karts that finished (cup_points)
        if (!cpu_n)
        {
            points[winner] += cup_points[0];
            if (finished[1 - winner])
                points[1 - winner] += cup_points[1];
        }
        else
            for (k = 0; k < 2 + cpu_n; k++)
                if (finished[k])
                    points[k] += cup_points[5 + place[k] - 1];
        text_mid(16, 2, "CUP RACE 1 OF 4", 0);
        head[0] = '1' + cup_race; // over the 1: "CUP RACE " is 9 letters from column 9
        head[1] = 0;
        text(18, 2, head, 0);
    }
    else if (battle)
        text_mid(16, 2, battle == 1 ? "BALLOON BATTLE" : "COIN BATTLE", 0);
    else
        text_mid(16, 2, trk_names[track_no], 0);
    if (cpu_n)
    {
        // every kart in place order, three text rows apart, from row 9: no pictures
        for (r = 1; r <= 2 + cpu_n; r++)
            for (k = 0; k < 2 + cpu_n; k++)
                if (place[k] == r)
                {
                    if (r == 1)
                        winner_text(animal_of(k));
                    result_row_cpu(k, 6 + 3 * r);
                }
        r = 24;
        k = 26;
    }
    else
    {
        winner_text(pick[winner]);
        result_row(winner, 11);
        result_row(1 - winner, 16);
        r = 22;
        k = 24;
    }
    text(7, r, "START", 1);
    if (!cup_on)
        text(14, r, "RACE AGAIN", 0);
    else if (cup_race < CUP_RACES - 1)
        text(14, r, "NEXT RACE", 0);
    else
        text(14, r, "SEE THE PODIUM", 0);
    text(7, k, "SELECT", 1);
    text(14, k, "PICK ANIMALS", 0);
    input_wait = 60; // a button still held from the race does not skip the results
    game_state = ST_RESULTS;
    setScreenOn();
}

// ---------------------------------------------------------------- select screen (Mode 1)

void start_race(void);
void show_tracks(void);

// Player p's cursor: half brackets on the left (player 1) or right (player 2) edge of a portrait.
void sel_cursor(u8 p)
{
    s16 x;
    u8 y, c;
    c = cursor[p];
    x = SEL_X + 40 * (c % SEL_COLS) + (p ? 22 : -6);
    y = SEL_Y + 56 * (c / SEL_COLS);
    spr(p << 1, x, y - 2, CURSOR_TILE(p, locked[p], 0), PAL_CURSOR, 0, 0);
    spr((p << 1) + 1, x, y + 14, CURSOR_TILE(p, locked[p], 1), PAL_CURSOR, 0, 0);
}

// Both players' cursors start on their last picks. Loads the portraits over the race sprites,
// so the race reloads its own.
void show_select(void)
{
    u8 i, p;
    mode1_screen();
    dmaCopyVram(&select_bg_gfx, UI_TILES, (&select_bg_gfx_end - &select_bg_gfx));
    dmaCopyVram(&select_bg_map, UI_MAP, 2048);
    dmaCopyCGram(&select_bg_pal, 0, 256);
    dmaCopyVram(&select_obj_gfx, 0x6000, 384 * 32);
    dmaCopyCGram(&select_obj_pal, 128, 7 * 32);
    for (i = 0; i < CAST; i++)
        spr(4 + i, SEL_X + 40 * (i % SEL_COLS), SEL_Y + 56 * (i / SEL_COLS), BIG_TILE(i), i / 3, 0, 1);
    for (p = 0; p < 2; p++)
    {
        cursor[p] = pick[p];
        locked[p] = 0;
        refuse_t[p] = 0;
        sel_cursor(p);
    }
    input_wait = 20; // the Start that opened this screen does not pick
    game_state = ST_SELECT;
    setScreenOn();
}

// Both players move and pick at once. An animal the other player has picked cannot be picked, and
// the cursor flashes; if both pick the same one on the same frame, player 1 gets it. Y undoes a
// locked pick until the race starts.
void select_frame(void)
{
    u8 p, c;
    u16 down;
    if (input_wait)
    {
        input_wait--;
        return;
    }
    for (p = 0; p < 2; p++)
    {
        if (refuse_t[p])
        {
            refuse_t[p]--;
            if (refuse_t[p] & 4)
                hide_range(p << 1, 2);
            else
                sel_cursor(p);
        }
        if (locked[p] && (padsDown(p) & KEY_Y))
        {
            locked[p] = 0;
            sel_cursor(p);
        }
    }
    if (locked[0] && locked[1])
    {
        if (!--start_wait)
            show_tracks();
        return;
    }
    for (p = 0; p < 2; p++)
    {
        if (locked[p])
            continue;
        down = padsDown(p);
        c = cursor[p];
        if (down & KEY_LEFT)
            c = (c % SEL_COLS) ? c - 1 : c + SEL_COLS - 1;
        else if (down & KEY_RIGHT)
            c = (c % SEL_COLS == SEL_COLS - 1) ? c - (SEL_COLS - 1) : c + 1;
        else if (down & KEY_UP)
            c = c >= SEL_COLS ? c - SEL_COLS : c + CAST - SEL_COLS;
        else if (down & KEY_DOWN)
            c = c < CAST - SEL_COLS ? c + SEL_COLS : c - (CAST - SEL_COLS);
        if (c != cursor[p])
        {
            cursor[p] = c;
            sel_cursor(p);
        }
        if (down & (KEY_B | KEY_START))
        {
            if (locked[1 - p] && pick[1 - p] == c)
                refuse_t[p] = REFUSE_FRAMES;
            else
            {
                pick[p] = c;
                locked[p] = 1;
                refuse_t[p] = 0;
                sel_cursor(p);
                start_wait = START_WAIT;
            }
        }
    }
}

// ---------------------------------------------------------------- race (Mode 7)

// With the screen off: each player's animal into its sprite tiles and palette, then the shared tiles.
void load_race_gfx(void)
{
    dmaCopyVram(cast_gfx[pick[0]], 0x6000, 4096);
    dmaCopyVram(cast_gfx[pick[1]], 0x6800, 4096);
    dmaCopyVram(&shared_gfx, 0x7000, 8192);
    dmaCopyCGram(&cast_pal + (pick[0] << 5), 128, 32);
    dmaCopyCGram(&cast_pal + (pick[1] << 5), 144, 32);
    dmaCopyCGram(&shared_pal, 160, 128); // palettes 2-5: text (palette 2 also holds the minimap's colours), items
    dmaCopyCGram(&cast_pal + (cpu_pick[0] << 5), CGRAM_CPU(0), 32); // the computer animals
    dmaCopyCGram(&cast_pal + (cpu_pick[1] << 5), CGRAM_CPU(1), 32);
}

// The k-th animal that neither player picked and that is not `skip` (255: none).
u8 free_animal(u8 k, u8 skip)
{
    u8 i, ok;
    for (i = 0; i < CAST; i++)
    {
        ok = (i != pick[0]) & (i != pick[1]) & (i != skip);
        if (ok)
        {
            if (!k)
                break;
            k--;
        }
    }
    return i;
}

// Two animals for the computer karts from the ones nobody picked, different from each other.
// A cup keeps them from its first race to its last.
void choose_cpu(void)
{
    u8 keep;
    keep = cup_on;
    if (!cup_race)
        keep = 0; // (no `a || b` here: tcc-816 miscompiles it, see docs/engine.md)
    if (!keep)
    {
        cpu_pick[0] = free_animal((rng & 255) % (CAST - 2), 255);
        cpu_pick[1] = free_animal(((rng >> 8) & 255) % (CAST - 3), cpu_pick[0]);
    }
    cpu_loaded = 0;
    cpu_gfx_ready = 0;
    leader_ready = 0;
}

// In vblank, once GO has gone and the countdown's big digits are no longer shown: one computer animal's
// frames a frame (4 copies of tile rows, 1,024 bytes) into the band of shared tiles where the digits were.
void load_cpu_gfx(void)
{
    u8 i;
    if (!cpu_gfx_ready && game_state == ST_RACE && !timer && !battle)
    {
        for (i = 0; i < CPU_COPIES; i++)
            dmaCopyVram(cast_gfx[cpu_pick[cpu_loaded]] + cpu_src[i], 0x6000 + ((CPU_BASE + (cpu_loaded << 5) + cpu_dst[i]) << 4), cpu_len[i]);
        cpu_loaded++;
        cpu_gfx_ready = cpu_loaded == 2;
    }
}

// In vblank, once the animals' frames are in (or in a battle, which has none): the leader shot's three pictures into the
// 16 tiles that held the "O" of GO, which is hidden by now. Four copies of one tile row.
void load_leader_gfx(void)
{
    u8 i, ok;
    ok = cpu_gfx_ready;
    if (battle)
        ok = 1;
    if (!ok)
        return;
    if (leader_ready)
        return;
    if (game_state != ST_RACE)
        return;
    if (timer)
        return;
    for (i = 0; i < 4; i++)
        dmaCopyVram(&leader_pic + (i << 7), 0x6000 + ((TILE_LEADER + (i << 4)) << 4), 128);
    leader_ready = 1;
}

// With the screen off: track t's tiles, map, colours and minimap, and its facts into RAM.
void load_track(u8 t)
{
    u16 i;
    const s16 *o;
    track_no = t;
    cur_map = trk_map[t];
    cur_surf = trk_surf[t];
    cur_cells = trk_cells[t];
    cur_prog = trk_prog[t];
    cur_steer = trk_steer[t];
    dmaCopyCGram(trk_pal[t], 0, 512);
    // the tiles are the high byte of each VRAM word, the map the low byte; coins, panels and slime come
    // back as the track starts: the map, and what lies in each cell
    dmaCopyVram7(trk_tiles[t], 0, trk_tiles_size[t], VRAM_INCHIGH | VRAM_ADRSTINC_1, 0x1900);
    dmaCopyVram7(cur_map, 0, 0x4000, VRAM_INCLOW | VRAM_ADRSTINC_1, 0x1800);
    for (i = 0; i < 4096; i++)
        cells[i] = cur_cells[i];
    for (i = 0; i < 24; i++)
        floor_set[i >> 2][i & 3] = trk_floor[t * 24 + i];
    for (i = 0; i < PANELS; i++)
    {
        panel_cell[i] = trk_panels[t * PANELS + i];
        panel_wait[i] = 0;
    }
    tile_grass_dark = trk_grass_dark[t];
    for (i = 0; i < 2; i++)
    {
        o = &trk_obstacles[t * 10 + i * 5];
        ob_x[i] = o[0];
        ob_y[i] = o[1];
        ob_dx[i] = o[2];
        ob_dy[i] = o[3];
        ob_len[i] = o[4];
        ob_t[i] = 0;
        ob_on[i] = o[4] != 0;
        ob_struck[i] = 0;
    }
    load_race_gfx();
    hud_pic[0] = hud_pic[1] = hud_shown[0] = hud_shown[1] = 0; // the HUD frames were just cleared
    // the minimap: a 32x32 frame, four rows of 4 tiles 16 apart in the sheet, then the obstacle colours
    for (i = 0; i < 4; i++)
        dmaCopyVram(trk_mini[t] + (i << 7), 0x6000 + ((TILE_MINIMAP + (i << 4)) << 4), 128);
    dmaCopyCGram(trk_obpal[t], CGRAM_OB, 10);
}

void start_race(void)
{
    u8 p;
    u16 i;
    setScreenOff();
    REG_HDMAEN = 0;
    setMode7(0xC0); // outside the map repeats tile 0, plain grass
    if (battle)
        cpu_n = 0; // battles are between the two players
    if (cpu_n > CPU_MAX)
        cpu_n = CPU_MAX;
    choose_cpu();
    load_track(track_no);
    if (battle == 1)
        for (i = 0; i < 6; i++) // the balloons over the lap and banner letters
        {
            dmaCopyVram(&battle_pic + (i << 7), 0x6000 + (glyph_tile[G_L + i] << 4), 64);
            dmaCopyVram(&battle_pic + (i << 7) + 64, 0x6000 + ((glyph_tile[G_L + i] + 16) << 4), 64);
        }
    coin_cells = trk_ncoins[track_no];
    for (i = 0; i < coin_cells; i++)
        coin_cell[i] = trk_coins[track_no * ARENA_COINS + i];
    battle_time = COIN_TIME;
    clock_t = 1;
    coin_wait = COIN_BACK;
    coin_next = 0;
    for (i = 0; i < SHOTS; i++)
    {
        shot_on[i] = 0;
        shot_home[i] = 0;
    }
    for (i = 0; i < NK_MAX; i++)
        shot_struck[i] = ob_struck[i] = 0;
    oamMemory[522] = oamMemory[523] = 0; // the shots' high bits: small, x below 256 (proj.asm)
    oamMemory[527] = oamMemory[528] = 0; // the obstacles' and the minimap dots' high bits: small, x below 256
    oamMemory[531] = oamMemory[532] = oamMemory[533] = oamMemory[534] = 0; // the computer karts' and their dots': likewise
    for (i = 0; i < PEELS; i++)
        peel_on[i] = 0;
    mq_n = 0;
    hide_range(0, SLOTS);

    // the grid: the players side by side 20 px before the start line, facing along the road, then the computer
    // karts in two rows behind them (tools/tracks.py GRID_BACK); karts that do not race still sit on their places
    for (p = 0; p < NK_MAX; p++)
    {
        karts[p].x = trk_grid[track_no * 12 + p * 2] << 4;
        karts[p].y = trk_grid[track_no * 12 + p * 2 + 1] << 4;
        karts[p].speed = 0;
        karts[p].angle = trk_angle[track_no * 6 + p];
        karts[p].accx = 0;
        karts[p].accy = 0;
        kart_type[p] = p < 2 ? cast_type[pick[p]] : cast_type[cpu_pick[(p - 2) & 1]];
        accel_frac[p] = 0;
        lap[p] = 0;
        cp[p] = NCP - 1;
        fine[p] = cur_prog[cell_of(karts[p].x, karts[p].y)];
        finished[p] = 0;
        finish_time[p] = 0;
        place[p] = p + 1;
        frac[p] = 0;
        prog[p] = 0;
        coins[p] = 0;
        item[p] = 0;
        roll[p] = 0;
        boost_t[p] = 0;
        spin_t[p] = 0;
        spin_off[p] = 0;
        hop_t[p] = 0;
        wheelspin_t[p] = 0;
        drift[p] = 0;
        charge[p] = 0;
        air_t[p] = 0;
        trick[p] = 0;
        trick_t[p] = 0;
        fall_t[p] = 0;
        kart_lift[p] = 0;
        wrong[p] = 0;
        wrong_shown[p] = 0;
        uses[p] = 0;
        shield_t[p] = 0;
        star_t[p] = 0;
        shrink_t[p] = 0;
        cpu_use_t[p] = 0;
        cpu_age[p] = 0;
        cpu_used[p] = 0;
    }
    cpu_due = 0;
    for (p = 0; p < 2; p++)
    {
        banner_left[p] = 0;
        press_t[p] = 0;
        own_was[p] = 0;
        fx_was[p] = 0;
        banner_kind[p] = 0;
        banner_t[p] = 0;
        finals[p] = 0;
        balloons[p] = BALLOONS;
        pops[p] = 0;
        slip[p] = 0;
        spr(MINI_SLOT(p), MINI_X, p * HALF + MINI_Y, TILE_MINIMAP, PAL_MINI, 0, 1);
        spr(p, 112, p * HALF + KART_LINE - NEAR_CONTACT, NEAR_FRAME(p, 0), p, 0, 1);
        hud_static(p);
        hud_lap(p);
        hud_place(p);
        hud_coins(p);
        camera(p);
    }
    done_count = 0;
    winner = 0;
    lead_p = 0; // after the coin counters: hud_coins() sets it from the coins
    if (battle == 2)
        hud_clock(); // the clock shows during the countdown too
    race_time = 0;
    end_timer = 0;
    timer = 3 * COUNT_STEP;
    banner_count(3);
    game_state = ST_COUNTDOWN;
    setScreenOn();
    init_hdma();
}

void race_frame(void)
{
    u8 p, m, n, b;
    u16 pad, down, lead;
    clock_step(); // the random number, and once the countdown is over the race clock and the banner timers
    if (game_state == ST_COUNTDOWN)
    {
        countdown_pedal(0);
        countdown_pedal(1);
        timer--;
        if (timer == 2 * COUNT_STEP)
            banner_count(2);
        else if (timer == COUNT_STEP)
            banner_count(1);
        else if (timer == 0)
        {
            banner_count(0);
            game_state = ST_RACE;
            timer = GO_FRAMES;
            rocket_start(0);
            rocket_start(1);
        }
    }

    if (game_state == ST_RACE)
    {
        m = kart_timers();
        if (m & 1)
            hud_item(0, 0); // the shield ran out
        if (m & 2)
            hud_item(1, 0);
    }
    PROBE();
    for (p = 0; p < 2; p++)
    {
        pad = 0;
        if (game_state == ST_RACE)
        {
            down = 0;
            if (!finished[p])
            {
                pad = padsCurrent(p);
                down = padsDown(p);
            }
            if (roll[p] | hop_t[p] | drift[p] | (down & (KEY_X | KEY_L | KEY_R))) // kart_frame() does nothing otherwise
                kart_frame(p, pad, down);
        }
        drive(p, pad);
    }
    PROBE();
    if (cpu_n)
        cpu_frame();
    PROBE();
    if (game_state == ST_RACE)
    {
        m = ground_all();
        if (m)
            for (p = 0, b = 1; p < NK_MAX; p++, b <<= 1)
                if (m & b)
                    rescue(p);
    }
    PROBE();
    m = bump_all();
    if (m)
        for (p = 0, b = 1; p < NK_MAX; p++, b <<= 1)
            if (m & b)
                hit(p);
    keep_all();
    PROBE();
    camera_both();
    PROBE();
    if (game_state == ST_RACE)
    {
        m = floor_scan();
        if (m)
            for (p = 0, b = 1; p < NK_MAX; p++, b <<= 1)
                if (m & b)
                    floor_things(p);
        PROBE();
        steer_fast();
        PROBE();
        m = move_shots();
        PROBE();
        n = move_obstacles();
        if (n)
            for (p = 0; p < NK_MAX; p++)
                if (ob_struck[p])
                {
                    ob_struck[p] = 0;
                    if (!air_t[p] && !fall_t[p])
                        hit(p);
                }
        if (m)
            for (p = 0; p < NK_MAX; p++)
                if (shot_struck[p])
                {
                    shot_struck[p] = 0;
                    if (!air_t[p])
                        if (!fall_t[p])
                            hit(p); // a jumping or sinking kart takes no harm from the shot
                }
        PROBE();
        slipstream();
        PROBE();
        panel_tick();
        PROBE();
        m = progress_players();
        if (m)
        {
            if (m & 1)
                lap_done(0);
            if (m & 2)
                wrong_way(0);
            if (m & 4)
                lap_done(1);
            if (m & 8)
                wrong_way(1);
        }
        PROBE();
        if (cpu_n)
        {
            lead = progress_cpu();
            if (lead)
                for (p = 2, b = 4; p < 2 + cpu_n; p++, b <<= 1)
                {
                    if (lead & b)
                        lap_done(p);
                    if (lead & ((u16)b << 8))
                        wrong_way(p);
                }
        }
        PROBE();
        positions();
        PROBE();
        m = busy_flags();
        if (m)
        {
            if (m & 16)
                banner_step(0);
            if (m & 32)
                banner_step(1);
            if (m & 1)
                own_kart(0);
            if (m & 2)
                own_kart(1);
            if (m & 4)
                effects(0);
            if (m & 8)
                effects(1);
        }
    }
    PROBE();
    minimap();
    PROBE();
    draw_objects();
    PROBE();
    if (battle && game_state == ST_RACE)
        battle_frame();
    if (cpu_due)
        if (frame_lines() < CPU_GATE)
            cpu_items();
    PROBE();
    if (end_timer)
        end_timer--;
}

// ---------------------------------------------------------------- track select, cup and podium (Mode 1)

// The track menu: the cup (all four tracks in order) or one track. Rows of the menu, cup first.
const u8 menu_row[MENU_LAST + 1] = {9, 11, 13, 15, 17, 19, 21};

void menu_cursor(u8 show)
{
    text(6, menu_row[menu_pos], show ? ">" : " ", 1);
}

// The line under the menu: how many computer karts race. Only the four characters after the label are
// rewritten on a change (the menu's writes must fit in vblank); a battle under the cursor has none.
void cpu_value(void)
{
    char buf[5];
    u8 i;
    const char *s;
    if (menu_pos > ARENA)
    {
        s = "NONE";
        for (i = 0; i < 4; i++)
            buf[i] = s[i];
    }
    else
    {
        buf[0] = '0' + cpu_menu;
        buf[1] = buf[2] = buf[3] = ' ';
    }
    buf[4] = 0;
    text(24, 23, buf, 0);
}

void clear_points(void)
{
    u8 i;
    for (i = 0; i < NK_MAX; i++)
        points[i] = 0;
}

// Opens after both have picked their animals; either pad chooses. The portraits stay loaded from the
// select screen and show both animals.
void show_tracks(void)
{
    u8 i;
    ui_screen();
    big_text(4, 2, "PICK A TRACK");
    for (i = 0; i < 2; i++)
        spr(4 + i, i ? 200 : 24, 40, BIG_TILE(pick[i]), pick[i] / 3, 0, 1);
    text(8, menu_row[0], "CUP: ALL FOUR TRACKS", 0);
    for (i = 0; i < ARENA; i++)
        text(8, menu_row[i + 1], trk_names[i], 0);
    text(8, menu_row[5], "BALLOON BATTLE", 0);
    text(8, menu_row[6], "COIN BATTLE", 0);
    text(1, 25, "D-PAD: CHOOSE  B: RACE  Y: BACK", 0);
    text(1, 26, "LEFT/RIGHT: COMPUTER KARTS", 0);
    text(8, 23, "COMPUTER KARTS:", 0);
    cpu_value();
    menu_cursor(1);
    input_wait = 20; // the B that locked the second pick does not choose
    game_state = ST_TRACKS;
    setScreenOn();
}

// Starts race `cup_race` of the cup, or the chosen track. The menu's text writes run in vblank.
void tracks_frame(void)
{
    u16 down;
    if (input_wait)
    {
        input_wait--;
        return;
    }
    down = padsDown(0) | padsDown(1);
    if (down & (KEY_UP | KEY_DOWN))
    {
        menu_cursor(0);
        if (down & KEY_UP)
            menu_pos = menu_pos ? menu_pos - 1 : MENU_LAST;
        else
            menu_pos = menu_pos < MENU_LAST ? menu_pos + 1 : 0;
        menu_cursor(1);
        cpu_value();
    }
    else if ((down & (KEY_LEFT | KEY_RIGHT)) && menu_pos <= ARENA)
    {
        if (down & KEY_LEFT)
            cpu_menu = cpu_menu ? cpu_menu - 1 : CPU_MAX;
        else
            cpu_menu = cpu_menu < CPU_MAX ? cpu_menu + 1 : 0;
        cpu_value();
    }
    else if (down & (KEY_B | KEY_START))
    {
        cup_on = menu_pos == 0;
        battle = menu_pos == 5 ? 1 : (menu_pos == 6 ? 2 : 0);
        cup_race = 0;
        clear_points();
        cpu_n = cpu_menu; // a battle sets it to 0 in start_race, and the choice stays
        track_no = cup_on ? 0 : (battle ? ARENA : menu_pos - 1);
        start_race();
    }
    else if (down & KEY_Y)
        show_select();
}

// A block of the podium: solid tiles (gold 176, silver 177, bronze 178 in the letter tiles) from column x, row y down
// to row 22, w tiles wide.
void podium_block(u8 x, u8 y, u8 w, u8 tile)
{
    u8 r, c;
    for (r = y; r <= 22; r++)
    {
        vram_at(UI_MAP + (r << 5) + x);
        for (c = 0; c < w; c++)
        {
            VMDATAL = tile;
            VMDATAH = 0;
        }
    }
}

// Block i of the podium: top row, left column of the block and of its points, for the two-player cup (the third is
// not drawn) and for a cup with computer karts (three blocks, further apart so the points and the driver names do not touch).
const u8 pod_row[3] = {15, 18, 20};
const u8 pod_x[6] = {12, 4, 20, 12, 1, 23};
const u8 pod_text[6] = {14, 4, 0, 13, 2, 24};

// After the fourth race: the karts with the most points on the gold, silver and (with computer karts) bronze
// blocks, each with its animal and points. A tie in points goes to the better place in the last race.
void show_podium(void)
{
    u8 order[3];
    u8 i, k, n, b, o;
    u16 key, best;
    ui_screen();
    n = cpu_n ? 3 : 2;
    for (i = 0; i < n; i++)
    {
        best = 0;
        order[i] = 0;
        for (k = 0; k < 2 + cpu_n; k++)
        {
            for (b = 0, o = 0; o < i; o++)
                b |= order[o] == k;
            key = ((u16)points[k] << 3) + 8 - place[k];
            if (!b && key >= best)
            {
                best = key;
                order[i] = k;
            }
        }
    }
    cup_winner = order[0];
    o = cpu_n ? 3 : 0;
    if (cpu_n)
    {
        dmaCopyVram(&select_obj_gfx, 0x6000, 384 * 32); // the portraits: a computer animal has no race frame of its own
        dmaCopyCGram(&select_obj_pal, 128, 7 * 32);
    }
    text_mid(16, 1, "CUP RESULTS", 0);
    winner_text(animal_of(cup_winner));
    for (i = 0; i < n; i++)
    {
        k = order[i];
        podium_block(pod_x[o + i], pod_row[i], 8, 176 + i);
        text(pod_x[o + i] + 2, pod_row[i] + 1, i == 0 ? "1ST" : (i == 1 ? "2ND" : "3RD"), i == 0);
        points_text(pod_text[o + i], 23, points[k], cpu_n ? "PTS" : "POINTS"); // up to "36 PTS": three texts with blank columns between
        if (cpu_n)
        {
            spr(i, pod_x[o + i] * 8 + 16, pod_row[i] * 8 - 32, BIG_TILE(animal_of(k)), animal_of(k) / 3, 0, 1);
            text_mid(pod_x[o + i] + 4, pod_row[i] + 2, driver_name[k], 0); // who drives it, on the block under the animal
        }
        else
            spr(k, pod_x[o + i] * 8 + 16, pod_row[i] * 8 - 32, NEAR_FRAME(k, 4), k, 0, 1);
    }
    text(8, 25, "START", 1);
    text(15, 25, "NEW CUP", 0);
    text(8, 26, "SELECT", 1);
    text(15, 26, "PICK ANIMALS", 0);
    input_wait = 60;
    game_state = ST_PODIUM;
    setScreenOn();
}

void podium_frame(void)
{
    u16 pressed;
    if (input_wait)
    {
        input_wait--;
        return;
    }
    pressed = padsDown(0) | padsDown(1);
    if (pressed & KEY_START)
    {
        cup_race = 0;
        clear_points();
        track_no = 0;
        start_race();
    }
    else if (pressed & KEY_SELECT)
        show_select();
}

void title_frame(void)
{
    if ((padsDown(0) | padsDown(1)) & KEY_START)
        show_select();
}

void results_frame(void)
{
    u16 pressed;
    if (input_wait)
    {
        input_wait--;
        return;
    }
    pressed = padsDown(0) | padsDown(1);
    if (pressed & KEY_START)
    {
        // a single race goes again on the same track; the cup goes on to its next track, then the podium
        if (cup_on && cup_race == CUP_RACES - 1)
            show_podium();
        else
        {
            if (cup_on)
                track_no = ++cup_race;
            start_race();
        }
    }
    else if (pressed & KEY_SELECT)
        show_select();
}

int main(void)
{
    bgInitMapTileSet7(trk_tiles[0], trk_map[0], trk_pal[0], trk_tiles_size[0], 0x0000);
    oamInitGfxSet(&shared_gfx, 8192, &shared_pal, 96, 2, 0x6000, OBJ_SIZE16_L32);
    init_tables();
    cpu_n = 0; // no computer karts until a menu sets them
    cpu_menu = CPU_MAX; // the track menu starts on the most
    cpu_alt = 1; // the computer karts of each half are projected on alternate frames: three fit the budget that way only
    pick[0] = 0; // the otter and the T-Rex until the players pick
    pick[1] = 1;
    cpu_pick[0] = 2; // until a race picks the computer karts' animals
    cpu_pick[1] = 3;
    rng = 0xACE1;
    load_race_gfx();
    show_title();

    while (1)
    {
        WaitForVBlank();
        if (game_state != ST_RACE && game_state != ST_COUNTDOWN)
        {
            rng = (rng >> 1) ^ ((rng & 1) ? 0xB400 : 0); // steps on every menu frame too: the first race after power-on picks its computer animals from when the players got there
            if (game_state == ST_TITLE)
                title_frame();
            else if (game_state == ST_SELECT)
                select_frame();
            else if (game_state == ST_RESULTS)
                results_frame();
            else if (game_state == ST_TRACKS)
                tracks_frame();
            else if (game_state == ST_PODIUM)
                podium_frame();
        }
        else
        {
            PROBE();
            init_hdma();
            if (mq_n)
                flush_map();
            if ((hud_pic[0] ^ hud_shown[0]) | (hud_pic[1] ^ hud_shown[1]))
                load_hud();
            load_leader_gfx(); // before the animals' frames, so its copy lands on a frame of its own
            load_cpu_gfx();
            PROBE();
            race_frame();
            measure();
            frames_done++;
            if (done_count && !end_timer && (battle | finished[0] | finished[1])) // a computer kart finishing alone does not end the race
                show_results(); // after measure(): the mode switch runs with the screen off and takes frames
        }
    }
    return 0;
}
