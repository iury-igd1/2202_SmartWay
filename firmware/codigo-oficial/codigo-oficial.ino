#include <driver/i2s.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "DFRobotDFPlayerMini.h"
#include <esp_bt.h>

// Configurações de rede e servidor
const char* ssid = "NOME_REDE";
const char* password = "SINHA_REDE";
const char* serverIp = "IP_SERVIDOR";
const int serverPort = 5000;

// Configurações de hardware
#define LED_PIN 10
#define BUTTON_PIN 3
#define VIBRATION_PIN 2
#define I2S_WS_PIN 5
#define I2S_SCK_PIN 4
#define I2S_SD_PIN 6
#define DFPLAYER_RX_PIN 8
#define DFPLAYER_TX_PIN 9
#define BATTERY_ADC_PIN 0 // Pino para leitura da bateria

// Configurações do DFPlayer
HardwareSerial dfplayerSerial(1);
DFRobotDFPlayerMini myDFPlayer;
#define AUDIO_BEM_VINDO           1
#define AUDIO_INICIAR_VIAGEM      2
#define AUDIO_DEFINIR_DESTINO     3
#define AUDIO_MONITORANDO_ONIBUS  4
#define AUDIO_ONIBUS_PERTO_ORIGEM 5
#define AUDIO_EMBARQUE_IMINENTE   6
#define AUDIO_DESTINO_PROXIMO     7
#define AUDIO_PROXIMA_PARADA      8
#define AUDIO_CHEGOU_DESTINO      9
#define AUDIO_VIAGEM_CANCELADA    10
#define AUDIO_ERRO_ROTA           11
#define AUDIO_ERRO_GERAL          12
#define AUDIO_REPETIR_ORIGEM      13
#define AUDIO_REPETIR_DESTINO     14
#define AUDIO_BATERIA_BAIXA       15

// Configurações de áudio
#define I2S_PORT I2S_NUM_0
#define SAMPLE_RATE 16000
#define BITS_PER_SAMPLE I2S_BITS_PER_SAMPLE_16BIT
#define MAX_AUDIO_SECONDS 4
#define AUDIO_BUFFER_SIZE (SAMPLE_RATE * (BITS_PER_SAMPLE / 8) * 1 * MAX_AUDIO_SECONDS)
uint8_t audioBuffer[AUDIO_BUFFER_SIZE + 44];
unsigned int dataSize = 0;

// Configurações de vibração
#define VIBRATION_WEAK_PULSE 80
#define VIBRATION_STD_PULSE 120

// Estados globais do sistema
enum SystemState { IDLE, RECORDING, UPLOADING, MONITORING };
SystemState currentState = IDLE;
String lastKnownState = "IDLE";

// Variáveis de controle de botão
int buttonState = HIGH;
int lastButtonState = HIGH;
unsigned long buttonPressTime = 0;
bool isRecording = false;
unsigned long lastDebounceTime = 0;
unsigned long debounceDelay = 50;
unsigned long longPressTime = 500;
unsigned long firstClickTime = 0;
bool waitingForSecondClick = false;
const unsigned long doubleClickTimeout = 750;

// Variáveis de controle de rede e feedback
unsigned long lastMonitorTime = 0;
const long monitorInterval = 2000;
unsigned long lastProcessingVibrationTime = 0;
bool alerted_5_min_origin = false, alerted_1_min_origin = false, alerted_5_min_dest = false, alerted_1_min_dest = false;

// Protótipos de funções
void connectToWiFi();
void checkTripStatus();
void startRecording();
void stopAndUpload();
void startNewTrip(float currentVoltage);
void cancelTrip();
void uploadAudioBuffer();
void writeWavHeaderToBuffer(uint8_t* buffer, unsigned int sampleRate, uint16_t bitsPerSample, uint16_t channels);
void updateWavHeaderInBuffer(uint8_t* buffer, unsigned int dataSize);
void setupI2S();
void enterMonitoringMode();
void vibratePattern(int pulses, int duration, int pause);
void handleVibrationFeedback(int eta, const char* estado);
float checkBattery();

