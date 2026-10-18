"""Mostra, sem editar nada, o que o editor consegue ler de um save.

Uso:

    python3 ver_save.py "/caminho/BL00000000"

Serve para comparar o que está GRAVADO no arquivo com o que o jogo mostra.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "codigo-fonte-pc"))

from pes2016mlbl import core as C

ORDER = ["attack", "ball_control", "dribbling", "low_pass", "lofted_pass",
         "finishing", "place_kicking", "swerve", "header", "defence",
         "ball_winning", "kicking_power", "speed", "explosive_power",
         "body_balance", "jump", "stamina"]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    path = Path(argv[1])
    loaded = C.load(path)
    data = loaded.data
    fh = loaded.save.file_header
    print(f"arquivo ......... {path}")
    print(f"tamanho ......... {path.stat().st_size:,} bytes")
    print(f"tipo ............ {fh.file_type.decode(errors='replace')}")
    print(f"descricao ....... {bytes(loaded.save.description).split(b'\\x00')[0].decode(errors='replace')}")
    print(f"criptografado ... {loaded.encrypted}")
    print(f"bloco de dados .. {len(data):,} bytes")

    mode = C.detect_mode(path.name)
    if mode == "ML":
        print(f"dinheiro (raw) .. {C.read_money_raw(data)}")
        print(f"manager ......... {C.read_manager_name(data)!r}")

    created = C.find_created_player(data)
    if created is None:
        print("\n(jogador BAL nao localizado neste arquivo)")
    else:
        base, name = created
        h = data[base + C.PLAYER_HEIGHT_OFFSET]
        w = data[base + C.PLAYER_WEIGHT_OFFSET]
        bases = C._order_records(
            C.filter_records_by_body(data, C.find_player_records(data, name), h, w), base)
        print(f"\njogador BAL ..... {name}")
        print(f"registros ....... {bases}")
        for b in bases:
            v = C.read_player(data, b)
            print(f"\n--- registro em {b} ({b:#x}) ---")
            for key in ORDER:
                label = C.PLAYER_FIELD_BY_KEY[key][1]
                print(f"  {label:<28} {v[key]}")
            print(f"  {'Idade':<28} {v['age']}")
            print(f"  {'Altura (cm)':<28} {v['height']}")
            print(f"  {'Peso (kg)':<28} {v['weight']}")
            print(f"  {'Condicao fisica':<28} {v['form']}")
            print(f"  {'Resist. a lesao':<28} {v['injury']}")
            print(f"  {'Melhor pe (0/1)':<28} {v['stronger_foot']}")
            for key in ("goalkeeping", "gk_catching", "gk_clearing",
                        "gk_reflexes", "gk_coverage"):
                print(f"  {C.PLAYER_FIELD_BY_KEY[key][1]:<28} {v[key]}")

    stats = C.read_stats(data)
    print("\nstats de treino ...", [stats[n] for n in C.STAT_NAMES])
    print("Training ..........", stats["Training"])
    print("Focus .............", stats["Focus"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
