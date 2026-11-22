#!/usr/bin/env python3
"""Draws the cast and their karts from small 3D models, so every viewing
angle and size of a character comes from one description.

A model is a list of rounded shapes (ellipsoids, boxes and tapered capsules),
each with a material. The renderer ray-marches the shapes from a camera above
and behind, shades each material in up to three tones and adds a dark outline,
then returns palette indices. All art is original and made here in code.

Each animal has its own 16-colour palette for the race (sprite palettes 0 and
1 hold the two players'). The select screen shows all 18 at once as busts,
three animals to a sprite palette: see portrait_palette().

Preview sheet: python3 tools/characters.py /tmp/sheet.png [NAME ...]
"""
import math
import sys

import numpy as np

ELEVATION = math.radians(24)  # the race camera looks down on the kart by this much
SS = 4                        # supersampling: rays per pixel side

# Race palette slots shared by every character (sprite palettes have 16 colours, 0 is clear).
OUTLINE, KART_L, KART_M, KART_D, TYRE, METAL = 1, 2, 3, 4, 5, 6
SKIN_L, SKIN_M, SKIN_D, BELLY_L, BELLY_D, EYE, PUPIL, ACCENT, ACCENT2 = 7, 8, 9, 10, 11, 12, 13, 14, 15

# material -> palette indices from lit to shaded
MATERIALS = {
    "kart": (KART_L, KART_M, KART_D),
    "tyre": (TYRE, TYRE, OUTLINE),
    "metal": (METAL, METAL, TYRE),
    "skin": (SKIN_L, SKIN_M, SKIN_D),
    "dark": (SKIN_D, SKIN_D, SKIN_D),     # stripes and patches in the skin's own shade
    "belly": (BELLY_L, BELLY_L, BELLY_D),
    "eye": (EYE, EYE, EYE),
    "tooth": (EYE, EYE, EYE),
    "pupil": (PUPIL, PUPIL, PUPIL),
    "nose": (ACCENT, ACCENT, ACCENT),
    "accent": (ACCENT, ACCENT, ACCENT),
    "accent2": (ACCENT2, ACCENT2, ACCENT2),
}
KART_MATERIALS = ("kart", "tyre", "metal")


def _rot(deg):
    """Rotation matrix from (about x, about y, about z) in degrees, applied x first."""
    ax, ay, az = (math.radians(a) for a in deg)
    rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    return rz @ ry @ rx


def ell(c, r, mat, rot=None):
    """Ellipsoid at c with radii r, optionally turned by rot (degrees about x, y, z)."""
    return ("e", np.array(c, float), np.array(r, float), mat, None if rot is None else _rot(rot))


def box(c, h, mat, round_=0.04):
    return ("b", np.array(c, float), np.array(h, float), mat, round_)


def cap(a, b, r1, r2, mat):
    """Capsule from a (radius r1) to b (radius r2): horns, spikes, quills, necks."""
    return ("c", np.array(a, float), np.array(b, float), mat, (r1, r2))


def mirror(shape):
    """The same shape on the other side of the kart (x negated)."""
    m = np.array([1.0, 1.0, 1.0])
    m[0] = -1
    if shape[0] == "e":
        rot = shape[4]
        if rot is not None:
            M = np.diag([-1.0, 1.0, 1.0])
            rot = M @ rot @ M
        return ("e", shape[1] * m, shape[2], shape[3], rot)
    if shape[0] == "b":
        return ("b", shape[1] * m, shape[2], shape[3], shape[4])
    return ("c", shape[1] * m, shape[2] * m, shape[3], shape[4])


def pair(*shapes):
    """Each shape and its mirror image."""
    out = []
    for s in shapes:
        out += [s, mirror(s)]
    return out


# Model space: x to the kart's right, y forward, z up; the kart is about 2 long and 1.6 wide.
def kart_shapes():
    return [
        box((0, -0.05, 0.30), (0.42, 0.80, 0.12), "kart", 0.08),
        ell((0, 0.78, 0.30), (0.36, 0.34, 0.12), "kart"),
        box((0, -0.86, 0.40), (0.46, 0.08, 0.14), "kart", 0.04),
        box((0.50, -0.05, 0.30), (0.08, 0.42, 0.08), "kart", 0.04),
        box((-0.50, -0.05, 0.30), (0.08, 0.42, 0.08), "kart", 0.04),
        box((0, 0.98, 0.24), (0.52, 0.06, 0.06), "metal", 0.03),
        ell((0.62, -0.58, 0.22), (0.16, 0.22, 0.22), "tyre"),
        ell((-0.62, -0.58, 0.22), (0.16, 0.22, 0.22), "tyre"),
        ell((0.58, 0.62, 0.18), (0.13, 0.18, 0.18), "tyre"),
        ell((-0.58, 0.62, 0.18), (0.13, 0.18, 0.18), "tyre"),
        ell((0, 0.38, 0.62), (0.16, 0.05, 0.14), "metal"),  # steering wheel
    ]


def arms(mat="skin", z=0.66, r=0.08):
    """Arms reaching forward to the steering wheel."""
    return pair(ell((0.26, 0.10, z), (r, 0.24, r), mat))


def dot_eyes(x, y, z, r=0.055):
    return pair(ell((x, y, z), (r, 0.05, r * 1.1), "pupil"))


