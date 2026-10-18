"""Gera saves de TESTE (prontos para copiar, já com o nome BL00000000).

Objetivo: descobrir se o jogo está mesmo carregando o arquivo editado e
qual campo aparece na tela.

Cada pasta de saída contém um `BL00000000` com mudanças BEM visíveis:
  * habilidades: Ataque/Controle/Velocidade/Resistência = 99
  * idade 25, altura 199, peso 99
  * stats de treino (os 9) = 6 e Training = 20  (campo já validado antes)
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pes2016mlbl import core as C

PROJ = Path(__file__).resolve().parent.parent
OUT = PROJ / "TESTE-DE-CARREGAMENTO"

CASES = {
    "1 - base ORIGINAL (BL00000000)": PROJ / "BL00000000",
    "2 - base DEPOIS (BL00000000.depois.bak)": PROJ / "BL00000000.depois.bak",
}

NOTES = {
    "habilidades": "Ataque=99, Controle de bola=99, Velocidade=99, Resistencia=99",
    "fisico": "Idade=25, Altura=199cm, Peso=99kg",
    "treino": "os 9 stats de treino = 6, Training = 20",
}

if OUT.exists():
    shutil.rmtree(OUT)

for label, src in CASES.items():
    if not src.exists():
        print("pulado (nao existe):", src)
        continue
    loaded = C.load(src)
    data = loaded.data

    # --- habilidades
    created = C.find_created_player(data)
    if created is None:
        print("!! jogador nao localizado em", src)
        continue
    base, name = created
    h = data[base + C.PLAYER_HEIGHT_OFFSET]
    w = data[base + C.PLAYER_WEIGHT_OFFSET]
    bases = C.filter_records_by_body(data, C.find_player_records(data, name), h, w)
    bases = C._order_records(bases, base)
    vals = C.read_player(data, bases[0])
    vals.update({"attack": 99, "ball_control": 99, "speed": 99, "stamina": 99,
                 "age": 25, "height": 199, "weight": 99})
    for b in bases:
        C.write_player(data, b, vals)

    # --- stats de treino (campo que ja funcionou no jogo)
    st = {n: C.STAT_MAX for n in C.STAT_NAMES}
    st["Training"] = C.TRAINING_MAX
    st["Focus"] = C.read_stats(data)["Focus"]
    C.write_stats(data, st)

    d = OUT / label
    d.mkdir(parents=True)
    C.save(loaded, d / "BL00000000")
    print(f"{label}: jogador '{name}' registros {bases} -> {d/'BL00000000'}")

(OUT / "LEIA-ME.txt").write_text(
    "TESTE: descobrir se o jogo carrega o arquivo editado\n"
    "====================================================\n\n"
    "Escolha a pasta que corresponde ao save que voce esta usando agora\n"
    "(a 1 e a base do arquivo BL00000000 original; a 2 e a base do save\n"
    "mais novo), e copie o arquivo 'BL00000000' de dentro dela para a\n"
    "pasta de saves do jogo, substituindo o que estiver la.\n\n"
    "IMPORTANTE: faca uma copia do save que esta na pasta do jogo antes.\n"
    "IMPORTANTE 2: feche o jogo (e o Steam) antes de copiar.\n\n"
    "O que foi alterado nesse arquivo:\n"
    "  * Habilidades: Ataque=99, Controle de bola=99, Velocidade=99, Resistencia=99\n"
    "  * Fisico: Idade=25, Altura=199cm, Peso=99kg\n"
    "  * Treino: os 9 stats = 6 e Training = 20\n\n"
    "Depois de abrir o jogo, olhe e me diga:\n"
    "  [ ] a idade/altura/peso do jogador mudou? (25 / 199 / 99)\n"
    "  [ ] a tela de Habilidades mudou? (99 em Ataque/Velocidade/Resistencia)\n"
    "  [ ] a tela de Treino mudou? (tudo 6)\n\n"
    "Se NADA mudou, o jogo nao esta lendo o arquivo que voce copiou\n"
    "(pasta errada, nuvem do Steam, ou o jogo estava aberto ao copiar).\n",
    encoding="utf-8",
)
print("\nLEIA-ME escrito em", OUT / "LEIA-ME.txt")
