"""Valida o layout de habilidades descoberto no EDIT00000000."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pes2016mlbl import core as C, pes16crypt as CR

PROJ = Path(__file__).resolve().parent.parent

BL_ORDER = [
    ("attack", 120), ("defence", 128), ("goalkeeping", 135), ("dribbling", 142),
    ("ball_control", 149), ("finishing", 160), ("low_pass", 167),
    ("lofted_pass", 174), ("header", 181), ("ball_winning", 192),
    ("place_kicking", 199), ("swerve", 206), ("gk2", 213), ("gk3", 224),
    ("gk4", 231), ("gk5", 238), ("speed", 245), ("body_balance", 256),
    ("kicking_power", 263), ("explosive_power", 270), ("jump", 277),
    ("stamina", 288),
]

EDIT_ORDER = [
    ("attack", 128), ("defence", 135), ("goalkeeping", 142), ("dribbling", 149),
    ("finishing", 160), ("low_pass", 167), ("lofted_pass", 174), ("header", 181),
    ("ball_control", 266), ("ball_winning", 273), ("place_kicking", 330),
    ("swerve", 192), ("gk2", 199), ("gk3", 206), ("gk4", 213), ("gk5", 280),
    ("speed", 337), ("body_balance", 224), ("kicking_power", 231),
    ("explosive_power", 238), ("jump", 245), ("stamina", 352),
]

bl_data = C.load(PROJ / "BL00000000.original").data
ed = CR.decrypt((PROJ / "EDIT00000000.original").read_bytes(),
                CR.MASTER_KEYS["pes16"]).data

TABLE_BASE, TABLE_SIZE = 2611932, 228
EDIT_BASE, EDIT_STEP = 76, 112

hits_full = 0
hits_part = 0
total = 0
for i in range(0, 400):
    b = TABLE_BASE + i * TABLE_SIZE
    if b + TABLE_SIZE > len(bl_data):
        break
    nm = bl_data[b + 0x40:b + 0x40 + 46].split(b"\x00")[0].decode("latin1", "ignore").strip()
    if not (3 <= len(nm) <= 25 and nm[0].isalpha()):
        continue
    bl_vals = {k: C.read_bits(bl_data, b * 8 + off, 7) for k, off in BL_ORDER}
    if any(v > 99 for v in bl_vals.values()):
        continue
    sn = nm.split()[-1].encode("latin1")
    if len(sn) < 4:
        continue
    prefix = len(nm.encode("latin1")) - len(sn)
    base = None
    for h in range(len(ed)):
        if ed.startswith(sn, h):
            cand = h - 0x32 - prefix
            if cand >= EDIT_BASE and (cand - EDIT_BASE) % EDIT_STEP == 0:
                base = cand
            break
    if base is None:
        continue
    total += 1
    ed_vals = {k: C.read_bits(ed, base * 8 + off, 7) for k, off in EDIT_ORDER}
    bad = [k for k in bl_vals if bl_vals[k] != ed_vals[k]]
    if not bad:
        hits_full += 1
    else:
        hits_part += 1
        if hits_part <= 8:
            print("  %-16s difere em: %s" % (nm, ", ".join("%s %d/%d" % (k, bl_vals[k], ed_vals[k]) for k in bad)))

print()
print("jogadores comparados: %d | bateram TODOS os 22 campos: %d | parciais: %d"
      % (total, hits_full, hits_part))

# WARLISON
print()
print("WARLISON no EDIT (base 1646588):")
for k, off in EDIT_ORDER:
    print("   %-16s %3d" % (k, C.read_bits(ed, 1646588 * 8 + off, 7)))
