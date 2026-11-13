// // Arduino Transmitter Firmware (PC #1)
// // Pin 7 -> 1kΩ resistor -> BC547 Base

// const int LASER_PIN = 7;
// int BIT_TIME_MS = 45;

// String txQueue = "";
// bool isTransmitting = false;
// int txCharIdx = 0;
// int txBitIdx = -1; // -1: Start bit (1), 0..7: Data bits (MSB first), 8: Stop bit (0)
// unsigned long lastTxMicros = 0;

// void setup() {
//   Serial.begin(115200);
//   pinMode(LASER_PIN, OUTPUT);
//   digitalWrite(LASER_PIN, LOW);
// }

// void loop() {
//   unsigned long nowMicros = micros();

//   while (Serial.available()) {
//     String cmd = Serial.readStringUntil('\n');
//     cmd.trim();
//     if (cmd.startsWith("TX:")) {
//       txQueue += cmd.substring(3);
//       if (!isTransmitting && txQueue.length() > 0) {
//         isTransmitting = true;
//         txCharIdx = 0;
//         txBitIdx = -1;
//         lastTxMicros = nowMicros;
//       }
//     } else if (cmd.startsWith("SPD:")) {
//       BIT_TIME_MS = constrain(cmd.substring(4).toInt(), 15, 250);
//     } else if (cmd == "ALIGN_ON") {
//       isTransmitting = false;
//       txQueue = "";
//       digitalWrite(LASER_PIN, HIGH);
//     } else if (cmd == "ALIGN_OFF") {
//       digitalWrite(LASER_PIN, LOW);
//     }
//   }

//   if (isTransmitting) {
//     if (nowMicros - lastTxMicros >= (unsigned long)BIT_TIME_MS * 1000UL) {
//       lastTxMicros += (unsigned long)BIT_TIME_MS * 1000UL;

//       if (txBitIdx == -1) {
//         digitalWrite(LASER_PIN, HIGH); // Start bit
//         txBitIdx = 0;
//       } else if (txBitIdx < 8) {
//         char c = txQueue[txCharIdx];
//         bool bitVal = (c >> (7 - txBitIdx)) & 0x01;
//         digitalWrite(LASER_PIN, bitVal ? HIGH : LOW);
//         txBitIdx++;
//       } else {
//         digitalWrite(LASER_PIN, LOW); // Stop bit
//         txBitIdx = -1;
//         txCharIdx++;
//         if (txCharIdx >= (int)txQueue.length()) {
//           isTransmitting = false;
//           txQueue = "";
//           Serial.println("TX_DONE");
//         }
//       }
//     }
//   }
// }


// Arduino Receiver Firmware (PC #2)
// 5V -> LDR -> Pin A0 -> 10kΩ Resistor -> GND

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
      THRESHOLD = cmd.substring(3).toInt();
    } else if (cmd.startsWith("SPD:")) {
      BIT_TIME_MS = constrain(cmd.substring(4).toInt(), 15, 250);
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
      nextRxSampleMicros = nowMicros + (unsigned long)(BIT_TIME_MS * 1500UL);
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