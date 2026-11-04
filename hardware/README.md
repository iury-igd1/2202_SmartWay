# Hardware SmartWay

Esta pasta contém o layout da placa, um esquemático corrigido para corresponder a ele e as duas malhas do case da pulseira. O arquivo `.brd` é o desenho físico da PCB; o `.sch` contém símbolos e conexões elétricas. Não há arquivos Gerber nem lista de materiais separada nesta pasta.

| Arquivo | Conteúdo |
| --- | --- |
| [`pulseira2202.brd`](pulseira2202.brd) | Layout de PCB em XML do Autodesk EAGLE 9.7.0. |
| [`pulseira2202.sch`](pulseira2202.sch) | Esquemático EAGLE 9.7.0 corrigido a partir de `Pulseira_v2.sch` para corresponder à placa. |
| [`pulseira_2202_base.stl`](pulseira_2202_base.stl) | Malha binária da peça chamada base. |
| [`pulseira_2202_topo.stl`](pulseira_2202_topo.stl) | Malha binária da peça chamada topo. |

## Placa de circuito

O contorno na camada `Dimension` é um retângulo de **51,74 × 44,762 mm**. O arquivo contém **17 elementos** entre módulos, componentes e conectores. Há trilhas nas camadas `Top` e `Bottom`, com vias entre elas. Não encontrei fios na camada `Unrouted` no XML, mas isso **não substitui** a verificação elétrica e de regras de projeto (DRC) no EAGLE.

| Parte do layout | Elementos identificados | Função indicada pelas conexões |
| --- | --- | --- |
| Processamento | `U$4` — ESP32 C3 SuperMini | Executa o firmware e concentra os sinais. |
| Entrada de voz | `U$2` — INMP441 circular | Microfone I2S ligado aos GPIOs 4, 5 e 6. |
| Saída de áudio | `U$1` — DFPlayer; `JACKP2` — conector de 3 pinos | Reproduz áudio e leva `SPK1`/`SPK2` ao conector. |
| Interação | `S1` — botão; `LED1` — LED de 3 mm | Entrada pelo GPIO 3 e indicação pelo GPIO 10. |
| Vibração | `VIBRA` — conector de 2 pinos; `Q2` — BC847; `D1` — diodo; `R7` — 1 kΩ | Acionamento do motor pelo GPIO 2. |
| Energia | `IC1` — regulador HT7833; `C1` — 10 µF; conectores `B-/OUT-1` e `OUT+/B+1` | Entrada de alimentação e linha de 3,3 V. |
| Medição da bateria | `R1` e `R2` — 100 kΩ cada | Divisor entre a entrada de alimentação e o terra, com ponto central no GPIO 0. |
| LED | `R3` — 100 kΩ | Resistor em série no caminho do LED. |

### Correspondência com o firmware

| Sinal no firmware | Conexão encontrada no `.brd` |
| --- | --- |
| `BATTERY_ADC_PIN` 0 | GPIO 0 ao ponto central de `R1`/`R2`. |
| `VIBRATION_PIN` 2 | GPIO 2 a `R7`/`Q2`, que comandam o conector `VIBRA`. |
| `BUTTON_PIN` 3 | GPIO 3 a `S1`. |
| `I2S_SCK_PIN` 4 | GPIO 4 ao `SCK` do microfone. |
| `I2S_WS_PIN` 5 | GPIO 5 ao `WS` do microfone. |
| `I2S_SD_PIN` 6 | GPIO 6 ao `SD` do microfone. |
| `DFPLAYER_RX_PIN` 8 | GPIO 8 ao `TX` do DFPlayer. |
| `DFPLAYER_TX_PIN` 9 | GPIO 9 ao `RX` do DFPlayer. |
| `LED_PIN` 10 | GPIO 10 a `R3` e ao LED. |

Os dois resistores de 100 kΩ formam um divisor de tensão por 2. Isso explica a multiplicação por 2 em `checkBattery()` no [firmware](../firmware/codigo-oficial/codigo-oficial.ino). A correspondência de pinos foi conferida pelos contatos das redes no arquivo `.brd`; ela não comprova, por si só, a operação elétrica da placa montada.

