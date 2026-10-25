#include <Arduino.h>
#include <Wire.h>
#include <DHT.h>
#include <Adafruit_INA219.h>
#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <time.h>

// ==========================================
// 1. FEATURE FLAGS & CONTROL CONFIGURATION
// ==========================================
constexpr bool ENABLE_DUMMY_MODE = false;  
constexpr bool ENABLE_WIFI_TEST = true;    
constexpr bool ENABLE_DEMO_MODE = true;

// ==========================================
// 2. CONSTANTS & PIN DEFINITIONS
// ==========================================
const char* WIFI_SSID = "Redmi Note 10S";
const char* WIFI_PASSWORD = "63345919";

const char* GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbyI1ht0nzNpVPTjShN2vG2ySraaxtj6_TNFTjep7IZltd_G4ynmRSFOSf3YKXAbvXdp/exec";

#define DHTPIN 4
#define DHTTYPE DHT11
constexpr int I2C_SDA = 2;
constexpr int I2C_SCL = 3;

constexpr unsigned long READ_INTERVAL = 8000;         // Sensor read interval (8s)
constexpr unsigned long DEMO_UPLOAD_INTERVAL = 30000; // 30s upload interval for demo mode
constexpr unsigned long SENSOR_TIMEOUT = 1000;        

const long GMT_OFFSET_SEC = 19800;
const int DAYLIGHT_OFFSET_SEC = 0;

// ==========================================
// 3. GLOBAL VARIABLES & STATE TRACKERS
// ==========================================
char sheetsConnectionStatus[128] = "Not connected yet / Waiting...";

unsigned long lastReadTime = 0;
unsigned long lastUploadTime = 0;
int lastRecordedHour = -1;         
unsigned long nextCheckDelay = 10000; // Dynamic check interval

// Hourly Accumulators and Sample Count
float sumTemp = 0.0;
float sumHum = 0.0;
float sumVoltage = 0.0;
float sumVal_mA = 0.0;
float sumPower_mW = 0.0;
unsigned int sampleCount = 0;

// Live Dashboard State
float currentTemp = 0.0;
float currentHum = 0.0;
float currentVoltage = 0.0;
float currentVal_mA = 0.0;
float currentPower_mW = 0.0;
bool sensorDataValid = false;
bool dhtDetected = true;
bool inaDetected = true;

DHT dht(DHTPIN, DHTTYPE);
Adafruit_INA219 ina219;
WebServer server(80);

// ==========================================
// 4. WEB SERVER ENDPOINT HANDLER
// ==========================================
void handleRoot() {
  char html[1024];
  
  if (!sensorDataValid) {
    snprintf(html, sizeof(html),
      "<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
      "<title>ESP32-C3 Sensor Dashboard</title>"
      "<style>body{font-family:Arial,sans-serif;background:#f4f4f9;margin:0;padding:20px;text-align:center;}"
      ".card{background:white;padding:20px;margin:10px auto;max-width:400px;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);}"
      "h1{color:#333;} p{font-size:1.2em;color:#555;}</style></head><body>"
      "<h1>ESP32-C3 Live Dashboard</h1>"
      "<div class='card'><p>Waiting for valid sensor data...</p>"
      "<p><b>GSheets Status:</b> %s</p></div></body></html>",
      sheetsConnectionStatus
    );
  } else {
    snprintf(html, sizeof(html),
      "<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
      "<title>ESP32-C3 Sensor Dashboard</title>"
      "<style>body{font-family:Arial,sans-serif;background:#f4f4f9;margin:0;padding:20px;text-align:center;}"
      ".card{background:white;padding:20px;margin:10px auto;max-width:400px;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1);}"
      "h1{color:#333;} p{font-size:1.2em;color:#555;}</style></head><body>"
      "<h1>ESP32-C3 Live Dashboard</h1>"
      "<div class='card'>"
      "<p><b>Temperature:</b> %.1f C</p>"
      "<p><b>Humidity:</b> %.1f %%</p>"
      "<p><b>Voltage:</b> %.2f V</p>"
      "<p><b>Current:</b> %.2f mA</p>"
      "<p><b>Power:</b> %.2f mW</p>"
      "<hr style='border:0; border-top:1px solid #eee; margin:15px 0;'>"
      "<p style='font-size:0.9em;'><b>MCU to Google Sheets:</b><br>%s</p>"
      "</div></body></html>",
      currentTemp, currentHum, currentVoltage, currentVal_mA, currentPower_mW, sheetsConnectionStatus
    );
  }
  server.send(200, "text/html", html);
}

