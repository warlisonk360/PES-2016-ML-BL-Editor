#!/usr/bin/env python3
"""Treinador de memoria do PES 2016 (PC via Bottles/Proton no Linux).

Diferente do editor de save (que mexe no arquivo), este programa le e escreve
na memoria do jogo em execucao.  Ele nao precisa de DLL, injecao nem sudo:
usa /proc/<pid>/mem do proprio Linux.

O que ele faz:
  * acha o processo do PES2016.exe (Bottles/Flatpak ou Wine normal);
  * varre a memoria procurando o registro do jogador pelo NOME e valida pelo
    layout conhecido (altura +0x0C, peso +0x0D, ID +0x38, nome +0x40);
  * mostra os valores ao vivo e permite curar a lesao (byte +0x0E = 0).

Descoberto por engenharia reversa comparando a mesma carreira antes/depois de
o jogador se recuperar: o byte +0x0E vai de 44 (lesionado) para 0 (saudavel),
tanto no save quanto na copia que o jogo mantem na memoria.

Uso:
    python3 treinador-pc/treinador.py
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import queue
import struct
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

APP_TITLE = "PES 2016 - Treinador (memoria)"
APP_VERSION = "0.1"

# Layout do registro do jogador (o mesmo do save de 228 bytes).
RECORD_SIZE = 0xE4
NAME_OFFSET = 0x40
NAME_LEN = 46
ID_OFFSET = 0x38
HEIGHT_OFFSET = 0x0C
WEIGHT_OFFSET = 0x0D
INJURY_OFFSET = 0x0E

INJURY_HEALTHY = 0
INJURY_TEST = 44          # codigo visto no save de um jogador lesionado

CHUNK = 8 * 1024 * 1024
DEFAULT_PLAYER = "WARLISON"

# O editor de save tem os offsets/bits dos outros campos; reaproveitamos para
# mostrar condicao fisica etc.  Se o modulo nao existir, o painel funciona
# mesmo assim (so nao mostra os campos extras).
try:
    _REPO = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_REPO / "codigo-fonte-pc"))
    from pes2016mlbl import core as SAVE  # type: ignore
except Exception:  # pragma: no cover - opcional
    SAVE = None


# ---------------------------------------------------------------------------
# Acesso ao processo
# ---------------------------------------------------------------------------
@dataclass
class Copy:
    """Uma copia do registro do jogador na memoria."""

    base: int
    ident: int
    height: int
    weight: int
    injury: int
    form: int | None


def rss_kb(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as fh:
            for linha in fh:
                if linha.startswith("VmRSS:"):
                    return int(linha.split()[1])
    except OSError:
        pass
    return 0


def find_game_pid(hint: str = "PES2016.exe") -> tuple[int, str] | None:
    """Acha o processo do jogo pelo trecho *hint* na linha de comando."""
    alvo = hint.lower()
    candidatos: list[tuple[int, str, int]] = []
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
            candidatos.append((pid, texto.strip(), rss_kb(pid)))
    if not candidatos:
        return None
    candidatos.sort(key=lambda item: item[2], reverse=True)
    return candidatos[0][0], candidatos[0][1]


def read_maps(pid: int) -> list[tuple[int, int, str, str, int]]:
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


def scan_memory(pid: int, needle: bytes,
                progresso=None) -> list[tuple[int, str]]:
    """Procura *needle* em todas as regioes legiveis (somente leitura)."""
    regioes = read_maps(pid)
    sobreposicao = len(needle) - 1
    achados: list[tuple[int, str]] = []
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    try:
        for indice, (ini, fim, perms, caminho, _off) in enumerate(regioes):
            if "r" not in perms or caminho in ("[vvar]", "[vsyscall]", "[vdso]"):
                continue
            if progresso and indice % 64 == 0:
                progresso(indice, len(regioes))
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
                indice_hit = dados.find(needle)
                while indice_hit != -1:
                    achados.append((pos + indice_hit, caminho or "anon"))
                    indice_hit = dados.find(needle, indice_hit + 1)
                pos += max(1, len(dados) - sobreposicao)
    finally:
        os.close(fd)
    return achados


def _form_from_record(registro: bytes) -> int | None:
    if SAVE is None:
        return None
    try:
        buf = bytearray(registro)
        return int(SAVE.read_player(buf, 0).get("form", 0))
    except Exception:
        return None


def discover(pid: int, nome: str,
             progresso=None) -> list[Copy]:
    """Acha as copias do registro do jogador e escolhe as da carreira.

    A mesma estrutura aparece varias vezes na memoria (carreira, tela, banco
    do EDIT...).  Agrupamos pelo ID: a copia "de verdade" e o grupo com o ID
    nao-zero mais comum, que foi o que respondeu no teste (3 copias).
    """
    needle = nome.encode("ascii", "ignore")
    if len(needle) < 2:
        return []
    hits = scan_memory(pid, needle, progresso)
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    copias: list[Copy] = []
    vistos: set[int] = set()
    try:
        for endereco, _regiao in hits:
            base = endereco - NAME_OFFSET
            if base in vistos:
                continue
            try:
                registro = os.pread(fd, RECORD_SIZE, base)
            except OSError:
                continue
            if len(registro) < RECORD_SIZE:
                continue
            campo_nome = registro[NAME_OFFSET:NAME_OFFSET + NAME_LEN]
            if not campo_nome.startswith(needle):
                continue
            if len(needle) < len(campo_nome) and campo_nome[len(needle)] != 0:
                continue  # evita pedaco de outra string
            altura = registro[HEIGHT_OFFSET]
            peso = registro[WEIGHT_OFFSET]
            if not (140 <= altura <= 230 and 30 <= peso <= 150):
                continue
            ident = struct.unpack_from("<I", registro, ID_OFFSET)[0]
            vistos.add(base)
            copias.append(Copy(base=base, ident=ident, height=altura,
                               weight=peso, injury=registro[INJURY_OFFSET],
                               form=_form_from_record(registro)))
    finally:
        os.close(fd)

    ids = Counter(c.ident for c in copias if c.ident)
    if ids:
        alvo = ids.most_common(1)[0][0]
        escolhidas = [c for c in copias if c.ident == alvo]
        if escolhidas:
            return escolhidas
    return copias


def write_injury(pid: int, copias: list[Copy], valor: int) -> list[int]:
    """Escreve o byte de lesao em todas as copias e devolve o que ficou."""
    fd = os.open(f"/proc/{pid}/mem", os.O_RDWR)
    lidos = []
    try:
        for copia in copias:
            os.pwrite(fd, bytes([valor & 0xFF]), copia.base + INJURY_OFFSET)
        for copia in copias:
            lidos.append(os.pread(fd, 1, copia.base + INJURY_OFFSET)[0])
    finally:
        os.close(fd)
    return lidos


def read_injuries(pid: int, copias: list[Copy]) -> list[int]:
    if not copias:
        return []
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)
    try:
        return [os.pread(fd, 1, c.base + INJURY_OFFSET)[0] for c in copias]
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Atalhos globais (X11, sem dependencia externa)
# ---------------------------------------------------------------------------
class X11Hotkeys(threading.Thread):
    """Captura teclas globais via XGrabKey (libX11 por ctypes).

    Experimental: alguns jogos em tela cheia usam XInput2/raw input e podem
    nao entregar a tecla.  Se falhar, os botoes e os atalhos com a janela
    focada continuam funcionando.
    """

    KEY_PRESS = 2

    def __init__(self, teclas: dict[str, str], callback):
        super().__init__(daemon=True)
        self.teclas = teclas            # {"F9": "curar", ...}
        self.callback = callback
        self._parar = threading.Event()
        self.erro: str | None = None

    def stop(self):
        self._parar.set()

    def run(self):  # pragma: no cover - depende de X11
        try:
            lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib.XDefaultRootWindow.restype = ctypes.c_ulong
            lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            lib.XStringToKeysym.restype = ctypes.c_ulong
            lib.XStringToKeysym.argtypes = [ctypes.c_char_p]
            lib.XKeysymToKeycode.restype = ctypes.c_ubyte
            lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            lib.XGrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_uint, ctypes.c_ulong,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int]
            lib.XPending.argtypes = [ctypes.c_void_p]
            lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            lib.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_uint, ctypes.c_ulong]
            lib.XCloseDisplay.argtypes = [ctypes.c_void_p]

            dpy = lib.XOpenDisplay(None)
            if not dpy:
                self.erro = "nao consegui abrir o display X11"
                return
            root = lib.XDefaultRootWindow(dpy)
            any_modifier = 1 << 15  # AnyModifier
            codigos: dict[int, str] = {}
            for nome in self.teclas:
                ks = lib.XStringToKeysym(nome.encode())
                if not ks:
                    continue
                kc = lib.XKeysymToKeycode(dpy, ks)
                codigos[kc] = nome
                lib.XGrabKey(dpy, kc, any_modifier, root, True, 1, 1)

            evento = ctypes.create_string_buffer(192)
            while not self._parar.is_set():
                if lib.XPending(dpy):
                    lib.XNextEvent(dpy, ctypes.byref(evento))
                    tipo = struct.unpack_from("i", evento, 0)[0]
                    if tipo == self.KEY_PRESS:
                        # XKeyEvent: keycode fica no offset 84 em x86_64
                        # (state=80, keycode=84, same_screen=88).
                        keycode = struct.unpack_from("I", evento, 84)[0]
                        nome = codigos.get(keycode)
                        if nome:
                            try:
                                self.callback(self.teclas[nome])
                            except Exception:
                                pass
                else:
                    time.sleep(0.05)
            for kc in codigos:
                lib.XUngrabKey(dpy, kc, any_modifier, root)
            lib.XCloseDisplay(dpy)
        except Exception as exc:  # pragma: no cover
            self.erro = str(exc)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------
class TreinadorApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=10)
        self.master.title(f"{APP_TITLE} v{APP_VERSION}")
        self.master.minsize(820, 520)
        self.pack(fill="both", expand=True)

        self.pid: int | None = None
        self.copias: list[Copy] = []
        self._fila: queue.Queue = queue.Queue()
        self._ocupado = False
        self._hotkeys: X11Hotkeys | None = None
        self._ultimo_aviso = 0.0

        self._montar()
        self._atualizar_atalhos()
        self.after(500, self._processar_fila)
        self.after(1000, self._tick)

    # ---- construcao da tela ------------------------------------------------
    def _montar(self):
        barra = ttk.Frame(self)
        barra.pack(fill="x")
        ttk.Label(barra, text="Jogador:").pack(side="left")
        self.var_nome = tk.StringVar(value=DEFAULT_PLAYER)
        ttk.Entry(barra, textvariable=self.var_nome, width=18).pack(
            side="left", padx=(4, 10))
        self.btn_conectar = ttk.Button(barra, text="Conectar ao jogo",
                                       command=self.conectar)
        self.btn_conectar.pack(side="left")
        self.lbl_status = ttk.Label(barra, text="Jogo nao conectado",
                                    foreground="#a00")
        self.lbl_status.pack(side="left", padx=12)

        self.tree = ttk.Treeview(
            self, columns=("addr", "id", "alt", "peso", "lesao", "cond"),
            show="headings", height=8)
        for col, titulo, largura in (
                ("addr", "Endereco", 140), ("id", "ID", 100),
                ("alt", "Altura", 70), ("peso", "Peso", 70),
                ("lesao", "Lesao ativa", 100), ("cond", "Condicao", 80)):
            self.tree.heading(col, text=titulo)
            self.tree.column(col, width=largura, anchor="center")
        self.tree.pack(fill="x", pady=10)

        acoes = ttk.Frame(self)
        acoes.pack(fill="x")
        self.btn_curar = ttk.Button(acoes, text="Curar lesao (0)",
                                    command=self.curar, state="disabled")
        self.btn_curar.pack(side="left")
        self.btn_testar = ttk.Button(
            acoes, text="Lesionar (44) - teste",
            command=self.lesionar, state="disabled")
        self.btn_testar.pack(side="left", padx=8)
        self.btn_atualizar = ttk.Button(acoes, text="Reler valores",
                                        command=self.atualizar,
                                        state="disabled")
        self.btn_atualizar.pack(side="left")
        ttk.Label(acoes, text="   F9 = curar   |   F10 = reconectar",
                  foreground="#555").pack(side="left", padx=10)

        ttk.Label(self, text="Registro:").pack(anchor="w", pady=(10, 2))
        self.log = tk.Text(self, height=9, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

        self.master.protocol("WM_DELETE_WINDOW", self.fechar)

    # ---- utilidades --------------------------------------------------------
    def _log(self, texto: str):
        hora = time.strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{hora}] {texto}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_botoes(self, ativo: bool):
        estado = "normal" if ativo else "disabled"
        for botao in (self.btn_curar, self.btn_testar, self.btn_atualizar):
            botao.configure(state=estado)

    def _preencher(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for copia in self.copias:
            self.tree.insert("", "end", values=(
                f"0x{copia.base:x}", copia.ident, copia.height,
                copia.weight, copia.injury,
                "-" if copia.form is None else copia.form))

    def _atualizar_atalhos(self):
        self.master.bind_all("<F9>", lambda _e: self.curar())
        self.master.bind_all("<F10>", lambda _e: self.conectar())

    # ---- conexao -----------------------------------------------------------
    def conectar(self):
        if self._ocupado:
            return
        achado = find_game_pid()
        if not achado:
            self.pid = None
            self.copias = []
            self._preencher()
            self._set_botoes(False)
            self.lbl_status.configure(text="Jogo nao encontrado (PES2016.exe)",
                                      foreground="#a00")
            self._log("Nao achei o PES2016.exe. Abra o jogo pelo Bottles.")
            return
        self.pid, cmdline = achado
        nome = self.var_nome.get().strip() or DEFAULT_PLAYER
        self.lbl_status.configure(text=f"Procurando '{nome}' na memoria...",
                                  foreground="#b60")
        self._log(f"Conectado ao PID {self.pid}; varrendo a memoria...")
        self._ocupado = True
        self.btn_conectar.configure(state="disabled")

        def trabalho():
            try:
                copias = discover(self.pid, nome,
                                  progresso=lambda i, t: None)
                self._fila.put(("ok", copias))
            except Exception as exc:  # noqa: BLE001
                self._fila.put(("erro", str(exc)))

        threading.Thread(target=trabalho, daemon=True).start()

    def _aplicar_descoberta(self, copias: list[Copy]):
        self._ocupado = False
        self.btn_conectar.configure(state="normal")
        self.copias = copias
        self._preencher()
        if not copias:
            self.lbl_status.configure(
                text="Jogador nao encontrado na memoria", foreground="#a00")
            self._log("Nenhuma copia valida encontrada. O jogador esta na "
                      "carreira? O nome esta certo?")
            self._set_botoes(False)
            return
        self.lbl_status.configure(
            text=f"Conectado (PID {self.pid}) - {len(copias)} copia(s)",
            foreground="#070")
        self._log(f"Achei {len(copias)} copia(s) do registro "
                  f"(ID {copias[0].ident}).")
        self._set_botoes(True)
        self._iniciar_hotkeys()

    def _iniciar_hotkeys(self):
        if self._hotkeys is not None:
            return
        self._hotkeys = X11Hotkeys(
            {"F9": "curar", "F10": "conectar"},
            lambda acao: self._fila.put(("hotkey", acao)))
        self._hotkeys.start()

    # ---- acoes -------------------------------------------------------------
    def curar(self):
        self._escrever(INJURY_HEALTHY, "curado")

    def lesionar(self):
        if not messagebox.askyesno(
                APP_TITLE,
                "Isto vai deixar o jogador LESIONADO na memoria (teste).\n"
                "Nao salve o jogo enquanto estiver assim.\n\nContinuar?"):
            return
        self._escrever(INJURY_TEST, "lesionado (teste)")

    def _escrever(self, valor: int, rotulo: str):
        if self.pid is None or not self.copias:
            return
        try:
            lidos = write_injury(self.pid, self.copias, valor)
        except OSError as exc:
            self._log(f"Falha ao escrever: {exc}")
            self.lbl_status.configure(text="Conexao perdida", foreground="#a00")
            return
        for copia, lido in zip(self.copias, lidos):
            copia.injury = lido
        self._preencher()
        self._log(f"Jogador {rotulo}: {lidos} (0x{valor:02x})")
        if rotulo.startswith("curado"):
            self._log("Dica: entre/saia da tela do jogo para ela reler o valor.")

    def atualizar(self):
        if self.pid is None or not self.copias:
            return
        try:
            lidos = read_injuries(self.pid, self.copias)
        except OSError as exc:
            self._log(f"Falha ao ler: {exc}")
            return
        for copia, lido in zip(self.copias, lidos):
            copia.injury = lido
        self._preencher()

    # ---- laco de eventos ---------------------------------------------------
    def _processar_fila(self):
        try:
            while True:
                tipo, dado = self._fila.get_nowait()
                if tipo == "ok":
                    self._aplicar_descoberta(dado)
                elif tipo == "erro":
                    self._ocupado = False
                    self.btn_conectar.configure(state="normal")
                    self._log(f"Erro na varredura: {dado}")
                elif tipo == "hotkey":
                    if dado == "curar":
                        self.curar()
                    elif dado == "conectar":
                        self.conectar()
        except queue.Empty:
            pass
        self.after(200, self._processar_fila)

    def _tick(self):
        if self.pid is not None and self.copias and not self._ocupado:
            try:
                lidos = read_injuries(self.pid, self.copias)
                if any(c.injury != v for c, v in zip(self.copias, lidos)):
                    for copia, lido in zip(self.copias, lidos):
                        copia.injury = lido
                    self._preencher()
            except OSError:
                self.lbl_status.configure(text="Jogo fechou/conexao perdida",
                                          foreground="#a00")
                self.pid = None
                self.copias = []
                self._set_botoes(False)
        self.after(1000, self._tick)

    def fechar(self):
        if self._hotkeys is not None:
            self._hotkeys.stop()
        self.master.destroy()


def main() -> int:
    raiz = tk.Tk()
    TreinadorApp(raiz)
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
