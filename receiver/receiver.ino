const int LDR_PIN = A0;

int BIT_TIME_MS = 45;
int THRESHOLD   = 550;

bool isReceiving = false;
int rxBitIdx = 0;
byte rxCurrentByte = 0;
unsigned long nextRxSampleMicros = 0;
unsigned long lastTelemetryMillis = 0;

void setup() {
  Serial.begin(115200);
}

void loop() {
  unsigned long nowMicros = micros();
  unsigned long nowMillis = millis();

  while (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.startsWith("TH:")) {
      THRESHOLD = constrain(cmd.substring(3).toInt(), 10, 1020);
    } else if (cmd.startsWith("SPD:")) {
      BIT_TIME_MS = constrain(cmd.substring(4).toInt(), 5, 500);
    }
  }

  int ldrVal = analogRead(LDR_PIN);
  bool beamDetected = (ldrVal > THRESHOLD);

  if (!isReceiving) {
    if (beamDetected) {
      isReceiving = true;
      rxBitIdx = 0;
      rxCurrentByte = 0;
      // Sample 1.5 bit widths later to hit the dead center of bit 0
      nextRxSampleMicros = nowMicros + ((unsigned long)BIT_TIME_MS * 1500UL);
    }
  } else {
    if ((long)(nowMicros - nextRxSampleMicros) >= 0) {
      if (rxBitIdx < 8) {
        if (beamDetected) {
          rxCurrentByte |= (1 << (7 - rxBitIdx));
        }
        rxBitIdx++;
        nextRxSampleMicros += (unsigned long)BIT_TIME_MS * 1000UL;
      } else {
        Serial.print("RX:");
        Serial.println((int)rxCurrentByte);
        isReceiving = false;
      }
    }
  }

  if (nowMillis - lastTelemetryMillis >= 30) {
    lastTelemetryMillis = nowMillis;
    Serial.print("LDR:");
    Serial.println(ldrVal);
  }
}