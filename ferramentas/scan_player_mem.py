#!/usr/bin/env python3
"""Fase 0 - localiza o jogador BAL na memoria do PES 2016 (SOMENTE LEITURA).

Uso:
    python3 scan_player_mem.py --name WARLISON

Nao escreve nada no jogo. Apenas:
  1. acha o PID do PES2016.exe;
  2. lista os modulos (base do executavel, para lidar com ASLR);
  3. varre a memoria legivel procurando o nome do jogador (ASCII e UTF-16);
  4. para cada ocorrencia, mostra uma janela de +/-0x200 bytes e tenta
     reconhecer altura/peso e o padrao de stats por perto.

Se o /proc/<pid>/mem nao puder ser aberto, o kernel esta barrando por
ptrace_scope=1 (Yama): veja as instrucoes no final da mensagem.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

CHUNK = 8 * 1024 * 1024  # 8 MiB por leitura


def rss_kb(pid: int) -> int:
    try:
        for linha in open(f"/proc/{pid}/status", "r", encoding="utf-8"):
            if linha.startswith("VmRSS:"):
                return int(linha.split()[1])
    except OSError:
        pass
    return 0


def find_game_pids(hint: str = "PES2016.exe") -> list[tuple[int, str, int]]:
    """[(pid, cmdline, rss_kb), ...] cujo cmdline contem *hint*."""
    alvo = hint.lower()
    achados = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except OSError:
            continue
        texto = cmdline.decode("utf-8", "replace")
        if alvo in texto.lower():
            pid = int(entry.name)
            achados.append((pid, texto.strip(), rss_kb(pid)))
    achados.sort(key=lambda item: item[2], reverse=True)
    return achados


def read_maps(pid: int) -> list[tuple[int, int, str, str, int]]:
    """[(inicio, fim, perms, caminho, offset), ...] a partir de /proc/pid/maps."""
    regioes = []
    with open(f"/proc/{pid}/maps", "r", encoding="utf-8", errors="replace") as fh:
        for linha in fh:
            partes = linha.split(maxsplit=5)
            if len(partes) < 5:
                continue
            faixa, perms, offset = partes[0], partes[1], partes[2]
            caminho = partes[5].strip() if len(partes) > 5 else ""
            ini_s, fim_s = faixa.split("-")
            regioes.append((int(ini_s, 16), int(fim_s, 16), perms, caminho,
                            int(offset, 16)))
    return regioes


def module_base(regioes, nome: str) -> int | None:
    """Endereco base do modulo cujo caminho termina com *nome*."""
    nome = nome.lower()
    for ini, _fim, perms, caminho, offset in regioes:
        if caminho.lower().endswith(nome) and offset == 0:
            return ini
    return None


def scan_buffer(pid: int, regioes, needle: bytes) -> list[tuple[int, str]]:
    """Procura *needle* em todas as regioes legiveis. Retorna (endereco, regiao)."""
    achados: list[tuple[int, str]] = []
    try:
        fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    except OSError as exc:
        raise SystemExit(
            f"ERRO: nao consegui abrir /proc/{pid}/mem ({exc.strerror}).\n"
            "Provavelmente e o Yama (ptrace_scope). Solucao temporaria:\n"
            "    sudo sysctl -w kernel.yama.ptrace_scope=0\n"
            "(volta ao normal quando reiniciar o PC)"
        ) from exc

    sobreposicao = len(needle) - 1
    try:
        for ini, fim, perms, caminho, _off in regioes:
            if "r" not in perms or caminho in ("[vvar]", "[vsyscall]", "[vdso]"):
                continue
            tamanho = fim - ini
            if tamanho <= 0 or tamanho > 8 * 1024 * 1024 * 1024:
                continue
            pos = ini
            while pos < fim:
                bloco = min(CHUNK, fim - pos)
                try:
                    dados = os.pread(fd, bloco, pos)
                except OSError:
                    pos += bloco
                    continue
                if not dados:
                    break
                indice = dados.find(needle)
                while indice != -1:
                    achados.append((pos + indice, caminho or "anon"))
                    indice = dados.find(needle, indice + 1)
                # recua para pegar ocorrencias que cruzam a fronteira do bloco
                pos += max(1, len(dados) - sobreposicao)
    finally:
        os.close(fd)
    return achados


def dump_window(pid: int, endereco: int, antes: int = 0x100,
                depois: int = 0x200) -> bytes:
    inicio = max(0, endereco - antes)
    try:
        with open(f"/proc/{pid}/mem", "rb", buffering=0) as fh:
            fh.seek(inicio)
            return fh.read(antes + depois)
    except OSError:
        return b""


def anotar(janela: bytes, base_endereco: int, needle: bytes) -> list[str]:
    """Tenta achar altura/peso e valores 'de jogador' perto da ocorrencia."""
    notas = []
    pos_nome = janela.find(needle)
    if pos_nome == -1:
        return notas
    # Altura 180 e peso 75 costumam ficar a poucos bytes do nome.
    for desloc in range(-0x40, 0x41, 1):
        i = pos_nome + desloc
        if 0 <= i < len(janela) - 1:
            if janela[i] == 180 and janela[i + 1] == 75:
                notas.append(f"altura 180 / peso 75 em nome{desloc:+#x}")
    # Stats altos (99 = 0x63) na vizinhanca: so um indicio, nao prova.
    vizinhos = janela[max(0, pos_nome - 0x80):pos_nome + 0x120]
    if vizinhos.count(0x63) >= 8:
        notas.append(f"{vizinhos.count(0x63)} bytes 0x63 (99) na vizinhanca")
    return notas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="WARLISON", help="nome do jogador (ASCII)")
    ap.add_argument("--pid", type=int, help="PID do jogo (padrao: achar sozinho)")
    ap.add_argument("--hint", default="PES2016.exe", help="trecho do cmdline do jogo")
    args = ap.parse_args()

    if args.pid:
        pid, cmdline = args.pid, "(informado na linha de comando)"
    else:
        candidatos = find_game_pids(args.hint)
        if not candidatos:
            print(f"NAO ACHEI processo com '{args.hint}' na linha de comando.")
            print("Abra o PES 2016 pelo Bottles e rode de novo.")
            return 2
        print("processos encontrados:")
        for cpid, ccmd, crss in candidatos:
            print(f"  PID {cpid}  RSS {crss / 1024:.0f} MiB  {ccmd[:120]}")
        pid, cmdline = candidatos[0][0], candidatos[0][1]

    print(f"PID {pid}: {cmdline[:160]}")
    regioes = read_maps(pid)
    total = sum(f - i for i, f, p, _c, _o in regioes if "r" in p)
    print(f"regioes: {len(regioes)}  ({total / 1024 / 1024:.1f} MiB legiveis)")

    for modulo in ("PES2016.exe", "ntdll.dll", "kernel32.dll"):
        base = module_base(regioes, modulo)
        if base is not None:
            print(f"  base {modulo}: 0x{base:x}")

    nome = args.name.encode("ascii", "ignore")
    alvos = [nome, nome.decode("ascii").encode("utf-16-le")]
    vistos: set[int] = set()
    for etiqueta, needle in zip(("ASCII", "UTF-16LE"), alvos):
        print(f"\nvarrendo {etiqueta} {needle!r} ...")
        achados = scan_buffer(pid, regioes, needle)
        print(f"  ocorrencias: {len(achados)}")
        for endereco, regiao in achados[:40]:
            if endereco in vistos:
                continue
            vistos.add(endereco)
            janela = dump_window(pid, endereco)
            notas = anotar(janela, endereco, needle)
            extra = ("  <-- " + "; ".join(notas)) if notas else ""
            print(f"  0x{endereco:x}  [{regiao}]{extra}")
            if notas and len(vistos) <= 5:
                print("    " + janela[:64].hex(" "))
        if len(achados) > 40:
            print(f"  ... e mais {len(achados) - 40}")
    if not vistos:
        print("\nNada encontrado. O jogo esta com a carreira carregada?")
        return 1
    print("\nNada foi escrito: esta varredura e 100% leitura.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