def big_eyes(x, y, z, r=0.10, pupil=0.05, look=0.07):
    """White eyes with pupils looking forward: the cute look."""
    return pair(ell((x, y, z), (r, r * 0.9, r), "eye"),
                ell((x + 0.02, y + look, z + 0.01), (pupil, pupil, pupil * 1.1), "pupil"))


def otter():
    """A round brown otter with a cream face, small ears and a flat tail out the back."""
    return kart_shapes() + [
        ell((0, -0.25, 0.72), (0.32, 0.28, 0.34), "skin"),
        ell((0, -0.02, 0.70), (0.22, 0.12, 0.24), "belly"),
        *arms(),
        ell((0, -0.15, 1.17), (0.30, 0.27, 0.27), "skin"),
        ell((0, 0.07, 1.10), (0.20, 0.13, 0.13), "belly"),     # muzzle
        ell((0, 0.19, 1.15), (0.065, 0.05, 0.05), "nose"),
        *dot_eyes(0.12, 0.05, 1.27),
        *pair(ell((0.25, -0.18, 1.36), (0.08, 0.05, 0.07), "skin")),  # ears
        ell((0, -1.12, 0.40), (0.16, 0.36, 0.06), "skin"),     # flat tail
    ]


def trex():
    """A cute green T-Rex: big head with big eyes and a toothy grin, tiny arms, tail out the back."""
    return kart_shapes() + [
        ell((0, -0.30, 0.76), (0.34, 0.30, 0.38), "skin"),
        ell((0, -0.06, 0.72), (0.22, 0.12, 0.26), "belly"),
        *pair(ell((0.25, 0.10, 0.86), (0.06, 0.14, 0.06), "skin")),   # tiny arms
        ell((0, -0.05, 1.25), (0.31, 0.44, 0.26), "skin"),     # big head
        ell((0, 0.06, 1.08), (0.25, 0.36, 0.08), "belly"),     # lower jaw
        box((0, 0.33, 1.15), (0.20, 0.06, 0.025), "tooth", 0.01),
        *big_eyes(0.17, 0.10, 1.41, 0.10, 0.05, 0.07),
        *pair(ell((0.08, 0.36, 1.33), (0.03, 0.03, 0.03), "nose")),   # nostrils
        ell((0, -1.05, 0.55), (0.15, 0.45, 0.14), "skin"),     # tail
        ell((0, -0.42, 1.18), (0.05, 0.10, 0.08), "nose"),     # back ridge
        ell((0, -0.55, 0.98), (0.05, 0.10, 0.08), "nose"),
    ]


def penguin():
    """A round navy penguin with a white front and face, an orange beak and flippers on the wheel."""
    return kart_shapes() + [
        ell((0, -0.25, 0.74), (0.33, 0.30, 0.38), "skin"),
        ell((0, -0.01, 0.72), (0.24, 0.12, 0.30), "belly"),
        *pair(ell((0.30, 0.06, 0.72), (0.06, 0.24, 0.13), "skin", (20, 0, 0))),  # flippers
        ell((0, -0.15, 1.20), (0.29, 0.27, 0.27), "skin"),
        ell((0, 0.02, 1.16), (0.22, 0.14, 0.18), "belly"),     # white face
        ell((0, 0.20, 1.12), (0.07, 0.13, 0.05), "accent"),    # beak
        *big_eyes(0.10, 0.11, 1.24, 0.06, 0.035, 0.04),
        ell((0, -0.10, 1.47), (0.05, 0.08, 0.06), "skin", (-30, 0, 0)),  # hair tuft
    ]


def capybara():
    """A calm, chunky capybara with a long blunt head, tiny ears and an orange balanced on its head."""
    return kart_shapes() + [
        ell((0, -0.30, 0.72), (0.37, 0.34, 0.36), "skin"),
        ell((0, -0.04, 0.66), (0.24, 0.12, 0.22), "belly"),
        *arms(r=0.09),
        ell((0, -0.06, 1.13), (0.27, 0.36, 0.24), "skin"),     # long head
        ell((0, 0.24, 1.06), (0.20, 0.15, 0.15), "skin"),      # blunt snout
        ell((0, 0.37, 1.10), (0.12, 0.05, 0.06), "nose"),
        *dot_eyes(0.17, 0.10, 1.23, 0.045),
        *pair(ell((0.19, -0.25, 1.33), (0.06, 0.04, 0.05), "dark")),  # tiny ears
        ell((0, -0.12, 1.45), (0.12, 0.12, 0.11), "accent2"),  # the orange
    ]


def sloth():
    """A sleepy sloth: shaggy grey-brown, a cream face with dark eye patches and a little smile, long arms."""
    return kart_shapes() + [
        ell((0, -0.26, 0.72), (0.31, 0.28, 0.34), "skin"),
        ell((0, -0.04, 0.70), (0.20, 0.12, 0.22), "belly"),
        *pair(ell((0.27, 0.08, 0.72), (0.07, 0.30, 0.07), "skin", (12, 0, 0))),  # long arms
        *pair(cap((0.24, 0.36, 0.66), (0.20, 0.42, 0.60), 0.025, 0.015, "accent")),  # claws
        ell((0, -0.14, 1.18), (0.29, 0.27, 0.27), "skin"),
        ell((0, 0.03, 1.16), (0.23, 0.14, 0.19), "belly"),     # face
        *pair(ell((0.11, 0.12, 1.20), (0.08, 0.05, 0.045), "accent", (0, 0, -25))),  # eye patches
        *pair(ell((0.11, 0.155, 1.205), (0.022, 0.02, 0.022), "eye")),
        ell((0, 0.17, 1.12), (0.05, 0.035, 0.035), "accent"),  # nose
        ell((0, -0.12, 1.45), (0.10, 0.10, 0.04), "skin"),     # shaggy top
    ]


