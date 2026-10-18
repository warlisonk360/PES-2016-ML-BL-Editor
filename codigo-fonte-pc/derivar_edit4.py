"""Descobre os offsets das habilidades no EDIT00000000 por consenso global.

Para cada offset de bit (0..895) do registro de 112 bytes do EDIT, mede em
quantos dos 53 jogadores conhecidos o valor de 7 bits ali lido coincide com
o valor conhecido (lido do save BL).  O offset correto de cada habilidade
acerta praticamente todos.
"""

import sys
from collections import Counter, defaultdict
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

bl_data = C.load(PROJ / "BL00000000.original").data
ed = CR.decrypt((PROJ / "EDIT00000000.original").read_bytes(),
                CR.MASTER_KEYS["pes16"]).data

TABLE_BASE, TABLE_SIZE = 2611932, 228
EDIT_BASE, EDIT_STEP = 76, 112


def bl_players():
    out = {}
    for i in range(0, 400):
        b = TABLE_BASE + i * TABLE_SIZE
        if b + TABLE_SIZE > len(bl_data):
            break
        nm = bl_data[b + 0x40:b + 0x40 + 46].split(b"\x00")[0].decode("latin1", "ignore").strip()
        if not (3 <= len(nm) <= 25 and nm[0].isalpha()):
            continue
        vals = {k: C.read_bits(bl_data, b * 8 + off, 7) for k, off in BL_ORDER}
        if any(v > 99 for v in vals.values()):
            continue
        out[nm] = vals
    return out


players = bl_players()

records = []
for nm, vals in players.items():
    sn = nm.split()[-1].encode("latin1")
    if len(sn) < 4:
        continue
    prefix = len(nm.encode("latin1")) - len(sn)
    for h in range(len(ed)):
        if ed.startswith(sn, h):
            base = h - 0x32 - prefix
            if base >= EDIT_BASE and (base - EDIT_BASE) % EDIT_STEP == 0:
                records.append((nm, base, vals))
            break

print("registros:", len(records))
N = len(records)

# matriz offset x campo -> quantos jogadores batem
score = defaultdict(int)
for nm, base, vals in records:
    seen = {}
    for o in range(0, EDIT_STEP * 8 - 7):
        v = C.read_bits(ed, base * 8 + o, 7)
        seen[o] = v
    for k, _ in BL_ORDER:
        want = vals[k]
        for o, v in seen.items():
            if v == want:
                score[(k, o)] += 1

print()
print("campo            -> melhores offsets (offset, jogadores que batem / %d)" % N)
assign = {}
for k, _ in BL_ORDER:
    opts = sorted([(o, n) for (kk, o), n in score.items() if kk == k], key=lambda t: -t[1])
    # descarta os que sao apenas coincidencia de valor comum (muitos valores 40/68)
    print("  %-16s %s" % (k, ["%d:%d" % (o, n) for o, n in opts[:6]]))
    if opts:
        assign[k] = opts

print()
print("consenso forte (>= 90% dos jogadores):")
for k, _ in BL_ORDER:
    opts = [(o, n) for (kk, o), n in score.items() if kk == k and n >= 0.9 * N]
    print("  %-16s %s" % (k, opts))
