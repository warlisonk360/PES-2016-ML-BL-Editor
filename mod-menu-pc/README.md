# Mod menu injetado (PC) — Etapas 1 e 2

Menu desenhado **por cima do jogo** (ImGui via Direct3D 9), aberto com
**Insert**. Roda dentro do `PES2016.exe` como um **proxy `d3d9.dll`**.

> Estado atual: **Etapa 2** — além de provar a injeção, o menu lê e grava na
> memória do próprio jogo (cura de lesão e dinheiro da Liga Master), sempre com
> ação explícita e opção de reverter. O save em disco não é tocado.

## Como funciona

```
PES2016.exe
   └─ importa d3d9.dll  →  <jogo>/d3d9.dll   (este proxy)
                              └─ LoadLibrary("d3d9_real.dll")  (DXVK renomeado)
                              └─ hook em Direct3DCreate9
                                   └─ hook em IDirect3D9::CreateDevice
                                        └─ hook em IDirect3DDevice9::EndScene
                                             └─ desenha o ImGui
```

- O jogo é **32-bit** (`PE32 i386`) e usa **DXVK** (D3D9 sobre Vulkan).
- O proxy repassa `Direct3DCreate9` e os quatro `D3DPERF_*` que o jogo importa.
- Os hooks são instalados **no lugar** (patch do slot com `VirtualProtect`), sem
  trocar o ponteiro da vtable — trocar o ponteiro quebra o DXVK.
- O menu é desenhado **antes** da `EndScene` original.
- `Insert` abre/fecha; `Esc` fecha; **setas/Tab + Enter** navegam no menu (o
  jogo prende o cursor no X11, então mouse absoluto não funciona).
- `modmenu.log` (ao lado da DLL) registra o que aconteceu.

## O que o menu faz

| Seção | Ação |
|---|---|
| **Jogador** | digite o nome exato, **Procurar jogador** localiza o registro na memória e mostra as cópias, o ID e a lesão atual |
| | **Curar lesão** grava `0`; **Lesionar (teste)** grava `44`; **Reverter lesão** volta ao valor lido |
| **Dinheiro da Liga Master** | digite o saldo que aparece em **Negociação → Fundos do time** e aperte Enter (ou **Procurar saldo**); depois digite o novo saldo e aperte Enter (ou **Aplicar**); **Reverter** devolve o valor original |

A busca usa a mesma lógica do
[treinador externo](../treinador-pc/treinador.py): procura o nome no registro de
228 bytes (`0xE4`), valida altura/peso e agrupa pelo ID mais comum. A varredura
leva ~1 s e bloqueia o frame só nesse instante.

O dinheiro da ML fica na memória como `int32` = saldo exibido ÷ 100
(`$27.486.800` → `274868`). Como esse valor também aparece por coincidência em
buffers de áudio e de pilha, a busca:

1. ignora regiões de DLL/EXE (`MEM_IMAGE`), o próprio módulo e endereços
   desalinhados;
2. relê os candidatos ~0,5 s depois e **descarta os que já mudaram** — só sobra o
   campo estável da carreira;
3. antes de gravar, confere se o valor ainda é o mesmo da busca; se mudou (outra
   tela, carregamento), **não grava** e registra no log.

## Compilar

Requisitos (sem sudo): Zig 0.13+ e o fonte do ImGui.

```bash
# uma vez
mkdir -p /tmp/opencode/toolchain
curl -L -o /tmp/opencode/toolchain/zig.tar.xz \
  https://ziglang.org/download/0.13.0/zig-linux-x86_64-0.13.0.tar.xz
tar -xf /tmp/opencode/toolchain/zig.tar.xz -C /tmp/opencode/toolchain
mv /tmp/opencode/toolchain/zig-linux-x86_64-0.13.0 /tmp/opencode/toolchain/zig

git clone --depth 1 https://github.com/ocornut/imgui.git /tmp/opencode/vendor/imgui

# compilar
cd mod-menu-pc
./build.sh
```

Saída: `build/d3d9.dll` (~1,2 MB).

## Instalar

1. Feche o jogo e o Bottles.
2. Rode `./install.sh` (copia `d3d9.dll` + `d3d9_real.dll` para a pasta do jogo).
3. Na garrafa **Games**, em **DLL Overrides**, adicione `d3d9` = `n,b`
   (nativo primeiro). Sem isso o Wine carrega a d3d9 embutida e ignora o proxy.
4. Abra o jogo. Ao entrar em qualquer parte 3D, aperte **Insert**.

O `install.sh` usa por padrão a garrafa `Games` do Bottles Flatpak. Para outro
caminho:

```bash
GAME_DIR="/caminho/Pro Evolution Soccer 2016" ./install.sh
```

## Desinstalar

```bash
./uninstall.sh
```

Remove `d3d9.dll`, `d3d9_real.dll` e `modmenu.log` da pasta do jogo. O override
`d3d9=n,b` pode ficar (não atrapalha).

## Diagnóstico

`modmenu.log`, na pasta do jogo, deve conter algo como:

```
=== d3d9 proxy (mod menu) anexado ao jogo (safe_mode=0) ===
Direct3DCreate9(32) chamado
LoadLibrary(C:\Games\...\d3d9_real.dll) = 78A30000
Direct3DCreate9 -> 02DD3DC8
vtable ptr = 790CE000
vtable do IDirect3D9 patchada in-place (CreateDevice idx 16 ok, CreateDeviceEx idx 20 ok)
hook_CreateDevice entrou (orig=78A32980 this=02E92760)
CreateDevice hr=0x00000000 hwnd=0005006C dev=042A6440
EndScene hookado in-place (idx 42, orig=78A53DA0)
WndProc subclassado (antigo=78AA33C0 novo=79ED1910)
ImGui inicializado (hwnd=0005006C dev=042A6440)
menu ABERTO (Insert)
busca de 'WARLISON': 16 ocorrencias
registros validos: 2 (0.9 s)
jogador escolhido: ID=00100000 copias=2 lesao=0
lesao copia 0: 0 -> 44 (0xf9533a9a)
lesao copia 1: 0 -> 44 (0xfc5018ca)
lesao copia 0 revertida para 0 (0xf9533a9a)
lesao copia 1 revertida para 0 (0xfc5018ca)
dinheiro: alvo=274868 achados=2 (0.7 s)
dinheiro 0x0af1f92c: descartado (valor instavel)
dinheiro: 1 candidato(s) estavel(is) de 2
dinheiro 0xfcf3c0b8: 274868 -> 999999
dinheiro 0xfcf3c0b8 revertido para 274868
```

Modo de segurança: crie um arquivo vazio `modmenu_nohook.txt` na pasta do jogo
para o proxy carregar mas **não** instalar nenhum hook. Serve para confirmar que
o problema é o hook e não o proxy:

```
=== d3d9 proxy (mod menu) anexado ao jogo (safe_mode=1) ===
Direct3DCreate9(32) chamado
MODO SEGURO: vtable nao foi hookada
```

Se o jogo não abrir ou a tela ficar preta, rode `./uninstall.sh` — o jogo volta
ao normal na próxima execução.

## Notas técnicas

- **Exports sem `@N`**: o linker do Zig decora funções `__stdcall`
  (`Direct3DCreate9@4`), mas o jogo importa o nome puro. O
  [`tools/fix_exports.py`](tools/fix_exports.py) reescreve a tabela de nomes do
  PE em ordem alfabética após o link (o loader faz busca binária).
- **Índices de vtable**: `IDirect3D9::CreateDevice` = 16 e
  `IDirect3D9Ex::CreateDeviceEx` = 20; `IDirect3DDevice9::EndScene` = 42.
- **Hook in-place, não cópia da vtable**: o DXVK devolve objetos cujo
  funcionamento depende da vtable original. Substituir o ponteiro da vtable
  (mesmo com todos os 22/134 slots copiados) fazia o jogo saltar para memória
  inválida. A solução é proteger a página com `VirtualProtect` e trocar só o
  slot desejado, preservando o ponteiro da vtable e o tamanho real dela.
- **`ImGui::Render()`**: no backend DX9 é preciso chamar `ImGui::Render()`
  (e não `ImGui::EndFrame()`) antes de `ImGui_ImplDX9_RenderDrawData`, senão os
  dados de desenho não são montados.
- **Mouse**: o jogo mantém o ponteiro preso/centralizado no X11 (grab), então
  a posição absoluta do cursor não chega ao ImGui. O menu usa navegação por
  teclado (`NavEnableKeyboard`): setas, Enter e Esc.
- **Subclasse de janela**: necessária para o ImGui receber teclas
  (`ImGui_ImplWin32_WndProcHandler`). Com o menu aberto, o teclado é **modal**:
  `WM_KEY*`/`WM_CHAR` não chegam ao jogo (nem para navegar nem para digitar).
- **Campos numéricos**: `InputInt` vira três itens de foco (campo + `+`/`-`),
  o que atrapalha a navegação por teclado; por isso o saldo usa `InputText` com
  filtro decimal, e **Enter no campo** já dispara buscar/aplicar.
- **`Direct3DCreate9` é chamado 3 vezes** pelo jogo; o patch do slot é
  idempotente (se o slot já aponta para o hook, nada é feito).
- **Segurança**: nenhuma gravação acontece sem apertar um botão. Toda escrita é
  registrada no log com o valor antigo, e as duas seções têm **Reverter**. O
  save em disco não é tocado; se o jogo for encerrado sem salvar, nada muda.

## Teste automático da busca

Crie um arquivo vazio `modmenu_autoscan.txt` na pasta do jogo: ao abrir o menu,
ele procura o nome que estiver no campo **Jogador** e registra o resultado no
`modmenu.log` (útil para conferir se a memória da carreira já carregou):

```
menu ABERTO (Insert)
autoscan: procurando 'WARLISON'
busca de 'WARLISON': 19 ocorrencias
registros validos: 2 (1.0 s)
jogador escolhido: ID=00100000 copias=2 lesao=0
```