// Inicializa periféricos, desliga Bluetooth, conecta ao Wi-Fi e reproduz a saudação.
void setup() {
  setCpuFrequencyMhz(80);

  pinMode(LED_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(VIBRATION_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  digitalWrite(VIBRATION_PIN, LOW);

  btStop();

  dfplayerSerial.begin(9600, SERIAL_8N1, DFPLAYER_RX_PIN, DFPLAYER_TX_PIN);
  if (!myDFPlayer.begin(dfplayerSerial, true, true)) {
    while (true) delay(100);
  }
  myDFPlayer.volume(15);

  setupI2S();
  connectToWiFi();

  WiFi.setSleep(true);

  myDFPlayer.play(AUDIO_BEM_VINDO);
}

// Distingue clique único, duplo e longo pelo tempo, com debounce sem bloquear a leitura.
void handleButton() {
  int reading = digitalRead(BUTTON_PIN);
  if (reading != lastButtonState) { lastDebounceTime = millis(); }
  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != buttonState) {
      buttonState = reading;
      if (buttonState == LOW) { // Botão foi pressionado
        buttonPressTime = millis();
        isRecording = false;
        vibratePattern(1, VIBRATION_WEAK_PULSE, 0);

        // A verificação de bateria crítica que existia aqui foi removida.

      } else { // Botão foi solto
        if ((millis() - buttonPressTime) < longPressTime) { // Clique curto
          if (waitingForSecondClick && (millis() - firstClickTime < doubleClickTimeout)) { // Clique duplo
            cancelTrip();
            waitingForSecondClick = false;
          } else { // Primeiro clique de um potencial duplo
            waitingForSecondClick = true;
            firstClickTime = millis();
          }
        }
      }
    }
  }
  lastButtonState = reading;
  
  // Ação de clique longo (iniciar gravação)
  if (buttonState == LOW && !isRecording && (millis() - buttonPressTime >= longPressTime)) {
    isRecording = true;
    waitingForSecondClick = false;
    startRecording();
  }
  
  // Ação de clique único (timeout do duplo clique)
  if (waitingForSecondClick && (millis() - firstClickTime >= doubleClickTimeout)) {
    waitingForSecondClick = false;
    float currentVoltage = checkBattery(); // Mede a tensão no momento de iniciar
    startNewTrip(currentVoltage);
  }
}

// Mantém captura I2S e consulta periódica do servidor conforme o estado local.
void loop() {
  if (WiFi.status() != WL_CONNECTED) { connectToWiFi(); }
  if (currentState == IDLE || currentState == MONITORING) { handleButton(); }
  if (currentState == RECORDING && digitalRead(BUTTON_PIN) == HIGH) { stopAndUpload(); }

  if (currentState == RECORDING) {
    size_t bytesRead = 0;
    char i2s_read_buffer[1024];
    i2s_read(I2S_PORT, i2s_read_buffer, sizeof(i2s_read_buffer), &bytesRead, portMAX_DELAY);
    if (bytesRead > 0) {
      if ((dataSize + bytesRead) < AUDIO_BUFFER_SIZE) {
        memcpy(audioBuffer + 44 + dataSize, i2s_read_buffer, bytesRead);
        dataSize += bytesRead;
      } else { stopAndUpload(); }
    }
  }

  unsigned long now = millis();
  if (currentState == UPLOADING || currentState == MONITORING) {
    if (now - lastMonitorTime > monitorInterval) {
      checkTripStatus();
      lastMonitorTime = now;
    }
    if (currentState == UPLOADING && (now - lastProcessingVibrationTime > 2000)) {
        vibratePattern(1, VIBRATION_WEAK_PULSE, 0);
        lastProcessingVibrationTime = now;
    }
  }
}

// Converte a leitura ADC em tensão estimada da bateria pelo divisor resistivo.
float checkBattery() {
  int mv_at_pin = analogReadMilliVolts(BATTERY_ADC_PIN);
  float batteryVoltage = (mv_at_pin * 2.0) / 1000.0;
  return batteryVoltage;
}

void connectToWiFi() {
  WiFi.begin(ssid, password);
  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    delay(500);
    retries++;
  }
  if(WiFi.status() != WL_CONNECTED) { myDFPlayer.play(AUDIO_ERRO_GERAL); }
}

// Avisa bateria baixa, mas envia a solicitação de viagem mesmo assim.
void startNewTrip(float currentVoltage) {
  // A verificação de bateria baixa agora usa o valor 3.3V
  // e apenas toca o áudio, continuando a execução normalmente.
  if (currentVoltage <= 3.3) {
    myDFPlayer.play(AUDIO_BATERIA_BAIXA);
    delay(1500); // Adiciona uma pequena pausa para o áudio tocar antes de prosseguir
  }

  HTTPClient http;
  String serverUrl = "http://" + String(serverIp) + ":" + String(serverPort) + "/iniciar_viagem";

  currentState = UPLOADING;
  lastProcessingVibrationTime = millis();

  http.begin(serverUrl);
  http.addHeader("Content-Type", "application/json");

  String jsonPayload = "{\"tensao\":" + String(currentVoltage, 2) + "}";
  int httpResponseCode = http.POST(jsonPayload);
  
  if (httpResponseCode != 200) {
    myDFPlayer.play(AUDIO_ERRO_GERAL);
    currentState = IDLE;
  }
  http.end();
}

