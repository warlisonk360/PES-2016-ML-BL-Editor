# PES 2016 ML-BL Editor — versão PC (Linux AppImage + Windows .exe)

Reimplementação **nativa** do programa Windows
"[XBOX 360-PC] PES 2016 ML-BL Editor.exe" (v1.2.0.0, por extream87),
cobrindo **apenas o caminho PC**. Roda no **Linux** (AppImage, sem instalar
nada) e no **Windows** (um `.exe` só, também sem instalar nada).

## A grande diferença em relação ao original
Os saves do PES 2016 (PC) são **criptografados**. O programa original **não**
fazia a criptografia no PC (`DecryptPC`/`EncryptPC` só copiavam o arquivo), por
isso só funcionava junto com um "crypter" separado — e mesmo assim os offsets
"PC" do original não batem com saves reais (caem em área zerada).

Esta versão **descriptografa ao abrir e re-criptografa ao salvar, sozinha**, e
usa os offsets corretos (validados no jogo, veja abaixo).

## Como usar

**Linux (AppImage)** — não precisa instalar nada (nem Python):
1. Dê permissão de execução (só na primeira vez):
   `chmod +x PES2016-MLBL-Editor-PC-x86_64.AppImage`
2. Rode: `./PES2016-MLBL-Editor-PC-x86_64.AppImage`
3. **Abrir arquivo…** e escolha o save do jogo (`BL00000000` ou `ML00000000`).
4. Edite os campos e clique em **Aplicar (Salvar)**.
   - Por padrão, grava **no próprio save aberto** e cria um backup automático
     `BL00000000.bak` (ou `ML00000000.bak`) na primeira vez.
   - Dá para escolher outro destino em **"Escolher destino…"**.

**Windows (.exe)** — também não precisa instalar nada:
1. Baixe `PES2016-MLBL-Editor-Windows-x64.exe` e dê dois cliques.
   (Windows x64. Se aparecer o aviso do SmartScreen, clique em *Mais
   informações → Executar assim mesmo*, porque o `.exe` não é assinado
   digitalmente.)
2. O resto é igual: **Abrir arquivo…**, editar, **Aplicar (Salvar)**.

**Nas duas versões** dá para abrir um save direto por linha de comando ou
arrastando o arquivo em cima do ícone (Windows):

```
PES2016-MLBL-Editor-Windows-x64.exe  BL00000000
./PES2016-MLBL-Editor-PC-x86_64.AppImage  BL00000000
```

Depois de salvar, o arquivo já está no formato que o jogo carrega — é só
deixar na pasta de save do jogo (com o nome original).

### ⚠️ Muito importante para o "Rumo ao Estrelato" (BL): são TRÊS lugares
No BAL o seu jogador é um **jogador criado**, e o jogo guarda as habilidades
dele em **três lugares diferentes**:

| # | Onde | Quem lê |
|---|---|---|
| 1 | `EDIT00000000` — banco de jogadores, registro de 112 bytes | o menu **Edit** do jogo (é o que aparecia primeiro) |
| 2 | `BL00000000` — registro de 228 bytes em **texto puro** ("cópia viva" na tabela de jogadores) | usada na gravação/consistência |
| 3 | `BL00000000` — **cópia comprimida no fim do arquivo** (o "snapshot da carreira": 22 blocos zlib de 256 KB) | é **deste** que a tela do modo **Rumo ao Estrelato** lê o jogador |

Na prática isso foi confirmado no seu save: deixamos os itens **1** e **2** com
99, o menu Edit passou a mostrar 99, mas **a carreira continuou mostrando os
valores antigos** — porque ela lê o item **3**, que ainda tinha 74/41/40/79…

Por isso, ao abrir um `BL00000000`, o editor:
- procura automaticamente um `EDIT00000000` **na mesma pasta** do save
  (aceita nomes como `EDIT00000000.original`);
- localiza também o **snapshot comprimido da carreira** dentro do BL;
- mostra os dois estados na aba **Habilidades**;
- ao aplicar, grava nas **três cópias de uma vez**.