def axolotl():
    """A pink axolotl with a wide flat head, frilly magenta gills on each side and a big smile."""
    gills = []
    for z, tilt, length in ((1.30, 35, 0.15), (1.17, 0, 0.17), (1.04, -35, 0.15)):
        gills += pair(ell((0.40 + length * 0.6, -0.12, z), (length, 0.04, 0.045), "accent", (0, -tilt, 0)))
    return kart_shapes() + [
        ell((0, -0.26, 0.70), (0.30, 0.28, 0.32), "skin"),
        ell((0, -0.04, 0.68), (0.20, 0.12, 0.22), "belly"),
        *arms(r=0.07),
        ell((0, -0.08, 1.15), (0.38, 0.28, 0.22), "skin"),     # wide flat head
        *gills,
        *pair(ell((0.24, 0.10, 1.20), (0.05, 0.05, 0.055), "pupil")),  # eyes far apart
        box((0, 0.195, 1.09), (0.13, 0.02, 0.012), "accent", 0.01),  # smile
        ell((0, -0.95, 0.52), (0.06, 0.40, 0.14), "skin"),     # tail fin
    ]


def red_panda():
    """A rusty red panda with white cheeks and ear rims, dark legs, a dark nose and a ringed tail."""
    tail = [ell((0, -0.95 - 0.13 * i, 0.55 + 0.05 * i), (0.14, 0.09, 0.13), "skin" if i % 2 == 0 else "dark")
            for i in range(4)]
    return kart_shapes() + [
        ell((0, -0.25, 0.72), (0.31, 0.28, 0.34), "skin"),
        ell((0, -0.03, 0.68), (0.20, 0.11, 0.22), "accent2"),  # dark chest
        *arms("accent2"),
        ell((0, -0.14, 1.17), (0.31, 0.27, 0.26), "skin"),
        *pair(ell((0.14, 0.06, 1.12), (0.11, 0.12, 0.10), "belly")),  # white cheeks
        ell((0, 0.13, 1.25), (0.05, 0.05, 0.08), "belly"),      # white brow stripe
        ell((0, 0.18, 1.11), (0.07, 0.06, 0.055), "accent"),    # nose
        *dot_eyes(0.12, 0.10, 1.22, 0.05),
        *pair(ell((0.24, -0.16, 1.39), (0.10, 0.05, 0.11), "skin", (0, -25, 0)),   # big ears
              ell((0.25, -0.13, 1.39), (0.065, 0.03, 0.07), "belly", (0, -25, 0))),
        *tail,
    ]


def hedgehog():
    """A round hedgehog: a spiky brown back, a cream face with a pointy snout, a black nose and beady eyes."""
    spikes = []
    for i, (z, y) in enumerate(((1.42, -0.15), (1.36, -0.32), (1.20, -0.42), (1.00, -0.50), (0.78, -0.52),
                                (0.58, -0.48))):
        for x in ((-0.20, 0.0, 0.20) if i % 2 == 0 else (-0.10, 0.10)) + ((-0.30, 0.30) if 1 <= i <= 4 else ()):
            base = np.array((x * 0.8, y + 0.10, z - 0.10))
            tip = base + np.array((x * 0.6, -0.22, 0.12 if i < 2 else 0.02))
            spikes.append(cap(base, tip, 0.06, 0.012, "dark"))
    return kart_shapes() + [
        ell((0, -0.25, 0.72), (0.32, 0.30, 0.34), "skin"),
        ell((0, -0.01, 0.68), (0.21, 0.11, 0.22), "belly"),
        *arms("belly", r=0.07),
        ell((0, -0.14, 1.14), (0.30, 0.28, 0.28), "skin"),
        ell((0, 0.04, 1.08), (0.22, 0.16, 0.18), "belly"),      # face
        ell((0, 0.20, 1.04), (0.08, 0.14, 0.07), "belly"),      # pointy snout
        ell((0, 0.33, 1.05), (0.05, 0.04, 0.045), "accent"),    # nose
        *dot_eyes(0.11, 0.13, 1.17, 0.045),
        *pair(ell((0.19, -0.02, 1.34), (0.06, 0.04, 0.06), "belly")),  # little ears
        *spikes,
    ]


def goat():
    """A white goat with curved horns, floppy ears, a beige beard and a pink nose."""
    horn = []
    for i in range(4):
        a = i / 3
        horn.append(ell((0.13 + 0.05 * a, -0.18 - 0.17 * a, 1.42 + 0.06 * math.sin(a * 2.4) - 0.05 * a),
                        (0.065 - 0.01 * i, 0.075, 0.065 - 0.01 * i), "accent"))
    return kart_shapes() + [
        ell((0, -0.25, 0.72), (0.31, 0.28, 0.34), "skin"),
        ell((0, -0.02, 0.70), (0.20, 0.11, 0.22), "belly"),
        *arms(),
        ell((0, -0.10, 1.17), (0.25, 0.30, 0.27), "skin"),
        ell((0, 0.14, 1.06), (0.16, 0.16, 0.14), "skin"),       # long muzzle
        ell((0, 0.27, 1.08), (0.07, 0.04, 0.05), "accent2"),    # pink nose
        ell((0, 0.17, 0.90), (0.06, 0.06, 0.10), "belly"),      # beard
        *big_eyes(0.13, 0.08, 1.25, 0.065, 0.035, 0.05),
        *pair(ell((0.30, -0.08, 1.20), (0.15, 0.05, 0.06), "skin", (0, 30, 0))),  # floppy ears
        *horn, *[mirror(h) for h in horn],
    ]


