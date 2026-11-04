# Software e simulador

Esta pasta reúne a API Python, o simulador no navegador e os dados compartilhados por ambos. A pulseira envia comandos à API; o simulador fornece posições de ônibus para que o servidor acompanhe uma viagem.

Volte à [visão geral do SmartWay](../README.md) ou consulte o [guia detalhado do código](../docs/GUIA_DO_CODIGO.md).

## Arquivos e dados

| Arquivo | Para que serve |
| --- | --- |
| [`servidor.py`](servidor.py) | API Flask/Waitress, transcrição Whisper, escolha de paradas e rota, estado e ETA. |
| [`simulador.html`](simulador.html) | Interface Leaflet, horários, ônibus em movimento e painel da viagem. |
| [`rotas_data.json`](rotas_data.json) | Traçados e horários das linhas vermelha, verde, rosa e amarela. |
| [`paradas_data.json`](paradas_data.json) | Nomes, apelidos, referências e coordenadas das paradas. |
| [`icones_data.json`](icones_data.json) | Endereços e dimensões dos marcadores usados no mapa. |
| [`requirements.txt`](requirements.txt) | Dependências Python declaradas pelo código, sem versões fixas. |

Servidor e simulador abrem os JSONs por caminhos relativos. **Mantenha esses arquivos nesta pasta** e inicie o servidor a partir dela. O mapa também carrega Leaflet, fontes, imagens e blocos de mapa de serviços externos; esses recursos exigem internet.

## Como as partes conversam

| Rota HTTP | Origem | Efeito |
| --- | --- | --- |
| `POST /iniciar_viagem` | Pulseira | Inicia o pedido de origem e recebe a tensão da bateria. |
| `POST /comando_de_voz` | Pulseira | Recebe WAV; a transcrição continua em outra thread. |
| `GET /cancelar_viagem` | Pulseira | Cancela a viagem. |
| `POST /atualizar_posicoes_onibus` | Simulador | Substitui as posições atuais dos ônibus. |
| `GET /get_viagem_atual` | Pulseira e simulador | Devolve estado, linha, ônibus, distância e ETA quando disponíveis. |

O servidor identifica paradas com Whisper e correspondência aproximada de apelidos. Ele aceita origem e destino na **mesma linha**, com o destino depois da origem. O ETA usa uma velocidade média fixa de **12 km/h**. O estado da viagem fica em memória; se o simulador parar de enviar posições por mais de **15 segundos**, uma viagem ativa é encerrada.

## Executar no Windows

Na raiz do repositório, prepare um ambiente Python 3.11 e instale FFmpeg no sistema:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\software\requirements.txt
```

Em um terminal, inicie a API na pasta `software/`:

```powershell
cd .\software
..\.venv\Scripts\python.exe .\servidor.py
```

Em outro terminal, na raiz do repositório, sirva o simulador:

```powershell
.\.venv\Scripts\python.exe -m http.server 8000 --directory .\software
```

Abra `http://localhost:8000/simulador.html` e inicie a simulação. O servidor escuta na porta **5000**. O HTML contém um IP fixo para essa API; ele deve apontar para o computador onde o servidor está rodando.

O modelo Whisper `small` pode precisar ser baixado na primeira execução. Os arquivos gerados durante o uso, como `uploads/` e `viagens_log.txt`, estão no `.gitignore` da raiz.
