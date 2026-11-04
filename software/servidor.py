# --- Importações de Bibliotecas ---
import os
import unicodedata
import json
import math
import time
import threading
import logging
import string
from datetime import datetime
from threading import Lock

# Bibliotecas de terceiros
from flask import Flask, request, jsonify
from flask_cors import CORS
import whisper
from waitress import serve
from thefuzz import process

# --- CONFIGURAÇÃO DO SISTEMA DE LOG ---
# Adicionado um formato de log mais detalhado
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [%(threadName)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.getLogger('waitress').setLevel(logging.WARNING)

# --- Parâmetros de Configuração do Protótipo ---
MODEL_NAME = "small"
UPLOADS_FOLDER = "uploads"
UNRECOGNIZED_LOG_FILE = "transcricoes_nao_reconhecidas.txt"
VIAGENS_LOG_FILE = "viagens_log.txt"

CONFIDENCE_THRESHOLD = 80
DISTANCIA_CHEGA_METROS = 75
VELOCIDADE_MEDIA_KMH = 12
SIMULADOR_TIMEOUT_SEGUNDOS = 15
LARGURA_CONSOLE_STATUS = 85

STOPWORDS = [
    "ponto", "parada", "de", "no", "a", "o", "em", "um", "uma",
    "para", "com", "por", "sem", "sob", "sobre", "me", "minha", "eu", "quero",
    "ir", "pegar", "descer", "gostaria", "por favor", "obrigado", "perto", "proximo", "próximo", "frente"
]

CORRECOES_MANUAIS = { "e ate o proximo video": "inatel" }

# --- Variáveis Globais de Estado ---
ROTAS, NOMES_DAS_PARADAS, APELIDOS_DAS_PARADAS, COORDENADAS_PARADAS = {}, {}, {}, {}
viagem_atual, posicoes_onibus_atuais = {}, {}
viagem_lock, posicoes_lock = Lock(), Lock()
ultimo_update_simulador = 0

# --- INICIALIZAÇÃO DO FLASK E WHISPER ---
os.makedirs(UPLOADS_FOLDER, exist_ok=True)
app = Flask(__name__)
CORS(app)

logging.info("[SISTEMA] Carregando modelo Whisper '%s'... Isso pode demorar.", MODEL_NAME)
model = whisper.load_model(MODEL_NAME)
logging.info("[SISTEMA] Modelo Whisper carregado com sucesso.")

# --- Funções de Inicialização e Carregamento de Dados ---
# Carrega os dados compartilhados com o simulador; os caminhos dependem da pasta atual.
def carregar_dados_dos_arquivos():
    global ROTAS, NOMES_DAS_PARADAS, APELIDOS_DAS_PARADAS, COORDENADAS_PARADAS
    try:
        with open('rotas_data.json', 'r', encoding='utf-8') as f: ROTAS = json.load(f)
        with open('paradas_data.json', 'r', encoding='utf-8') as f:
            paradas_data = json.load(f)
        
        nomes_das_paradas_str_keys = paradas_data.get("NOMES_DAS_PARADAS", {})
        NOMES_DAS_PARADAS = {cor: {int(k): v for k, v in paradas.items()} for cor, paradas in nomes_das_paradas_str_keys.items()}
        APELIDOS_DAS_PARADAS = paradas_data.get("APELIDOS_DAS_PARADAS", {})
        COORDENADAS_PARADAS = paradas_data.get("COORDENADAS_PARADAS", {})
        logging.info("[SISTEMA] Arquivos de rotas e paradas carregados.")
    except Exception as e:
        logging.critical(f"[ERRO CRÍTICO] Falha ao carregar arquivos de dados: {e}. Encerrando.", exc_info=True)
        exit()

# Acrescenta a cada rota as distâncias acumuladas usadas para localizar ônibus e calcular ETA.
def pre_calcular_distancias():
    for cor, rota in ROTAS.items():
        rota['distancias_acumuladas'] = [0] * len(rota['coords'])
        distancia_acumulada_total = 0
        for i in range(1, len(rota['coords'])):
            ponto_anterior = rota['coords'][i-1]
            ponto_atual = rota['coords'][i]
            distancia_segmento = haversine(ponto_anterior[0], ponto_anterior[1], ponto_atual[0], ponto_atual[1])
            distancia_acumulada_total += distancia_segmento
            rota['distancias_acumuladas'][i] = distancia_acumulada_total
        rota['distancia_total_rota'] = distancia_acumulada_total
    logging.info("[SISTEMA] Distâncias das rotas pré-calculadas.")

# --- Funções Utilitárias ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2, delta_phi, delta_lambda = map(math.radians, [lat1, lat2, lat2 - lat1, lon2 - lon1])
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def normalizar_texto(texto):
    try:
        texto = texto.lower()
        nfkd_form = unicodedata.normalize('NFKD', texto)
        return "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    except: return texto

# Normaliza a fala e escolhe um apelido de parada apenas acima do limiar de confiança.
def encontrar_parada_por_apelido(texto_falado):
    texto_normalizado = normalizar_texto(texto_falado)
    texto_sem_pontuacao = texto_normalizado.translate(str.maketrans('', '', string.punctuation))
    texto_para_busca = texto_sem_pontuacao

    if texto_sem_pontuacao in CORRECOES_MANUAIS:
        texto_corrigido = CORRECOES_MANUAIS[texto_sem_pontuacao]
        logging.info(f"  Correção manual aplicada: '{texto_falado}' -> '{texto_corrigido}'")
        texto_para_busca = texto_corrigido

    palavras_filtradas = [p for p in texto_para_busca.split() if p not in STOPWORDS]
    texto_final_busca = " ".join(palavras_filtradas)
    if not texto_final_busca: return None

    todos_apelidos, mapa_apelido_para_nome = [], {}
    for nome_oficial, lista_apelidos in APELIDOS_DAS_PARADAS.items():
        for apelido in lista_apelidos:
            apelido_normalizado = normalizar_texto(apelido)
            todos_apelidos.append(apelido_normalizado)
            mapa_apelido_para_nome[apelido_normalizado] = nome_oficial

    melhor_match = process.extractOne(texto_final_busca, todos_apelidos)
    if melhor_match and melhor_match[1] >= CONFIDENCE_THRESHOLD:
        return { "nome": mapa_apelido_para_nome[melhor_match[0]], "confianca": melhor_match[1] }
    return None

def encontrar_ocorrencias_parada(nome_parada):
    return [{"id": id_p, "cor": cor, "nome": nome_parada} for cor, paradas in NOMES_DAS_PARADAS.items() for id_p, nome in paradas.items() if nome == nome_parada]

# Aceita somente origem e destino na mesma linha, na ordem dos pontos cadastrados.
def calcular_rota(origem, destino):
    if not origem or not destino: return {"status": "erro_interno"}
    mesma_linha_encontrada = False
    for oc_origem in origem["ocorrencias"]:
        for oc_destino in destino["ocorrencias"]:
            if oc_origem["cor"] == oc_destino["cor"]:
                mesma_linha_encontrada = True
                if oc_origem["id"] < oc_destino["id"]:
                    return {"status": "sucesso", "linha": oc_origem["cor"], "id_origem": oc_origem["id"], "id_destino": oc_destino["id"]}
    return {"status": "erro_ordem"} if mesma_linha_encontrada else {"status": "erro_rota"}

def calcular_eta(distancia_metros):
    if distancia_metros <= 0: return 0
    velocidade_ms = (VELOCIDADE_MEDIA_KMH * 1000) / 3600
    return math.ceil((distancia_metros / velocidade_ms) / 60) if velocidade_ms > 0 else -1

def logar_estatisticas_viagem(viagem_obj):
    try:
        status, origem, destino, linha, tensao = (
            viagem_obj.get('estado', 'N/A'),
            viagem_obj.get('origem', {}).get('nome', 'N/A'),
            viagem_obj.get('destino', {}).get('nome', 'N/A'),
            viagem_obj.get('linha', 'N/A').upper(),
            viagem_obj.get('tensao_inicial', 'N/A')
        )
        log_entry = f"Status: {status} | Bateria: {tensao}V | Linha: {linha} | Origem: {origem} | Destino: {destino}"
        logging.info(f"[LOG VIAGEM] {log_entry}")
        with open(VIAGENS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {log_entry}\n")
    except Exception as e:
        logging.error(f"Falha ao salvar log da viagem: {e}")

# --- Lógica Principal da Viagem (Executada em Threads) ---
# Atualiza distância, ETA e estado da viagem a partir das posições enviadas pelo simulador.
def _processar_status_viagem():
    with viagem_lock:
        viagem_snapshot = viagem_atual.copy()
    
    estado_atual = viagem_snapshot.get("estado")
    if estado_atual not in ["MONITORANDO", "AGUARDANDO_EMBARQUE", "EM_VIAGEM", "CHEGOU_AO_DESTINO"]:
        if estado_atual and "FINALIZADO" in estado_atual:
            time.sleep(2)
            with viagem_lock:
                if viagem_atual.get("estado") == estado_atual:
                    viagem_atual["estado"] = "IDLE"
                    logging.info(f"[LÓGICA] Viagem finalizada. Resetando estado para IDLE.")
        return

    onibus_id = viagem_snapshot.get("onibus_id")
    if onibus_id is None: return

    with posicoes_lock: onibus_info = posicoes_onibus_atuais.get(onibus_id)
    if not onibus_info:
        with viagem_lock: viagem_atual.update({'distancia_onibus': -1, 'eta_minutos': -1})
        return
        
    rota_onibus = ROTAS[onibus_info['cor']]
    with viagem_lock:
        estado_no_lock = viagem_atual.get("estado")
        id_ponto_alvo = viagem_atual.get("id_origem") if estado_no_lock in ["MONITORANDO", "AGUARDANDO_EMBARQUE"] else viagem_atual.get("id_destino")
        if id_ponto_alvo is None: return

        dist_acumulada_onibus = rota_onibus['distancias_acumuladas'][onibus_info['indiceCoordAtual']]
        dist_extra = haversine(rota_onibus['coords'][onibus_info['indiceCoordAtual']][0], rota_onibus['coords'][onibus_info['indiceCoordAtual']][1], onibus_info['lat'], onibus_info['lng'])
        dist_total_onibus = dist_acumulada_onibus + dist_extra
        dist_total_alvo = rota_onibus['distancias_acumuladas'][id_ponto_alvo]
        dist_restante = max(0, dist_total_alvo - dist_total_onibus)
        
        eta = calcular_eta(dist_restante)
        viagem_atual.update({'distancia_onibus': dist_restante, 'eta_minutos': eta})
        
        linha_status = ""
        if estado_no_lock == "MONITORANDO":
            linha_status = f"[Monitoramento] Onibus {onibus_id} -> ORIGEM: {int(dist_restante)}m | ETA: {eta} min"
            if dist_restante <= DISTANCIA_CHEGA_METROS:
                viagem_atual["estado"] = "AGUARDANDO_EMBARQUE"
        elif estado_no_lock == "AGUARDANDO_EMBARQUE":
            linha_status = f"[Aguardando Embarque] Onibus {onibus_id} parado na origem."
            if (dist_total_alvo - dist_total_onibus) < -10:
                viagem_atual["estado"] = "EM_VIAGEM"
        elif estado_no_lock == "EM_VIAGEM":
            linha_status = f"[Em Viagem] Onibus {onibus_id} -> DESTINO: {int(dist_restante)}m | ETA: {eta} min"
            if dist_restante <= DISTANCIA_CHEGA_METROS:
                viagem_atual["estado"] = "CHEGOU_AO_DESTINO"
        elif estado_no_lock == "CHEGOU_AO_DESTINO":
            linha_status = f"[Chegou ao Destino] Onibus {onibus_id} parado no destino."
            if (dist_total_alvo - dist_total_onibus) < -10:
                viagem_atual["estado"] = "FINALIZADO_SUCESSO"
                logar_estatisticas_viagem(viagem_atual)
        if linha_status: print(f"\r{linha_status.ljust(LARGURA_CONSOLE_STATUS)}", end="", flush=True)

# Transcreve em outra thread e descarta o resultado se o estado mudou durante a espera.
def processar_audio_em_background(filepath, estado_quando_gravou):
    try:
        logging.info(f"[WHISPER] Iniciando transcrição para o estado '{estado_quando_gravou}'.")
        result = model.transcribe(filepath, language="pt")
        transcription = result["text"].strip() or " "
        
        logging.info(f"\n{' INFORMAÇÕES DA TRANSCRIÇÃO '.center(LARGURA_CONSOLE_STATUS, '-')}")
        logging.info(f"  Texto Transcrito: '{transcription}'")

        resultado_match = encontrar_parada_por_apelido(transcription)
        if not resultado_match:
            logging.warning("  Parada NÃO RECONHECIDA. Nenhuma correspondência acima do limiar.")
            with viagem_lock:
                if viagem_atual.get("estado") == estado_quando_gravou:
                    novo_estado = "REPETIR_ORIGEM" if "ORIGEM" in estado_quando_gravou else "REPETIR_DESTINO"
                    viagem_atual["estado"] = novo_estado
                    logging.info(f"[LÓGICA] Estado alterado para {novo_estado}.")
            return
        
        nome_parada, confianca = resultado_match["nome"], resultado_match["confianca"]
        logging.info(f"  Parada Reconhecida: '{nome_parada}' (Confiança: {confianca:.2f}%)")
        ponto_info = {"nome": nome_parada, "ocorrencias": encontrar_ocorrencias_parada(nome_parada)}
        
        with viagem_lock:
            if viagem_atual.get("estado") != estado_quando_gravou: 
                logging.warning(f"[LÓGICA] Estado da viagem mudou durante transcrição. Abortando atualização.")
                return
            if "ORIGEM" in estado_quando_gravou:
                viagem_atual.update({"origem": ponto_info, "estado": "AGUARDANDO_DESTINO"})
                logging.info(f"[LÓGICA] Origem DEFINIDA como '{nome_parada}'. Aguardando destino.")
            elif "DESTINO" in estado_quando_gravou:
                viagem_atual["destino"] = ponto_info
                logging.info(f"[LÓGICA] Destino DEFINIDO como '{nome_parada}'. Calculando rota...")
                resultado_rota = calcular_rota(viagem_atual.get("origem"), viagem_atual.get("destino"))
                if resultado_rota.get("status") == "sucesso":
                    viagem_atual.update({"estado": "MONITORANDO", **resultado_rota})
                    logging.info(f"[LÓGICA] ROTA ENCONTRADA! Linha: {resultado_rota['linha'].upper()}.")
                else:
                    novo_estado = "FINALIZADO_ERRO_ORDEM" if resultado_rota.get("status") == "erro_ordem" else "FINALIZADO_ERRO"
                    viagem_atual["estado"] = novo_estado
                    logar_estatisticas_viagem(viagem_atual)
                    logging.error(f"[LÓGICA] Erro ao calcular rota: {novo_estado}")
    except Exception as e:
        logging.error(f"Erro CRÍTICO no processamento de áudio: {e}", exc_info=True)
    finally:
        if os.path.exists(filepath): os.remove(filepath)

# Encerra a viagem ativa se as posições deixarem de chegar pelo tempo configurado.
def _monitorar_conexao_simulador():
    global viagem_atual 
    if ultimo_update_simulador == 0: return
    if (time.time() - ultimo_update_simulador) > SIMULADOR_TIMEOUT_SEGUNDOS:
        with viagem_lock:
            if viagem_atual.get("estado") != "IDLE":
                logging.warning(f"\n{'!':-^{LARGURA_CONSOLE_STATUS}}\n{' CONEXÃO COM O SIMULADOR PERDIDA '.center(LARGURA_CONSOLE_STATUS, ' ')}\n{'!':-^{LARGURA_CONSOLE_STATUS}}")
                logar_estatisticas_viagem({**viagem_atual, "estado": "FINALIZADO_ERRO_CONEXAO"})
                viagem_atual = {"estado": "IDLE"}

# --- Endpoints da API (Rotas HTTP) ---
# A pulseira inicia a viagem e envia a tensão lida no momento do clique único.
@app.route('/iniciar_viagem', methods=['POST'])
def iniciar_viagem():
    global viagem_atual
    client_ip = request.remote_addr
    logging.info(f"[REDE] Requisição /iniciar_viagem recebida de {client_ip}")
    
    if ultimo_update_simulador > 0 and (time.time() - ultimo_update_simulador > SIMULADOR_TIMEOUT_SEGUNDOS):
        logging.warning("[REDE] Tentativa de iniciar viagem com simulador inativo.")
        return jsonify({"status": "erro", "message": "simulador_inativo"}), 503

    dados = request.get_json()
    tensao = dados.get('tensao', -1.0) if dados else -1.0

    logging.info(f"\n{' NOVA VIAGEM INICIADA '.center(LARGURA_CONSOLE_STATUS, '=')}")
    logging.info(f" [BATERIA] Tensão da pulseira ({client_ip}): {tensao:.2f}V ")
    print("=" * LARGURA_CONSOLE_STATUS)
    
    with viagem_lock:
        viagem_atual = {"estado": "AGUARDANDO_ORIGEM", "tensao_inicial": tensao}
    return jsonify({"status": "ok"})

@app.route('/cancelar_viagem', methods=['GET'])
def cancelar_viagem():
    global viagem_atual
    logging.info(f"[REDE] Requisição /cancelar_viagem recebida de {request.remote_addr}")
    with viagem_lock:
        if viagem_atual.get("estado") and viagem_atual.get("estado") != "IDLE":
            logar_estatisticas_viagem({**viagem_atual, "estado": "CANCELADO_USUARIO"})
            viagem_atual = {"estado": "IDLE"}
            logging.info(f"\n{' VIAGEM CANCELADA PELO USUÁRIO '.center(LARGURA_CONSOLE_STATUS, '=')}")
            return jsonify({"status": "ok"})
    return jsonify({"status": "nenhuma_viagem_em_andamento"})

# Recebe o WAV bruto da pulseira; a transcrição continua em segundo plano.
@app.route('/comando_de_voz', methods=['POST'])
def comando_de_voz():
    if not request.data: return jsonify({'status': 'erro', 'message': 'Nenhum dado de áudio recebido'}), 400
    
    with viagem_lock: estado_no_momento_da_gravacao = viagem_atual.get("estado")
    logging.info(f"[REDE] Recebido áudio de {request.remote_addr} para o estado '{estado_no_momento_da_gravacao}'.")

    filepath = os.path.join(UPLOADS_FOLDER, f"audio_{int(time.time() * 1000)}.wav")
    try:
        with open(filepath, "wb") as f: f.write(request.data)
        thread = threading.Thread(target=processar_audio_em_background, args=(filepath, estado_no_momento_da_gravacao), name=f"WhisperThread-{int(time.time())}")
        thread.daemon = True
        thread.start()
        return jsonify({"status": "processando"})
    except Exception as e:
        logging.error(f"[ERRO CRÍTICO] Falha ao salvar ou processar áudio: {e}", exc_info=True)
        return jsonify({'status': 'erro', 'message': str(e)}), 500

# O simulador substitui o conjunto atual de ônibus e renova o sinal de atividade.
@app.route('/atualizar_posicoes_onibus', methods=['POST'])
def atualizar_posicoes_onibus():
    global ultimo_update_simulador, posicoes_onibus_atuais
    ultimo_update_simulador = time.time()
    dados = request.get_json()
    if not dados: return jsonify({'status': 'erro'}), 400
    with posicoes_lock:
        posicoes_onibus_atuais.clear()
        for onibus in dados: posicoes_onibus_atuais[onibus['id']] = onibus
    return jsonify({'status': 'ok'})

# Pulseira e simulador consultam o mesmo estado; aqui é escolhido o ônibus da linha.
@app.route('/get_viagem_atual', methods=['GET'])
def get_viagem_atual():
    # O log abaixo foi comentado para evitar "spam" no console, já que a pulseira
    # requisita o status constantemente durante o monitoramento.
    # logging.info(f"[REDE] Pulseira ({request.remote_addr}) requisitou status da viagem.")
    with viagem_lock:
        estado = viagem_atual.get("estado")
        if estado == "MONITORANDO" and "onibus_id" not in viagem_atual:
            linha_cor, id_origem = viagem_atual.get("linha"), viagem_atual.get("id_origem")
            if linha_cor and id_origem is not None:
                logging.info(f"[LÓGICA] Procurando ônibus da linha {linha_cor.upper()} antes do ponto de origem {id_origem}.")
                menor_dist, onibus_id = float('inf'), None
                with posicoes_lock:
                    candidatos = [b for b in posicoes_onibus_atuais.values() if b['cor'] == linha_cor and b.get('indiceCoordAtual', float('inf')) < id_origem]
                if candidatos:
                    logging.info(f"[LÓGICA] Encontrados {len(candidatos)} ônibus candidatos.")
                    for bus in candidatos:
                        dist = ROTAS[bus['cor']]['distancias_acumuladas'][id_origem] - ROTAS[bus['cor']]['distancias_acumuladas'][bus['indiceCoordAtual']]
                        if dist < menor_dist: menor_dist, onibus_id = dist, bus['id']
                    if onibus_id:
                        viagem_atual["onibus_id"] = onibus_id
                        logging.info(f"[ALOCAÇÃO] ÔNIBUS {onibus_id} ALOCADO PARA A VIAGEM.")
                else:
                    logging.warning("[LÓGICA] Nenhum ônibus disponível se aproximando da origem.")
                    viagem_atual["estado"] = "FINALIZADO_ERRO_SEM_ONIBUS"
                    logar_estatisticas_viagem(viagem_atual)
        return jsonify(viagem_atual)

# --- Bloco Principal de Execução ---
if __name__ == '__main__':
    carregar_dados_dos_arquivos()
    pre_calcular_distancias()
    
    threading.Thread(target=lambda: serve(app, host='0.0.0.0', port=5000), daemon=True).start()

    def run_threaded(job_func, interval):
        # Corrigido o loop infinito dentro da lambda para uma forma mais padrão
        def thread_func():
            while True:
                job_func()
                time.sleep(interval)
        thread = threading.Thread(target=thread_func, daemon=True)
        thread.start()

    run_threaded(_processar_status_viagem, 0.5)
    run_threaded(_monitorar_conexao_simulador, 5)

    logging.info("[REDE] Servidor SmartWay pronto e rodando em http://0.0.0.0:5000")
    
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        logging.info("\n[SISTEMA] Servidor encerrado pelo usuário.")
