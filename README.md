[![build](https://github.com/warlisonk360/PES-2016-ML-BL-Editor/actions/workflows/build.yml/badge.svg)](https://github.com/warlisonk360/PES-2016-ML-BL-Editor/actions/workflows/build.yml)
[![licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-green.svg)](LICENSE)

# PES 2016 ML-BL Editor (PC) — Linux e Windows

Editor de saves do **PES 2016 para PC** (Master League / Become a Legend):
reimplementação nativa, para **Linux e Windows**, do programa
`[XBOX 360-PC] PES 2016 ML-BL Editor.exe` (v1.2.0.0, por **extream87**).

- 🐧 **Linux** — um arquivo só (`AppImage`), não precisa instalar nada;
- 🪟 **Windows** — um `.exe` só (x64), não precisa instalar nada;
- faz a **criptografia do save sozinho** (o programa original não fazia isso no
  PC, por isso precisava de um "crypter" separado);
- no "Rumo ao Estrelato" (BAL) grava o jogador nos **três lugares** em que o
  jogo guarda as habilidades dele (veja abaixo);
- funciona **offline**, sem telemetria.

## 📥 Baixar

Pegue os arquivos na página de **[Releases](../../releases)**:

| Plataforma | Arquivo |
|---|---|
| Windows (x64) | `PES2016-MLBL-Editor-Windows-x64.exe` |
| Linux (x86_64) | `PES2016-MLBL-Editor-PC-x86_64.AppImage` |

Também dá para baixar os arquivos gerados por qualquer build em
**Actions → build → artifact**.

> **Windows:** o `.exe` não é assinado digitalmente, então o SmartScreen pode
> avisar. Clique em *Mais informações → Executar assim mesmo*.

## ▶️ Como usar

1. Abra o programa (**Abrir arquivo…**) e escolha o save do jogo:
   - `ML00000000` (Master League), ou
   - `BL00000000` (Rumo ao Estrelato / Become a Legend).
2. Edite os campos.
3. **Aplicar (Salvar)**.
   - Por padrão grava **no próprio save aberto** e cria um backup automático
     `.bak` na primeira vez.
   - Dá para escolher outro destino em **"Escolher destino…"**.
4. No BAL, copie **os dois arquivos** de volta para a pasta de save do jogo
   (`BL00000000` e `EDIT00000000`).

Também dá para abrir um save direto por linha de comando (ou arrastando o
arquivo em cima do programa, no Windows):

```bash
./PES2016-MLBL-Editor-PC-x86_64.AppImage  BL00000000
PES2016-MLBL-Editor-Windows-x64.exe  BL00000000
```

### Linux: precisa dar permissão de execução (só na primeira vez)

```bash
chmod +x PES2016-MLBL-Editor-PC-x86_64.AppImage
./PES2016-MLBL-Editor-PC-x86_64.AppImage
```

## 🎮 O que dá para editar

**Master League (`ML00000000`)**

- Team Funds (presets de € / $ / ¥ / £ / R$ + valor personalizado)
- Nome do Manager

**Rumo ao Estrelato (`BL00000000`)** — o jogador é achado **pelo nome**

- aba **Treino / Focus**: os 9 atributos de treino (0–6), Training (0–20),
  Focus (0–100) e botão *Max Stats*;
- aba **Habilidades**: as 17 habilidades da tela do jogo, as 5 de goleiro,
  **condição física (1–8)**, **resistência a lesão (1–3)**, **pior pé**
  (frequência e precisão, 1–4), **melhor pé**, idade, altura e peso;
- **lesão ativa** (`0` = saudável): coloque `0` para **curar** o jogador que
  está machucado e não joga. O jogo grava um código próprio nesse byte (vi `44`
  num jogador lesionado); voltar para `0` o libera na hora. É o único valor
  testado — não invente outros.

### ⚠️ No BAL o jogador existe em três lugares

| # | Onde | Quem lê |
|---|---|---|
| 1 | `EDIT00000000` (banco de jogadores, registro de 112 bytes) | o menu **Edit** do jogo |
| 2 | `BL00000000` (registro de 228 bytes em texto puro) | gravação/consistência |
| 3 | `BL00000000` (**snapshot comprimido** no fim do arquivo, 22 blocos zlib) | a tela do modo **Rumo ao Estrelato** |

O editor localiza os três automaticamente e, ao aplicar, **grava nos três de
uma vez** (recomprime o snapshot e recalcula tamanhos/offsets). O `EDIT00000000`
é procurado na mesma pasta do `BL00000000`.

### 🧠 Treinador ao vivo (Linux, opcional)

`treinador-pc/treinador.py` é um painel separado que **lê e escreve na memória
do jogo aberto** (Bottles/Wine), para o que precisa valer na hora — hoje:
**curar a lesão** do jogador do BAL sem fechar o jogo.

- Acha o processo `PES2016.exe` e o registro pelo **nome + layout** (sem
  endereço fixo: os endereços mudam a cada execução);
- Mostra ao vivo ID, altura, peso, lesão ativa e condição física;
- **Atributos ao vivo** (**Atributos...**): os 31 campos do registro do jogador
  (habilidades, goleiro, físico) com **Aplicar** e **Max habilidades**; grava
  só os bytes que mudam, nas cópias da carreira;
- **Dinheiro da Liga Master** (**Dinheiro ML...**): localiza o saldo pelo valor
  que aparece no jogo e permite definir outro (ex.: `$28.706.900` →
  `$50.000.000`);
- Atalhos globais **F9** (curar) e **F10** (reconectar);
- **Não toca no arquivo do save**: só na memória.

Requer Python 3 + Tkinter (`python3-tk`). **Somente Linux.**
Detalhes em `treinador-pc/README.md`.

### 🧪 Mod menu injetado (experimental — Etapa 2)

Em `mod-menu-pc/` há um **proxy `d3d9.dll`** que injeta um menu ImGui por cima
do jogo (aberto com **Insert**). Na Etapa 2 ele também **lê e grava na memória do
próprio jogo**, sempre por ação explícita e com botão de reverter:

- **Jogador**: busca o registro pelo nome, mostra ID/lesão e permite curar,
  lesionar (teste) ou reverter a lesão.
- **Dinheiro da Liga Master**: busca o saldo exibido no jogo, aplica um novo
  valor e reverte para o original.

- Funciona com o **DXVK** (o proxy carrega o DXVK renomeado como `d3d9_real.dll`).
- Navegação por **setas/Tab + Enter**; **Esc** fecha (o jogo prende o cursor).
- Instalação/desinstalação por `install.sh` / `uninstall.sh`.
- Detalhes técnicos e diagnóstico em
  [`mod-menu-pc/README.md`](mod-menu-pc/README.md).

## 🛡️ Segurança

- Sempre que grava em cima do próprio arquivo, o programa cria um `.bak`.
  Mesmo assim: **faça uma cópia do seu save antes do primeiro teste.**
- Os testes automatizados (`codigo-fonte-pc/test_core.py`) trabalham **em
  cópias** dos saves (nunca no original).

## 🔧 Detalhes técnicos

- Os saves do PES 2016 (PC) são **criptografados**. A criptografia é portada do
  projeto de domínio público
  [`the4chancup/pesXdecrypter`](https://github.com/the4chancup/pesXdecrypter)
  (MT19937 + cifra em fluxo) e foi validada byte a byte contra o crypter de
  referência; o jogo carrega normalmente o save re-gravado.
- Os layouts foram recuperados com engenharia reversa (REA + ILSpy) na
  documentação da wiki do PES 2016/Texport e **confirmados no jogo**: para
  54 de 54 jogadores reais os valores lidos no `BL` e no `EDIT` batem.
- A tabela completa de offsets (BL, EDIT e snapshot) está em
  [`LEIA-ME - Editor PC (Linux e Windows).md`](LEIA-ME%20-%20Editor%20PC%20(Linux%20e%20Windows).md).

## 🏗️ Compilar você mesmo

O código está em `codigo-fonte-pc/` (Python 3.10+; a única dependência é o
Tkinter, que já vem no Python do Windows e no pacote `python3-tk` no Linux).

**Windows** (PowerShell, na raiz do repositório):

```powershell
.\empacotamento\build-exe-windows.ps1
```

**Linux** (precisa de `curl`, `tar` e `python3`):

```bash
./empacotamento/build-appimage.sh
```

Cada script baixa o que precisa (PyInstaller / Python portátil + appimagetool),
roda os testes e gera o arquivo final na raiz do repositório.

**Testes** (a parte principal funciona sem os saves):

```bash
python3 codigo-fonte-pc/test_core.py
```

### 🧰 Ferramentas de engenharia reversa (`ferramentas/`)

Scripts usados para descobrir e validar os offsets. **Não fazem parte do
programa** — servem para conferir/refazer o mapeamento. Todos precisam de um
save real (`BL00000000.original` / `EDIT00000000.original`) na raiz do projeto,
então não rodam no repositório (os saves não são versionados).

| Script | Para que serve |
|---|---|
| `ver_save.py` | mostra tudo o que o editor consegue ler de um save, sem alterar nada |
| `derivar_edit4.py` | descobre os offsets das habilidades dentro do `EDIT00000000` |
| `derivar_edit5.py` | descobre altura, peso e idade no `EDIT00000000` |
| `verificar_edit.py` | confere o layout do `EDIT` contra o `BL` |
| `gerar_teste.py` | gera saves de teste com valores bem visíveis, para conferir no jogo |
| `gerar_teste_edit.py` | gera um par `BL` + `EDIT` de teste |

Exemplo:

```bash
python3 ferramentas/ver_save.py "/caminho/do/save/BL00000000"
```

### Releases automáticos

O workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) gera os
dois arquivos a cada push/PR. Para publicar uma release, é só criar uma tag:

```bash
git tag v1.2.0
git push origin v1.2.0
```

O workflow compila o `.exe` e a `AppImage`, roda um teste rápido (a janela
abre?) e **anexa os dois arquivos na release**.

## 🙏 Créditos

- **extream87** — autor do programa original
  `[XBOX 360-PC] PES 2016 ML-BL Editor`.
- **[the4chancup/pesXdecrypter](https://github.com/the4chancup/pesXdecrypter)** —
  criptografia dos saves.
- **Wiki [implyingrigged.info](https://implyingrigged.info/wiki/Pro_Evolution_Soccer_2016/Texport)** —
  documentação do formato `Texport`.
- Comunidade do PES 2016 (PES-Patch / pesdb etc.) pelas referências.

## 📄 Licença

[MIT](LICENSE) © 2026 Warlison Santos — pode usar, estudar, modificar e
redistribuir, mantendo o aviso de copyright.

O programa original `[XBOX 360-PC] PES 2016 ML-BL Editor.exe` é de autoria de
**extream87** e **não** faz parte deste repositório: aqui existe apenas uma
reimplementação independente, feita por engenharia reversa para uso pessoal.
Use por sua conta e risco, sempre com backup dos saves.

Os saves e o jogo são seus; "Pro Evolution Soccer" e "PES" são marcas da
**Konami Digital Entertainment** — este projeto não é afiliado nem endossado
por ela.