def flamingo():
    """A pink flamingo whose long neck lifts its small head high, with a pale beak tipped in black."""
    neck = [ell((0, -0.08 + 0.05 * math.sin(i * 1.1), 0.98 + 0.13 * i), (0.09, 0.09, 0.10), "skin") for i in range(4)]
    return kart_shapes() + [
        ell((0, -0.28, 0.74), (0.30, 0.34, 0.30), "skin"),
        ell((0, -0.04, 0.72), (0.18, 0.11, 0.20), "belly"),
        *pair(ell((0.29, -0.30, 0.80), (0.07, 0.30, 0.17), "dark", (-15, 0, 0))),  # folded wings
        *arms(r=0.06),
        *neck,
        ell((0, 0.00, 1.52), (0.17, 0.18, 0.16), "skin"),       # small head
        cap((0, 0.14, 1.52), (0, 0.32, 1.44), 0.065, 0.045, "accent"),   # beak, bent down
        cap((0, 0.32, 1.44), (0, 0.38, 1.35), 0.045, 0.02, "accent2"),   # black tip
        *big_eyes(0.09, 0.08, 1.58, 0.055, 0.03, 0.04),
        ell((0, -0.75, 0.86), (0.12, 0.16, 0.08), "dark", (30, 0, 0)),   # tail feathers
    ]


def triceratops():
    """A blue triceratops with a big orange frill, three ivory horns, a beak and a short tail."""
    frill = [ell((0, -0.30, 1.30), (0.42, 0.06, 0.32), "accent2", (-20, 0, 0))]
    frill += [ell((0.36 * math.cos(a), -0.33, 1.30 + 0.30 * math.sin(a)), (0.06, 0.05, 0.06), "dark")
              for a in np.linspace(0.3, math.pi - 0.3, 5)]
    return kart_shapes() + [
        ell((0, -0.30, 0.74), (0.36, 0.32, 0.36), "skin"),
        ell((0, -0.05, 0.70), (0.22, 0.12, 0.24), "belly"),
        *arms(r=0.09),
        *frill,
        ell((0, -0.02, 1.16), (0.27, 0.32, 0.24), "skin"),
        ell((0, 0.25, 1.06), (0.15, 0.12, 0.12), "belly"),       # beak
        *pair(cap((0.13, 0.05, 1.33), (0.18, 0.30, 1.56), 0.06, 0.015, "accent")),  # brow horns
        cap((0, 0.27, 1.17), (0, 0.36, 1.32), 0.05, 0.015, "accent"),  # nose horn
        *big_eyes(0.15, 0.13, 1.25, 0.07, 0.035, 0.05),
        ell((0, -1.02, 0.52), (0.14, 0.36, 0.12), "skin"),       # tail
    ]


def pterodactyl():
    """An orange pterodactyl with a long beak, a red crest pointing back and wings over the kart's sides."""
    return kart_shapes() + [
        ell((0, -0.25, 0.72), (0.27, 0.26, 0.32), "skin"),
        ell((0, -0.04, 0.70), (0.18, 0.10, 0.22), "belly"),
        *pair(ell((0.50, -0.30, 0.86), (0.36, 0.22, 0.04), "dark", (0, -18, 0)),   # wings
              cap((0.20, -0.18, 0.98), (0.80, -0.24, 0.82), 0.04, 0.025, "skin")),  # wing arm
        *arms(r=0.06),
        ell((0, -0.08, 1.15), (0.24, 0.26, 0.22), "skin"),
        cap((0, 0.12, 1.10), (0, 0.52, 1.02), 0.10, 0.025, "accent"),   # long beak
        ell((0, -0.32, 1.32), (0.05, 0.32, 0.12), "accent2", (-30, 0, 0)),  # crest
        *big_eyes(0.12, 0.08, 1.21, 0.07, 0.035, 0.05),
    ]


def hippo():
    """A big lavender hippo with a wide pink muzzle, nostrils on top, tiny ears and two little teeth."""
    return kart_shapes() + [
        ell((0, -0.30, 0.74), (0.40, 0.34, 0.38), "skin"),
        ell((0, -0.04, 0.70), (0.26, 0.12, 0.24), "belly"),
        *arms(r=0.10),
        ell((0, -0.14, 1.20), (0.30, 0.28, 0.26), "skin"),
        ell((0, 0.14, 1.08), (0.31, 0.20, 0.17), "belly"),       # wide muzzle
        *pair(ell((0.10, 0.25, 1.21), (0.045, 0.04, 0.03), "accent")),  # nostrils
        *pair(box((0.09, 0.32, 0.98), (0.03, 0.02, 0.035), "tooth", 0.01)),
        *big_eyes(0.13, 0.01, 1.36, 0.06, 0.035, 0.05),
        *pair(ell((0.21, -0.20, 1.44), (0.06, 0.04, 0.06), "skin")),   # tiny ears
    ]


