# Mapeamento do "Pior pé" (e das outras características) — RESOLVIDO

Status: **resolvido em 18/10**. O editor já grava os dois campos (frequência e
precisão) nas três cópias do jogador. Esta nota fica como registro de *como* as
posições foram descobertas. Pode apagar quando quiser.

## Como foi resolvido

1. A wiki **implyingrigged.info** documenta o formato do registro de jogador do
   PES 2016 (EDIT / TEXPORT), com **112 bytes** — bate 100% com o nosso EDIT
   (nome em `0x32`, altura `0x0C`, peso `0x0D`).
   <https://implyingrigged.info/wiki/Pro_Evolution_Soccer_2016/Texport>

2. Com o layout do EDIT documentado, lemos as características de **54 jogadores
   reais** (casando os jogadores do `BL00000000` com o `EDIT00000000` pelo ID do
   jogador, que fica em `0x38`).

3. Varremos o registro do **BL (228 bytes)** procurando, para cada uma dessas
   características, uma posição de bits em que **os 54 jogadores** batessem com
   o valor do EDIT. Cada campo deu **uma única posição**:

| Campo | BL (228 B) | EDIT (112 B) |
|---|---|---|
| Pior pé: precisão | bit **366** (2 bits) | bit 294 (2 bits) |
| Resistência a lesão | bit **368** (2 bits) | bit 220 (2 bits) |
| Pior pé: frequência | bit **370** (2 bits) | bit 296 (2 bits) |
| Condição física (form) | bit **220** (3 bits) | bit 188 (3 bits) |
| Melhor pé | bit **127** (1 bit) | bit 364 (1 bit) |

   Os valores são gravados **um a menos** do que o jogo mostra (condição física
   de 1 a 8, lesão de 1 a 3, pior pé de 1 a 4); o editor esconde isso mostrando
   o valor do jogo.

4. Conferência independente: no **arquivo original do jogo** o seu jogador lê
   **condição física 6, lesão 3, pior pé 2/2 e pé direito** — exatamente o que a
   captura da tela do jogo mostrava. E o C. Wilson lê 6/2/2/2/direito, igual ao
   pesdb.

4. **Confirmado no jogo (18/10)**: com o par de teste, a tela do jogo mostrou
   condição física 8, lesão 3, **melhor pé esquerdo** e **pior pé frequência 4 /
   precisão 2** — exatamente o que o editor gravou. Os rótulos
   frequência/precisão também estão na ordem certa (não estão trocados).

### Antes (errado) x depois (certo)

| Campo | Offset antigo no BL | Offset novo |
|---|---|---|
| Condição física | 188 | **220** |
| Resistência a lesão | 220 | **368** |
| Melhor pé | 345 | **127** |
| Pior pé (precisão) | não existia | **366** |
| Pior pé (frequência) | não existia | **370** |

| Campo | Offset antigo no EDIT | Offset novo |
|---|---|---|
| Condição física | 156 | **188** |
| Resistência a lesão | 188 | **220** |
| Melhor pé | 303 | **364** |
| Pior pé (precisão) | não existia | **294** |
| Pior pé (frequência) | não existia | **296** |

> Efeito colateral do editor antigo: ele escrevia "resistência a lesão" em cima
> dos bits da condição física (bits 220–221 no BL). No seu save atual a condição
> física do WARLISON ficou em 8 por causa disso — basta abrir o editor e colocar
> o valor que você quer (o original era 6).

## Tabela da wiki (registro do EDIT de 112 bytes) — referência

| Campo | Offset | Bit | Tam | Obs |
|---|---|---|---|---|
| Form (Condição física) | 0x17:4 | 188 | 3 | valor do jogo − 1 (0–7), padrão 3 |
| Flag "Edited/Created player" | 0x17:7 | 191 | 1 | 1 = editado/criado |
| Injury Resistance | 0x1B:4 | 220 | 2 | valor do jogo − 1 (0–2), padrão 1 |
| Unknown B (padding) | 0x1B:6 | 222 | 1 | |
| Flag "Basic Settings" | 0x1B:7 | 223 | 1 | |
| Flag "Registered Position" | 0x1F:7 | 255 | 1 | |
| Flag "Playable Position" | 0x23:7 | 287 | 1 | |
| **Weak Foot Accuracy** | 0x24:6 | **294** | **2** | **valor do jogo − 1 (0–3), padrão 1** |
| **Weak Foot Usage** | 0x25:0 | **296** | **2** | **valor do jogo − 1 (0–3), padrão 1** |
| Flag "Ability" | 0x2B:6 | 350 | 1 | |
| Flag "Playing Styles" | 0x2C:7 | 359 | 1 | |
| Flag "COM Playing Styles" | 0x2D:0 | 360 | 1 | |
| Flag "Motion" | 0x2D:1 | 361 | 1 | |
| Base Copy | 0x2D:3 | 363 | 1 | |
| **Stronger Foot** | 0x2D:4 | **364** | **1** | **0 = direito, 1 = esquerdo** |
| COM Playing Style (bitmask 7) | 0x2D:5 | 365 | 7 | |
| Player Skills (bitmask 28) | 0x2E:4 | 372 | 28 | |
| Player Name | 0x32 | 400 | 46 B | |
| Print Name | 0x60 | 768 | 16 B | |

## Observações da investigação

- O registro do **EDIT** e o do **BL (228 B)** têm ordens de campos **diferentes**
  (ex.: ball winning = bit 192 no BL, 273 no EDIT).
- **O pesdb NÃO serve de referência** para as habilidades: os valores do save do
  usuário diferem dos do pesdb (data pack diferente). Para as características
  (condição física, lesão, pior pé, pé) os valores batem.
- O registro do jogador tem o **ID do jogador** em `0x38` (u32 LE, duplicado em
  `0x3C`) — bate com os IDs do pesdb (ex.: A. BORUC = 9515, S. COOK = 101736).
- Tabela de jogadores no BL em texto puro: base **2.611.932**, passo **228**;
  WARLISON = índice 30 (base 2.618.772). O snapshot comprimido tem o registro do
  WARLISON em base **−12** (offset 9.088.400 − 12).
- O teste de regressão `codigo-fonte-pc/test_core.py` (função
  `test_characteristics`) refaz essa conferência BL × EDIT a cada execução.
