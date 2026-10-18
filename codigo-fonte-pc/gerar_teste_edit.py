"""Gera um par de teste (BL + EDIT) com habilidades muito visíveis.

Usa o estado real do usuário como base e grava os MESMOS valores no
BL00000000 (todos os registros do jogador) e no EDIT00000000 (banco de
jogadores).  Depois recarrega os dois arquivos para conferir.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pes2016mlbl import core as C

PROJ = Path(__file__).resolve().parent.parent
DEST = PROJ / "TESTE-ABILIDADES"

# valores bem diferentes dos atuais (o jogador tinha 74/41/40/79/...)
NOVOS = {
    "attack": 99, "ball_control": 99, "dribbling": 99, "low_pass": 99,
    "lofted_pass": 99, "finishing": 99, "place_kicking": 99, "swerve": 99,
    "header": 99, "defence": 99, "ball_winning": 99, "kicking_power": 99,
    "speed": 99, "explosive_power": 99, "body_balance": 99, "jump": 99,
    "stamina": 99,
    "goalkeeping": 99, "gk_catching": 99, "gk_clearing": 99,
    "gk_reflexes": 99, "gk_coverage": 99,
    "age": 25, "height": 199, "weight": 99,
    # características (valores do jogo, como aparecem na tela):
    # condição física cheia, lesão máxima, pé esquerdo e pior pé com valores
    # diferentes entre si (4 e 2) para dar para ver se frequência/precisão
    # estão trocadas.
    "form": 8, "injury": 3, "stronger_foot": 1,
    "weak_foot_usage": 4, "weak_foot_accuracy": 2,
}


def _fmt(g: dict) -> str:
    return (f"ataq {g['attack']} vel {g['speed']} res {g['stamina']} | "
            f"idade {g['age']} altura {g['height']} peso {g['weight']} | "
            f"condição {g['form']} lesão {g['injury']} "
            f"pior pé {g['weak_foot_usage']}/{g['weak_foot_accuracy']} "
            f"melhor pé {'esq' if g['stronger_foot'] else 'dir'}")


def main() -> None:
    bl_src = next((p for p in (PROJ / "BL00000000.original.bak",
                               PROJ / "BL00000000.original",
                               PROJ / "BL00000000") if p.exists()), None)
    ed_src = next((p for p in (PROJ / "EDIT00000000.original",
                               PROJ / "EDIT00000000") if p.exists()), None)
    if bl_src is None or ed_src is None:
        raise SystemExit("Preciso do BL00000000 e do EDIT00000000 na pasta do projeto.")

    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir()

    # --- BL: localiza o jogador e grava em todos os registros dele ---------
    bl = C.load(bl_src)
    created = C.find_created_player(bl.data)
    assert created, "jogador BAL não localizado no BL"
    name = created[1]
    h0 = bl.data[created[0] + C.PLAYER_HEIGHT_OFFSET]
    w0 = bl.data[created[0] + C.PLAYER_WEIGHT_OFFSET]
    bases = C.filter_records_by_body(
        bl.data, C.find_player_records(bl.data, name), h0, w0) or [created[0]]
    for b in bases:
        C.write_player(bl.data, b, {**C.read_player(bl.data, b), **NOVOS})

    # --- BL: snapshot comprimido da carreira (é o que a carreira BAL lê) ---
    snap_vals = {**C.read_player(bl.data, created[0])}
    n_snap = C.patch_compressed_players(bl.data, name, snap_vals, h0, w0)
    assert n_snap, "snapshot da carreira não localizado no BL"
    srecs = C.find_compressed_player_records(bl.data, name)

    # --- EDIT: o mesmo jogador no banco -----------------------------------
    ed = C.load(ed_src, strict=False)
    ebases = C.find_edit_records(ed.data, name, h0, w0) or C.find_edit_records(ed.data, name)
    assert ebases, f"'{name}' não está no EDIT (salve o Edit data no jogo)"
    for b in ebases:
        C.write_edit_player(ed.data, b, {**C.read_edit_player(ed.data, b), **NOVOS})

    C.save(bl, DEST / "BL00000000")
    C.save(ed, DEST / "EDIT00000000")

    # --- validação ---------------------------------------------------------
    bl2 = C.load(DEST / "BL00000000")
    ed2 = C.load(DEST / "EDIT00000000", strict=False)
    print(f"jogador '{name}'  (base: {bl_src.name} / {ed_src.name})")
    for b in bases:
        got = C.read_player(bl2.data, b)
        assert all(got[k] == v for k, v in NOVOS.items()), (b, got)
        print(f"  OK  BL   registro {b}: {_fmt(got)}")
    for b in ebases:
        got = C.read_edit_player(ed2.data, b)
        assert all(got[k] == v for k, v in NOVOS.items()), (b, got)
        print(f"  OK  EDIT registro {b}: {_fmt(got)}")

    snap2 = C.decompressed_snapshot(bl2.data)
    for b in srecs:
        got = C.read_player(snap2, b)
        assert all(got[k] == v for k, v in NOVOS.items()), (b, got)
        print(f"  OK  SNAP carreira registro {b}: {_fmt(got)}")

    (DEST / "LEIA-ME.txt").write_text(
        "TESTE DAS HABILIDADES (BL + EDIT)\n"
        "================================\n\n"
        "Copie OS DOIS arquivos desta pasta para a pasta de save do PES 2016,\n"
        "com estes nomes exatos:\n"
        "  BL00000000\n"
        "  EDIT00000000\n\n"
        "Faca backup da pasta de save antes. Feche o jogo (e o Steam) antes de\n"
        "copiar, e entre no jogo depois de copiar.\n\n"
        "O que voce deve ver na tela Habilidades do seu jogador:\n"
        "  todas as 17 habilidades e as 5 de goleiro = 99\n"
        "  idade 25, altura 199, peso 99\n"
        "  condicao fisica 8, resistencia a lesao 3, melhor pe ESQUERDO\n"
        "  pior pe: frequencia 4 e precisao 2\n\n"
        "Os dois ultimos campos (pior pe frequencia/precisao) sao novos. Se os\n"
        "numeros aparecerem trocados (precisao 4 e frequencia 2), avise que eu\n"
        "inverto os rotulos.\n\n"
        "IMPORTANTE: confira TAMBEM na carreira (Rumo ao Estrelato), na tela de\n"
        "habilidades do jogador dentro da carreira - antes ela continuava com os\n"
        "valores antigos. Agora o editor grava tambem na copia comprimida que a\n"
        "carreira usa.\n\n"
        f"(base: {bl_src.name} / {ed_src.name})\n",
        encoding="utf-8")
    print("gravado em", DEST)


if __name__ == "__main__":
    main()
