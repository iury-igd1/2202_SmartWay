# Guia do código SmartWay

Este guia descreve a implementação recebida. Os nomes abaixo correspondem aos arquivos da estrutura principal do repositório.

## Relação entre as partes

`firmware/codigo-oficial/codigo-oficial.ino` conversa com `software/servidor.py` por HTTP. `software/simulador.html` é outro cliente da mesma API: ele publica as posições dos ônibus e lê a viagem atual para atualizar o mapa. Servidor e simulador leem `rotas_data.json` e `paradas_data.json`; só o simulador lê `icones_data.json`.

O [guia de hardware](../hardware/README.md) descreve o layout EAGLE da PCB, a correspondência dos pinos com o firmware e as duas malhas STL do case.

Os JSONs precisam permanecer ao lado do servidor e do HTML porque os caminhos estão escritos como relativos. O servidor não serve o HTML: ele usa a porta 5000 para a API; um servidor HTTP estático separado pode servir `software/` na porta 8000.

## Firmware da pulseira

### Hardware e configuração

| Componente | Pino(s) ESP32 | Papel no código |
| --- | --- | --- |
| LED | GPIO 10 | Acende durante a gravação. |
| Botão | GPIO 3 | Entrada com `INPUT_PULLUP`; pressionado equivale a `LOW`. |
| Motor de vibração | GPIO 2 | Pulsos de confirmação, aviso e erro. |
| Microfone I2S | SCK 4, WS 5, SD 6 | Captura PCM mono, 16 kHz e 16 bits. |
| DFPlayer Mini | RX 8, TX 9 | Reproduz faixas do cartão SD pela serial de hardware. |
| Leitura da bateria | ADC GPIO 0 | `checkBattery()` estima a tensão usando fator 2. |

O código também fixa o nome e a senha da rede, o IP e a porta 5000 do servidor. `setup()` reduz o clock a 80 MHz, desliga Bluetooth, configura o DFPlayer e o I2S, conecta ao Wi-Fi e toca a saudação. Se o DFPlayer não inicializa, permanece no laço de espera dentro de `setup()`.

### Funções e fluxo

| Função | O que faz |
| --- | --- |
| `handleButton()` | Faz debounce e separa os três gestos: clique único após timeout, duplo clique e pressão longa. |
| `loop()` | Reconecta Wi-Fi, lê o botão, captura amostras I2S e consulta o servidor quando necessário. |
| `startRecording()` / `stopAndUpload()` | Preparam o buffer WAV, ligam/desligam LED e terminam a gravação ao soltar o botão ou encher o buffer. |
| `writeWavHeaderToBuffer()` / `updateWavHeaderInBuffer()` | Criam o cabeçalho RIFF/WAV de 44 bytes e escrevem os tamanhos finais. |
| `uploadAudioBuffer()` | Envia o WAV completo ao endpoint de voz e vibra ao receber HTTP 200. |
| `startNewTrip()` / `cancelTrip()` | Iniciam a viagem com a tensão lida ou solicitam o cancelamento. |
| `checkTripStatus()` | Consulta o JSON, identifica mudanças do estado do servidor e escolhe faixa de áudio e vibração. |
| `handleVibrationFeedback()` | Usa o ETA para avisar aproximação; as quatro flags impedem repetição dos alertas. |
| `enterMonitoringMode()` | Muda o estado local para `MONITORING` e reinicia as flags de alerta. |
| `vibratePattern()` | Liga e desliga o motor com quantidade e duração de pulsos informadas. |

`MAX_AUDIO_SECONDS` limita o buffer a 4 segundos. `monitorInterval` é 2000 ms. O clique longo começa após 500 ms, o duplo precisa ocorrer em 750 ms e o debounce é de 50 ms. A leitura da bateria em ou abaixo de 3,3 V toca a faixa 15 antes de iniciar a viagem.

### Faixas esperadas no cartão SD

Os números são os argumentos passados a `myDFPlayer.play(...)`; os arquivos de áudio não estão no material recebido.

| Faixa | Constante | Uso |
| --- | --- | --- |
| 1 | `AUDIO_BEM_VINDO` | Inicialização. |
| 2 | `AUDIO_INICIAR_VIAGEM` | Pedido da origem. |
| 3 | `AUDIO_DEFINIR_DESTINO` | Pedido do destino. |
| 4 | `AUDIO_MONITORANDO_ONIBUS` | Linha encontrada e monitoramento iniciado. |
| 5 | `AUDIO_ONIBUS_PERTO_ORIGEM` | ETA na faixa antecipada para embarque. |
| 6 | `AUDIO_EMBARQUE_IMINENTE` | Ônibus chegou ao ponto de origem. |
| 7 | `AUDIO_DESTINO_PROXIMO` | ETA na faixa antecipada para desembarque. |
| 8 | `AUDIO_PROXIMA_PARADA` | ETA de 2 minutos ou menos para o destino. |
| 9 | `AUDIO_CHEGOU_DESTINO` | Chegada ao destino. |
| 10 | `AUDIO_VIAGEM_CANCELADA` | Cancelamento. |
| 11 | `AUDIO_ERRO_ROTA` | Erro de rota. |
| 12 | `AUDIO_ERRO_GERAL` | Falha de rede ou requisição. |
| 13 | `AUDIO_REPETIR_ORIGEM` | Origem não reconhecida. |
| 14 | `AUDIO_REPETIR_DESTINO` | Destino não reconhecido. |
| 15 | `AUDIO_BATERIA_BAIXA` | Bateria em ou abaixo de 3,3 V. |

