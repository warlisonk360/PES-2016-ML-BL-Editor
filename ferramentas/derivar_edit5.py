"""Descobre altura, peso e idade no registro do EDIT00000000 por consenso."""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "codigo-fonte-pc"))

from pes2016mlbl import core as C, pes16crypt as CR

PROJ = Path(__file__).resolve().parent.parent
bl_data = C.load(PROJ / "BL00000000.original").data
ed = CR.decrypt((PROJ / "EDIT00000000.original").read_bytes(),
                CR.MASTER_KEYS["pes16"]).data

TABLE_BASE, TABLE_SIZE = 2611932, 228
EDIT_BASE, EDIT_STEP = 76, 112

recs = []
for i in range(0, 400):
    b = TABLE_BASE + i * TABLE_SIZE
    if b + TABLE_SIZE > len(bl_data):
        break
    nm = bl_data[b + 0x40:b + 0x40 + 46].split(b"\x00")[0].decode("latin1", "ignore").strip()
    if not (3 <= len(nm) <= 25 and nm[0].isalpha()):
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
    recs.append((nm, base, b))

print("registros:", len(recs))
N = len(recs)

# altura/peso: 1 byte cada
byte_hits = defaultdict(int)
age_hits = defaultdict(int)
for nm, eb, bl in recs:
    alt = bl_data[bl + 0x0C]
    peso = bl_data[bl + 0x0D]
    idade = C.read_bits(bl_data, bl * 8 + 320, 6)
    for o in range(0, EDIT_STEP - 1):
        if ed[eb + o] == alt:
            byte_hits[("altura", o)] += 1
        if ed[eb + o] == peso:
            byte_hits[("peso", o)] += 1
    for o in range(0, EDIT_STEP * 8 - 6):
        if C.read_bits(ed, eb * 8 + o, 6) == idade:
            age_hits[o] += 1

for k in ("altura", "peso"):
    opts = sorted([(o, n) for (kk, o), n in byte_hits.items() if kk == k], key=lambda t: -t[1])
    print("%-8s byte   -> %s" % (k, ["%d:%d" % (o, n) for o, n in opts[:6]]))
opts = sorted(age_hits.items(), key=lambda t: -t[1])
print("%-8s 6 bits -> %s" % ("idade", ["%d:%d" % (o, n) for o, n in opts[:6]]))