// ==========================================
// 5. GOOGLE SHEETS UPLOAD FUNCTION
// ==========================================
void sendDataToGoogleSheets() {
  if (sampleCount == 0) return;

  float avgTemp = sumTemp / sampleCount;
  float avgHum = sumHum / sampleCount;
  float avgVoltage = sumVoltage / sampleCount;
  float avgVal_mA = sumVal_mA / sampleCount;
  float avgPower_mW = sumPower_mW / sampleCount;

  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(GOOGLE_SCRIPT_URL);
    http.addHeader("Content-Type", "application/json");

    char payload[256];
    snprintf(payload, sizeof(payload), 
      "{\"temperature\":%.2f,\"humidity\":%.2f,\"voltage\":%.2f,\"current\":%.2f,\"power\":%.2f}",
      avgTemp, avgHum, avgVoltage, avgVal_mA, avgPower_mW
    );

    int httpResponseCode = http.POST(payload);
    if (httpResponseCode > 0) {
      Serial.printf("Cloud upload successful. Response code: %d\n", httpResponseCode);
      snprintf(sheetsConnectionStatus, sizeof(sheetsConnectionStatus), "Upload OK (Code: %d, Samples: %u)", httpResponseCode, sampleCount);
    } else {
      Serial.printf("Cloud upload failed. Error code: %d\n", httpResponseCode);
      snprintf(sheetsConnectionStatus, sizeof(sheetsConnectionStatus), "Upload Failed (Error: %d)", httpResponseCode);
    }
    http.end();
  } else {
    snprintf(sheetsConnectionStatus, sizeof(sheetsConnectionStatus), "Disconnected (WiFi unavailable)");
  }

  // Reset accumulators
  sumTemp = sumHum = sumVoltage = sumVal_mA = sumPower_mW = 0.0;
  sampleCount = 0;
}

// ==========================================
// 6. SETUP ROUTINE
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n\n=== ESP32-C3 Optimized Sensor Logger Setup ===");

  WiFi.persistent(false);
  WiFi.disconnect(true, true);
  delay(500);
  
  WiFi.setTxPower(WIFI_POWER_8_5dBm);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);

  Serial.println("Connecting to WiFi...");
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startAttemptTime = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startAttemptTime < 25000) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("-> WiFi CONNECTED SUCCESSFULLY!");
    Serial.print("IP Address : ");
    Serial.println(WiFi.localIP());

    configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET_SEC, "pool.ntp.org", "time.nist.gov");
    Serial.print("Synchronizing time with NTP");
    struct tm timeinfo;
    int retry = 0;
    while (!getLocalTime(&timeinfo) && retry < 10) {
      delay(500);
      Serial.print(".");
      retry++;
    }
    Serial.println();
  } else {
    Serial.println("-> WiFi CONNECTION FAILED!");
  }

  server.on("/", handleRoot);
  server.begin();
  Serial.println("HTTP web server started!");

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(100000); 

  dht.begin();
  delay(500);
  float test_h = dht.readHumidity();
  float test_t = dht.readTemperature();
  if (ENABLE_DUMMY_MODE || isnan(test_h) || isnan(test_t)) {
    dhtDetected = false;
    Serial.println("DHT11 in dummy mode.");
  } else {
    dhtDetected = true;
    Serial.println("DHT11 detected successfully!");
  }

  unsigned long initStart = millis();
  bool inaInitialized = false;
  while (!ENABLE_DUMMY_MODE && millis() - initStart < 5000) {
    if (ina219.begin()) {
      inaInitialized = true;
      break;
    }
    delay(500);
  }

  if (ENABLE_DUMMY_MODE || !inaInitialized) {
    inaDetected = false;
    Serial.println("INA219 in dummy mode.");
  } else {
    inaDetected = true;
    Serial.println("INA219 detected successfully!");
  }

  struct tm timeinfo;
  if (getLocalTime(&timeinfo)) {
    lastRecordedHour = timeinfo.tm_hour;
  }
  
  lastUploadTime = millis();
}

