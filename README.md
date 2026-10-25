# ESP32-C3 Sensor Dashboard & Web App

## Prerequisites
* **Tools:** Arduino IDE 2.x, Astral `uv`
* **Hardware:** ESP32-C3, DHT11, INA219

## Install & Configure
1. Install Arduino libraries (**Adafruit DHT Sensor Library** and **Adafruit INA219**) via **Tools > Manage Libraries...**.
2. Run `uv sync` in the project root directory.
3. Open the sketch in Arduino IDE, select the ESP32-C3 board and COM port, then compile and upload.

## Run
1. Start the web app:
   ```bash
   uv run app.py
   ```
2. Power on or reset the ESP32-C3.

## Cleanup
* Delete the local virtual environment directory (`.venv`).
* Clear the package cache:
  ```bash
  uv cache clean
  ```

  https://docs.google.com/spreadsheets/d/15F194vrJJNnuHxXpFhss0EsLHfVUf3yhx8eKEWV0EDU/edit?usp=sharing