def raccoon():
    """A grey raccoon with a black mask, a white face, pointed ears and a ringed tail."""
    tail = [ell((0, -0.95 - 0.13 * i, 0.55 + 0.06 * i), (0.14, 0.09, 0.13), "skin" if i % 2 == 0 else "accent")
            for i in range(5)]
    return kart_shapes() + [
        ell((0, -0.25, 0.72), (0.31, 0.28, 0.34), "skin"),
        ell((0, -0.02, 0.70), (0.20, 0.11, 0.22), "belly"),
        *arms("dark"),
        ell((0, -0.14, 1.17), (0.31, 0.27, 0.26), "skin"),
        ell((0, 0.05, 1.11), (0.22, 0.14, 0.15), "belly"),        # white face
        ell((0, 0.10, 1.21), (0.27, 0.10, 0.06), "accent"),       # mask
        *pair(ell((0.11, 0.18, 1.215), (0.035, 0.03, 0.035), "eye")),
        ell((0, 0.19, 1.07), (0.06, 0.05, 0.045), "accent"),      # nose
        *pair(cap((0.18, -0.15, 1.36), (0.25, -0.18, 1.52), 0.08, 0.02, "skin"),  # pointed ears
              cap((0.18, -0.12, 1.37), (0.24, -0.15, 1.48), 0.045, 0.01, "dark")),
        *tail,
    ]


def frog():
    """A lime frog: a wide head, big bulging eyes on top, a wide grin and pink cheeks."""
    return kart_shapes() + [
        ell((0, -0.25, 0.70), (0.33, 0.28, 0.32), "skin"),
        ell((0, -0.02, 0.68), (0.23, 0.12, 0.22), "belly"),
        *arms(r=0.07),
        ell((0, -0.08, 1.08), (0.36, 0.30, 0.22), "skin"),         # wide head
        ell((0, 0.06, 0.98), (0.28, 0.18, 0.10), "belly"),         # throat
        *pair(ell((0.18, -0.02, 1.30), (0.12, 0.11, 0.11), "skin")),  # eye bumps
        *big_eyes(0.18, 0.03, 1.33, 0.10, 0.05, 0.07),
        box((0, 0.21, 1.06), (0.20, 0.02, 0.012), "accent2", 0.01),  # grin
        *pair(ell((0.27, 0.12, 1.10), (0.06, 0.04, 0.04), "accent")),  # pink cheeks
    ]


def snail():
    """A snail on a kart: a big orange spiral shell on its back, a soft body and eyes on stalks."""
    shell = [ell((0, -0.50, 0.98), (0.30, 0.42, 0.42), "skin")]
    shell += pair(ell((0.27, -0.50, 1.00), (0.05, 0.27, 0.27), "accent2"),
                  ell((0.31, -0.50, 1.00), (0.03, 0.16, 0.16), "skin"),
                  ell((0.33, -0.50, 1.00), (0.02, 0.07, 0.07), "accent2"))
    return kart_shapes() + shell + [
        ell((0, -0.05, 0.70), (0.24, 0.20, 0.30), "belly"),        # soft body
        *arms("belly", r=0.07),
        ell((0, 0.05, 1.06), (0.24, 0.22, 0.20), "belly"),         # head
        *pair(cap((0.08, 0.08, 1.20), (0.14, 0.12, 1.50), 0.035, 0.03, "belly")),  # stalks
        *pair(ell((0.14, 0.12, 1.53), (0.07, 0.07, 0.07), "eye"),
              ell((0.15, 0.17, 1.54), (0.04, 0.03, 0.04), "pupil")),
        box((0, 0.27, 1.02), (0.10, 0.02, 0.012), "accent", 0.01),  # smile
    ]


def bunicorn():
    """A made-up bunny-unicorn: lavender-white with tall pink-lined ears, a golden horn and a mint mane."""
    horn = [cap((0, 0.10, 1.38), (0, 0.22, 1.62), 0.06, 0.012, "accent")]
    return kart_shapes() + [
        ell((0, -0.25, 0.70), (0.31, 0.28, 0.33), "skin"),
        ell((0, -0.02, 0.68), (0.20, 0.11, 0.22), "belly"),
        *arms(),
        ell((0, -0.10, 1.13), (0.29, 0.26, 0.26), "skin"),
        *pair(ell((0.14, -0.20, 1.54), (0.07, 0.05, 0.24), "skin", (0, 12, 0)),   # tall ears
              ell((0.145, -0.165, 1.54), (0.04, 0.02, 0.18), "belly", (0, 12, 0))),
        *horn,
        ell((0, -0.30, 1.30), (0.09, 0.14, 0.12), "accent2"),      # mane
        ell((0, -0.38, 1.12), (0.08, 0.10, 0.12), "accent2"),
        *big_eyes(0.12, 0.08, 1.17, 0.075, 0.04, 0.055),
        *pair(ell((0.20, 0.10, 1.04), (0.05, 0.03, 0.035), "belly")),  # pink cheeks
        ell((0, 0.16, 1.06), (0.04, 0.03, 0.03), "belly"),         # nose
        ell((0, -0.86, 0.62), (0.12, 0.10, 0.11), "eye"),          # cotton tail
    ]


