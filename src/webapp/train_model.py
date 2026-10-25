# train_model.py
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor, IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
import warnings
warnings.filterwarnings('ignore')

def load_and_preprocess(filename='synthetic_solar_data.csv'):
    print(f"Loading data from {filename}...")
    df = pd.read_csv(filename)
    
    # Convert timestamp and set as index
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.dropna() # Remove IoT packet timeout NaNs (~0.8%)
    
    # Extract temporal features
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_year'] = df['timestamp'].dt.dayofyear
    df['progress'] = np.linspace(0, 1, len(df)) # Normalized timeline progress
    
    # Filter daylight hours only (irradiance/power active period)
    df_day = df[df['power'] > 0.1].copy()
    
    # Temperature Correction for Power (Normalize to 25 deg C standard test conditions)
    # Efficiency drop is -0.35% per deg C above 25 deg C
    df_day['temp_correction_factor'] = 1.0 + 0.0035 * np.maximum(0, df_day['temperature'] - 25.0)
    df_day['corrected_power'] = df_day['power'] * df_day['temp_correction_factor']
    
    return df, df_day

def train_degradation_regressor(df_day):
    print("\n--- Training Gradual Degradation Regressor ---")
    
    # Features for predicting long-term health/power degradation
    features = ['hour', 'day_of_year', 'temperature', 'humidity', 'voltage', 'corrected_power']
    X = df_day[features]
    
    # Target: We want to estimate the underlying long-term capacity or health proxy
    # Using rolling daily max corrected power as a stable target proxy
    df_day['daily_peak_power'] = df_day.groupby(df_day['timestamp'].dt.date)['corrected_power'].transform('max')
    y = df_day['daily_peak_power']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    
    y_pred = model.predict(X_test)
    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    print(f"Model Evaluation -> R2 Score: {r2:.4f} | RMSE: {np.sqrt(mse):.4f} mW")
    return model

def train_anomaly_detector(df_day):
    print("\n--- Training Micro-Crack / Fault Anomaly Detector ---")
    
    # Isolation Forest is ideal for unsupervised anomaly detection (sudden current/power drops)
    features = ['temperature', 'humidity', 'voltage', 'current', 'power', 'corrected_power']
    X = df_day[features]
    
    # Contamination factor set to match expected anomalies (e.g., ~20% of data affected late in the season)
    iso_forest = IsolationForest(contamination=0.15, random_state=42, n_jobs=-1)
    df_day['anomaly'] = iso_forest.fit_predict(X)
    
    # -1 indicates anomaly/outlier, 1 indicates normal operation
    anomalies_detected = (df_day['anomaly'] == -1).sum()
    print(f"Anomaly Detection Complete. Flagged {anomalies_detected} anomalous data points.")
    
    return iso_forest, df_day

if __name__ == '__main__':
    df_raw, df_day = load_and_preprocess()
    regressor = train_degradation_regressor(df_day)
    anomaly_model, processed_df = train_anomaly_detector(df_day)
    
    print("\nTraining pipeline executed successfully. Models are ready for deployment or evaluation.")