Depois de salvar, copie **os dois arquivos** de volta para a pasta de save do
jogo, com os nomes originais (`BL00000000` e `EDIT00000000`).

> Se o EDIT não tiver o seu jogador, entre no jogo e salve o *Edit data*
> (menu **Edit → Salvar**) uma vez para que ele passe a existir no arquivo.

### O snapshot comprimido do `BL00000000`
O fim do `BL00000000` não é dado solto: é uma sequência de blocos de 256 KB
guardados com **zlib** (nível 9). Num save real são 22 blocos ≈ 5,25 MB depois
de descomprimidos. O formato do container foi recuperado e validado
reconstruindo um save real **byte a byte**:

```
... dados normais ...
u32LE  tamanho da seção | u32LE 0
u32BE  assinatura       | u32BE 0
u32BE  total descomprimido | u32BE total comprimido
repete:
    u32BE  tamanho descomprimido
    u32BE  tamanho comprimido
    u32BE  offset do próximo bloco (relativo à seção; 0 = último)
    fluxo zlib  (sempre começa com 78 DA)
```

O editor descomprime os blocos, altera o registro do jogador (o mesmo layout de
228 bytes do texto puro — o primeiro registro começa até "no meio", com o nome
em `+0x40`) e **recomprime tudo**, recalculando os tamanhos e os offsets. Se
você aplicar sem mudar nada, o arquivo sai **idêntico** ao original.

## O que dá para editar
- **BL (Rumo ao Estrelato / Become a Legend)**
  - Aba **Treino / Focus**
    - 9 atributos de treino (0–6): Shooting, Passing, Dribbling, Defence, Speed,
      Physical, Stamina, Skill Training, Position Training
    - Training (0–20), Focus (0–100) e botão **Max Stats**
  - Aba **Habilidades** (novidade)
    - As **17 habilidades** da tela do jogo: Ataque (habil. ofensiva), Controle
      de bola, Drible, Passe rasteiro, Passe pelo alto, Finalização, Chute
      colocado, Efeito, Cabeçada, Defesa (habil. defensiva), Desarme, Força do
      chute, Velocidade, Explosão, Equilíbrio, Impulsão, Resistência
    - As **5 habilidades de goleiro**
    - **Condição física (1–8)**, **Resistência a lesão (1–3)**, **Pior pé:
      frequência (1–4)**, **Pior pé: precisão (1–4)**, **Melhor pé** (direito/
      esquerdo), **Idade**, **Altura** e **Peso** — os valores são mostrados
      como o jogo mostra (por exemplo, a condição física vai de 1 a 8)
    - O jogador é localizado **pelo nome** (botão *Procurar*), não por offset
      fixo; o editor grava em **todas** as cópias do registro que encontrar:
      as do `BL00000000` (texto puro **e** o snapshot comprimido da carreira)
      e a do banco `EDIT00000000`
- **ML (Master League)**
  - Team Funds por presets (5 valores) + **Custom** (valor manual),
    com moeda € / $ / ¥ / £ / R$
  - Nome do Manager (até 15 caracteres)

> No BL, os campos de ML (dinheiro/manager) não se aplicam, e vice-versa.

## Offsets usados
Os offsets são **relativos ao bloco de dados** já descriptografado (não ao
arquivo). Foram confirmados carregando um save modificado no próprio jogo.

| Campo | Offset (bloco de dados) | Formato |
|---|---|---|
| Dinheiro ML | 7961553 | 3 bytes little-endian |
| Stats BAL (9) | 8815624 | 1 byte cada |
| Training | 8815633 | 1 byte |
| Focus | 7973083 | 1 byte |
| Nome do Manager | 1468712, 1469336, 7973152 | UTF-8, 30 bytes (limpos antes) |

Habilidades do BAL **não** usam offset fixo: o editor procura o registro de
228 bytes do jogador (nome em `+0x40`, altura em `+0x0C`, peso em `+0x0D`) e lê
os campos em nível de **bit**, no modelo `[7,7,7,7,4]` que reinicia a cada
4 bytes a partir do bit 128. O mesmo layout é usado dentro do snapshot
comprimido da carreira (aí o registro pode começar com base "negativa", ou
seja, o container começa já no meio do registro do seu jogador).