def duckupine():
    """A made-up duck-porcupine: a round yellow duck with an orange bill and brown quills down its back."""
    quills = []
    for i, (y, z) in enumerate(((-0.08, 1.38), (-0.22, 1.34), (-0.34, 1.20), (-0.44, 1.02), (-0.48, 0.82))):
        for x in ((-0.16, 0.0, 0.16) if i % 2 == 0 else (-0.24, -0.08, 0.08, 0.24)):
            base = np.array((x, y, z))
            tip = base + np.array((x * 0.7, -0.22, 0.26 if i < 2 else 0.10))
            quills.append(cap(base, tip, 0.035, 0.01, "accent2"))
    return kart_shapes() + [
        ell((0, -0.25, 0.72), (0.32, 0.29, 0.34), "skin"),
        ell((0, -0.02, 0.68), (0.21, 0.11, 0.22), "belly"),
        *pair(ell((0.29, 0.04, 0.72), (0.06, 0.24, 0.12), "skin", (20, 0, 0))),  # wings on the wheel
        ell((0, -0.10, 1.17), (0.28, 0.26, 0.26), "skin"),
        ell((0, 0.20, 1.09), (0.15, 0.15, 0.05), "accent"),        # flat bill
        *big_eyes(0.11, 0.08, 1.24, 0.07, 0.038, 0.05),
        *quills,
    ]


def palette(kart, kart_dark, skin, skin_dark, belly, accent, accent2=None):
    """16 colours (r, g, b) in the slot order above."""
    def mix(a, b, f):
        return tuple(int(a[i] + (b[i] - a[i]) * f) for i in range(3))
    return [
        (0, 0, 0), (24, 16, 32), mix(kart, (255, 255, 255), 0.35), kart, kart_dark,
        (48, 48, 56), (176, 176, 192), mix(skin, (255, 255, 255), 0.25), skin, skin_dark,
        belly, mix(belly, (0, 0, 0), 0.25), (248, 248, 248), (16, 16, 24), accent, accent2 or accent,
    ]


LIGHT, MEDIUM, HEAVY = 0, 1, 2
TYPE_NAMES = ("LIGHT", "MEDIUM", "HEAVY")

# The cast, in select-screen order (6 columns, 3 rows; three in a row share a portrait palette).
# "type" is the kart: light, medium or heavy (game/main.c holds the numbers).
CHARACTERS = [
    {"name": "OTTER", "model": otter, "type": LIGHT,
     "palette": palette((40, 120, 232), (24, 64, 152), (150, 92, 52), (96, 56, 32), (238, 214, 172), (56, 32, 24))},
    {"name": "T-REX", "model": trex, "type": HEAVY, "bust_view": 3,  # its snout shows; head-on it reads as a frog
     "palette": palette((240, 112, 32), (168, 56, 16), (96, 192, 72), (48, 120, 48), (232, 228, 160), (40, 88, 40))},
    {"name": "PENGUIN", "model": penguin, "type": LIGHT,
     "palette": palette((216, 40, 56), (136, 16, 32), (60, 70, 108), (36, 40, 68), (240, 240, 248), (248, 160, 40))},
    {"name": "CAPYBARA", "model": capybara, "type": HEAVY, "portrait": (SKIN_M, SKIN_D, BELLY_L, ACCENT2),
     "palette": palette((32, 168, 160), (16, 104, 104), (184, 132, 84), (124, 84, 52), (212, 172, 124), (64, 40, 32),
                        (248, 160, 32))},
    {"name": "GOAT", "model": goat, "type": MEDIUM,
     "palette": palette((208, 48, 144), (128, 24, 88), (236, 232, 224), (168, 160, 156), (212, 190, 150),
                        (112, 92, 76), (248, 150, 168))},
    {"name": "AXOLOTL", "model": axolotl, "type": LIGHT,
     "palette": palette((136, 72, 200), (80, 40, 128), (248, 160, 184), (208, 104, 140), (255, 210, 220),
                        (224, 56, 120))},
    {"name": "RED PANDA", "model": red_panda, "type": MEDIUM,
     "palette": palette((40, 152, 72), (20, 92, 44), (208, 96, 40), (140, 56, 24), (246, 238, 226), (40, 24, 20),
                        (72, 36, 24))},
    {"name": "SLOTH", "model": sloth, "type": HEAVY,
     "palette": palette((160, 208, 48), (96, 136, 24), (160, 140, 112), (104, 90, 72), (232, 216, 182),
                        (64, 46, 36))},
    {"name": "FLAMINGO", "model": flamingo, "type": MEDIUM,
     "palette": palette((48, 192, 232), (24, 112, 160), (248, 128, 168), (200, 76, 120), (255, 200, 216),
                        (248, 228, 168), (40, 32, 40))},
    {"name": "HEDGEHOG", "model": hedgehog, "type": LIGHT,
     "palette": palette((248, 200, 32), (176, 128, 16), (136, 96, 64), (84, 58, 40), (240, 212, 170), (32, 24, 24))},
    {"name": "TRICERATOPS", "model": triceratops, "type": HEAVY, "portrait": (SKIN_M, SKIN_D, BELLY_L, ACCENT2),
     "palette": palette((208, 56, 48), (128, 28, 28), (84, 160, 208), (48, 100, 148), (232, 222, 180),
                        (250, 244, 216), (240, 140, 56))},
    {"name": "RACCOON", "model": raccoon, "type": MEDIUM,
     "palette": palette((120, 216, 168), (56, 144, 104), (152, 152, 164), (96, 96, 110), (238, 238, 242),
                        (36, 36, 44))},
    {"name": "FROG", "model": frog, "type": LIGHT,
     "palette": palette((248, 104, 96), (176, 48, 48), (136, 212, 64), (72, 148, 40), (232, 240, 168),
                        (248, 136, 160), (120, 40, 48))},
    {"name": "PTERODACTYL", "model": pterodactyl, "type": MEDIUM,
     "palette": palette((80, 88, 216), (40, 44, 136), (216, 128, 72), (150, 76, 40), (244, 204, 160),
                        (248, 216, 120), (200, 48, 56))},
    {"name": "HIPPO", "model": hippo, "type": HEAVY,
     "palette": palette((248, 168, 40), (176, 104, 16), (164, 150, 204), (110, 98, 152), (244, 176, 196),
                        (84, 64, 104))},
    {"name": "BUNICORN", "model": bunicorn, "type": LIGHT,
     "palette": palette((248, 96, 176), (168, 40, 112), (236, 228, 252), (176, 164, 220), (255, 184, 216),
                        (252, 204, 56), (112, 224, 200))},
    {"name": "DUCKUPINE", "model": duckupine, "type": MEDIUM, "portrait": (SKIN_M, ACCENT2, BELLY_L, ACCENT),
     "palette": palette((64, 136, 152), (32, 80, 96), (252, 220, 64), (204, 160, 32), (255, 244, 184),
                        (248, 136, 32), (112, 72, 44))},
    {"name": "SNAIL", "model": snail, "type": HEAVY,
     "palette": palette((192, 152, 240), (112, 80, 168), (216, 124, 64), (148, 76, 36), (236, 214, 150),
                        (120, 60, 48), (120, 56, 32))},
]

