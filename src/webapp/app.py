# app.py
from flask import Flask, render_template_string, jsonify, request
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import threading
import time

app = Flask(__name__)

# CONFIGURATION
ESP32_URL = "10.159.156.227/json"  # Replace with your ESP32 local IP

# Replace with your actual Google Sheet ID (extracted from your spreadsheet URL)
SPREADSHEET_ID = "15F194vrJJNnuHxXpFhss0EsLHfVUf3yhx8eKEWV0EDU"
GOOGLE_CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv"
)

# Global Cache Store
cache_lock = threading.Lock()
cached_analytics_data = {
    "timestamps": [],
    "corrected_power": [],
    "baseline_peak": 1.0,
    "health_index": 100.0,
    "maintenance_events": {},
    "last_updated": None,
}


def update_sheet_cache():
    """Background worker that fetches CSV from Google Sheets once an hour
    and pre-processes the Pandas DataFrame with a cooldown mechanism for maintenance events.
    """
    global cached_analytics_data
    while True:
        try:
            print(f"[{datetime.now()}] Fetching Google Sheet CSV data...")
            df = pd.read_csv(GOOGLE_CSV_URL)

            if not df.empty:
                df.columns = [c.strip().lower() for c in df.columns]

                if "timestamp" in df.columns and "power" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
                    df.dropna(subset=["timestamp"], inplace=True)
                    df = df.sort_values("timestamp")

                    df["temperature"] = pd.to_numeric(
                        df["temperature"], errors="coerce"
                    )
                    df["power"] = pd.to_numeric(df["power"], errors="coerce")
                    df.dropna(subset=["temperature", "power"], inplace=True)

                    # Resample to hourly averages to keep the chart clean and lightning fast
                    df = (
                        df.set_index("timestamp")
                        .resample("1h")
                        .mean(numeric_only=True)
                        .reset_index()
                    )
                    df.dropna(subset=["temperature", "power"], inplace=True)

                    df["timestamp_str"] = df["timestamp"].dt.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")

                    if not df.empty:
                        # 1. Temperature Correction formula to STC (25°C)
                        df["corrected_power"] = df["power"] * (
                            1 + 0.0035 * (25 - df["temperature"])
                        )

                        # 2. Baseline Peak Power
                        baseline_peak = (
                            df["corrected_power"].quantile(0.95)
                            if len(df) > 10
                            else df["corrected_power"].max()
                        )
                        if baseline_peak == 0:
                            baseline_peak = 1.0

                        # 3. Recent Rolling Peak & Health Index
                        recent_window = min(len(df), 24)
                        recent_peak = df["corrected_power"].tail(recent_window).max()
                        health_index = min(100.0, (recent_peak / baseline_peak) * 100.0)

                        # 4. Automated Predictive Maintenance Scheduler with Cooldown
                        daily_groups = sorted(list(df.groupby("date_str")), key=lambda x: x[0])
                        maintenance_events = {}
                        cooldown_until = None

                        for d_str, group in daily_groups:
                            # Skip days falling within an active maintenance cooldown window
                            if cooldown_until and d_str <= cooldown_until:
                                continue

                            day_peak = group["corrected_power"].max()
                            daily_health = (day_peak / baseline_peak) * 100.0

                            dt_obj = datetime.strptime(d_str, "%Y-%m-%d")

                            if daily_health < 50.0:
                                maintenance_events[d_str] = {
                                    "title": "Panel Replacement",
                                    "css": "event-replace",
                                    "desc": (
                                        f"Critical Degradation Detected! Health: {daily_health:.1f}%. "
                                        f"Immediate replacement recommended."
                                    ),
                                }
                                # Cooldown for 14 days after a replacement notice
                                cooldown_until = (dt_obj + timedelta(days=14)).strftime("%Y-%m-%d")
                            elif daily_health < 75.0:
                                maintenance_events[d_str] = {
                                    "title": "Class 2 Maintenance",
                                    "css": "event-class2",
                                    "desc": (
                                        f"Moderate Degradation. Health: {daily_health:.1f}%. "
                                        f"Deep cleaning & thermal inspection required."
                                    ),
                                }
                                # Cooldown for 14 days after class 2 maintenance
                                cooldown_until = (dt_obj + timedelta(days=14)).strftime("%Y-%m-%d")
                            elif daily_health < 88.0:
                                maintenance_events[d_str] = {
                                    "title": "Class 1 Maintenance",
                                    "css": "event-class1",
                                    "desc": (
                                        f"Minor Degradation / Dust buildup. Health: {daily_health:.1f}%. "
                                        f"Surface washing recommended."
                                    ),
                                }
                                # Cooldown for 7 days after minor maintenance notice
                                cooldown_until = (dt_obj + timedelta(days=7)).strftime("%Y-%m-%d")

                        with cache_lock:
                            cached_analytics_data = {
                                "success": True,
                                "timestamps": df["timestamp_str"].tolist(),
                                "corrected_power": df["corrected_power"].tolist(),
                                "baseline_peak": float(baseline_peak),
                                "health_index": float(health_index),
                                "maintenance_events": maintenance_events,
                                "last_updated": datetime.now().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                ),
                            }
                        print(
                            f"[{datetime.now()}] Google Sheet CSV successfully cached ("
                            f"{len(df)} rows processed)."
                        )
        except Exception as e:
            print(f"[{datetime.now()}] Error updating sheet cache: {e}")

        time.sleep(3600)

