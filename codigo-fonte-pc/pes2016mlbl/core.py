"""
Core (GUI-free) logic for the [PC] PES 2016 ML-BL Editor.

How this works
--------------
PES 2016 (PC) save files (BL00000000 / ML00000000, and EDIT files) are
*encrypted*.  The original Windows tool never actually implemented the PC
crypto ("DecryptPC"/"EncryptPC" only copy the bytes), which is why it only
worked when paired with a separate "crypter".  This version decrypts the
save, edits the plaintext, and re-encrypts it - all by itself.

The crypto (MT19937 + stream cipher) was ported from the public-domain
project https://github.com/the4chancup/pesXdecrypter and validated: our
decrypted output is byte-for-byte identical to the reference crypter's, and
encrypt(decrypt(x)) == x.

Field offsets
-------------
Offsets are RELATIVE TO THE DECRYPTED DATA BLOCK (not the file).  They were
validated in-game on a real PC "Become a Legend" save.  The original tool's
"PC" offsets are wrong for real saves (they point at zeroed areas); the
"XBOX 360" offsets turned out to be the correct data-block offsets.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from . import pes16crypt as CR

# ---------------------------------------------------------------------------
# Field offsets, relative to the decrypted DATA block
# ---------------------------------------------------------------------------

# Master League team funds: 3 bytes little-endian.
ML_MONEY_OFFSET = 7961553

# BAL (Become a Legend) training block: 9 consecutive bytes, 1 byte each.
BAL_STATS_BASE = 8815624
BAL_STAT_COUNT = 9
BAL_TRAINING_OFFSET = 8815633        # Training (0-20)
BAL_FOCUS_OFFSET = 7973083           # Focus Points (0-100)

# Manager name is written (after clearing 30 bytes) at these three locations.
MANAGER_NAME_OFFSETS = (1468712, 1469336, 7973152)
MANAGER_NAME_CLEAR = 30
MANAGER_NAME_MAX_CHARS = 15

# The data block must be at least this long to contain every field we touch.
MIN_DATA_SIZE = max(
    ML_MONEY_OFFSET + 3,
    BAL_STATS_BASE + BAL_STAT_COUNT + 1,
    BAL_FOCUS_OFFSET + 1,
    MANAGER_NAME_OFFSETS[-1] + MANAGER_NAME_CLEAR,
)

# X360 STFS title id, used only to give a friendly error message.
X360_TITLEID_OFFSET = 864
X360_TITLEID = b"KN\x08a"  # 4B 4E 08 61

# ---------------------------------------------------------------------------
# Currency / stat metadata (recovered from the original tool)
# ---------------------------------------------------------------------------

CURRENCIES = ["€ Euro", "$ US Dollar", "¥ Yen", "£ Pound", "R$ Brazilian Real"]
CURRENCY_FACTOR = [70, 100, 10000, 60, 200]
CURRENCY_MULT = [1.428571428571429, 1.0, 0.01, 1.666666666666667, 0.5]

# Five "Team Funds" radio presets: raw 24-bit values (little-endian).
PRESET_RAW = [714286, 1428572, 2857144, 4285716, 16777215]

PRESET_LABELS = {
    0: ["50.000.020€", "100.000.040€", "200.000.080€", "300.000.120€", "1.174.405.050€ (Max Funds)"],
    1: ["71.428.600$", "142.857.200$", "285.714.400$", "428.571.600$", "1.677.721.500$ (Max Funds)"],
    2: ["7.142.860.000¥", "14.285.720.000¥", "28.571.440.000¥", "42.857.160.000¥", "167.772.150.000¥ (Max Funds)"],
    3: ["42.857.160£", "85.714.320£", "171.428.640£", "257.142.960£", "1.006.632.900£ (Max Funds)"],
    4: ["142.857.200R$", "285.714.400R$", "571.428.800R$", "857.143.200R$", "3.355.443.000R$ (Max Funds)"],
}

STAT_NAMES = [
    "Shooting", "Passing", "Dribbling", "Defence", "Speed",
    "Physical", "Stamina", "Skill Training", "Position Training",
]
STAT_MAX = 6
TRAINING_MAX = 20
FOCUS_MAX = 100
MAX_STATS_VALUES = [6] * 9 + [20]


class EditorError(Exception):
    pass


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _round_half_away(x: float) -> int:
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def detect_mode(filename: str) -> str | None:
    """Return 'ML', 'BL' or None based on the file name."""
    base = Path(filename).name.upper()
    if "ML00" in base:
        return "ML"
    if "BL00" in base:
        return "BL"
    return None


# ---------------------------------------------------------------------------
# Money / manager name / stats (operate on the decrypted DATA block)
# ---------------------------------------------------------------------------

def read_money_raw(data: bytes) -> int:
    b0, b1, b2 = data[ML_MONEY_OFFSET:ML_MONEY_OFFSET + 3]
    return b0 | (b1 << 8) | (b2 << 16)


def write_money_raw(buf: bytearray, raw: int) -> None:
    raw &= 0xFFFFFF
    buf[ML_MONEY_OFFSET] = raw & 0xFF
    buf[ML_MONEY_OFFSET + 1] = (raw >> 8) & 0xFF
    buf[ML_MONEY_OFFSET + 2] = (raw >> 16) & 0xFF


def money_display(raw: int, currency_index: int) -> int:
    return raw * CURRENCY_FACTOR[currency_index]


def money_raw_from_display(value: float, currency_index: int) -> int:
    mult = CURRENCY_MULT[currency_index]
    t = _round_half_away(value * mult)
    raw = _round_half_away(t * 0.01)
    return max(0, min(raw, 0xFFFFFF))


def read_manager_name(data: bytes) -> str:
    chunk = data[MANAGER_NAME_OFFSETS[0]:MANAGER_NAME_OFFSETS[0] + MANAGER_NAME_CLEAR]
    cut = chunk.find(b"\x00")
    if cut != -1:
        chunk = chunk[:cut]
    return chunk.decode("utf-8", errors="ignore")[:MANAGER_NAME_MAX_CHARS]


def write_manager_name(buf: bytearray, name: str) -> None:
    encoded = name.encode("utf-8")[:MANAGER_NAME_CLEAR]
    zeros = bytes(MANAGER_NAME_CLEAR)
    for off in MANAGER_NAME_OFFSETS:
        buf[off:off + MANAGER_NAME_CLEAR] = zeros
        buf[off:off + len(encoded)] = encoded


def read_stats(data: bytes) -> dict:
    stats = {}
    for i, name in enumerate(STAT_NAMES):
        stats[name] = data[BAL_STATS_BASE + i]
    stats["Training"] = data[BAL_TRAINING_OFFSET]
    stats["Focus"] = data[BAL_FOCUS_OFFSET]
    return stats


def write_stats(buf: bytearray, stats: dict) -> None:
    for i, name in enumerate(STAT_NAMES):
        buf[BAL_STATS_BASE + i] = int(stats[name]) & 0xFF
    buf[BAL_TRAINING_OFFSET] = int(stats["Training"]) & 0xFF
    buf[BAL_FOCUS_OFFSET] = int(stats["Focus"]) & 0xFF


# ---------------------------------------------------------------------------
# BAL player record ("Habilidades" / abilities screen)
# ---------------------------------------------------------------------------
# The BAL player is stored as a 228-byte player record; the name lives at
# +0x40 (46 bytes, zero terminated) and height/weight are plain bytes at
# +0x0C / +0x0D.  The very same player also appears in a second table (the
# league's player database), using an identical layout, so we locate *every*
# record that carries the player's name and write the values to all of them
# (that way it does not matter which copy the game reads).
#
# Ability values are bit-packed, LSB-first, with 7-bit fields grouped as
# [7,7,7,7,4] (32 bits = 4 bytes) starting at bit 128.  Attacking Prowess
# sits alone at bit 120, just before the first group (bit 127, the last
# free bit before the group, holds the stronger foot).
#
# Positions were recovered with an in-game before/after diff (only the three
# stats that changed on screen changed in the record) and validated against
# the ages of dozens of real players.
#
# The "characteristics" that sit outside the 7-bit grid (form, injury, weak
# foot, stronger foot) were located by matching this record against the EDIT
# player database, whose 112-byte layout is documented (see EDIT_FIELD_POS);
# every one of them matched for 54 of 54 real players:
#
#     stronger foot  bit 127 (1 bit, 0 = right, 1 = left)
#     form           bit 220 (3 bits, stored = in-game - 1, so 1..8)
#     weak foot acc. bit 366 (2 bits, stored = in-game - 1, so 1..4)
#     injury         bit 368 (2 bits, stored = in-game - 1, so 1..3)
#     weak foot freq.bit 370 (2 bits, stored = in-game - 1, so 1..4)
#
# The *active* injury (the one that keeps the player out) is separate from the
# "injury resistance" above and is a plain byte at +0x0E: 0 = healthy, any
# other value = injured (the game's own code).  It was recovered by diffing
# the same BAL career before and after the player recovered - the byte went
# 44 -> 0 in both the plain record and the compressed snapshot.
#
# The game shows some of these one higher than they are stored; FIELD_BIAS
# below hides that from the UI.

PLAYER_RECORD_SIZE = 228
PLAYER_NAME_OFFSET = 0x40
PLAYER_NAME_LEN = 46
PLAYER_HEIGHT_OFFSET = 0x0C
PLAYER_WEIGHT_OFFSET = 0x0D
# Active injury state: 0 = healthy, anything else = injured (the game stores
# its own code there; 44 was seen on a player out injured).  Found by diffing
# the same career before/after the player recovered: the byte went 44 -> 0 in
# both copies (plain record and career snapshot).  Writing 0 heals the player.
PLAYER_INJURY_STATE_OFFSET = 0x0E

# (key, label, kind, pos, width, max).  kind is "bit" (pos = bit offset) or
# "byte" (pos = byte offset).
PLAYER_FIELDS = [
    # --- Habilidades (mesma ordem da tela do jogo) ---
    ("attack",          "Ataque (habil. ofensiva)", "bit",  120, 7,  99),
    ("ball_control",    "Controle de bola",         "bit",  149, 7,  99),
    ("dribbling",       "Drible",                   "bit",  142, 7,  99),
    ("low_pass",        "Passe rasteiro",           "bit",  167, 7,  99),
    ("lofted_pass",     "Passe pelo alto",          "bit",  174, 7,  99),
    ("finishing",       "Finalização",              "bit",  160, 7,  99),
    ("place_kicking",   "Chute colocado",           "bit",  199, 7,  99),
    ("swerve",          "Efeito",                   "bit",  206, 7,  99),
    ("header",          "Cabeçada",                 "bit",  181, 7,  99),
    ("defence",         "Defesa (habil. defensiva)","bit",  128, 7,  99),
    ("ball_winning",    "Desarme",                  "bit",  192, 7,  99),
    ("kicking_power",   "Força do chute",           "bit",  263, 7,  99),
    ("speed",           "Velocidade",               "bit",  245, 7,  99),
    ("explosive_power", "Explosão",                 "bit",  270, 7,  99),
    ("body_balance",    "Equilíbrio",               "bit",  256, 7,  99),
    ("jump",            "Impulsão",                 "bit",  277, 7,  99),
    ("stamina",         "Resistência",              "bit",  288, 7,  99),
    # --- Habilidades de goleiro ---
    ("goalkeeping",     "Habil. goleiro",           "bit",  135, 7,  99),
    ("gk_catching",     "Defesas (catching)",       "bit",  213, 7,  99),
    ("gk_clearing",     "Reposição (clearing)",     "bit",  224, 7,  99),
    ("gk_reflexes",     "Reflexos",                 "bit",  231, 7,  99),
    ("gk_coverage",     "Cobertura",                "bit",  238, 7,  99),
    # --- Físico / outros (mesma ordem da tela 3/5 do jogo) ---
    ("weak_foot_usage",    "Pior pé: frequência (1-4)", "bit", 370, 2, 4),
    ("weak_foot_accuracy", "Pior pé: precisão (1-4)",   "bit", 366, 2, 4),
    ("form",               "Condição física (1-8)",     "bit", 220, 3, 8),
    ("injury",             "Resistência a lesão (1-3)", "bit", 368, 2, 3),
    ("injury_state",       "Lesão ativa (0 = saudável)", "byte", PLAYER_INJURY_STATE_OFFSET, 0, 255),
    ("age",                "Idade",                     "bit", 320, 6, 63),
    ("height",             "Altura (cm)",               "byte", PLAYER_HEIGHT_OFFSET, 0, 255),
    ("weight",             "Peso (kg)",                 "byte", PLAYER_WEIGHT_OFFSET, 0, 130),
    ("stronger_foot",      "Melhor pé (0=dir, 1=esq)",  "bit", 127, 1, 1),
]

# Some values are stored one lower than the game displays them ("in-game
# value minus one"): the UI shows stored + bias.
FIELD_BIAS = {
    "form": 1,
    "injury": 1,
    "weak_foot_usage": 1,
    "weak_foot_accuracy": 1,
}

PLAYER_GROUPS = [
    ("Habilidades", [f[0] for f in PLAYER_FIELDS if f[0] in (
        "attack", "ball_control", "dribbling", "low_pass", "lofted_pass",
        "finishing", "place_kicking", "swerve", "header", "defence",
        "ball_winning", "kicking_power", "speed", "explosive_power",
        "body_balance", "jump", "stamina")]),
    ("Goleiro", [f[0] for f in PLAYER_FIELDS if f[0] in (
        "goalkeeping", "gk_catching", "gk_clearing", "gk_reflexes",
        "gk_coverage")]),
    ("Físico / outros", [f[0] for f in PLAYER_FIELDS if f[0] in (
        "weak_foot_usage", "weak_foot_accuracy", "form", "injury",
        "injury_state", "age", "height", "weight", "stronger_foot")]),
]

PLAYER_FIELD_BY_KEY = {f[0]: f for f in PLAYER_FIELDS}


# ---------------------------------------------------------------------------
# Bit-level helpers (little-endian bit order)
# ---------------------------------------------------------------------------

def read_bits(data: bytes, pos: int, width: int) -> int:
    shift = pos & 7
    start = pos >> 3
    n = (shift + width + 7) >> 3
    val = int.from_bytes(data[start:start + n], "little")
    return (val >> shift) & ((1 << width) - 1)


def write_bits(buf: bytearray, pos: int, width: int, value: int) -> None:
    shift = pos & 7
    start = pos >> 3
    n = (shift + width + 7) >> 3
    mask = ((1 << width) - 1) << shift
    cur = int.from_bytes(buf[start:start + n], "little")
    cur = (cur & ~mask) | ((value << shift) & mask)
    buf[start:start + n] = cur.to_bytes(n, "little")


def _readable_name(chunk: bytes) -> str | None:
    cut = chunk.find(b"\x00")
    body = chunk if cut == -1 else chunk[:cut]
    if len(body) < 2:
        return None
    for c in body:
        if c < 32 or c > 126:
            return None
    return body.decode("latin1")


_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ .'-")


def _person_name(chunk: bytes) -> str | None:
    s = _readable_name(chunk)
    if s is None:
        return None
    s = s.strip()
    if len(s) < 2 or not s[0].isalpha() or any(c not in _NAME_CHARS for c in s):
        return None
    return s


def _plausible_player_record(rec: bytes) -> bool:
    if len(rec) < PLAYER_RECORD_SIZE:
        return False
    h = rec[PLAYER_HEIGHT_OFFSET]
    w = rec[PLAYER_WEIGHT_OFFSET]
    return 120 <= h <= 230 and 30 <= w <= 130


def find_created_player(data: bytes) -> tuple[int, str] | None:
    """Find the BAL created-player record (Player ID = 0xFFFFFFFF).

    The 0xFFFFFFFF marker also appears in lots of unrelated structures, so
    candidates are scored: a real record has a person-like name at +0x40, a
    matching print name at +0x6E and a plausible age.
    """
    marker = b"\xff\xff\xff\xff"
    start = 0
    best: tuple[int, tuple[int, str]] | None = None
    while True:
        o = data.find(marker, start)
        if o < 0:
            break
        start = o + 1
        end = o + PLAYER_RECORD_SIZE
        if end > len(data):
            continue
        rec = data[o:end]
        if not _plausible_player_record(rec):
            continue
        name = _person_name(rec[PLAYER_NAME_OFFSET:PLAYER_NAME_OFFSET + PLAYER_NAME_LEN])
        if not name:
            continue
        score = 0
        if _readable_name(rec[0x6E:0x6E + 16]):
            score += 3
        age = read_bits(data, o * 8 + 320, 6)
        if 15 <= age <= 45:
            score += 2
        if 150 <= rec[PLAYER_HEIGHT_OFFSET] <= 210 and 50 <= rec[PLAYER_WEIGHT_OFFSET] <= 100:
            score += 1
        if best is None or score > best[0]:
            best = (score, (o, name))
            if score >= 6:
                break
    return best[1] if best else None


def find_player_records(data: bytes, name: str,
                        height: int | None = None,
                        weight: int | None = None) -> list[int]:
    """All record bases in *data* that carry *name* (and optional H/W)."""
    raw = name.encode("latin1", errors="ignore")
    if len(raw) < 2:
        return []
    out: list[int] = []
    start = 0
    while True:
        hit = data.find(raw, start)
        if hit < 0:
            break
        start = hit + 1
        base = hit - PLAYER_NAME_OFFSET
        if base < 0 or base + PLAYER_RECORD_SIZE > len(data):
            continue
        rec = data[base:base + PLAYER_RECORD_SIZE]
        if not _plausible_player_record(rec):
            continue
        if _readable_name(rec[PLAYER_NAME_OFFSET:PLAYER_NAME_OFFSET + PLAYER_NAME_LEN]) != name:
            continue
        if height is not None and rec[PLAYER_HEIGHT_OFFSET] != height:
            continue
        if weight is not None and rec[PLAYER_WEIGHT_OFFSET] != weight:
            continue
        out.append(base)
    return out


def filter_records_by_body(data: bytes, bases: list[int],
                           height: int, weight: int,
                           tol_h: int = 8, tol_w: int = 12) -> list[int]:
    """Keep only records whose height/weight are close to *height*/*weight*.

    The BL save also holds the league's real players, so matching by name
    alone could edit a real player that happens to share the name (there is
    an "A. SMITH" in the user's save, for instance).  The created player and
    its database copy always have the same body, so this narrows it safely.
    """
    out = []
    for b in bases:
        rec = data[b:b + PLAYER_RECORD_SIZE]
        if (abs(rec[PLAYER_HEIGHT_OFFSET] - height) <= tol_h
                and abs(rec[PLAYER_WEIGHT_OFFSET] - weight) <= tol_w):
            out.append(b)
    return out


def _order_records(bases: list[int], created_base: int | None = None) -> list[int]:
    """Put the "live" player-table record first and the created record last.

    The created-player record (Player ID 0xFFFFFFFF) is only a snapshot from
    the moment the player was created; once the save has been played the
    game keeps an updated copy inside the player database.  Reading the
    database copy first therefore shows the values the game actually uses.
    """
    ordered = [b for b in bases if b != created_base]
    if created_base is not None and created_base in bases:
        ordered.append(created_base)
    return ordered


def read_player(data: bytes, base: int) -> dict:
    vals: dict[str, int] = {}
    for key, _label, kind, pos, width, _mx in PLAYER_FIELDS:
        if kind == "bit":
            vals[key] = (read_bits(data, base * 8 + pos, width)
                         + FIELD_BIAS.get(key, 0))
        else:
            vals[key] = data[base + pos]
    return vals


def write_player(buf: bytearray, base: int, vals: dict) -> None:
    """Write *vals* (the values shown by the UI) into a player record."""
    for key, _label, kind, pos, width, _mx in PLAYER_FIELDS:
        if key not in vals:
            continue
        v = int(vals[key])
        if kind == "bit":
            v = max(0, min(v - FIELD_BIAS.get(key, 0), (1 << width) - 1))
            write_bits(buf, base * 8 + pos, width, v)
        else:
            buf[base + pos] = max(0, min(v, 255))


# ---------------------------------------------------------------------------
# EDIT00000000 - the player database (where the BAL player really lives)
# ---------------------------------------------------------------------------
# The "Become a Legend" player is a *created player*: the game registers it in
# the EDIT data (the player database) and it is that copy which the in-game
# "Habilidades" screen shows.  Editing only BL00000000 therefore changes the
# file but not what the game displays; the EDIT record has to be written too.
#
# EDIT records are 112 bytes at `76 + 112*i`, name at +0x32 (46 bytes) and
# print name at +0x60; height/weight sit at the same +0x0C/+0x0D as in BL.
# The ability bits use a *different* layout from BL, recovered by matching the
# EDIT database against the league players found in the BL save (40 of 53
# players match all 22 fields, and the user's own player matches the values
# shown by the game exactly).
EDIT_RECORD_SIZE = 112
EDIT_TABLE_BASE = 76
EDIT_TABLE_STEP = 112
EDIT_NAME_OFFSET = 0x32
EDIT_NAME_LEN = 46
EDIT_PRINT_NAME_OFFSET = 0x60
EDIT_HEIGHT_OFFSET = 0x0C
EDIT_WEIGHT_OFFSET = 0x0D

# key -> ("bit"|"byte", position).  Only the fields whose position is known.
EDIT_FIELD_POS = {
    "attack":          ("bit", 128),
    "defence":         ("bit", 135),
    "goalkeeping":     ("bit", 142),
    "dribbling":       ("bit", 149),
    "ball_control":    ("bit", 266),
    "finishing":       ("bit", 160),
    "low_pass":        ("bit", 167),
    "lofted_pass":     ("bit", 174),
    "header":          ("bit", 181),
    "ball_winning":    ("bit", 273),
    "place_kicking":   ("bit", 330),
    "swerve":          ("bit", 192),
    "gk_catching":     ("bit", 199),
    "gk_clearing":     ("bit", 206),
    "gk_reflexes":     ("bit", 213),
    "gk_coverage":     ("bit", 280),
    "speed":           ("bit", 337),
    "body_balance":    ("bit", 224),
    "kicking_power":   ("bit", 231),
    "explosive_power": ("bit", 238),
    "jump":            ("bit", 245),
    "stamina":         ("bit", 352),
    "age":             ("bit", 344),
    "form":            ("bit", 188),
    "injury":          ("bit", 220),
    "weak_foot_accuracy": ("bit", 294),
    "weak_foot_usage": ("bit", 296),
    "stronger_foot":   ("bit", 364),
    "height":          ("byte", EDIT_HEIGHT_OFFSET),
    "weight":          ("byte", EDIT_WEIGHT_OFFSET),
}

# Common save-file names for the EDIT file, tried in order.
EDIT_FILE_NAMES = ("EDIT00000000", "EDIT00000000.bin", "EDIT")


def find_edit_records(data: bytes, name: str,
                      height: int | None = None,
                      weight: int | None = None,
                      tol_h: int = 8, tol_w: int = 12) -> list[int]:
    """Record bases inside the EDIT player database that carry *name*.

    The database is a fixed grid, so every hit is snapped to `76 + 112*i`;
    when the name is not on the grid (a few records are not) a looser match
    is accepted as long as the body looks right.
    """
    raw = name.encode("latin1", errors="ignore")
    if len(raw) < 2:
        return []
    aligned: list[int] = []
    loose: list[int] = []
    start = 0
    while True:
        hit = data.find(raw, start)
        if hit < 0:
            break
        start = hit + 1
        base = hit - EDIT_NAME_OFFSET
        if base < 0 or base + EDIT_RECORD_SIZE > len(data):
            continue
        rec = data[base:base + EDIT_RECORD_SIZE]
        if _readable_name(rec[EDIT_NAME_OFFSET:EDIT_NAME_OFFSET + EDIT_NAME_LEN]) != name:
            continue
        h, w = rec[EDIT_HEIGHT_OFFSET], rec[EDIT_WEIGHT_OFFSET]
        if height is not None and abs(h - height) > tol_h:
            continue
        if weight is not None and abs(w - weight) > tol_w:
            continue
        if (base - EDIT_TABLE_BASE) % EDIT_TABLE_STEP == 0:
            aligned.append(base)
        else:
            loose.append(base)
    return aligned or loose


def read_edit_player(data: bytes, base: int) -> dict:
    vals: dict[str, int] = {}
    for key, (kind, pos) in EDIT_FIELD_POS.items():
        if kind == "bit":
            _k, _l, _kind, _p, width, _mx = PLAYER_FIELD_BY_KEY[key]
            vals[key] = (read_bits(data, base * 8 + pos, width)
                         + FIELD_BIAS.get(key, 0))
        else:
            vals[key] = data[base + pos]
    return vals


def write_edit_player(buf: bytearray, base: int, vals: dict) -> None:
    """Write *vals* into an EDIT database record (unknown fields are left)."""
    for key, (kind, pos) in EDIT_FIELD_POS.items():
        if key not in vals:
            continue
        v = int(vals[key])
        if kind == "bit":
            _k, _l, _kind, _p, width, _mx = PLAYER_FIELD_BY_KEY[key]
            v = max(0, min(v - FIELD_BIAS.get(key, 0), (1 << width) - 1))
            write_bits(buf, base * 8 + pos, width, v)
        else:
            buf[base + pos] = max(0, min(v, 255))


def find_edit_file(near: str | Path) -> Path | None:
    """Look for an EDIT00000000 next to *near* (case-insensitive).

    Accepts the plain name as well as copies such as ``EDIT00000000.original``
    that people often keep in the same folder.
    """
    folder = Path(near).parent
    try:
        entries = {p.name.upper(): p for p in folder.iterdir() if p.is_file()}
    except OSError:
        return None
    for wanted in EDIT_FILE_NAMES:
        hit = entries.get(wanted.upper())
        if hit is not None:
            return hit
    for up, p in sorted(entries.items()):
        if up.startswith("EDIT00000000"):
            return p
    return None


# ---------------------------------------------------------------------------
# The BL "career snapshot" - a compressed copy of the player inside the save
# ---------------------------------------------------------------------------
# BL00000000 does not end with plain data: the tail is a run of 256 KiB blocks
# that are stored zlib-compressed (a real save has 22 of them, 5.25 MB
# decompressed).  That region holds the career's own copy of the player
# database, and THAT is the copy the game reads for the "Become a Legend"
# career: on a real save we set every plain-text record to 99 while this copy
# kept the old numbers, and the in-game screen kept showing the old numbers.
# The EDIT database copy is what the game's *Edit* menu shows; the career
# screen reads this snapshot.  Both have to be written.
#
# Container layout (validated by rebuilding a real save byte-for-byte):
#
#   ... raw data ...
#   u32LE  section size | u32LE 0
#   u32BE  magic        | u32BE 0
#   u32BE  total uncompressed bytes | u32BE total compressed bytes
#   then, repeated:
#       u32BE uncompressed size | u32BE compressed size | u32BE next offset
#       zlib stream (level 9 -> always starts with 78 DA)
#
# `next offset` is relative to the section start and points at the following
# block's header; the last block stores 0 and its stream ends the data block.
#
# Inside the snapshot the player records keep the exact same 228-byte layout
# as the plain-text database (the first record even starts mid-record, with
# its name at +0x40), so the very same field offsets are used to patch it.

COMP_CHUNK_SIZE = 262144
COMP_ZLIB_HEADER = b"\x78\xda"
COMP_SECTION_HEADER = 16


def _be32(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 4], "big")


def _walk_compressed_section(data: bytes, base: int):
    """Follow the block chain from *base*; return the block list or None."""
    pos = base + COMP_SECTION_HEADER
    blocks: list[tuple[int, int, int]] = []
    while pos + 12 <= len(data):
        unc = _be32(data, pos)
        comp = _be32(data, pos + 4)
        nxt = _be32(data, pos + 8)
        if comp <= 0 or unc <= 0 or pos + 12 + comp > len(data):
            return None
        if data[pos + 12:pos + 14] != COMP_ZLIB_HEADER:
            return None
        blocks.append((pos, unc, comp))
        if nxt == 0:
            return blocks if pos + 12 + comp == len(data) else None
        if base + nxt != pos + 12 + comp:
            return None
        pos = base + nxt
    return None


def find_compressed_section(data: bytes):
    """Locate the zlib block chain of a BL save.

    Returns ``(base, [(pos, uncompressed, compressed), ...])`` or ``None``.
    The chain must decompress-block-consistently and end exactly at the end
    of the data block, so random look-alikes are rejected.
    """
    start = 0
    while True:
        i = data.find(COMP_ZLIB_HEADER, start)
        if i < 0:
            return None
        start = i + 1
        base = i - (COMP_SECTION_HEADER + 12)
        if base < 0:
            continue
        blocks = _walk_compressed_section(data, base)
        if blocks:
            return base, blocks


def compressed_section_info(data: bytes):
    """(number of blocks, total decompressed bytes) or None."""
    found = find_compressed_section(data)
    if found is None:
        return None
    _base, blocks = found
    return len(blocks), sum(unc for _p, unc, _c in blocks)


def decompressed_snapshot(data: bytes) -> bytes:
    """The career snapshot with every block decompressed (b'' when absent)."""
    found = find_compressed_section(data)
    if found is None:
        return b""
    _base, blocks = found
    out = bytearray()
    for pos, _unc, comp in blocks:
        out += zlib.decompress(bytes(data[pos + 12:pos + 12 + comp]))
    return bytes(out)


def _rebuild_compressed_section(data: bytes, base: int, blocks, contents) -> bytes:
    """Re-serialise the section with *contents* as the decompressed blocks."""
    streams = [zlib.compress(c, 9) for c in contents]
    total_unc = sum(len(c) for c in contents)
    total_comp = sum(len(s) for s in streams)

    header = bytearray(data[base:base + COMP_SECTION_HEADER])
    header[8:12] = total_unc.to_bytes(4, "big")
    header[12:16] = total_comp.to_bytes(4, "big")

    out = bytearray(data[:base - 8])
    out += struct.pack("<II", COMP_SECTION_HEADER + 12 * len(blocks) + total_comp, 0)
    out += bytes(header)
    for i, (_pos, unc, _comp) in enumerate(blocks):
        stream = streams[i]
        end = len(out) + 12 + len(stream)
        nxt = 0 if i + 1 == len(blocks) else end - base
        out += unc.to_bytes(4, "big")
        out += len(stream).to_bytes(4, "big")
        out += nxt.to_bytes(4, "big")
        out += stream
    return bytes(out)


def find_compressed_player_records(data: bytes, name: str,
                                  height: int | None = None,
                                  weight: int | None = None,
                                  tol_h: int = 8, tol_w: int = 12) -> list[int]:
    """Record bases of *name* inside the decompressed snapshot (may be < 0)."""
    found = find_compressed_section(data)
    if found is None:
        return []
    _base, blocks = found
    raw = bytearray()
    for pos, _unc, comp in blocks:
        raw += zlib.decompress(data[pos + 12:pos + 12 + comp])
    return _find_records_in(raw, name, height, weight, tol_h, tol_w)


def _find_records_in(raw: bytes, name: str,
                     height: int | None, weight: int | None,
                     tol_h: int, tol_w: int) -> list[int]:
    """Shared record lookup used by the snapshot (bases may be negative)."""
    needle = name.encode("latin1", errors="ignore")
    if len(needle) < 2:
        return []
    out: list[int] = []
    start = 0
    while True:
        hit = raw.find(needle, start)
        if hit < 0:
            break
        start = hit + 1
        rec_base = hit - PLAYER_NAME_OFFSET
        # Inside the snapshot the first record may start a few bytes before
        # the region (its head lives in the plain-text part), so negative
        # bases are fine as long as every field we touch is inside *raw*.
        if rec_base + PLAYER_HEIGHT_OFFSET < 0:
            continue
        if rec_base + PLAYER_RECORD_SIZE > len(raw):
            continue
        h = raw[rec_base + PLAYER_HEIGHT_OFFSET]
        w = raw[rec_base + PLAYER_WEIGHT_OFFSET]
        if not (120 <= h <= 230 and 30 <= w <= 130):
            continue
        if _readable_name(raw[rec_base + PLAYER_NAME_OFFSET:
                             rec_base + PLAYER_NAME_OFFSET + PLAYER_NAME_LEN]) != name:
            continue
        h = raw[rec_base + PLAYER_HEIGHT_OFFSET]
        w = raw[rec_base + PLAYER_WEIGHT_OFFSET]
        if height is not None and abs(h - height) > tol_h:
            continue
        if weight is not None and abs(w - weight) > tol_w:
            continue
        out.append(rec_base)
    return out


def patch_compressed_players(data: bytearray, name: str, vals: dict,
                             height: int | None = None,
                             weight: int | None = None) -> int:
    """Write *vals* into every copy of the player in the compressed snapshot.

    *data* is modified in place when a snapshot is found.  Returns the number
    of records patched (0 when the save has no snapshot or no match).
    """
    found = find_compressed_section(data)
    if found is None:
        return 0
    base, blocks = found
    raw = bytearray()
    for pos, _unc, comp in blocks:
        raw += zlib.decompress(bytes(data[pos + 12:pos + 12 + comp]))

    records = _find_records_in(raw, name, height, weight, 8, 12)
    if not records:
        return 0

    for rec in records:
        write_player(raw, rec, vals)

    contents = []
    off = 0
    for _pos, unc, _comp in blocks:
        contents.append(bytes(raw[off:off + unc]))
        off += unc
    data[:] = _rebuild_compressed_section(data, base, blocks, contents)
    return len(records)


# ---------------------------------------------------------------------------
# Loading / saving (crypto aware)
# ---------------------------------------------------------------------------

@dataclass
class LoadedSave:
    path: Path
    save: "CR.SaveFile"          # full decrypted save (blocks kept separately)
    data: bytearray              # editable copy of the data block
    encrypted: bool              # was the source file encrypted?
    key_name: str | None         # which master key matched

    @property
    def file_type(self) -> bytes:
        return self.save.file_header.file_type


def _looks_valid(raw: bytes, sf: "CR.SaveFile") -> bool:
    fh = sf.file_header
    total = (CR.ENCRYPTION_HEADER_SIZE + CR.FILEHEADER_SIZE + fh.desc_size
             + fh.logo_size + fh.data_size + fh.serial_length * CR.SERIAL_DOUBLE)
    if total != len(raw):
        return False
    if fh.data_size < 100_000:
        return False
    if not fh.file_type or not all(32 <= c < 127 for c in fh.file_type):
        return False
    if fh.logo_size and sf.logo[:4] not in (b"\x89PNG", b"\xff\xd8\xff"):
        return False
    return True


def _parse_combined(buf: bytes) -> "CR.SaveFile":
    """Parse a file already decrypted by the old 'PES 2016 Edit Crypter'.

    That tool stores the blocks as: header + description + encryptHeader +
    version(serial) + logo + data.
    """
    if len(buf) < CR.FILEHEADER_SIZE:
        raise EditorError("Arquivo pequeno demais.")
    fh = CR.FileHeader(buf[:CR.FILEHEADER_SIZE])
    pos = CR.FILEHEADER_SIZE
    need = pos + fh.desc_size + CR.ENCRYPTION_HEADER_SIZE + fh.serial_length * CR.SERIAL_DOUBLE \
        + fh.logo_size + fh.data_size
    if need != len(buf):
        raise EditorError("Layout de arquivo não reconhecido.")
    desc = buf[pos:pos + fh.desc_size]; pos += fh.desc_size
    enc = buf[pos:pos + CR.ENCRYPTION_HEADER_SIZE]; pos += CR.ENCRYPTION_HEADER_SIZE
    serial = buf[pos:pos + fh.serial_length * CR.SERIAL_DOUBLE]; pos += fh.serial_length * CR.SERIAL_DOUBLE
    logo = buf[pos:pos + fh.logo_size]; pos += fh.logo_size
    data = buf[pos:pos + fh.data_size]
    return CR.SaveFile(enc, fh, desc, logo, data, serial)


def load(path: str | Path, *, strict: bool = True) -> LoadedSave:
    """Read a PES 2016 save (BL / ML) or the EDIT database.

    *strict* enforces the minimum data size expected of a real ML/BL save;
    pass ``strict=False`` for EDIT00000000 (whose data block is smaller).
    """
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise EditorError(f"Não foi possível ler o arquivo:\n{e}") from e

    # Friendly message for Xbox 360 packages.
    if raw[X360_TITLEID_OFFSET:X360_TITLEID_OFFSET + 4] == X360_TITLEID:
        raise EditorError(
            "Este arquivo é um pacote do Xbox 360.\n\n"
            "Esta versão edita apenas saves do PC.")

    # 1) Try the encrypted PES 2016 format.
    for key_name, key in CR.MASTER_KEYS.items():
        try:
            sf = CR.decrypt(raw, key)
        except Exception:
            continue
        if _looks_valid(raw, sf):
            if strict and len(sf.data) < MIN_DATA_SIZE:
                raise EditorError(
                    f"O bloco de dados é pequeno demais ({len(sf.data):,} bytes).\n"
                    "Confirme que selecionou o save certo (ML00000000 / BL00000000).")
            return LoadedSave(p, sf, bytearray(sf.data), True, key_name)

    # 2) Maybe it is already decrypted (old crypter output).
    try:
        sf = _parse_combined(raw)
    except EditorError:
        raise EditorError(
            "Não foi possível ler este arquivo.\n\n"
            "Selecione o save do jogo (ML00000000 / BL00000000) - ele pode estar\n"
            "criptografado; este editor cuida disso sozinho.")
    if strict and len(sf.data) < MIN_DATA_SIZE:
        raise EditorError(
            f"O bloco de dados é pequeno demais ({len(sf.data):,} bytes).\n"
            "Confirme que selecionou o save certo (ML00000000 / BL00000000).")
    return LoadedSave(p, sf, bytearray(sf.data), False, None)


def save(loaded: LoadedSave, out_path: str | Path) -> Path:
    """Write *loaded* (with its current data) back out as a valid save file."""
    out = Path(out_path)
    loaded.save.data = bytes(loaded.data)
    # The data block may have changed size (recompressing the BL snapshot
    # does that), so the length recorded in the file header must follow.
    loaded.save.file_header.data_size = len(loaded.save.data)
    key = CR.MASTER_KEYS[loaded.key_name] if loaded.key_name else CR.MASTER_KEYS["pes16"]
    blob = CR.encrypt(loaded.save, key)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    return out