# Frame sizes: (box in pixels, pixels per model unit, ground row under the kart's centre)
NEAR, MID, FAR = (32, 12.5, 27), (16, 6.5, 13), (16, 4.2, 12)
BUST_ELEVATION = math.radians(8)
BUST_SCALE = 27.0   # pixels per model unit in a 32x32 portrait
BUST_HEAD = 1.18    # model height of the portrait's centre


def sdf(shape, p):
    kind = shape[0]
    if kind == "e":
        _, c, r, _, rot = shape
        q = p - c
        if rot is not None:
            q = q @ rot
        q = q / r
        k = np.linalg.norm(q, axis=-1)
        return (k - 1.0) * r.min()
    if kind == "b":
        _, c, h, _, rr = shape
        q = np.abs(p - c) - (h - rr)
        out = np.linalg.norm(np.maximum(q, 0), axis=-1)
        return out + np.minimum(q.max(axis=-1), 0) - rr
    _, a, b, _, (r1, r2) = shape
    pa, ba = p - a, b - a
    h = np.clip((pa @ ba) / (ba @ ba), 0, 1)
    return np.linalg.norm(pa - h[..., None] * ba, axis=-1) - (r1 + (r2 - r1) * h)


def render(shapes, view, size, scale, contact, elevation=ELEVATION):
    """Palette indices (size x size) of the model seen from view step 0..4 (0 = from behind,
    2 = its right side with the nose to the right, 4 = from the front), `scale` pixels per
    model unit, with the ground under the kart's centre at row `contact`."""
    yaw = view * math.pi / 4
    look = np.array([-math.sin(yaw) * math.cos(elevation), math.cos(yaw) * math.cos(elevation), -math.sin(elevation)])
    right = np.array([math.cos(yaw), math.sin(yaw), 0.0])
    up = np.cross(right, look)
    n = size * SS
    u = (np.arange(n) + 0.5) / SS - size / 2
    v = contact - (np.arange(n) + 0.5) / SS
    U, V = np.meshgrid(u / scale, v / scale)
    origin = U[..., None] * right + V[..., None] * up - 4 * look
    t = np.zeros(U.shape)
    hit = np.zeros(U.shape, bool)
    for _ in range(80):
        p = origin + t[..., None] * look
        d = np.min([sdf(s, p) for s in shapes], axis=0)
        hit |= d < 0.004
        t = np.where(hit, t, t + np.maximum(d, 0.004))
    p = origin + t[..., None] * look
    dists = np.array([sdf(s, p) for s in shapes])
    which = dists.argmin(axis=0)
    eps = 0.01
    grad = np.stack([np.min([sdf(s, p + e) for s in shapes], axis=0) - np.min([sdf(s, p - e) for s in shapes], axis=0)
                     for e in np.eye(3) * eps], axis=-1)
    normal = grad / (np.linalg.norm(grad, axis=-1, keepdims=True) + 1e-9)
    light = -look * 0.35 + up * 0.75 + right * -0.35   # from above, a little left, towards the camera
    light /= np.linalg.norm(light)
    lit = (normal * light).sum(-1)
    tone = np.where(lit > 0.55, 0, np.where(lit > 0.1, 1, 2))
    idx = np.zeros(U.shape, int)
    for i, s in enumerate(shapes):
        tones = MATERIALS[s[3]]
        for k in range(3):
            idx[hit & (which == i) & (tone == k)] = tones[k]
    # each pixel takes the most common index of its samples; clear wins only with a majority
    blocks = idx.reshape(size, SS, size, SS).transpose(0, 2, 1, 3).reshape(size, size, SS * SS)
    out = np.zeros((size, size), int)
    for y in range(size):
        for x in range(size):
            vals = blocks[y, x]
            solid = vals[vals > 0]
            if len(solid) * 2 >= SS * SS:
                out[y, x] = np.bincount(solid).argmax()
    # dark outline around the silhouette
    solid = out > 0
    edge = np.zeros_like(solid)
    edge[1:] |= solid[:-1]; edge[:-1] |= solid[1:]; edge[:, 1:] |= solid[:, :-1]; edge[:, :-1] |= solid[:, 1:]
    out[edge & ~solid] = OUTLINE
    return out


