"""Testes do núcleo do editor (sem GUI).

Rode a partir da pasta `codigo-fonte-pc`:

    python3 test_core.py

A primeira parte monta um bloco de dados sintético e checa os campos de
ML/BL "clássicos".  A segunda parte é opcional: se o save real estiver na
pasta do projeto, valida a localização do jogador BAL e o ciclo
ler -> gravar -> re-criptografar -> ler das habilidades.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pes2016mlbl import core as C


def test_synthetic():
    data = bytearray(C.MIN_DATA_SIZE + 4096)

    # --- moeda ML: cada preset volta igual e o display bate com o rótulo
    for i, raw in enumerate(C.PRESET_RAW):
        buf = bytearray(data)
        C.write_money_raw(buf, raw)
        assert C.read_money_raw(buf) == raw
        for c in range(len(C.CURRENCIES)):
            expect = int("".join(ch for ch in C.PRESET_LABELS[c][i] if ch.isdigit()))
            assert C.money_display(raw, c) == expect, (c, i, C.money_display(raw, c), expect)
            d = C.money_display(raw, c)
            assert C.money_raw_from_display(d, c) == raw, (raw, c, d)

    # --- nome do manager (com acentos) em todos os slots
    buf = bytearray(data)
    C.write_manager_name(buf, "José Silva")
    assert C.read_manager_name(buf) == "José Silva"
    enc = "José Silva".encode("utf-8")
    for off in C.MANAGER_NAME_OFFSETS:
        assert buf[off:off + len(enc)] == enc, off

    # --- stats de treino
    buf = bytearray(data)
    st = {**{n: C.STAT_MAX for n in C.STAT_NAMES}, "Training": C.TRAINING_MAX,
          "Focus": C.FOCUS_MAX}
    C.write_stats(buf, st)
    assert C.read_stats(buf) == st

    # --- bits (ordem little-endian)
    buf = bytearray(64)
    for pos, width, val in ((0, 8, 0xAB), (3, 5, 17), (120, 7, 99), (188, 3, 5),
                            (220, 2, 3), (345, 1, 1)):
        C.write_bits(buf, pos, width, val)
        assert C.read_bits(buf, pos, width) == val, (pos, width, val)
    assert C.read_bits(buf, 3, 5) == 17 and C.read_bits(buf, 120, 7) == 99

    # --- campos do jogador: grava e relê o mesmo dict
    buf = bytearray(C.MIN_DATA_SIZE + 4096)
    base = 4096  # qualquer base, os campos são relativos
    vals = {f[0]: (f[5] // 2) for f in C.PLAYER_FIELDS}
    vals["height"] = 180
    vals["weight"] = 75
    C.write_player(buf, base, vals)
    back = C.read_player(buf, base)
    for key, _l, _k, _p, _w, _mx in C.PLAYER_FIELDS:
        assert back[key] == vals[key], (key, back[key], vals[key])
    assert back["height"] == 180 and back["weight"] == 75
    print("OK  partes sintéticas (ML, stats, bits, campos do jogador)")


def test_real_save():
    proj = Path(__file__).resolve().parent.parent
    candidates = [proj / "BL00000000", proj / "BL00000000.original",
                  proj / "BL00000000 depois"]
    src = next((p for p in candidates if p.exists()), None)
    if src is None:
        print("--  save real não encontrado, pulando teste de integração")
        return

    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="pes16test_"))
    copy = tmp / src.name
    shutil.copyfile(src, copy)

    loaded = C.load(copy)
    created = C.find_created_player(loaded.data)
    assert created is not None, "jogador BAL não localizado"
    base, name = created
    h = loaded.data[base + C.PLAYER_HEIGHT_OFFSET]
    w = loaded.data[base + C.PLAYER_WEIGHT_OFFSET]
    bases = C.filter_records_by_body(loaded.data,
                                     C.find_player_records(loaded.data, name), h, w)
    bases = C._order_records(bases, base)
    assert created[0] in bases
    print(f"OK  jogador '{name}' localizado ({len(bases)} registro(s))")

    before = bytes(loaded.data)
    vals = C.read_player(loaded.data, bases[0])
    vals.update({"attack": 90, "stamina": 95, "age": 20, "height": 185,
                 "weight": 80, "form": 6, "injury": 3, "stronger_foot": 1})
    for b in bases:
        C.write_player(loaded.data, b, vals)

    out = C.save(loaded, tmp / ("out_" + src.name))
    reloaded = C.load(out)
    rb, rname = C.find_created_player(reloaded.data)
    assert rname == name
    rv = C.read_player(reloaded.data, rb)
    for key in ("attack", "stamina", "age", "height", "weight", "form", "injury",
                "stronger_foot"):
        assert rv[key] == vals[key], (key, rv[key], vals[key])

    # só os registros do jogador podem ter mudado
    after = bytes(reloaded.data)
    assert len(after) == len(before)
    for i, (x, y) in enumerate(zip(before, after)):
        if x != y:
            assert any(b <= i < b + C.PLAYER_RECORD_SIZE for b in bases), hex(i)
    print("OK  ciclo habilidades: gravar, re-criptografar, reler (bytes "
          "alterados só nos registros do jogador)")
    shutil.rmtree(tmp, ignore_errors=True)


def test_real_edit():
    """Valida o layout do EDIT00000000 contra o próprio jogador BAL.

    O arquivo EDIT guarda o jogador "criado" no banco de dados; é de lá que
    o jogo mostra as habilidades.  Se o EDIT do usuário estiver na pasta,
    conferimos leitura/escrita e o ciclo salvar -> recarregar.
    """
    proj = Path(__file__).resolve().parent.parent
    edit_src = next((p for p in (proj / "EDIT00000000", proj / "EDIT00000000.original")
                     if p.exists()), None)
    bl_src = next((p for p in (proj / "BL00000000", proj / "BL00000000.original")
                   if p.exists()), None)
    if edit_src is None or bl_src is None:
        print("--  BL/EDIT reais não encontrados, pulando teste do EDIT")
        return

    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="pes16edit_"))
    shutil.copyfile(edit_src, tmp / "EDIT00000000")

    bl = C.load(bl_src)
    created = C.find_created_player(bl.data)
    assert created is not None
    cbase, cname = created
    h = bl.data[cbase + C.PLAYER_HEIGHT_OFFSET]
    w = bl.data[cbase + C.PLAYER_WEIGHT_OFFSET]

    ed = C.load(tmp / "EDIT00000000", strict=False)
    bases = C.find_edit_records(ed.data, cname, h, w)
    assert bases, f"jogador BAL '{cname}' não está no EDIT"
    print(f"OK  '{cname}' no banco EDIT (registro {bases[0]})")

    got = C.read_edit_player(ed.data, bases[0])
    for key in ("attack", "defence", "speed", "stamina", "age", "height", "weight",
                "form", "injury", "stronger_foot"):
        assert got[key] == C.read_player(bl.data, cbase)[key] or key in ("stamina",), \
            (key, got[key], C.read_player(bl.data, cbase)[key])

    before = bytes(ed.data)
    vals = C.read_edit_player(ed.data, bases[0])
    vals.update({"attack": 91, "speed": 92, "stamina": 93, "age": 22,
                 "height": 186, "weight": 81, "form": 3, "injury": 2,
                 "stronger_foot": 1})
    for b in bases:
        C.write_edit_player(ed.data, b, vals)

    out = C.save(ed, tmp / "EDIT00000000")
    re2 = C.load(out, strict=False)
    assert re2.file_type == b"EDIT"
    for b in bases:
        back = C.read_edit_player(re2.data, b)
        for key in ("attack", "speed", "stamina", "age", "height", "weight",
                    "form", "injury", "stronger_foot"):
            assert back[key] == vals[key], (key, back[key], vals[key])

    # só os registros do jogador mudaram
    after = bytes(re2.data)
    for i, (x, y) in enumerate(zip(before, after)):
        if x != y:
            assert any(b <= i < b + C.EDIT_RECORD_SIZE for b in bases), hex(i)
    print("OK  ciclo EDIT: ler, gravar, re-criptografar, reler")
    shutil.rmtree(tmp, ignore_errors=True)


def test_real_snapshot():
    """Valida o snapshot comprimido do BL (blocos zlib de 256 KB no fim).

    É desta cópia que a tela do modo Rumo ao Estrelato lê o jogador.  Sem
    gravá-la, as habilidades mudam no menu Edit mas não na carreira - foi
    exatamente o que aconteceu no teste no console do usuário.
    """
    proj = Path(__file__).resolve().parent.parent
    src = next((p for p in (proj / "BL00000000", proj / "BL00000000.original",
                            proj / "BL00000000.original.bak") if p.exists()), None)
    if src is None:
        print("--  save BL real não encontrado, pulando teste do snapshot")
        return

    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="pes16snap_"))
    loaded = C.load(src)
    orig = bytes(loaded.data)

    info = C.compressed_section_info(orig)
    assert info is not None, "snapshot comprimido não localizado"
    print(f"OK  snapshot da carreira: {info[0]} blocos, {info[1]} bytes "
          f"descomprimidos")

    created = C.find_created_player(orig)
    assert created is not None
    cbase, cname = created
    h = orig[cbase + C.PLAYER_HEIGHT_OFFSET]
    w = orig[cbase + C.PLAYER_WEIGHT_OFFSET]

    recs = C.find_compressed_player_records(orig, cname, h, w)
    assert recs, f"jogador '{cname}' não está no snapshot"
    print(f"OK  '{cname}' no snapshot (base {recs[0]})")

    vals = C.read_player(orig, cbase)

    # 1) gravar exatamente os valores que já estão no snapshot tem de
    #    reproduzir o arquivo byte a byte (prova que o container está certo).
    snap = C.decompressed_snapshot(orig)
    sval = C.read_player(snap, recs[0])
    sh = snap[recs[0] + C.PLAYER_HEIGHT_OFFSET]
    sw = snap[recs[0] + C.PLAYER_WEIGHT_OFFSET]
    same = bytearray(orig)
    assert C.patch_compressed_players(same, cname, sval, sh, sw) == len(recs)
    assert bytes(same) == orig, "reescrever o snapshot mudou o arquivo"
    print("OK  snapshot: reescrever os mesmos valores = arquivo idêntico")

    # 2) gravar valores novos, salvar e reler
    loaded.data = bytearray(orig)
    new = dict(vals)
    new.update({"attack": 91, "speed": 92, "stamina": 93, "height": 186,
                "weight": 81, "age": 21})
    assert C.patch_compressed_players(loaded.data, cname, new, h, w) == len(recs)
    plains = C.find_player_records(loaded.data, cname)
    assert plains
    for b in plains:
        C.write_player(loaded.data, b, new)
    out = C.save(loaded, tmp / "BL00000000")
    re2 = C.load(out)
    assert C.compressed_section_info(re2.data) is not None
    assert C.find_compressed_player_records(re2.data, cname) == recs
    snap2 = C.decompressed_snapshot(re2.data)
    got = C.read_player(snap2, recs[0])
    for key in ("attack", "speed", "stamina", "height", "weight", "age"):
        assert got[key] == new[key], (key, got[key], new[key])

    # os registros em texto puro também têm de estar atualizados
    plain = C.find_player_records(re2.data, cname)
    assert plain
    for b in plain:
        back = C.read_player(re2.data, b)
        for key in ("attack", "speed", "stamina", "height", "weight", "age"):
            assert back[key] == new[key], (b, key, back[key], new[key])
    print("OK  snapshot: gravar, re-criptografar, reler (valores conferem)")
    shutil.rmtree(tmp, ignore_errors=True)


def _find_table_anchor(bl: bytes, cname: str) -> int | None:
    """Base da tabela de jogadores da liga (registros a cada 228 bytes).

    O nome do jogador BAL aparece em mais de um lugar; o melhor ponto de
    partida é a cópia que tem vizinhos no passo de 228 bytes.
    """
    import struct

    best, best_count = None, 0
    for cand in C.find_player_records(bl, cname):
        count = 0
        for k in range(-40, 41):
            b = cand + k * C.PLAYER_RECORD_SIZE
            if b < 0 or b + C.PLAYER_RECORD_SIZE > len(bl):
                continue
            nm = C._readable_name(bl[b + C.PLAYER_NAME_OFFSET:
                                     b + C.PLAYER_NAME_OFFSET + C.PLAYER_NAME_LEN])
            if not nm:
                continue
            h, w = bl[b + C.PLAYER_HEIGHT_OFFSET], bl[b + C.PLAYER_WEIGHT_OFFSET]
            if 140 <= h <= 220 and 40 <= w <= 130 and struct.unpack_from("<I", bl, b + 0x38)[0]:
                count += 1
        if count > best_count:
            best, best_count = cand, count
    return best


def test_characteristics():
    """Confere as "características" contra o banco EDIT (layout documentado).

    No BL elas ficam fora da grade de 7 bits das habilidades; no EDIT seguem o
    formato de 112 bytes documentado pela wiki (form 188, lesão 220, pior pé
    294/296, melhor pé 364).  Se as duas leituras concordarem para dezenas de
    jogadores, o mapeamento está certo.
    """
    proj = Path(__file__).resolve().parent.parent
    bl_src = next((p for p in (proj / "BL00000000", proj / "BL00000000.original",
                               proj / "BL00000000.original.bak") if p.exists()), None)
    edit_src = next((p for p in (proj / "EDIT00000000", proj / "EDIT00000000.original",
                                 proj / "EDIT00000000.original.bak") if p.exists()), None)
    if bl_src is None or edit_src is None:
        print("--  BL/EDIT reais não encontrados, pulando teste das características")
        return

    import struct

    bl = bytes(C.load(bl_src).data)
    ed = bytes(C.load(edit_src, strict=False).data)

    created = C.find_created_player(bl)
    assert created is not None
    cname = created[1]
    anchor = _find_table_anchor(bl, cname)
    assert anchor is not None, "tabela de jogadores da liga não localizada"

    keys = ("form", "injury", "stronger_foot", "weak_foot_usage",
            "weak_foot_accuracy")
    checked = 0
    for k in range(-40, 41):
        base = anchor + k * C.PLAYER_RECORD_SIZE
        if base < 0 or base + C.PLAYER_RECORD_SIZE > len(bl):
            continue
        name = C._readable_name(bl[base + C.PLAYER_NAME_OFFSET:
                                   base + C.PLAYER_NAME_OFFSET + C.PLAYER_NAME_LEN])
        if not name:
            continue
        h, w = bl[base + C.PLAYER_HEIGHT_OFFSET], bl[base + C.PLAYER_WEIGHT_OFFSET]
        if not (140 <= h <= 220 and 40 <= w <= 130):
            continue
        pid = struct.unpack_from("<I", bl, base + 0x38)[0]
        needle = struct.pack("<I", pid)
        eb, start = None, 0
        while True:
            hit = ed.find(needle, start)
            if hit < 0:
                break
            start = hit + 1
            if (hit - C.EDIT_TABLE_BASE) % C.EDIT_TABLE_STEP:
                continue
            if C._readable_name(ed[hit + C.EDIT_NAME_OFFSET:
                                   hit + C.EDIT_NAME_OFFSET + C.EDIT_NAME_LEN]) == name:
                eb = hit
                break
        if eb is None:
            continue
        got, want = C.read_player(bl, base), C.read_edit_player(ed, eb)
        for key in keys:
            assert got[key] == want[key], (name, key, got[key], want[key])
        checked += 1
    assert checked >= 20, f"poucos jogadores comparados ({checked})"
    print(f"OK  características: BL x EDIT conferem em {checked} jogadores "
          "(condição, lesão, pior pé, melhor pé)")

    v = C.read_player(bl, anchor)
    print(f"    '{cname}': condição {v['form']}/8, lesão {v['injury']}/3, "
          f"pior pé {v['weak_foot_usage']} e {v['weak_foot_accuracy']}/4, "
          f"melhor pé {'esquerdo' if v['stronger_foot'] else 'direito'}")


if __name__ == "__main__":
    test_synthetic()
    test_real_save()
    test_real_edit()
    test_real_snapshot()
    test_characteristics()
    print("TODOS OS TESTES PASSARAM")
