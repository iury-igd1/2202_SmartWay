# Firmware da pulseira

O arquivo [`codigo-oficial/codigo-oficial.ino`](codigo-oficial/codigo-oficial.ino) é o programa do ESP32. Ele transforma o botão em três gestos, grava voz pelo microfone I2S, envia comandos ao servidor e responde com áudio, vibração e LED.

Volte à [visão geral do SmartWay](../README.md) ou consulte o [guia detalhado do código](../docs/GUIA_DO_CODIGO.md).

## O que acontece ao ligar

`setup()` configura os pinos, desliga o Bluetooth, inicia o DFPlayer Mini e o microfone, conecta ao Wi-Fi e toca a saudação. `loop()` lê o botão, captura áudio quando necessário e consulta o servidor a cada **2 segundos** durante o acompanhamento. Se o DFPlayer não inicializa, o código permanece aguardando.

| Gesto | Tempo no código | Resultado |
| --- | --- | --- |
| **Clique único** | Confirmado após 750 ms sem segundo clique | Lê a bateria e chama `POST /iniciar_viagem`. |
| **Pressão longa** | Começa após 500 ms; termina ao soltar | Grava até 4 s e envia WAV a `POST /comando_de_voz`. |
| **Clique duplo** | Segundo clique dentro de 750 ms | Chama `GET /cancelar_viagem`. |

O debounce do botão é de 50 ms. Se a tensão medida estiver em **3,3 V ou menos**, a faixa 15 avisa sobre a bateria e o pedido de viagem continua.

## Ligações e retornos

| Recurso | GPIO | Uso |
| --- | --- | --- |
| Bateria | 0 | Leitura ADC; o firmware multiplica por 2 a tensão do divisor resistivo da placa. |
| Motor de vibração | 2 | Pulsos de confirmação e alerta. |
| Botão | 3 | Entrada com `INPUT_PULLUP`. |
| Microfone I2S | SCK 4, WS 5, SD 6 | Captura mono em 16 kHz e 16 bits. |
| DFPlayer Mini | RX 8, TX 9 | Reprodução dos avisos gravados no cartão SD. |
| LED | 10 | Aceso enquanto a voz é gravada. |

O [layout da PCB](../hardware/README.md) contém essas mesmas conexões. O DFPlayer recebe os números **1 a 15** definidos no início do `.ino`; os arquivos de áudio correspondentes não estão no repositório.

| Faixas | Aviso |
| --- | --- |
| 1–4 | Saudação, pedido de origem, pedido de destino e início do monitoramento. |
| 5–9 | Aproximação do ônibus, embarque, destino próximo e chegada. |
| 10–14 | Cancelamento, erros e pedidos para repetir origem ou destino. |
| 15 | Bateria baixa. |

O firmware emite um alerta antecipado quando o ETA entra em **3 a 7 minutos** e outro em **2 minutos ou menos**. Cada um é disparado uma vez para a origem e uma vez para o destino. A relação exata entre estados, faixas e padrões de vibração está no [guia do código](../docs/GUIA_DO_CODIGO.md).

## Dependências e configuração

Abra `codigo-oficial/codigo-oficial.ino` no Arduino IDE com suporte à placa ESP32 e as bibliotecas **ArduinoJson** e **DFRobotDFPlayerMini** instaladas.