| Campo | Bit (relativo ao registro) | Largura |
|---|---|---|
| Ataque (habil. ofensiva) | 120 | 7 |
| Melhor pé (0 = direito, 1 = esquerdo) | 127 | 1 |
| Defesa / Goleiro | 128 / 135 | 7 / 7 |
| Drible / Controle de bola | 142 / 149 | 7 / 7 |
| Finalização / Passe rasteiro / Passe pelo alto / Cabeçada | 160 / 167 / 174 / 181 | 7 cada |
| Desarme / Chute colocado / Efeito | 192 / 199 / 206 | 7 cada |
| Habil. goleiro (4 campos) | 213, 224, 231, 238 | 7 cada |
| Condição física (valor do jogo − 1) | 220 | 3 |
| Velocidade | 245 | 7 |
| Equilíbrio / Força do chute / Explosão / Impulsão | 256 / 263 / 270 / 277 | 7 cada |
| Resistência | 288 | 7 |
| Idade | 320 | 6 |
| Pior pé: precisão (valor do jogo − 1) | 366 | 2 |
| Resistência a lesão (valor do jogo − 1) | 368 | 2 |
| Pior pé: frequência (valor do jogo − 1) | 370 | 2 |
| Altura / Peso | bytes `0x0C` / `0x0D` | 1 cada |

### Layout no `EDIT00000000` (banco de jogadores)

O registro do banco tem **112 bytes**, na grade `76 + 112 × i`, com o nome em
`+0x32` (46 bytes) e o "print name" em `+0x60`. Altura/peso ficam nos mesmos
bytes `+0x0C`/`+0x0D`. As habilidades usam um layout **diferente** do `BL`:

| Campo | Bit (relativo ao registro) | Largura |
|---|---|---|
| Ataque | 128 | 7 |
| Defesa / Goleiro | 135 / 142 | 7 / 7 |
| Drible | 149 | 7 |
| Finalização / Passe rasteiro / Passe pelo alto / Cabeçada | 160 / 167 / 174 / 181 | 7 cada |
| Efeito | 192 | 7 |
| Defesas / Reposição / Reflexos (goleiro) | 199 / 206 / 213 | 7 cada |
| Equilíbrio / Força do chute / Explosão / Impulsão | 224 / 231 / 238 / 245 | 7 cada |
| Controle de bola | 266 | 7 |
| Desarme | 273 | 7 |
| Cobertura (goleiro) | 280 | 7 |
| Chute colocado | 330 | 7 |
| Velocidade | 337 | 7 |
| Idade | 344 | 6 |
| Resistência | 352 | 7 |
| Condição física (valor do jogo − 1) | 188 | 3 |
| Resistência a lesão (valor do jogo − 1) | 220 | 2 |
| Pior pé: precisão (valor do jogo − 1) | 294 | 2 |
| Pior pé: frequência (valor do jogo − 1) | 296 | 2 |
| Melhor pé (0 = direito, 1 = esquerdo) | 364 | 1 |

Esse layout foi recuperado comparando o banco do `EDIT00000000` com os
jogadores reais que também aparecem no `BL00000000` e conferido com o jogador
do usuário: os valores lidos no EDIT batem **exatamente** com o que a tela do
jogo mostrou (incluindo goleiros).

