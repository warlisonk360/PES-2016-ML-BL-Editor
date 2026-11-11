#!/usr/bin/env python3
"""Renomeia exports de uma DLL PE32 sem depender do linker.

O linker do Zig (lld via `zig c++`) sempre decora exports __stdcall com @N
(ex.: Direct3DCreate9@4), e o PES2016.exe importa os nomes SEM decoracao.
Este script reescreve a tabela de nomes da export directory do PE, em ordem
alfabetica (o loader do Windows faz busca binaria), mantendo os RVAs das
funcoes intactos.

Uso: fix_exports.py caminho/da.dll
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

# nome exportado pelo compilador -> nome que o jogo importa
RENAMES = {
    "Direct3DCreate9_impl@4": "Direct3DCreate9",
    "D3DPERF_BeginEvent_impl@8": "D3DPERF_BeginEvent",
    "D3DPERF_EndEvent_impl@0": "D3DPERF_EndEvent",
    "D3DPERF_SetMarker_impl@8": "D3DPERF_SetMarker",
    "D3DPERF_SetOptions_impl@4": "D3DPERF_SetOptions",
}


def main(path: Path) -> int:
    data = bytearray(path.read_bytes())

    if data[:2] != b"MZ":
        raise SystemExit("nao e um PE (assinatura MZ ausente)")
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        raise SystemExit("nao e um PE (assinatura PE ausente)")

    coff = pe_off + 4
    nsec, = struct.unpack_from("<H", data, coff + 2)
    opt_size, = struct.unpack_from("<H", data, coff + 16)
    opt = coff + 20
    magic, = struct.unpack_from("<H", data, opt)
    if magic != 0x10B:
        raise SystemExit(f"esperava PE32 (0x10b), achei 0x{magic:04x}")

    dirs = opt + 96                     # DataDirectory logo apos o header PE32
    exp_rva, exp_size = struct.unpack_from("<II", data, dirs)

    sections = []
    sec = opt + opt_size
    for i in range(nsec):
        off = sec + i * 40
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, off + 8)
        sections.append((vaddr, max(vsize, rsize), raddr))

    def rva_to_off(rva: int) -> int:
        for vaddr, size, raddr in sections:
            if vaddr <= rva < vaddr + size:
                return raddr + (rva - vaddr)
        raise SystemExit(f"RVA 0x{rva:x} fora das secoes")

    exp = rva_to_off(exp_rva)
    (
        _chars, _ts, _maj, _min, _name, _base,
        nfuncs, nnames, addr_funcs, addr_names, addr_ord,
    ) = struct.unpack_from("<IIHHIIIIIII", data, exp)

    name_rvas = list(struct.unpack_from(f"<{nnames}I", data, rva_to_off(addr_names)))
    ordinals = list(struct.unpack_from(f"<{nnames}H", data, rva_to_off(addr_ord)))

    if nnames == 0:
        raise SystemExit("DLL sem exports nomeados")

    entries = []  # (nome_novo, ordinal, rva_do_nome_antigo, nome_antigo)
    for rva, ordv in zip(name_rvas, ordinals):
        off = rva_to_off(rva)
        end = data.index(b"\0", off)
        old = data[off:end].decode("ascii")
        new = RENAMES.get(old, old)
        entries.append((new, ordv, rva, old))

    blob_start = min(rva for _, _, rva, _ in entries)
    blob_end = max(rva + len(old) + 1 for _, _, rva, old in entries)

    # A tabela de nomes precisa ficar em ordem ASCII (busca binaria do loader).
    entries.sort(key=lambda e: e[0].encode("ascii"))

    blob = bytearray()
    offsets = []
    for new, _ordv, _rva, _old in entries:
        offsets.append(blob_start + len(blob))
        blob += new.encode("ascii") + b"\0"

    if len(blob) > blob_end - blob_start:
        raise SystemExit("tabela de nomes maior que o espaco original")

    start_off = rva_to_off(blob_start)
    data[start_off:start_off + len(blob)] = blob
    data[start_off + len(blob):rva_to_off(blob_end)] = b"\0" * (
        (blob_end - blob_start) - len(blob))

    names_off = rva_to_off(addr_names)
    ords_off = rva_to_off(addr_ord)
    for i, ((new, ordv, _rva, _old), name_rva) in enumerate(zip(entries, offsets)):
        struct.pack_into("<I", data, names_off + i * 4, name_rva)
        struct.pack_into("<H", data, ords_off + i * 2, ordv)
        if new != _old:
            print(f"  {_old}  ->  {new}")

    path.write_bytes(data)
    print(f"OK: {path} ({len(entries)} exports, tabela reescrita)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"uso: {sys.argv[0]} d3d9.dll")
    raise SystemExit(main(Path(sys.argv[1])))