void cancelTrip() {
  HTTPClient http;
  String serverUrl = "http://" + String(serverIp) + ":" + String(serverPort) + "/cancelar_viagem";
  http.begin(serverUrl);
  int httpResponseCode = http.GET();
  if (httpResponseCode > 0) {
    myDFPlayer.play(AUDIO_VIAGEM_CANCELADA);
    vibratePattern(3, 100, 80);
  } else { myDFPlayer.play(AUDIO_ERRO_GERAL); }
  http.end();
  currentState = IDLE;
  lastKnownState = "IDLE";
}

// Envia ao servidor o cabeçalho WAV seguido das amostras já capturadas.
void uploadAudioBuffer() {
  currentState = UPLOADING;
  HTTPClient http;
  String serverUrl = "http://" + String(serverIp) + ":" + String(serverPort) + "/comando_de_voz";
  http.begin(serverUrl);
  int httpResponseCode = http.sendRequest("POST", audioBuffer, dataSize + 44);

  if (httpResponseCode == 200) {
    vibratePattern(2, VIBRATION_STD_PULSE, 80);
  } else {
    myDFPlayer.play(AUDIO_ERRO_GERAL);
    currentState = IDLE;
  }
  http.end();
}

void enterMonitoringMode() {
  currentState = MONITORING;
  lastMonitorTime = 0;
  alerted_5_min_origin = alerted_1_min_origin = alerted_5_min_dest = alerted_1_min_dest = false;
}

// Traduz mudanças de estado da API em áudio e vibração na pulseira.
void checkTripStatus() {
  HTTPClient http;
  String serverUrl = "http://" + String(serverIp) + ":" + String(serverPort) + "/get_viagem_atual";
  http.begin(serverUrl);
  int httpResponseCode = http.GET();
  if (httpResponseCode == 200) {
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, http.getStream());
    if (!error) {
      const char* estado = doc["estado"];
      int eta = doc["eta_minutos"] | -1;

      if (lastKnownState.compareTo(estado) != 0) {
        if(currentState == UPLOADING){
            if(strstr(estado, "AGUARDANDO") || strstr(estado, "REPETIR")) currentState = IDLE;
            else if (strstr(estado, "FINALIZADO") || strcmp(estado, "IDLE") == 0) currentState = IDLE;
            else enterMonitoringMode();
        }

        if (strcmp(estado, "AGUARDANDO_ORIGEM") == 0) { myDFPlayer.play(AUDIO_INICIAR_VIAGEM); vibratePattern(2, VIBRATION_STD_PULSE, 100); }
        else if (strcmp(estado, "AGUARDANDO_DESTINO") == 0) { myDFPlayer.play(AUDIO_DEFINIR_DESTINO); }
        else if (strcmp(estado, "REPETIR_ORIGEM") == 0) { myDFPlayer.play(AUDIO_REPETIR_ORIGEM); vibratePattern(3, VIBRATION_STD_PULSE, 80); }
        else if (strcmp(estado, "REPETIR_DESTINO") == 0) { myDFPlayer.play(AUDIO_REPETIR_DESTINO); vibratePattern(3, VIBRATION_STD_PULSE, 80); }
        else if (strcmp(estado, "MONITORANDO") == 0) { myDFPlayer.play(AUDIO_MONITORANDO_ONIBUS); vibratePattern(2, 200, 100); }
        else if (strcmp(estado, "AGUARDANDO_EMBARQUE") == 0) { myDFPlayer.play(AUDIO_EMBARQUE_IMINENTE); vibratePattern(5, 300, 150); }
        else if (strcmp(estado, "EM_VIAGEM") == 0) { vibratePattern(1, 300, 0); }
        else if (strcmp(estado, "CHEGOU_AO_DESTINO") == 0) { myDFPlayer.play(AUDIO_CHEGOU_DESTINO); vibratePattern(5, 300, 150); }
        else if (strcmp(estado, "FINALIZADO_SUCESSO") == 0) { vibratePattern(3, VIBRATION_STD_PULSE, 100); }
        else if (strcmp(estado, "FINALIZADO_ERRO") == 0) { myDFPlayer.play(AUDIO_ERRO_ROTA); vibratePattern(1, 1500, 0); }
        lastKnownState = estado;
      }
      handleVibrationFeedback(eta, estado);
    }
  } else { myDFPlayer.play(AUDIO_ERRO_GERAL); }
  http.end();
}

