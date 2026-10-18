"""Teste end-to-end da GUI (precisa de um display X).

Copia o save real + o EDIT00000000 para uma pasta temporária, abre pelo app,
altera habilidades e salva, depois recarrega os DOIS arquivos e confere se os
valores chegaram.  Pula automaticamente se não houver display.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pes2016mlbl import core as C


def main() -> int:
    try:
        import tkinter as tk
    except Exception as e:  # pragma: no cover
        print("--  tkinter indisponível:", e)
        return 0
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print("--  sem display:", e)
        return 0
    root.withdraw()

    from pes2016mlbl import gui as G

    proj = Path(__file__).resolve().parent.parent
    bl_src = next((p for p in (proj / "BL00000000", proj / "BL00000000.original")
                   if p.exists()), None)
    ed_src = next((p for p in (proj / "EDIT00000000", proj / "EDIT00000000.original")
                   if p.exists()), None)
    if bl_src is None or ed_src is None:
        print("--  BL/EDIT reais não encontrados, pulando teste da GUI")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="pes16gui_"))
    shutil.copyfile(bl_src, tmp / "BL00000000")
    shutil.copyfile(ed_src, tmp / "EDIT00000000")

    app = G.EditorApp(root)
    ok = app.open_path(tmp / "BL00000000")
    assert ok, "open_path falhou"
    assert app.mode == "BL"
    print("OK  BL aberto;", app.lbl_player.cget("text"))
    print("OK  ", app.lbl_edit.cget("text"))
    assert app.edit_loaded is not None, "EDIT não foi carregado"
    assert app.edit_bases, "jogador não localizado no EDIT"

    novo = {"attack": 93, "speed": 94, "stamina": 95, "age": 23,
            "height": 187, "weight": 82,
            "form": 7, "injury": 2, "stronger_foot": 1,
            "weak_foot_usage": 4, "weak_foot_accuracy": 3}
    for k, v in novo.items():
        app.player_vars[k].set(v)

    with mock.patch.object(G.messagebox, "showinfo"), \
            mock.patch.object(G.messagebox, "showerror") as err:
        app.apply()
        assert not err.called, err.call_args

    # recarrega os dois arquivos gravados
    bl2 = C.load(tmp / "BL00000000")
    for b in app.player_bases:
        rv = C.read_player(bl2.data, b)
        for k, v in novo.items():
            assert rv[k] == v, ("BL", k, rv[k], v)
    ed2 = C.load(tmp / "EDIT00000000", strict=False)
    for b in app.edit_bases:
        rv = C.read_edit_player(ed2.data, b)
        for k, v in novo.items():
            assert rv[k] == v, ("EDIT", k, rv[k], v)

    # os .bak guardam os arquivos originais
    assert (tmp / "BL00000000.bak").exists()
    assert (tmp / "EDIT00000000.bak").exists()
    assert (tmp / "EDIT00000000.bak").read_bytes() == ed_src.read_bytes()
    print("OK  habilidades gravaram no BL e no EDIT (e .bak preservado)")

    # o snapshot comprimido da carreira também tem de ser gravado: é dele
    # que a tela do modo Rumo ao Estrelato lê o jogador.
    assert app.snapshot_records >= 1, "snapshot da carreira não foi gravado"
    srecs = C.find_compressed_player_records(bl2.data, "WARLISON")
    assert srecs, "registro do jogador sumiu do snapshot"
    snap = C.decompressed_snapshot(bl2.data)
    for b in srecs:
        rv = C.read_player(snap, b)
        for k, v in novo.items():
            assert rv[k] == v, ("SNAP", k, rv[k], v)
    print(f"OK  snapshot comprimido da carreira gravado (registro {srecs[0]})")
    shutil.rmtree(tmp, ignore_errors=True)
    root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
