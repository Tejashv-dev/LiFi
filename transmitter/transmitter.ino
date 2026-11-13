const int LASER_PIN = 7; // Digital pin connected to BC547 base (via 200-ohm resistor)

int BIT_TIME_MS = 45;

void setup() {
  pinMode(LASER_PIN, OUTPUT);
  digitalWrite(LASER_PIN, LOW);
  Serial.begin(115200);
}

// Pulses a single byte using framing: Start[1] + 8 data bits (MSB first) + Stop[0]
void transmitByte(byte b) {
  unsigned long bitMicros = (unsigned long)BIT_TIME_MS * 1000UL;

  // 1. Start Bit (HIGH)
  digitalWrite(LASER_PIN, HIGH);
  delayMicroseconds(bitMicros);

  // 2. 8 Data Bits (MSB to LSB)
  for (int i = 7; i >= 0; i--) {
    bool bitVal = (b >> i) & 1;
    digitalWrite(LASER_PIN, bitVal ? HIGH : LOW);
    delayMicroseconds(bitMicros);
  }

  // 3. Stop Bit / Guard Interval (LOW for 1.5 bit durations so RX cleanly resets)
  digitalWrite(LASER_PIN, LOW);
  delayMicroseconds(bitMicros + (bitMicros / 2));
}

void loop() {
  while (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    
    // Strip trailing carriage return (\r) without stripping leading/trailing spaces in TX messages
    if (cmd.endsWith("\r")) {
      cmd.remove(cmd.length() - 1);
    }

    if (cmd.startsWith("SPD:")) {
      BIT_TIME_MS = constrain(cmd.substring(4).toInt(), 5, 500);
    } 
    else if (cmd == "ALIGN_ON") {
      digitalWrite(LASER_PIN, HIGH);
    } 
    else if (cmd == "ALIGN_OFF") {
      digitalWrite(LASER_PIN, LOW);
    } 
    else if (cmd.startsWith("TXB:")) {
      // Live Mode: transmits a single raw ASCII byte (supports Backspace=8, Enter=10, Space=32, etc.)
      byte b = (byte)cmd.substring(4).toInt();
      transmitByte(b);
      Serial.println("TX_DONE");
    } 
    else if (cmd.startsWith("TX:")) {
      // Batch Mode: transmits the entire string sequentially
      String msg = cmd.substring(3);
      for (unsigned int i = 0; i < msg.length(); i++) {
        transmitByte((byte)msg[i]);
      }
      Serial.println("TX_DONE");
    }
  }
}