### Comparação com os esquemáticos candidatos

Foram examinados `Pulseira_v2.sch` e `Pulseira_v2.fsch`, recebidos separadamente da pasta do repositório. O `.sch` é um esquemático EAGLE 9.7.0. O `.fsch` é um pacote de documento que contém outro `.sch` EAGLE. **Os dois têm a mesma lista de 26 partes e as mesmas 18 redes com 61 referências de pino**; portanto, representam a mesma configuração elétrica para esta comparação. Nove partes são símbolos de terra, sem componente físico na placa.

**Nenhum dos dois esquemáticos originais corresponde exatamente a `pulseira2202.brd`.** Muitas conexões coincidem, incluindo microfone I2S, serial do DFPlayer, alto-falante e divisor de bateria, mas há diferenças funcionais:

| Função | Nos dois esquemáticos | No `.brd` |
| --- | --- | --- |
| Vibração (`R7` → transistor) | GPIO 3 | GPIO 2 |
| Botão `S1` | GPIO 2, com `R8` de 10 kΩ ligado à alimentação | GPIO 3; `R8` ausente |
| LED | GPIO 7 ligado ao LED | GPIO 10 ligado ao LED por `R3` de 100 kΩ |
| Alimentação do DFPlayer | `VCC` ligado à entrada antes do regulador (`N$14`) | `VCC` ligado à linha regulada `VDD` |

O `.brd` coincide com os pinos declarados no firmware atual para botão, vibração e LED. Os esquemáticos candidatos originais permaneceram fora do repositório. Sem o projeto de origem sincronizado, não é possível afirmar qual revisão foi criada primeiro.

### Esquemático corrigido

[`pulseira2202.sch`](pulseira2202.sch) foi criado como uma **cópia nova** do `.sch` original, sem alterar os arquivos recebidos em Downloads. O resistor `R8` de 10 kΩ passou a ser `R3` de 100 kΩ e foi colocado em série com o LED. As redes de botão, vibração e LED foram ligadas aos GPIOs do `.brd`; a alimentação do DFPlayer passou para a linha regulada `VDD`. O segundo pino de terra do DFPlayer e o pino `5V` não utilizado do ESP32 também foram representados conforme a placa. Trechos separados da mesma rede receberam etiquetas com o mesmo nome para manter o desenho legível.

Uma comparação automática do XML confirmou **17 componentes físicos com os mesmos nomes e encapsulamentos, 18 redes com os mesmos nomes e todos os pares componente/pad idênticos aos do `.brd`**. Também foi verificado que cada referência de pino e etiqueta encosta no extremo de um fio do esquema. Essa conferência cobre a correspondência lógica dos arquivos. Como o par corrigido não foi aberto no EAGLE ou Fusion Electronics, não há validação de ERC/DRC registrada para ele.

## Case da pulseira

Os STL são binários e não registram unidade de medida. **Se o modelo foi exportado em milímetros**, as caixas delimitadoras são:

| Peça | Dimensões externas da malha (X × Y × Z) | Triângulos |
| --- | --- | ---: |
| Base | 61,428 × 66 × 12,458 mm | 1.650 |
| Topo | 58,940 × 66 × 26,000 mm | 532 |

As peças estão em posições X separadas nos arquivos, como em uma disposição lado a lado para modelagem ou impressão. Essas coordenadas **não representam a posição de montagem** entre base e topo.

Na análise das malhas, todas as arestas aparecem em duas faces e não há triângulos de área zero. O topo é uma única malha conectada. A base tem **três componentes desconectados por vértices**: o corpo principal e duas pequenas geometrias laterais. A análise do arquivo não determina se essas partes foram unidas no fatiamento original nem as tolerâncias de encaixe do case já produzido.

## Limites do registro

Esta documentação descreve os arquivos disponíveis e a comparação lógica entre esquema e placa. A placa e o case já foram produzidos no projeto original; não foi feita aqui uma nova inspeção física, abertura no EAGLE/Fusion ou reprodução da impressão. O `.sch` corrigido é uma reconstrução documental a partir do `.brd`, não o arquivo histórico usado na fabricação.