# Start background thread for hourly updates
threading.Thread(target=update_sheet_cache, daemon=True).start()

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Solar PV Dashboard & Maintenance Calendar</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #f4f4f9;
            --card-bg: #ffffff;
            --text-color: #333333;
            --sidebar-bg: #ffffff;
            --sidebar-border: #e2e8f0;
            --nav-bg: #ffffff;
            --primary-color: #007bff;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        }

        body.dark-mode {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-color: #f1f5f9;
            --sidebar-bg: #1e293b;
            --sidebar-border: #334155;
            --nav-bg: #1e293b;
            --primary-color: #38bdf8;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5);
        }

        body {
            font-family: Arial, sans-serif;
            background: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 0;
            transition: background 0.3s ease, color 0.3s ease;
        }

        /* Top Navbar */
        .navbar {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            height: 60px;
            background: var(--nav-bg);
            border-bottom: 1px solid var(--sidebar-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 20px;
            z-index: 1000;
            box-shadow: var(--shadow);
        }

        .navbar-left {
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .hamburger {
            background: none;
            border: none;
            font-size: 1.5em;
            cursor: pointer;
            color: var(--text-color);
            padding: 5px 10px;
            border-radius: 4px;
        }

        .hamburger:hover {
            background: rgba(0,0,0,0.05);
        }

        .navbar-brand {
            font-size: 1.2em;
            font-weight: bold;
            color: var(--text-color);
        }

        .theme-toggle {
            background: none;
            border: 1px solid var(--sidebar-border);
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            color: var(--text-color);
            font-size: 1em;
            transition: background 0.2s;
        }

        .theme-toggle:hover {
            background: rgba(0,0,0,0.05);
        }

        /* Left Sidebar */
        .sidebar {
            position: fixed;
            top: 60px;
            left: 0;
            width: 240px;
            height: calc(100vh - 60px);
            background: var(--sidebar-bg);
            border-right: 1px solid var(--sidebar-border);
            padding-top: 20px;
            transition: transform 0.3s ease;
            z-index: 999;
        }

        .sidebar.collapsed {
            transform: translateX(-100%);
        }

        .sidebar-menu {
            list-style: none;
            padding: 0;
            margin: 0;
        }

        .sidebar-item {
            padding: 15px 25px;
            cursor: pointer;
            font-weight: bold;
            color: var(--text-color);
            display: flex;
            align-items: center;
            gap: 12px;
            transition: background 0.2s, color 0.2s;
            border-left: 4px solid transparent;
        }

        .sidebar-item:hover {
            background: rgba(0, 123, 255, 0.1);
        }

        .sidebar-item.active {
            background: rgba(0, 123, 255, 0.15);
            color: var(--primary-color);
            border-left-color: var(--primary-color);
        }

        /* Main Content Area */
        .main-content {
            margin-top: 80px;
            margin-left: 240px;
            padding: 20px;
            transition: margin-left 0.3s ease;
        }

        .main-content.expanded {
            margin-left: 0;
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
        }

        .grid { 
            display: flex; 
            justify-content: center; 
            gap: 15px; 
            flex-wrap: wrap; 
            margin-bottom: 20px; 
        }

        .card { 
            background: var(--card-bg); 
            padding: 15px; 
            width: 170px; 
            border-radius: 8px; 
            box-shadow: var(--shadow); 
            border: 1px solid var(--sidebar-border);
        }

        .card h3 { 
            margin: 0 0 8px 0; 
            color: var(--text-color); 
            font-size: 1.0em; 
            opacity: 0.8;
        }

        .card p { 
            font-size: 1.3em; 
            margin: 0; 
            color: var(--primary-color); 
            font-weight: bold; 
        }

        .section { 
            background: var(--card-bg); 
            padding: 20px; 
            max-width: 950px; 
            margin: 20px auto; 
            border-radius: 8px; 
            box-shadow: var(--shadow); 
            border: 1px solid var(--sidebar-border);
        }

        .section h3 {
            margin-top: 0;
            color: var(--text-color);
        }

        canvas { 
            max-height: 320px; 
            width: 100% !important;
        }

        /* Calendar & Chart Controls */
        .calendar-controls {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }

        .view-switchers button, .calendar-controls button {
            background: var(--card-bg);
            border: 1px solid var(--sidebar-border);
            color: var(--text-color);
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.2s;
        }

        .view-switchers button:hover, .calendar-controls button:hover {
            background: rgba(0,0,0,0.05);
        }

        .view-switchers button.active {
            background: var(--primary-color);
            color: white;
            border-color: var(--primary-color);
        }

        .calendar-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 8px;
        }

        .calendar-header-day {
            text-align: center;
            font-weight: bold;
            padding: 8px;
            background: rgba(0,0,0,0.03);
            border-radius: 4px;
            font-size: 0.9em;
        }

        .calendar-cell {
            background: var(--card-bg);
            border: 1px solid var(--sidebar-border);
            border-radius: 6px;
            min-height: 90px;
            padding: 6px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
        }

        .calendar-cell.other-month {
            opacity: 0.4;
        }

        .cell-date {
            font-size: 0.85em;
            font-weight: bold;
            opacity: 0.7;
        }

        .event-badge {
            font-size: 0.75em;
            padding: 3px 6px;
            border-radius: 4px;
            margin-top: 2px;
            font-weight: bold;
            color: #fff;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .event-class1 { background-color: #ffc107; color: #333; }
        .event-class2 { background-color: #fd7e14; }
        .event-replace { background-color: #dc3545; }

        @media (max-width: 768px) {
            .sidebar {
                transform: translateX(-100%);
            }
            .sidebar.mobile-open {
                transform: translateX(0);
            }
            .main-content {
                margin-left: 0 !important;
            }
        }
    </style>
</head>
<body>

    <!-- Top Navbar -->
    <header class="navbar">
        <div class="navbar-left">
            <button class="hamburger" id="hamburgerBtn" onclick="toggleSidebar()">&#9776;</button>
            <span class="navbar-brand">Solar PV Monitoring System</span>
        </div>
        <button class="theme-toggle" id="themeToggle" onclick="toggleTheme()">&#127765; Dark Mode</button>
    </header>

    <!-- Left Sidebar Menu -->
    <nav class="sidebar" id="sidebar">
        <ul class="sidebar-menu">
            <li class="sidebar-item active" onclick="switchTab('dashboard', this)">
                <span>&#128202;</span> Dashboard
            </li>
            <li class="sidebar-item" onclick="switchTab('degradation', this)">
                <span>&#128200;</span> Degradation Analytics
            </li>
            <li class="sidebar-item" onclick="switchTab('maintenance', this)">
                <span>&#128197;</span> Maintenance Calendar
            </li>
        </ul>
    </nav>

    <!-- Main Content Area -->
    <main class="main-content" id="mainContent">

        <!-- Tab 1: Dashboard -->
        <div id="tab-dashboard" class="tab-content active">
            <h1 style="text-align: center; margin-bottom: 25px;">Live Solar PV Dashboard</h1>
            
            <div class="grid">
                <div class="card"><h3>Temperature</h3><p id="temp">-- &deg;C</p></div>
                <div class="card"><h3>Humidity</h3><p id="hum">-- %</p></div>
                <div class="card"><h3>Voltage</h3><p id="volt">-- V</p></div>
                <div class="card"><h3>Current</h3><p id="curr">-- mA</p></div>
                <div class="card"><h3>Power</h3><p id="power">-- mW</p></div>
            </div>

            <div class="section">
                <h3>Real-Time Power Output (mW)</h3>
                <canvas id="liveChart"></canvas>
            </div>
        </div>

        <!-- Tab 2: Degradation -->
        <div id="tab-degradation" class="tab-content">
            <h1 style="text-align: center; margin-bottom: 25px;">Health & Degradation Analytics</h1>

            <div class="grid">
                <div class="card" style="width: 250px;">
                    <h3>System Health Index</h3>
                    <p id="health">-- %</p>
                </div>
            </div>

            <div class="section">
                <div class="calendar-controls">
                    <div>
                        <button onclick="changeHistoryPeriod(-1)">&larr; Prev</button>
                        <span id="historyPeriodTitle" style="font-weight: bold; margin: 0 15px; font-size: 1.1em;">Loading...</span>
                        <button onclick="changeHistoryPeriod(1)">Next &rarr;</button>
                    </div>
                    <div class="view-switchers" id="historyViewSwitchers">
                        <button id="hist-btn-daily" onclick="setHistoryView('daily')">Daily</button>
                        <button id="hist-btn-weekly" onclick="setHistoryView('weekly')">Weekly</button>
                        <button id="hist-btn-monthly" class="active" onclick="setHistoryView('monthly')">Monthly</button>
                    </div>
                </div>
                <h3>Long-Term Solar PV Degradation & Corrected Power (STC 25&deg;C)</h3>
                <canvas id="historyChart"></canvas>
            </div>
        </div>

        <!-- Tab 3: Maintenance Calendar -->
        <div id="tab-maintenance" class="tab-content">
            <h1 style="text-align: center; margin-bottom: 20px;">Automated Maintenance Schedule & Calendar</h1>

            <div class="section">
                <div class="calendar-controls">
                    <div>
                        <button onclick="changeDate(-1)">&larr; Prev</button>
                        <span id="calendarTitle" style="font-weight: bold; margin: 0 15px; font-size: 1.1em;"></span>
                        <button onclick="changeDate(1)">Next &rarr;</button>
                    </div>
                    <div class="view-switchers">
                        <button id="btn-daily" onclick="setView('daily')">Daily</button>
                        <button id="btn-weekly" onclick="setView('weekly')">Weekly</button>
                        <button id="btn-monthly" class="active" onclick="setView('monthly')">Monthly</button>
                        <button id="btn-yearly" onclick="setView('yearly')">Yearly</button>
                    </div>
                </div>

                <div id="calendarContainer"></div>
            </div>
        </div>

    </main>

    <script>
        function toggleSidebar() {
            const sidebar = document.getElementById('sidebar');
            const mainContent = document.getElementById('mainContent');
            if (window.innerWidth <= 768) {
                sidebar.classList.toggle('mobile-open');
            } else {
                sidebar.classList.toggle('collapsed');
                mainContent.classList.toggle('expanded');
            }
        }

        function switchTab(tabId, element) {
            document.querySelectorAll('.sidebar-item').forEach(item => item.classList.remove('active'));
            element.classList.add('active');

            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
            document.getElementById('tab-' + tabId).classList.add('active');

            if (window.innerWidth <= 768) {
                document.getElementById('sidebar').classList.remove('mobile-open');
            }
        }

        function toggleTheme() {
            const body = document.body;
            const themeToggleBtn = document.getElementById('themeToggle');
            body.classList.toggle('dark-mode');
            
            if (body.classList.contains('dark-mode')) {
                themeToggleBtn.innerHTML = '&#9728;&#65039; Light Mode';
                localStorage.setItem('theme', 'dark');
            } else {
                themeToggleBtn.innerHTML = '&#127765; Dark Mode';
                localStorage.setItem('theme', 'light');
            }
        }

        let globalMaintenanceEvents = {};
        let currentView = 'monthly';
        let currentDateCursor = new Date();

        // Degradation History State
        let fullAnalyticsData = null;
        let currentHistoryView = 'monthly';
        let historyDateCursor = new Date();
        let historyCursorInitialized = false;

        window.addEventListener('DOMContentLoaded', () => {
            if (localStorage.getItem('theme') === 'dark') {
                document.body.classList.add('dark-mode');
                document.getElementById('themeToggle').innerHTML = '&#9728;&#65039; Light Mode';
            }
            
            renderCalendar(); 
            fetchAnalyticsData();
        });

        // Charts Setup (Continuous line with pointRadius: 0)
        const liveCtx = document.getElementById('liveChart').getContext('2d');
        const liveChart = new Chart(liveCtx, {
            type: 'line',
            data: { labels: [], datasets: [{ label: 'Live Power (mW)', data: [], borderColor: '#ffc107', backgroundColor: 'rgba(255, 193, 7, 0.2)', borderWidth: 2, fill: true, tension: 0.3, pointRadius: 0, pointHoverRadius: 4 }] },
            options: { responsive: true, scales: { x: { title: { display: true, text: 'Time' } }, y: { title: { display: true, text: 'Power (mW)' }, beginAtZero: true } } }
        });

        const historyCtx = document.getElementById('historyChart').getContext('2d');
        const historyChart = new Chart(historyCtx, {
            type: 'line',
            data: { labels: [], datasets: [
                { label: 'Corrected Power (STC 25C)', data: [], borderColor: '#28a745', backgroundColor: 'rgba(40, 167, 69, 0.1)', borderWidth: 2, fill: true, tension: 0.2, pointRadius: 0, pointHoverRadius: 4 },
                { label: 'Baseline Peak Power', data: [], borderColor: '#dc3545', borderDash: [5,5], borderWidth: 2, fill: false, pointRadius: 0 }
            ]},
            options: { 
                responsive: true, 
                scales: { 
                    x: { 
                        title: { display: true, text: 'Timestamp' },
                        ticks: {
                            maxTicksLimit: 10,
                            autoSkip: true
                        }
                    }, 
                    y: { 
                        title: { display: true, text: 'Power (mW)' }, 
                        beginAtZero: true 
                    } 
                } 
            }
        });

        async function fetchLiveData() {
            try {
                let res = await fetch('/api/live');
                let data = await res.json();
                if (data.valid) {
                    document.getElementById('temp').innerText = data.temperature.toFixed(1) + ' C';
                    document.getElementById('hum').innerText = data.humidity.toFixed(1) + ' %';
                    document.getElementById('volt').innerText = data.voltage.toFixed(2) + ' V';
                    document.getElementById('curr').innerText = data.current.toFixed(2) + ' mA';
                    document.getElementById('power').innerText = data.power.toFixed(2) + ' mW';

                    let timeStr = new Date().toLocaleTimeString();
                    if (liveChart.data.labels.length > 25) {
                        liveChart.data.labels.shift();
                        liveChart.data.datasets[0].data.shift();
                    }
                    liveChart.data.labels.push(timeStr);
                    liveChart.data.datasets[0].data.push(data.power);
                    liveChart.update();
                }
            } catch (err) { console.error("Live fetch error:", err); }
        }

        async function fetchAnalyticsData() {
            try {
                let res = await fetch('/api/analytics');
                let result = await res.json();
                if (result.success) {
                    document.getElementById('health').innerText = result.health_index.toFixed(1) + ' %';
                    fullAnalyticsData = result;

                    if (!historyCursorInitialized && result.timestamps && result.timestamps.length > 0) {
                        historyDateCursor = new Date(result.timestamps[0]);
                        historyCursorInitialized = true;
                    }

                    updateHistoryChart();

                    globalMaintenanceEvents = result.maintenance_events || {};
                    renderCalendar();
                }
            } catch (err) { console.error("Analytics fetch error:", err); }
        }

        // Degradation History View & Navigation Controllers
        function setHistoryView(view) {
            currentHistoryView = view;
            document.querySelectorAll('#historyViewSwitchers button').forEach(b => b.classList.remove('active'));
            document.getElementById('hist-btn-' + view).classList.add('active');
            updateHistoryChart();
        }

        function changeHistoryPeriod(direction) {
            if (currentHistoryView === 'daily') {
                historyDateCursor.setDate(historyDateCursor.getDate() + direction);
            } else if (currentHistoryView === 'weekly') {
                historyDateCursor.setDate(historyDateCursor.getDate() + (direction * 7));
            } else if (currentHistoryView === 'monthly') {
                historyDateCursor.setMonth(historyDateCursor.getMonth() + direction);
            }
            updateHistoryChart();
        }

        function updateHistoryChart() {
            if (!fullAnalyticsData || !fullAnalyticsData.timestamps || fullAnalyticsData.timestamps.length === 0) return;

            let filteredTimestamps = [];
            let filteredPower = [];

            if (currentHistoryView === 'daily') {
                let dateStr = historyDateCursor.toISOString().split('T')[0];
                document.getElementById('historyPeriodTitle').innerText = historyDateCursor.toDateString();

                for (let i = 0; i < fullAnalyticsData.timestamps.length; i++) {
                    let fullTs = fullAnalyticsData.timestamps[i];
                    if (fullTs.startsWith(dateStr)) {
                        // Format X-axis label to show time only (e.g. "14:00")
                        let dt = new Date(fullTs);
                        let label = !isNaN(dt) ? dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : fullTs.substring(11, 16);
                        
                        filteredTimestamps.push(label);
                        filteredPower.push(fullAnalyticsData.corrected_power[i]);
                    }
                }
            } else if (currentHistoryView === 'weekly') {
                let startOfWeek = new Date(historyDateCursor);
                startOfWeek.setDate(startOfWeek.getDate() - startOfWeek.getDay());
                let endOfWeek = new Date(startOfWeek);
                endOfWeek.setDate(endOfWeek.getDate() + 6);

                document.getElementById('historyPeriodTitle').innerText = `${startOfWeek.toLocaleDateString()} - ${endOfWeek.toLocaleDateString()}`;

                for (let i = 0; i < fullAnalyticsData.timestamps.length; i++) {
                    let fullTs = fullAnalyticsData.timestamps[i];
                    let tsDate = new Date(fullTs);
                    if (tsDate >= startOfWeek && tsDate <= new Date(endOfWeek.getTime() + 86400000 - 1)) {
                        // Format X-axis label to show Day & Time (e.g. "Mon 14:00")
                        let label = !isNaN(tsDate) ? tsDate.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) + ' ' + tsDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : fullTs.substring(5, 16);

                        filteredTimestamps.push(label);
                        filteredPower.push(fullAnalyticsData.corrected_power[i]);
                    }
                }
            } else if (currentHistoryView === 'monthly') {
                let year = historyDateCursor.getFullYear();
                let month = historyDateCursor.getMonth() + 1;
                let mStr = String(month).padStart(2, '0');
                let prefix = `${year}-${mStr}`;

                document.getElementById('historyPeriodTitle').innerText = historyDateCursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

                for (let i = 0; i < fullAnalyticsData.timestamps.length; i++) {
                    let fullTs = fullAnalyticsData.timestamps[i];
                    if (fullTs.startsWith(prefix)) {
                        // Format X-axis label to show Month & Day (e.g. "Apr 05")
                        let dt = new Date(fullTs);
                        let label = !isNaN(dt) ? dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : fullTs.substring(5, 16);

                        filteredTimestamps.push(label);
                        filteredPower.push(fullAnalyticsData.corrected_power[i]);
                    }
                }
            }

            historyChart.data.labels = filteredTimestamps;
            historyChart.data.datasets[0].data = filteredPower;
            historyChart.data.datasets[1].data = new Array(filteredTimestamps.length).fill(fullAnalyticsData.baseline_peak);
            historyChart.update();
        }

        // Calendar View Controller Logic
        function setView(view) {
            currentView = view;
            document.querySelectorAll('.view-switchers button').forEach(b => b.classList.remove('active'));
            document.getElementById('btn-' + view).classList.add('active');
            renderCalendar();
        }

        function changeDate(direction) {
            if (currentView === 'daily') {
                currentDateCursor.setDate(currentDateCursor.getDate() + direction);
            } else if (currentView === 'weekly') {
                currentDateCursor.setDate(currentDateCursor.getDate() + (direction * 7));
            } else if (currentView === 'monthly') {
                currentDateCursor.setMonth(currentDateCursor.getMonth() + direction);
            } else if (currentView === 'yearly') {
                currentDateCursor.setFullYear(currentDateCursor.getFullYear() + direction);
            }
            renderCalendar();
        }

        function renderCalendar() {
            const container = document.getElementById('calendarContainer');
            const titleEl = document.getElementById('calendarTitle');
            container.innerHTML = '';

            let year = currentDateCursor.getFullYear();
            let month = currentDateCursor.getMonth();

            if (currentView === 'monthly') {
                const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
                titleEl.innerText = `${monthNames[month]} ${year}`;
                
                let html = '<div class="calendar-grid">';
                ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].forEach(d => {
                    html += `<div class="calendar-header-day">${d}</div>`;
                });

                let firstDayIndex = new Date(year, month, 1).getDay();
                let totalDays = new Date(year, month + 1, 0).getDate();
                let prevTotalDays = new Date(year, month, 0).getDate();

                for (let i = firstDayIndex; i > 0; i--) {
                    let prevDateStr = `${year}-${String(month).padStart(2, '0')}-${String(prevTotalDays - i + 1).padStart(2, '0')}`;
                    html += generateCellHTML(prevTotalDays - i + 1, prevDateStr, true);
                }

                for (let d = 1; d <= totalDays; d++) {
                    let mStr = String(month + 1).padStart(2, '0');
                    let dStr = String(d).padStart(2, '0');
                    let dateStr = `${year}-${mStr}-${dStr}`;
                    html += generateCellHTML(d, dateStr, false);
                }

                html += '</div>';
                container.innerHTML = html;

            } else if (currentView === 'daily') {
                titleEl.innerText = currentDateCursor.toDateString();
                let dateStr = currentDateCursor.toISOString().split('T')[0];
                let html = '<div style="display: flex; flex-direction: column; gap: 10px;">';
                html += `<div class="card" style="width: 100%;"><h3>Schedule for ${dateStr}</h3>`;
                if (globalMaintenanceEvents[dateStr]) {
                    let ev = globalMaintenanceEvents[dateStr];
                    html += `<p style="color:var(--text-color); margin-top:5px;"><span class="event-badge ${ev.css}" style="display:inline-block; padding: 5px 10px;">${ev.title}</span><br><br>${ev.desc}</p>`;
                } else {
                    html += `<p style="color:var(--text-color); margin-top:5px; opacity:0.7;">No maintenance scheduled for this day.</p>`;
                }
                html += `</div></div>`;
                container.innerHTML = html;

            } else if (currentView === 'weekly') {
                let startOfWeek = new Date(currentDateCursor);
                startOfWeek.setDate(startOfWeek.getDate() - startOfWeek.getDay());
                let endOfWeek = new Date(startOfWeek);
                endOfWeek.setDate(endOfWeek.getDate() + 6);

                titleEl.innerText = `${startOfWeek.toLocaleDateString()} - ${endOfWeek.toLocaleDateString()}`;
                
                let html = '<div class="calendar-grid" style="grid-template-columns: repeat(7, 1fr);">';
                for (let i = 0; i < 7; i++) {
                    let currD = new Date(startOfWeek);
                    currD.setDate(currD.getDate() + i);
                    let dateStr = currD.toISOString().split('T')[0];
                    html += generateCellHTML(currD.getDate(), dateStr, false, currD.toLocaleDateString(undefined, {weekday: 'short'}));
                }
                html += '</div>';
                container.innerHTML = html;

            } else if (currentView === 'yearly') {
                titleEl.innerText = `${year} (Yearly Overview)`;
                let html = '<div style="display:grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px;">';
                
                const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
                monthNames.forEach((mName, mIdx) => {
                    let monthEventsCount = 0;
                    Object.keys(globalMaintenanceEvents).forEach(k => {
                        if (k.startsWith(`${year}-${String(mIdx + 1).padStart(2, '0')}`)) monthEventsCount++;
                    });

                    html += `<div class="card" style="width:auto;">`;
                    html += `<h3>${mName}</h3>`;
                    html += `<p style="font-size:1.0em; margin-top:5px;">${monthEventsCount === 1 ? '1 Maintenance Task' : monthEventsCount + ' Maintenance Tasks'}</p>`;
                    html += `</div>`;
                });
                html += '</div>';
                container.innerHTML = html;
            }
        }

        function generateCellHTML(dayNum, dateStr, isOtherMonth, customDayLabel = '') {
            let cellClass = isOtherMonth ? "calendar-cell other-month" : "calendar-cell";
            let badgeHTML = "";

            if (globalMaintenanceEvents[dateStr]) {
                let ev = globalMaintenanceEvents[dateStr];
                badgeHTML = `<div class="event-badge ${ev.css}" title="${ev.desc}">${ev.title}</div>`;
            }

            return `
                <div class="${cellClass}">
                    <div class="cell-date">${customDayLabel ? customDayLabel + ' ' : ''}${dayNum}</div>
                    <div>${badgeHTML}</div>
                </div>
            `;
        }

        setInterval(fetchLiveData, 8000);
        setInterval(fetchAnalyticsData, 60000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/live')
def get_live():
    try:
        resp = requests.get(ESP32_URL, timeout=2)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"valid": False, "error": str(e)})

@app.route("/api/analytics")
def get_analytics():
    with cache_lock:
        if not cached_analytics_data.get("success"):
            return jsonify(
                {"success": False, "error": "Cache is still initializing..."}
            )
        return jsonify(cached_analytics_data)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)