# Placa e case da pulseira

Esta pasta registra o hardware do SmartWay: o layout de uma PCB já produzida, um esquemático reconstruído para documentá-la e as duas malhas STL da caixa. O [firmware](../firmware/README.md) usa os pinos descritos abaixo.

Volte à [visão geral do SmartWay](../README.md).

## Arquivos disponíveis

| Arquivo | Conteúdo |
| --- | --- |
| [`pulseira2202.brd`](pulseira2202.brd) | Layout da PCB em XML do Autodesk EAGLE 9.7.0. |
| [`pulseira2202.sch`](pulseira2202.sch) | Esquemático EAGLE corrigido depois, a partir do layout. |
| [`pulseira_2202_base.stl`](pulseira_2202_base.stl) | Peça chamada base do case. |
| [`pulseira_2202_topo.stl`](pulseira_2202_topo.stl) | Peça chamada topo do case. |

O `.brd` é o desenho físico da placa; o `.sch` representa símbolos e ligações elétricas. Não há Gerbers ou lista de materiais separada nos arquivos recebidos.

## O que a placa reúne

O contorno da PCB mede **51,74 × 44,762 mm**. O layout contém **17 componentes e conectores**, trilhas nas camadas superior e inferior e vias entre elas.

| Conjunto | Elementos encontrados |
| --- | --- |
| Controle e voz | ESP32 C3 SuperMini (`U$4`) e microfone INMP441 (`U$2`). |
| Áudio | DFPlayer (`U$1`) e conector `JACKP2` para saída de alto-falante. |
| Interação | Botão `S1` e LED `LED1`. |
| Vibração | Conector `VIBRA`, transistor `Q2`, diodo `D1` e resistor `R7` de 1 kΩ. |
| Alimentação e bateria | Regulador HT7833 (`IC1`), capacitor `C1`, conectores de alimentação e divisor `R1`/`R2` de 100 kΩ cada. |

Os sinais do layout correspondem aos GPIOs usados no firmware: **0** para bateria, **2** para vibração, **3** para botão, **4/5/6** para I2S, **8/9** para DFPlayer e **10** para LED. O divisor de dois resistores iguais explica o fator 2 aplicado à tensão lida em `checkBattery()`.

## As duas peças do case

Os STL são binários e não registram unidade. **Se foram exportados em milímetros**, suas caixas delimitadoras são:

| Peça | X × Y × Z | Triângulos |
| --- | --- | ---: |
| Base | 61,428 × 66 × 12,458 mm | 1.650 |
| Topo | 58,940 × 66 × 26,000 mm | 532 |
