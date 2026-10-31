"""Tkinter GUI for the [PC] PES 2016 ML-BL Editor."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from . import core as C

APP_TITLE = "[PC] PES 2016 ML-BL Editor"
ABOUT = (
    "Editor de saves do PES 2016 (Master League / Become a Legend) - versão PC\n\n"
    "Reimplementação nativa (Linux) do programa Windows\n"
    "\"[XBOX 360-PC] PES 2016 ML-BL Editor\" v1.2.0.0 (by extream87).\n\n"
    "Diferente do original, esta versão CRIPTOGRAFA/DESCRIPTOGRAFA o save\n"
    "sozinha (o original no PC não fazia cripto). Abra o save do jogo,\n"
    "edite e salve: o arquivo gerado já é um save válido.\n\n"
    "Offsets (relativos ao bloco de dados, validados no jogo):\n"
    f"  Dinheiro ML (3 bytes LE) = {C.ML_MONEY_OFFSET}\n"
    f"  Nome do manager (3 locais) = {', '.join(map(str, C.MANAGER_NAME_OFFSETS))}\n"
    f"  Stats de treino BAL (9 bytes) = {C.BAL_STATS_BASE}\n"
    f"  Training (1 byte) = {C.BAL_TRAINING_OFFSET}\n"
    f"  Focus (1 byte) = {C.BAL_FOCUS_OFFSET}\n\n"
    "Aba \"BL > Habilidades\" (novidade desta versão):\n"
    "  As 17 habilidades da tela do jogo (Ataque, Controle de bola, Drible,\n"
    "  Passe rasteiro, Passe pelo alto, Finalização, Chute colocado, Efeito,\n"
    "  Cabeçada, Defesa, Desarme, Força do chute, Velocidade, Explosão,\n"
    "  Equilíbrio, Impulsão, Resistência), as 5 de goleiro, idade, altura,\n"
    "  peso, condição física, resistência a lesão e melhor pé.\n"
    "  Tem também o campo \"Lesão ativa\": 0 = saudável. Se o seu jogador\n"
    "  está machucado e não joga, coloque 0 para curá-lo (o jogo grava\n"
    "  um código próprio ali, ex.: 44; esse campo fica só no BL/snapshot).\n"
    "  O editor localiza o registro do jogador pelo nome (não por offset\n"
    "  fixo) e grava em todas as cópias que encontrar.\n\n"
    "IMPORTANTE - onde o jogo lê o jogador BAL:\n"
    "  O jogo guarda as habilidades do seu jogador em TRÊS lugares:\n"
    "   1) no EDIT00000000 (banco de jogadores) - é o que aparece no menu\n"
    "      Edit do jogo;\n"
    "   2) num registro em texto puro dentro do BL00000000;\n"
    "   3) numa CÓPIA COMPRIMIDA no fim do BL00000000 (\"snapshot da\n"
    "      carreira\") - é desta que a tela do modo Rumo ao Estrelato lê.\n"
    "  Este editor grava nos TRÊS.  Por isso ele carrega o EDIT00000000\n"
    "  que estiver na mesma pasta do save e mostra, na aba Habilidades, o\n"
    "  status do EDIT e do snapshot da carreira.\n"
    "  Copie os DOIS arquivos de volta para a pasta de save do jogo.\n"
)


class EditorApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=8)
        self.master.title(APP_TITLE)
        self.master.minsize(760, 580)

        self.loaded: C.LoadedSave | None = None
        self.mode: str | None = None
        self.out_path: Path | None = None
        self.player_bases: list[int] = []
        # EDIT00000000 (player database) - the game shows the BAL player's
        # abilities from here, so it is loaded and written together with BL.
        self.edit_loaded: C.LoadedSave | None = None
        self.edit_bases: list[int] = []
        # Number of records rewritten inside the compressed career snapshot.
        self.snapshot_records = 0

        self._build_toolbar()
        self._build_tabs()
        self._build_status()
        self.pack(fill="both", expand=True)
        self._set_enabled(False)

    # -- UI construction ----------------------------------------------------
    def _build_toolbar(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Button(bar, text="Abrir arquivo…", command=self.open_file).pack(side="left")
        self.btn_apply = ttk.Button(bar, text="Aplicar (Salvar)", command=self.apply)
        self.btn_apply.pack(side="left", padx=6)
        ttk.Button(bar, text="Sobre", command=lambda: messagebox.showinfo("Sobre", ABOUT)).pack(side="left")
        self.lbl_platform = ttk.Label(bar, text="Nenhum arquivo", foreground="#555")
        self.lbl_platform.pack(side="right")

    def _build_tabs(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        # ---- Master League tab
        ml = ttk.Frame(self.nb, padding=10)
        self.nb.add(ml, text="ML")
        ttk.Label(ml, text="Moeda:").grid(row=0, column=0, sticky="w")
        self.cmb_currency = ttk.Combobox(ml, values=C.CURRENCIES, state="readonly", width=20)
        self.cmb_currency.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.cmb_currency.bind("<<ComboboxSelected>>", lambda e: self.on_currency_change())
        ttk.Label(ml, text="Funds atuais:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.lbl_current = ttk.Label(ml, text="—", font=("TkDefaultFont", 10, "bold"))
        self.lbl_current.grid(row=1, column=1, sticky="w", pady=(8, 0))

        box = ttk.LabelFrame(ml, text="Team Funds (presets)", padding=8)
        box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=10)
        self.preset_var = tk.IntVar(value=0)
        self.preset_labels: list[str] = []
        self._preset_widgets: dict[int, ttk.Radiobutton] = {}
        for i in range(6):
            txt = "Custom (manual)" if i == 0 else ""
            rb = ttk.Radiobutton(box, text=txt, variable=self.preset_var, value=i,
                                 command=self._on_preset_change)
            rb.grid(row=i, column=0, sticky="w", pady=1)
            self.preset_labels.append(txt)
            self._preset_widgets[i] = rb

        custom = ttk.Frame(ml)
        custom.grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Label(custom, text="Custom (valor manual):").pack(side="left")
        self.var_custom = tk.StringVar(value="0")
        self.ent_custom = ttk.Entry(custom, textvariable=self.var_custom, width=20)
        self.ent_custom.pack(side="left", padx=6)

        mgr = ttk.Frame(ml)
        mgr.grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(mgr, text="Manager:").pack(side="left")
        self.var_manager = tk.StringVar()
        self.ent_manager = ttk.Entry(mgr, textvariable=self.var_manager, width=24)
        self.ent_manager.pack(side="left", padx=6)
        ttk.Label(mgr, text=f"(máx. {C.MANAGER_NAME_MAX_CHARS} caracteres)").pack(side="left")

        # ---- Become a Legend tab (sub-notebook: Treino / Habilidades)
        bl = ttk.Frame(self.nb, padding=0)
        self.nb.add(bl, text="BL")
        self.bl_nb = ttk.Notebook(bl)
        self.bl_nb.pack(fill="both", expand=True, padx=4, pady=4)

        # -- Treino / Focus
        train = ttk.Frame(self.bl_nb, padding=10)
        self.bl_nb.add(train, text="Treino / Focus")
        ttk.Label(train, text="Stats", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w", columnspan=3)
        self.stat_vars: dict[str, tk.IntVar] = {}
        self.stat_bars: dict[str, ttk.Progressbar] = {}
        for i, name in enumerate(C.STAT_NAMES):
            r = i + 1
            ttk.Label(train, text=f"{name}:").grid(row=r, column=0, sticky="w", pady=2)
            var = tk.IntVar(value=0)
            ttk.Spinbox(train, from_=0, to=C.STAT_MAX, textvariable=var, width=5).grid(row=r, column=1, padx=6)
            bar = ttk.Progressbar(train, maximum=C.STAT_MAX * 16, length=220)
            bar.grid(row=r, column=2, sticky="w")
            var.trace_add("write", lambda *a, n=name: self._on_stat_change(n))
            self.stat_vars[name] = var
            self.stat_bars[name] = bar

        r = len(C.STAT_NAMES) + 2
        ttk.Separator(train).grid(row=r, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(train, text="Training:").grid(row=r + 1, column=0, sticky="w", pady=2)
        self.var_training = tk.IntVar(value=0)
        ttk.Spinbox(train, from_=0, to=C.TRAINING_MAX, textvariable=self.var_training, width=5).grid(row=r + 1, column=1, padx=6)
        ttk.Label(train, text="Focus:").grid(row=r + 2, column=0, sticky="w", pady=2)
        self.var_focus = tk.IntVar(value=0)
        ttk.Spinbox(train, from_=0, to=C.FOCUS_MAX, textvariable=self.var_focus, width=5).grid(row=r + 2, column=1, padx=6)
        self.btn_max = ttk.Button(train, text="   Max Stats", command=self.max_stats)
        self.btn_max.grid(row=r + 3, column=0, sticky="w", pady=10)

        # -- Habilidades (player record)
        abil = ttk.Frame(self.bl_nb, padding=0)
        self.bl_nb.add(abil, text="Habilidades")
        top = ttk.Frame(abil, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Jogador:").pack(side="left")
        self.var_player = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_player, width=24).pack(side="left", padx=6)
        ttk.Button(top, text="Procurar", command=self.locate_player).pack(side="left")
        self.lbl_player = ttk.Label(top, text="—", foreground="#555")
        self.lbl_player.pack(side="left", padx=10)

        top2 = ttk.Frame(abil, padding=(8, 0))
        top2.pack(fill="x")
        self.lbl_edit = ttk.Label(top2, text="EDIT00000000: —", foreground="#555")
        self.lbl_edit.pack(side="left")
        self.btn_edit = ttk.Button(top2, text="Escolher EDIT00000000…", command=self.choose_edit)
        self.btn_edit.pack(side="left", padx=10)

        top3 = ttk.Frame(abil, padding=(8, 0))
        top3.pack(fill="x")
        self.lbl_snap = ttk.Label(top3, text="Snapshot da carreira: —", foreground="#555")
        self.lbl_snap.pack(side="left")

        inner = self._make_scroll(abil)
        self.player_vars: dict[str, tk.IntVar] = {}
        self.player_bars: dict[str, ttk.Progressbar] = {}
        for title, keys in C.PLAYER_GROUPS:
            g = ttk.LabelFrame(inner, text=title, padding=8)
            g.pack(fill="x", expand=True, padx=8, pady=6)
            for i, key in enumerate(keys):
                _k, label, _kind, _pos, _w, mx = C.PLAYER_FIELD_BY_KEY[key]
                lo = C.FIELD_BIAS.get(key, 0)
                ttk.Label(g, text=f"{label}:").grid(row=i, column=0, sticky="w", pady=1)
                var = tk.IntVar(value=lo)
                ttk.Spinbox(g, from_=lo, to=mx, textvariable=var, width=5).grid(row=i, column=1, padx=6)
                if mx >= 20:
                    bar = ttk.Progressbar(g, maximum=99, length=180)
                    bar.grid(row=i, column=2, sticky="w")
                    self.player_bars[key] = bar
                var.trace_add("write", lambda *a, k=key, m=mx: self._on_player_change(k, m))
                self.player_vars[key] = var

    def _build_status(self):
        f = ttk.Frame(self)
        f.pack(fill="x", pady=(6, 0))
        ttk.Label(f, text="Saída:").pack(side="left")
        self.lbl_out = ttk.Label(f, text="—", foreground="#333")
        self.lbl_out.pack(side="left", padx=6)
        self.btn_out = ttk.Button(f, text="Escolher destino…", command=self.choose_output)
        self.btn_out.pack(side="right")

    # -- helpers ------------------------------------------------------------
    def _make_scroll(self, parent) -> ttk.Frame:
        canvas = tk.Canvas(parent, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def _wheel(event):
            delta = -1 if getattr(event, "delta", 0) > 0 else 1
            if getattr(event, "num", None) == 4:
                delta = -1
            elif getattr(event, "num", None) == 5:
                delta = 1
            canvas.yview_scroll(delta, "units")

        def _enter(_e):
            canvas.bind_all("<MouseWheel>", _wheel)
            canvas.bind_all("<Button-4>", _wheel)
            canvas.bind_all("<Button-5>", _wheel)

        def _leave(_e):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _enter)
        canvas.bind("<Leave>", _leave)
        return inner

    def _set_enabled(self, on: bool):
        state = "normal" if on else "disabled"
        self.btn_apply.configure(state=state)
        self.btn_out.configure(state=state)
        self.btn_edit.configure(state=state)

    def _on_preset_change(self):
        self.ent_custom.configure(state="normal" if self.preset_var.get() == 0 else "disabled")

    def _on_player_change(self, key: str, mx: int):
        bar = self.player_bars.get(key)
        if bar is None:
            return
        try:
            v = int(self.player_vars[key].get())
        except Exception:
            return
        bar["value"] = max(0, min(v, 99))

    def _load_player_values(self, base: int):
        vals = C.read_player(self.loaded.data, base)
        for key, var in self.player_vars.items():
            var.set(vals.get(key, 0))
            _k, _l, _kind, _pos, _w, mx = C.PLAYER_FIELD_BY_KEY[key]
            self._on_player_change(key, mx)

    def _find_bal_player(self):
        """Auto-detect the BAL player -> (created_base, name, record_bases)."""
        if self.loaded is None:
            return None
        data = self.loaded.data
        created = C.find_created_player(data)
        if created is None:
            return None
        base, name = created
        h = data[base + C.PLAYER_HEIGHT_OFFSET]
        w = data[base + C.PLAYER_WEIGHT_OFFSET]
        bases = C.filter_records_by_body(data, C.find_player_records(data, name), h, w)
        return base, name, C._order_records(bases, base)

    # -- EDIT00000000 (player database) -------------------------------------
    def _attach_edit(self):
        """Find a sibling EDIT00000000 and remember it for the BL player."""
        self.edit_loaded = None
        self.edit_bases = []
        if self.loaded is None:
            self.lbl_edit.configure(text="EDIT00000000: —", foreground="#555")
            return
        path = C.find_edit_file(self.loaded.path)
        if path is None:
            self.lbl_edit.configure(
                text="EDIT00000000 não encontrado ao lado do save — use o botão "
                     "para escolhê-lo.", foreground="#b60")
            return
        self._load_edit_path(path)

    def _load_edit_path(self, path: Path):
        try:
            self.edit_loaded = C.load(path, strict=False)
        except C.EditorError as e:
            self.edit_loaded = None
            self.edit_bases = []
            self.lbl_edit.configure(text=f"EDIT inválido: {e}", foreground="#b00")
            return
        self._locate_in_edit()

    def _locate_in_edit(self):
        self.edit_bases = []
        if self.edit_loaded is None:
            return
        pname = self.edit_loaded.path.name
        name = self.var_player.get().strip()
        if not name:
            self.lbl_edit.configure(text=f"{pname}: escolha o jogador.", foreground="#b60")
            return
        h = w = None
        if self.loaded is not None:
            created = C.find_created_player(self.loaded.data)
            if created is not None and created[1] == name:
                h = self.loaded.data[created[0] + C.PLAYER_HEIGHT_OFFSET]
                w = self.loaded.data[created[0] + C.PLAYER_WEIGHT_OFFSET]
        bases = C.find_edit_records(self.edit_loaded.data, name, h, w)
        self.edit_bases = bases
        if bases:
            self.lbl_edit.configure(
                text=f"{pname}: '{name}' encontrado no banco (registro {bases[0]}).",
                foreground="#070")
        else:
            self.lbl_edit.configure(
                text=f"{pname}: '{name}' NÃO está no banco. Entre no jogo e salve "
                     "o Edit data (aba Edit > Salvar) para que ele apareça aqui.",
                foreground="#b60")

    def choose_edit(self):
        if self.loaded is None:
            return
        path = filedialog.askopenfilename(
            title="Escolher o arquivo EDIT00000000",
            initialdir=str(self.loaded.path.parent),
            filetypes=[("Todos os arquivos", "*.*")])
        if path:
            self._load_edit_path(Path(path))

    def locate_player(self):
        if self.loaded is None or self.mode != "BL":
            return
        name = self.var_player.get().strip()
        if not name:
            found = self._find_bal_player()
            if found is None:
                messagebox.showwarning(APP_TITLE, "Informe o nome do jogador BAL.")
                return
            base, name, self.player_bases = found
            self.var_player.set(name)
        else:
            bases = C.find_player_records(self.loaded.data, name)
            created = C.find_created_player(self.loaded.data)
            created_base = None
            if created is not None:
                created_base, created_name = created
                if created_name == name:
                    h = self.loaded.data[created_base + C.PLAYER_HEIGHT_OFFSET]
                    w = self.loaded.data[created_base + C.PLAYER_WEIGHT_OFFSET]
                    bases = (C.filter_records_by_body(self.loaded.data, bases, h, w)
                             or bases)
                else:
                    created_base = None
            self.player_bases = C._order_records(bases, created_base)
        if not self.player_bases:
            self.lbl_player.configure(text="não encontrado", foreground="#b00")
            self._locate_in_edit()
            return
        self.lbl_player.configure(
            text=f"{len(self.player_bases)} registro(s): "
                 + ", ".join(str(b) for b in self.player_bases), foreground="#070")
        self._load_player_values(self.player_bases[0])
        self._locate_in_edit()

    def _on_stat_change(self, name: str):
        try:
            v = int(self.stat_vars[name].get())
        except Exception:
            return
        self.stat_bars[name]["value"] = max(0, min(v, C.STAT_MAX)) * 16

    def _refresh_current(self):
        if self.loaded is None or self.mode != "ML":
            return
        raw = C.read_money_raw(self.loaded.data)
        c = self.cmb_currency.current() if self.cmb_currency.current() >= 0 else 0
        self.lbl_current.configure(text=f"{C.money_display(raw, c):,}".replace(",", "."))
        for i, lab in enumerate(C.PRESET_LABELS[c], start=1):
            self._preset_widgets[i].configure(text=lab)

    # -- actions ------------------------------------------------------------
    def open_file(self):
        path = filedialog.askopenfilename(title="Abrir save do PES 2016",
                                          filetypes=[("Todos os arquivos", "*.*")])
        if path:
            self.open_path(Path(path))

    def open_path(self, p: Path) -> bool:
        mode = C.detect_mode(p.name)
        if mode is None:
            messagebox.showerror(APP_TITLE,
                                 "PES 2016 - File Problem!\n"
                                 "Não renomeie o save ML/BL.\n\n"
                                 "O nome do arquivo precisa conter ML00 ou BL00.")
            return False

        try:
            loaded = C.load(p)
        except C.EditorError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return False

        self.loaded = loaded
        self.mode = mode
        self.out_path = p
        self.lbl_out.configure(text=f"{p}  (grava no mesmo arquivo — backup .bak automático)")
        crypto = "descriptografado e pronto" if loaded.encrypted else "já estava descriptografado"
        self.lbl_platform.configure(text=f"PC  |  {mode}  |  {p.name}  ({crypto})")
        self._set_enabled(True)

        if mode == "ML":
            self.nb.select(0)
            self.edit_loaded = None
            self.edit_bases = []
            self.lbl_edit.configure(text="EDIT00000000: —", foreground="#555")
            self.var_manager.set(C.read_manager_name(loaded.data))
            self.cmb_currency.current(0)
            self.preset_var.set(0)
            self._on_preset_change()
            self.var_custom.set("0")
            self._refresh_current()
        else:
            self.nb.select(1)
            s = C.read_stats(loaded.data)
            for n in C.STAT_NAMES:
                self.stat_vars[n].set(s[n])
                self._on_stat_change(n)
            self.var_training.set(s["Training"])
            self.var_focus.set(s["Focus"])
            # Auto-detect the BAL player record for the "Habilidades" tab.
            self.var_player.set("")
            self.player_bases = []
            found = self._find_bal_player()
            if found is not None:
                base, name, bases = found
                self.var_player.set(name)
                self.player_bases = bases
                self.lbl_player.configure(
                    text=f"{len(bases)} registro(s) do jogador "
                         f"'{name}' localizado(s).", foreground="#070")
                self._load_player_values(bases[0])
            else:
                self.lbl_player.configure(
                    text="Não localizei o jogador BAL automaticamente. "
                         "Digite o nome e clique em Procurar.",
                    foreground="#b60")
            # The game reads a created player's abilities from EDIT00000000,
            # so load it now and write it together with BL on "Aplicar".
            self._attach_edit()
            self._refresh_snapshot_label(loaded.data)
        return True

    def _refresh_snapshot_label(self, data: bytes):
        info = C.compressed_section_info(data)
        if info is None:
            self.lbl_snap.configure(
                text="Snapshot da carreira (bloco comprimido): não existe neste save.",
                foreground="#b60")
            return
        blocks, total = info
        self.lbl_snap.configure(
            text="Snapshot da carreira: %d blocos comprimidos (%.1f MB) — é dele que a "
                 "carreira BAL lê o jogador; será gravado junto."
                 % (blocks, total / 1048576.0),
            foreground="#070")

    def choose_output(self):
        if self.loaded is None:
            return
        path = filedialog.asksaveasfilename(title="Salvar save modificado como",
                                            initialdir=str(self.out_path.parent),
                                            initialfile=self.out_path.name)
        if path:
            self.out_path = Path(path)
            self.lbl_out.configure(text=str(self.out_path))

    def on_currency_change(self):
        self._refresh_current()

    def max_stats(self):
        for i, n in enumerate(C.STAT_NAMES):
            self.stat_vars[n].set(C.MAX_STATS_VALUES[i])
            self._on_stat_change(n)
        self.var_training.set(C.MAX_STATS_VALUES[9])
        self.var_focus.set(C.FOCUS_MAX)

    def apply(self):
        if self.loaded is None:
            return
        buf = bytearray(self.loaded.data)
        self.snapshot_records = 0
        try:
            if self.mode == "ML":
                C.write_manager_name(buf, self.var_manager.get())
                if self.preset_var.get() == 0:
                    try:
                        value = float(self.var_custom.get().replace(".", "").replace(",", "."))
                    except ValueError:
                        messagebox.showerror(APP_TITLE, "Valor custom inválido.")
                        return
                    c = self.cmb_currency.current() if self.cmb_currency.current() >= 0 else 0
                    raw = C.money_raw_from_display(value, c)
                else:
                    raw = C.PRESET_RAW[self.preset_var.get() - 1]
                C.write_money_raw(buf, raw)
            else:
                stats = {n: int(self.stat_vars[n].get()) for n in C.STAT_NAMES}
                stats["Training"] = int(self.var_training.get())
                stats["Focus"] = int(self.var_focus.get())
                C.write_stats(buf, stats)
                if self.player_bases:
                    vals = {k: int(v.get()) for k, v in self.player_vars.items()}
                    # The body used to find the snapshot copy must be the one
                    # already in the file (the user may be changing it).
                    old = self.loaded.data
                    b0 = self.player_bases[0]
                    h = old[b0 + C.PLAYER_HEIGHT_OFFSET]
                    w = old[b0 + C.PLAYER_WEIGHT_OFFSET]
                    for base in self.player_bases:
                        C.write_player(buf, base, vals)
                    # The BAL career screen reads the player from the save's
                    # compressed snapshot - keep that copy in sync too.
                    name = self.var_player.get().strip()
                    if name:
                        self.snapshot_records = C.patch_compressed_players(
                            buf, name, vals, h, w)
        except (ValueError, tk.TclError) as e:
            messagebox.showerror(APP_TITLE, f"Valor inválido: {e}")
            return

        self.loaded.data = buf

        # The BAL player's abilities are read by the game from the EDIT
        # database, so mirror the same values into it as well.
        wrote_edit = False
        if self.mode == "BL" and self.edit_loaded is not None and self.edit_bases:
            ebuf = bytearray(self.edit_loaded.data)
            vals = {k: int(v.get()) for k, v in self.player_vars.items()}
            for base in self.edit_bases:
                C.write_edit_player(ebuf, base, vals)
            self.edit_loaded.data = ebuf
            wrote_edit = True

        out, make_backup = self._write_save(self.loaded, self.out_path)
        if out is None:
            return
        edit_out = None
        if wrote_edit:
            edit_out, _ = self._write_save(self.edit_loaded, self.edit_loaded.path)

        if self.mode == "ML":
            self._refresh_current()
        if make_backup:
            tip = f"\n\nBackup do original: {out.name}.bak"
        else:
            tip = ("\n\nPara usar no jogo: copie esse arquivo para a pasta de save do "
                   "PES 2016,\nrenomeando para o nome original (ex.: BL00000000).")
        if edit_out is not None:
            tip += (f"\n\nEDIT00000000 atualizado também:\n{edit_out}\n"
                    "(copie os DOIS arquivos para a pasta de save do jogo)")
        if self.mode == "BL" and self.player_bases:
            if self.snapshot_records:
                tip += ("\n\nSnapshot da carreira atualizado (%d registro(s) no bloco "
                        "comprimido) — é a cópia que o modo Rumo ao Estrelato usa."
                        % self.snapshot_records)
            else:
                tip += ("\n\nATENÇÃO: não encontrei o snapshot da carreira para este "
                        "jogador. As habilidades vão aparecer no menu Edit, mas talvez "
                        "não na carreira.")
        messagebox.showinfo(
            APP_TITLE,
            "PES 2016 - Successfully modded!\n\n"
            "Save modificado (já criptografado) gravado em:\n"
            f"{out}" + tip)
        self.lbl_out.configure(text=str(out))

    def _write_save(self, loaded: C.LoadedSave, out_path):
        """Save *loaded* to *out_path*, making a .bak when overwriting itself."""
        out = Path(out_path)
        make_backup = False
        try:
            make_backup = out.resolve() == loaded.path.resolve()
        except OSError:
            make_backup = False
        if make_backup:
            bak = out.with_name(out.name + ".bak")
            if not bak.exists():
                try:
                    bak.write_bytes(loaded.path.read_bytes())
                except OSError:
                    pass
        try:
            return C.save(loaded, out), make_backup
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Não foi possível gravar:\n{e}")
            return None, False


def run(save_path: str | None = None):
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    app = EditorApp(root)
    if save_path:
        # Arquivo passado na linha de comando ("abrir com..." / arrastar e
        # soltar); abre depois da janela aparecer.
        root.after(100, lambda: app.open_path(Path(save_path)))
    root.mainloop()


if __name__ == "__main__":
    run()