// Dispara uma vez cada alerta antecipado de aproximação da origem ou destino.
void handleVibrationFeedback(int eta, const char* estado) {
  if (eta < 0) return;
  if (strcmp(estado, "MONITORANDO") == 0) {
    if (eta <= 7 && eta > 2 && !alerted_5_min_origin) { myDFPlayer.play(AUDIO_ONIBUS_PERTO_ORIGEM); vibratePattern(2, 500, 200); alerted_5_min_origin = true; }
    else if (eta <= 2 && !alerted_1_min_origin) { vibratePattern(4, 200, 100); alerted_1_min_origin = true; }
  } else if (strcmp(estado, "EM_VIAGEM") == 0) {
    if (eta <= 7 && eta > 2 && !alerted_5_min_dest) { myDFPlayer.play(AUDIO_DESTINO_PROXIMO); vibratePattern(2, 500, 200); alerted_5_min_dest = true; }
    else if (eta <= 2 && !alerted_1_min_dest) { myDFPlayer.play(AUDIO_PROXIMA_PARADA); vibratePattern(4, 200, 100); alerted_1_min_dest = true; }
  }
}

// --- Funções de baixo nível ---
void vibratePattern(int p, int d, int pa) { for(int i=0;i<p;i++){digitalWrite(VIBRATION_PIN,HIGH);delay(d);digitalWrite(VIBRATION_PIN,LOW);if(i<p-1)delay(pa);}}
// Configura o microfone I2S como entrada mono de 16 kHz e 16 bits.
void setupI2S() {
  i2s_config_t i2s_config = {.mode=(i2s_mode_t)(I2S_MODE_MASTER|I2S_MODE_RX),.sample_rate=SAMPLE_RATE,.bits_per_sample=BITS_PER_SAMPLE,.channel_format=I2S_CHANNEL_FMT_ONLY_LEFT,.communication_format=I2S_COMM_FORMAT_STAND_I2S,.intr_alloc_flags=ESP_INTR_FLAG_LEVEL1,.dma_buf_count=8,.dma_buf_len=1024,.use_apll=false,.tx_desc_auto_clear=false,.fixed_mclk=0};
  i2s_pin_config_t pin_config = {.bck_io_num=I2S_SCK_PIN,.ws_io_num=I2S_WS_PIN,.data_out_num=I2S_PIN_NO_CHANGE,.data_in_num=I2S_SD_PIN};
  i2s_driver_install(I2S_PORT,&i2s_config,0,NULL); i2s_set_pin(I2S_PORT,&pin_config);
}
void startRecording() {
  dataSize = 0;
  writeWavHeaderToBuffer(audioBuffer, SAMPLE_RATE, 16, 1);
  digitalWrite(LED_PIN, HIGH);
  currentState = RECORDING;
  i2s_zero_dma_buffer(I2S_PORT);
}
void stopAndUpload() {
  digitalWrite(LED_PIN, LOW);
  if (dataSize > 0) {
    updateWavHeaderInBuffer(audioBuffer, dataSize);
    uploadAudioBuffer();
  } else { currentState = IDLE; }
}
// Monta os 44 bytes iniciais do WAV PCM; os tamanhos são preenchidos ao terminar.
void writeWavHeaderToBuffer(uint8_t*b,unsigned int sr,uint16_t bps,uint16_t ch) {
  unsigned int br=sr*ch*(bps/8);b[0]='R';b[1]='I';b[2]='F';b[3]='F';b[4]=0;b[5]=0;b[6]=0;b[7]=0;b[8]='W';b[9]='A';b[10]='V';b[11]='E';b[12]='f';b[13]='m';b[14]='t';b[15]=' ';b[16]=16;b[17]=0;b[18]=0;b[19]=0;b[20]=1;b[21]=0;b[22]=ch;b[23]=0;b[24]=(byte)(sr&0xFF);b[25]=(byte)((sr>>8)&0xFF);b[26]=0;b[27]=0;b[28]=(byte)(br&0xFF);b[29]=(byte)((br>>8)&0xFF);b[30]=(byte)((br>>16)&0xFF);b[31]=(byte)((br>>24)&0xFF);b[32]=ch*(bps/8);b[33]=0;b[34]=bps;b[35]=0;b[36]='d';b[37]='a';b[38]='t';b[39]='a';b[40]=0;b[41]=0;b[42]=0;b[43]=0;
}
// Preenche os tamanhos RIFF e data com a quantidade real de áudio gravado.
void updateWavHeaderInBuffer(uint8_t*b,unsigned int ds){
  unsigned int fs=ds+36;b[4]=(byte)(fs&0xFF);b[5]=(byte)((fs>>8)&0xFF);b[6]=(byte)((fs>>16)&0xFF);b[7]=(byte)((fs>>24)&0xFF);b[40]=(byte)(ds&0xFF);b[41]=(byte)((ds>>8)&0xFF);b[42]=(byte)((ds>>16)&0xFF);b[43]=(byte)((ds>>24)&0xFF);
}
