# Treinador de memória (PES 2016 no Linux/Bottles)

Painel separado que **lê e escreve na memória do jogo em execução** — diferente
do editor de save, que mexe no arquivo. Serve para mudanças que precisam valer
**na hora**, sem fechar o jogo.

## O que já funciona

- **Curar lesão** do jogador do Rumo ao Estrelato (byte `+0x0E = 0`);
- Ler ao vivo: ID, altura, peso, **lesão ativa** e **condição física**;
- **Atributos ao vivo** (janela **Atributos...**): os 31 campos do registro,
  como no editor de save — habilidades, goleiro, físico (condição, resistência
  a lesão, pior pé, idade, altura, peso) e o botão **Max habilidades**
  (preenche só os campos que vão até 99, sem gravar ainda);
- **Reconectar** depois de reiniciar o jogo (os endereços mudam a cada sessão —
  o painel procura o registro pelo **nome + layout**, não por endereço fixo);
- Atalhos **F9** (curar) e **F10** (reconectar), inclusive com a janela do jogo
  em foco (captura global via X11; experimental em tela cheia).

## Como usar

1. Abra o PES 2016 pelo Bottles e **carregue a carreira** (Rumo ao Estrelato);
2. Rode:

   ```bash
   python3 treinador-pc/treinador.py
   ```

3. Confira o nome no campo **Jogador** (padrão `WARLISON`) e clique em
   **Conectar ao jogo** (a varredura leva de 4 a 30 s);
4. Use **Curar lesão (0)** ou **Atributos...** para editar os campos.

> Depois de curar ou aplicar atributos, **saia e entre de novo** na tela do
> jogo (ex.: Escalação/Elenco) para ela reler os valores — a tela é montada na
> entrada.

### Atributos ao vivo

O botão **Atributos...** abre uma janela com os mesmos grupos do editor de save
(Habilidades, Goleiro, Físico/outros). Ao clicar em **Aplicar**, o painel:

1. lê cada cópia do registro na memória;
2. aplica só as mudanças e **compara byte a byte** com o que estava lá;
3. grava **apenas os bytes que mudaram**, nas cópias da carreira.

Esse diff evita sobrescrever, sem querer, algo que o jogo tenha atualizado entre
a leitura e a gravação. O log mostra quantos bytes foram alterados (0 = nada
mudou).

> Os atributos são gravados no **registro da carreira** (na memória). O banco do
> EDIT não fica carregado na memória enquanto você não abre o menu Edit, então o
> painel não mexe nele.

## Como ele acha o jogador

1. Localiza o processo cujo `cmdline` contém `PES2016.exe` (maior RSS);
2. Varre só as regiões legíveis de `/proc/<pid>/mem` procurando o nome em ASCII;
3. Para cada ocorrência, testa o layout do registro de 228 bytes:
   altura `+0x0C`, peso `+0x0D`, lesão `+0x0E`, ID `+0x38`, nome `+0x40`;
4. Agrupa pelo **ID**: fica com o grupo de ID não-zero mais comum (na prática,
   as 3 cópias da carreira).

O layout na RAM é **idêntico** ao do save — confirmado comparando os 228 bytes
do registro com o arquivo (0 diferenças).

## Segurança

- Só escreve quando você clica (ou aperta F9);
- O botão **Lesionar (44)** é só para teste e pede confirmação;
- **Não salve o jogo** enquanto estiver testando uma lesão;
- Faça backup do save antes (o painel não toca no arquivo);
- Fechar o painel não altera nada no jogo; a memória volta ao normal quando o
  jogo fecha.

## Limitações

- **Linux** (usa `/proc/<pid>/mem`); não roda no Windows;
- Precisa do jogo **aberto e na carreira**;
- Se o kernel bloquear a leitura (`ptrace_scope=1` + Yama), rode o painel com
  `sudo` ou libere temporariamente:
  `sudo sysctl -w kernel.yama.ptrace_scope=0`;
- Atalhos globais podem não funcionar em jogos que capturam o teclado por
  XInput2/raw input (os botões continuam funcionando);
- Os endereços mudam a cada execução — por isso o **Reconectar**.

## Descoberta (engenharia reversa)

O byte de lesão foi encontrado comparando a mesma carreira **antes e depois**
de o jogador se recuperar: `+0x0E` foi de `44` (lesionado) para `0` (saudável),
tanto no registro em texto puro quanto no snapshot comprimido do save.

Teste de escrita validado no jogo: gravar `44` nas 3 cópias → a tela de
Escalação mostra o jogador **lesionado**; gravar `0` → volta ao normal. O save
em disco não foi alterado durante os testes (SHA-256 conferido).

A escrita de **atributos** também foi validada ao vivo: mudando o `attack`
(Ataque/Habil. ofensiva) de `99` para `40`, a tela de dados do jogador mostrou
`40` imediatamente; o valor foi revertido em seguida. O painel grava só os
bytes que mudam, nas cópias da carreira. Alguns indicadores, como a setinha de
**Condição** da tela de pré-jogo, só são recalculados quando o dia avança ou a
partida começa.