## Servidor e API

`servidor.py` inicia Flask com CORS, carrega o modelo Whisper `small`, lê os JSONs e pré-calcula a distância acumulada em cada coordenada de rota. O Waitress atende HTTP na porta 5000. Threads atualizam o status da viagem a cada 0,5 s e verificam a presença do simulador a cada 5 s. A transcrição também ocorre em uma thread para a API responder logo ao envio do WAV.

| Função | O que faz |
| --- | --- |
| `carregar_dados_dos_arquivos()` | Abre rotas e paradas; converte os índices de parada de texto para inteiro. |
| `pre_calcular_distancias()` / `haversine()` | Calculam comprimentos acumulados da rota em metros. |
| `normalizar_texto()` / `encontrar_parada_por_apelido()` | Removem acentos, pontuação e palavras de apoio; usam `thefuzz` para achar um apelido com confiança mínima 80. |
| `encontrar_ocorrencias_parada()` | Localiza os índices e linhas onde uma parada aparece. |
| `calcular_rota()` | Escolhe origem e destino na mesma linha, com destino depois da origem; não calcula transferências. |
| `calcular_eta()` | Converte distância restante em minutos com velocidade média fixa de 12 km/h e arredondamento para cima. |
| `processar_audio_em_background()` | Transcreve, identifica a parada e atualiza a origem, o destino ou um estado de repetição/erro. Apaga o WAV temporário ao terminar. |
| `_processar_status_viagem()` | Calcula a distância até o ponto alvo e avança a viagem conforme o ônibus passa pela origem e pelo destino. |
| `_monitorar_conexao_simulador()` | Registra erro de conexão e reinicia a viagem se faltarem atualizações por mais de 15 s. |
| `logar_estatisticas_viagem()` | Acrescenta encerramentos e cancelamentos a `viagens_log.txt`. |

`viagem_atual` e `posicoes_onibus_atuais` são dicionários em memória. `viagem_lock` e `posicoes_lock` protegem o acesso entre as threads. `uploads/`, `viagens_log.txt` e o arquivo de transcrições não reconhecidas são dados de execução ignorados pelo Git. O nome desse último arquivo é configurado no servidor, mas a implementação recebida não grava nele.

### Rotas HTTP

| Método e rota | Quem usa | Entrada e efeito |
| --- | --- | --- |
| `POST /iniciar_viagem` | Pulseira | JSON com `tensao`; define `AGUARDANDO_ORIGEM`. Pode devolver 503 se o simulador já foi visto, mas está inativo. |
| `GET /cancelar_viagem` | Pulseira | Registra o cancelamento e volta a `IDLE`. |
| `POST /comando_de_voz` | Pulseira | Corpo binário WAV; salva temporariamente e devolve `processando` enquanto o Whisper trabalha. |
| `POST /atualizar_posicoes_onibus` | Simulador | Lista JSON de ônibus com `id`, `cor`, `lat`, `lng` e `indiceCoordAtual`. Substitui as posições anteriores. |
| `GET /get_viagem_atual` | Pulseira e simulador | Devolve o estado da viagem; quando a linha já foi escolhida, procura o ônibus da linha mais próximo antes da origem. |

### Estados de viagem do servidor

```text
IDLE → AGUARDANDO_ORIGEM → AGUARDANDO_DESTINO → MONITORANDO
                 ↘ REPETIR_ORIGEM      ↘ REPETIR_DESTINO
MONITORANDO → AGUARDANDO_EMBARQUE → EM_VIAGEM → CHEGOU_AO_DESTINO
                                                → FINALIZADO_SUCESSO → IDLE
```

Erros de rota, ordem, ausência de ônibus e perda de conexão geram estados `FINALIZADO_*` ou retorno a `IDLE`. A pulseira usa também quatro estados **locais** (`IDLE`, `RECORDING`, `UPLOADING`, `MONITORING`) para organizar captura e consulta; eles não são os estados da viagem do servidor.

## Simulador e dados

O HTML contém CSS e JavaScript no mesmo arquivo e usa Leaflet para o mapa. `carregarDados()` lê os JSONs; `configurarInterface()` constrói os controles e as camadas; `preCalcularDistancias()` prepara os comprimentos; `loopPrincipal()` avança o relógio; `despacharNovosOnibus()` cria ônibus nos horários cadastrados; `atualizarOnibus()` move seus marcadores. `enviarPosicoesParaServidor()` e `verificarViagemAtiva()` fazem a ponte com a API, ambos agendados a cada 100 ms. O painel mostra o estado da viagem e o mapa pode destacar o ônibus vinculado a ela.

| Arquivo | Estrutura principal |
| --- | --- |
| `rotas_data.json` | Quatro linhas identificadas por cor, com coordenadas, índices de parada, horários e dados de exibição. |
| `paradas_data.json` | `NOMES_DAS_PARADAS`, `APELIDOS_DAS_PARADAS`, `REFERENCIAS_PRINCIPAIS` e `COORDENADAS_PARADAS`. |
| `icones_data.json` | URLs externas e dimensões dos marcadores de paradas, ônibus, destino e personagens. |

O mapa usa uma velocidade de simulação configurada no HTML; o ETA da API é uma estimativa separada, com velocidade média fixa de 12 km/h. Não há GPS de ônibus real nesta implementação.