def frames(ch):
    """{"near": [5 views], "mid": [...], "far": [...], "bust": 32x32} as palette indices of the race palette."""
    model = ch["model"]()
    out = {k: [render(model, v, *size) for v in range(5)] for k, size in (("near", NEAR), ("mid", MID), ("far", FAR))}
    body = [s for s in model if s[3] not in KART_MATERIALS]
    contact = 15 + BUST_HEAD * math.cos(BUST_ELEVATION) * BUST_SCALE
    out["bust"] = render(body, ch.get("bust_view", 4), 32, BUST_SCALE, contact, BUST_ELEVATION)
    return out


# Portraits: three animals to a palette. Slots 1 outline (pupils too) and 2 white (eyes and teeth),
# then four per animal: skin, skin shade, belly and accent.
PORTRAIT_FIXED = [(0, 0, 0), (24, 16, 32), (248, 248, 248)]


PORTRAIT_SLOTS = (SKIN_M, SKIN_D, BELLY_L, ACCENT)


def ch_portrait_slot(ch):
    """The race palette slot of the animal's main portrait colour (its skin)."""
    return ch.get("portrait", PORTRAIT_SLOTS)[0]


def portrait_colours(ch):
    pal = ch["palette"]
    return [pal[i] for i in ch.get("portrait", PORTRAIT_SLOTS)]


def portrait_palette(group):
    """16 colours for the three animals of a select-screen group, in their order."""
    out = list(PORTRAIT_FIXED)
    for ch in group:
        out += portrait_colours(ch)
    return out + [(0, 0, 0)] * (16 - len(out))


def portrait_indices(ch, slot, bust):
    """The bust re-coloured into its group's palette: each race colour goes to the nearest of
    the animal's six portrait colours."""
    pal = ch["palette"]
    choices = [(1, PORTRAIT_FIXED[1]), (2, PORTRAIT_FIXED[2])]
    choices += [(3 + slot * 4 + k, c) for k, c in enumerate(portrait_colours(ch))]
    fixed = {0: 0, OUTLINE: 1, PUPIL: 1, EYE: 2}
    for k, i in enumerate(ch.get("portrait", PORTRAIT_SLOTS)):
        fixed[i] = 3 + slot * 4 + k
    for light, shade in ((SKIN_L, SKIN_M), (BELLY_D, BELLY_L)):
        if light not in fixed and shade in fixed:
            fixed[light] = fixed[shade]
    remap = {}
    for i in range(16):
        if i in fixed:
            remap[i] = fixed[i]
        else:
            remap[i] = min(choices, key=lambda c: sum((pal[i][k] - c[1][k]) ** 2 for k in range(3)))[0]
    return np.vectorize(remap.get)(bust)


def write_sheet(path, names=None, zoom=3):
    """Preview: one row per character with its 5 near views, 5 mid, 5 far, and the portrait."""
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    import retro_run as rr
    chosen = [i for i, ch in enumerate(CHARACTERS) if not names or ch["name"] in names]
    rows = []
    for i in chosen:
        ch = CHARACTERS[i]
        fr = frames(ch)
        group = CHARACTERS[(i // 3) * 3:(i // 3) * 3 + 3]
        cells = [(f, ch["palette"]) for k in ("near", "mid", "far") for f in fr[k]]
        cells.append((portrait_indices(ch, i % 3, fr["bust"]), portrait_palette(group)))
        rows.append(cells)
    cols, cell = 16, 34
    W, H = cols * cell * zoom, len(rows) * cell * zoom
    img = bytearray([90, 150, 70] * W * H)
    for r, cells in enumerate(rows):
        for c, (pix, pal) in enumerate(cells):
            ox, oy = c * cell * zoom, r * cell * zoom
            if c == 15:  # the portrait sits on its kart colour, as on the select screen
                kc = bytes(CHARACTERS[chosen[r]]["palette"][KART_M])
                for y in range(32 * zoom):
                    o = ((oy + y) * W + ox) * 3
                    img[o:o + 32 * zoom * 3] = kc * (32 * zoom)
            for y in range(pix.shape[0]):
                for x in range(pix.shape[1]):
                    if pix[y, x]:
                        col = bytes(pal[pix[y, x]])
                        for dy in range(zoom):
                            o = ((oy + y * zoom + dy) * W + ox + x * zoom) * 3
                            img[o:o + 3 * zoom] = col * zoom
    rr.write_png(path, W, H, bytes(img))


if __name__ == "__main__":
    write_sheet(sys.argv[1] if len(sys.argv) > 1 else "/tmp/sheet.png", sys.argv[2:] or None)
