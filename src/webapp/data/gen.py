import pandas as pd
import numpy as np

# Configuration (Adapted for indoor testing of a 6V 300mA panel capping at 3V max)
START_DATE = '2025-04-01'
END_DATE = '2025-10-01'
FREQ = '1h'  # Matches hourly averages uploaded by main.cpp
FILENAME = 'synthetic_solar_data.csv'

print(f"Generating synthetic indoor-test data from {START_DATE} to {END_DATE}...")

# Create time range
timestamps = pd.date_range(start=START_DATE, end=END_DATE, freq=FREQ)
n_records = len(timestamps)

# Initialize DataFrame
df = pd.DataFrame({'timestamp': timestamps})

# Extract temporal features
hour_float = df['timestamp'].dt.hour + df['timestamp'].dt.minute / 60.0
day_of_year = df['timestamp'].dt.dayofyear

# Base parameters for indoor hardware architecture (INA219 scale: Volts & mA -> mW)
MAX_VOLTAGE = 3.0      # Volts (Capped at 3V due to indoor lighting limits)
PANEL_MAX_CURRENT = 300.0 # mA (Panel rating)
INDOOR_LIGHT_FACTOR = 0.08 # Indoor artificial lighting scales down irradiance (~8%)
DEGRADATION_RATE = 0.15 # 15% slow degradation over the 6-month period

# 1. Vectorized Progress and Health Factor
progress = np.linspace(0, 1, n_records)
health_factor = 1.0 - (DEGRADATION_RATE * progress)

# 2. Realistic Cloud Cover & Monsoon Volatility
is_monsoon = (day_of_year >= 152) & (day_of_year <= 273)
cloud_prob_threshold = np.where(is_monsoon, 0.50, 0.85)
cloud_cover = np.where(np.random.random(n_records) > cloud_prob_threshold, np.random.uniform(0.5, 0.95, n_records), 1.0)

# 3. Meteorological Realism: Temperature & Humidity
seasonal_temp_base = 28.0 + 5.0 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
temp_amplitude = 10.0 * (cloud_cover) 
temp_sine = np.sin(np.pi * np.clip(hour_float - 6, 0, 16) / 16)
temp = seasonal_temp_base + (temp_amplitude * temp_sine) + np.random.normal(0, 1.5, n_records)

monsoon_humidity_boost = np.where(is_monsoon, 20.0, 0.0)
cloud_humidity_boost = (1.0 - cloud_cover) * 30.0
humidity = 75.0 - (temp - 25) * 1.5 + monsoon_humidity_boost + cloud_humidity_boost + np.random.normal(0, 3, n_records)
humidity = np.clip(humidity, 40.0, 98.0)

# 4. Solar Physics & Indoor Lighting Profile
irradiance = np.sin(np.pi * np.clip(hour_float - 6, 0, 12) / 12) * INDOOR_LIGHT_FACTOR
irradiance = np.where((hour_float >= 6) & (hour_float <= 18), irradiance, 0.0)

# Efficiency drop based on temperature coefficient (-0.35% per °C above 25°C)
efficiency = 1.0 - 0.0035 * np.maximum(0, temp - 25)

# Voltage calculation
voltage_sag = 0.02 * np.maximum(0, temp - 25)
night_voltage = np.random.normal(0.02, 0.01, n_records)
voltage = np.where(irradiance > 0, MAX_VOLTAGE - voltage_sag + np.random.normal(0, 0.05, n_records), night_voltage)
voltage = np.clip(voltage, 0.0, MAX_VOLTAGE)

# 5. Fixed Current Calculation (Removed double scaling)
current = PANEL_MAX_CURRENT * irradiance * cloud_cover * efficiency * health_factor
current = np.where(progress > 0.80, current * 0.85, current) # Micro-crack drop event
current = np.maximum(0.0, current + np.random.normal(0, 1.0, n_records)) # Sensor noise

# Round early to keep calculations physically synchronized
df['temperature'] = np.round(temp, 1)
df['humidity'] = np.round(humidity, 1)
df['voltage'] = np.round(voltage, 2)
df['current'] = np.round(current, 2)

# Power explicitly computed in milliwatts (mW) using rounded elements
df['power'] = np.round(df['voltage'] * df['current'], 2)

# 6. Inject Realistic IoT Sensor Anomalies (Masking all features for real packet losses)
nan_mask = np.random.random(n_records) < 0.008
target_cols = ['temperature', 'humidity', 'voltage', 'current', 'power']
for col in target_cols:
    df[col] = np.where(nan_mask, np.nan, df[col])

# Timestamp formatting (24-hour format)
df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')

# Save to CSV
df.to_csv(FILENAME, index=False)
print(f"Successfully generated {n_records} rows of indoor-constrained synthetic data in '{FILENAME}'.")