As "características" (condição física, lesão, pior pé, melhor pé) seguem, no
EDIT, o **formato documentado pela wiki** do PES 2016 (registro de 112 bytes,
<https://implyingrigged.info/wiki/Pro_Evolution_Soccer_2016/Texport>). No `BL`
elas ficam em outras posições, que foram descobertas casando os dois arquivos:
para **54 de 54** jogadores reais os valores lidos no `BL` e no `EDIT` são
idênticos. No arquivo original do jogo, o seu jogador lê condição física **6**,
lesão **3**, pior pé **2 / 2** e pé **direito** — exatamente o que a tela do jogo
mostrava.

## Criptografia
Portada do projeto de domínio público
[`the4chancup/pesXdecrypter`](https://github.com/the4chancup/pesXdecrypter)
(MT19937 + cifra em fluxo). Validado:
- nossa descriptografia é **byte a byte idêntica** à do crypter de referência;
- `encrypt(decrypt(x)) == x` (ida e volta sem perdas);
- o jogo carrega normalmente o save re-criptografado.

## Observações
- O hash/checksum no cabeçalho do save **não é verificado pelo jogo**
  (confirmado na documentação do pesXdecrypter) — não precisa recalculá-lo.
- **Segurança:** ao gravar no mesmo arquivo, o app cria um `.bak` do original
  automaticamente. **Faça sempre uma cópia do save antes do primeiro teste.**
- **Como as duas versões são geradas:** as duas embutem o Python 3.12 + Tcl/Tk
  (no `.exe` via PyInstaller; na AppImage num AppDir com um Python próprio).
  Para refazer os arquivos: `empacotamento/build-exe-windows.ps1` (Windows) e
  `empacotamento/build-appimage.sh` (Linux) — cada um baixa o que precisa
  sozinho. Antes de publicar, as duas foram testadas fazendo o ciclo completo
  de abrir → editar → gravar nas **três cópias** (BL em texto puro, snapshot
  comprimido da carreira e banco do EDIT).
- Sem telemetria/phone-home.

## Novidades desta versão (18/10)
- **Versão para Windows**: um `.exe` único (`PES2016-MLBL-Editor-Windows-x64.exe`,
  x64, sem instalação), com ícone, informações de versão no arquivo e o mesmo
  comportamento da AppImage.
- **Pior pé: frequência** e **Pior pé: precisão** agora aparecem na aba
  Habilidades e são gravados nas três cópias (BL em texto puro, snapshot da
  carreira e banco do EDIT). **Confirmado no jogo** ✔
- **Condição física** e **Resistência a lesão** passaram a usar as posições
  corretas — e a ser mostradas como o jogo mostra (condição física de 1 a 8,
  lesão de 1 a 3, pior pé de 1 a 4). **Confirmado no jogo** ✔
- **Melhor pé** confirmado (antes estava em posição errada). **Confirmado no
  jogo** ✔
- Dá para abrir um save passando o arquivo por argumento ("abrir com…" no
  Windows, ou arrastar o arquivo sobre o programa).
- **Pronto para o GitHub**: scripts de build em `empacotamento/`
  (`build-appimage.sh` e `build-exe-windows.ps1`) e um workflow em
  `.github/workflows/build.yml` que gera o `.exe` e a AppImage sozinho a cada
  push — e, ao criar uma tag (ex.: `v1.2.0`), publica os dois numa release.

## Arquivos
| Plataforma | Arquivo |
|---|---|
| Linux (x86_64) | `PES2016-MLBL-Editor-PC-x86_64.AppImage` |
| Windows (x64) | `PES2016-MLBL-Editor-Windows-x64.exe` |

Os dois são gerados automaticamente pelo **GitHub Actions** (veja
`.github/workflows/build.yml`) a cada push e ficam anexados na página de
**Releases** quando você cria uma tag. Como o build recompila tudo (e o
AppImage guarda a data), o sha256 **muda de uma release para outra**; para
conferir um download:

```
sha256sum PES2016-MLBL-Editor-Windows-x64.exe
```

Conferidos na release **v1.2.0** (build do CI):

| Arquivo | sha256 |
|---|---|
| `PES2016-MLBL-Editor-PC-x86_64.AppImage` | `b39cff5646105e9318286afbd13d8e381b660cc1329ee658b96c4d1d8be89c9b` |
| `PES2016-MLBL-Editor-Windows-x64.exe` | `ad4e3e822f4ccd59e10acdee01c385862d4f7a8fd26a2210892a22abaf739c5e` |

Como as duas versões vieram do **mesmo código**, qualquer coisa que você editar
numa aparece igual na outra.

Baseado em engenharia reversa estática (REA + ILSpy) e validação in-game.