// ==========================================
// 7. MAIN LOOP
// ==========================================
void loop() {
  server.handleClient(); 
  unsigned long currentMillis = millis();

  // Non-blocking sensor read interval
  if (currentMillis - lastReadTime >= READ_INTERVAL) {
    lastReadTime = currentMillis;

    float h = NAN;
    float t = NAN;
    if (dhtDetected) {
      unsigned long dhtStart = millis();
      while (millis() - dhtStart < SENSOR_TIMEOUT) {
        h = dht.readHumidity();
        t = dht.readTemperature();
        if (!isnan(h) && !isnan(t)) break;
        delay(100);
      }
    }

    if (!dhtDetected || isnan(h) || isnan(t)) {
      t = 25.0 + ((currentMillis / 1000) % 10);
      h = 50.0 + ((currentMillis / 1000) % 15);
    }

    float shuntvoltage = 0.0;
    float busvoltage = 0.0;
    float current_mA = 0.0;
    float loadvoltage = 0.0;
    float power_mW = 0.0;

    if (inaDetected) {
      shuntvoltage = ina219.getShuntVoltage_mV();
      busvoltage = ina219.getBusVoltage_V();
      current_mA = ina219.getCurrent_mA();
      loadvoltage = busvoltage + (shuntvoltage / 1000.0);
      power_mW = ina219.getPower_mW();
    } else {
      loadvoltage = 3.3 + (((currentMillis / 1000) % 5) * 0.1);
      current_mA = 100.0 + ((currentMillis / 1000) % 50);
      power_mW = loadvoltage * current_mA;
    }

    currentTemp = t;
    currentHum = h;
    currentVoltage = loadvoltage;
    currentVal_mA = current_mA;
    currentPower_mW = power_mW;
    sensorDataValid = true;

    sumTemp += t;
    sumHum += h;
    sumVoltage += loadvoltage;
    sumVal_mA += current_mA;
    sumPower_mW += power_mW;
    sampleCount++;

    Serial.printf("Sample #%u | Temp: %.1f C | Humidity: %.1f%% | Voltage: %.2f V\n", sampleCount, t, h, loadvoltage);
    Serial.println("----------------------------------------");
  }

  // Upload Handling: Demo Mode vs Normal Hourly Mode
  if (ENABLE_DEMO_MODE) {
    // In demo mode, upload every 30 seconds so you can show live updates immediately
    if (currentMillis - lastUploadTime >= DEMO_UPLOAD_INTERVAL) {
      lastUploadTime = currentMillis;
      Serial.println("Demo Mode: Sending sample batch to Google Sheets...");
      sendDataToGoogleSheets();
    }
  } else {
    // Production Mode: Calculate exact milliseconds remaining until the next hour transition
    time_t now;
    time(&now);
    struct tm timeinfo;
    if (getLocalTime(&timeinfo)) {
      if (lastRecordedHour == -1) {
        lastRecordedHour = timeinfo.tm_hour;
      } else if (timeinfo.tm_hour != lastRecordedHour) {
        Serial.println("Hour changed! Processing and uploading hourly averages...");
        sendDataToGoogleSheets();
        lastRecordedHour = timeinfo.tm_hour;
      }
    }
  }
}