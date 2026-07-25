# 🏎️ RaceIntel

> **An engineering-first Formula 1 analytics platform built with FastF1, Python, and data engineering principles.**

RaceIntel is a long-term project focused on building an end-to-end Formula 1 analytics platform. The project starts with reliable data engineering foundations and will progressively evolve into a database-backed analytics system with AI-powered natural language querying and predictive analytics.

---

# 📌 Current Status

**Phase 1 – FastF1 Data Foundation** ✅ Completed

Current focus:

- Reliable FastF1 data ingestion
- Reusable session loader
- Race analysis
- Lap analysis
- Telemetry comparison
- Weather context analysis
- Engineering documentation
- Unit testing

---

# 🎯 Project Goals

RaceIntel aims to build a complete Formula 1 analytics ecosystem by combining:

- Data Engineering
- Data Analysis
- Machine Learning
- SQL Analytics
- AI Agents
- Interactive Dashboards

The project emphasizes software engineering best practices, reproducibility, and technical documentation throughout development.

---

# 📊 Phase 1 Highlights

Completed analyses using the **2024 British Grand Prix (Race Session):**

- Session metadata exploration
- Driver and race results analysis
- Grid vs finishing position analysis
- Position gain/loss visualization
- Lap time evolution
- Tyre stint analysis
- Fastest lap telemetry comparison
- Weather and track context analysis

---

# 📁 Project Structure

```text
RaceIntel/
│
├── data/
│   └── cache/
│
├── docs/
│   └── phase_01/
│       ├── README.md
│       ├── learnings.md
│       ├── findings.md
│       ├── challenges.md
│       ├── phase_summary.md
│       └── screenshots/
│
├── notebooks/
│   ├── phase_01_fastf1_exploration.ipynb
│   ├── phase_01_lap_analysis.ipynb
│   ├── phase_01_telemetry_analysis.ipynb
│   └── phase_01_weather_analysis.ipynb
│
├── src/
│   └── data/
│       └── fastf1_loader.py
│
├── tests/
│   └── test_fastf1_loader.py
│
├── requirements.txt
└── README.md
```

---

# ⚙️ Tech Stack

- Python
- FastF1
- Pandas
- NumPy
- Matplotlib
- Plotly
- Jupyter Notebook
- Pytest
- Git & GitHub

---

# 🚀 Getting Started

## 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/RaceIntel.git
cd RaceIntel
```

## 2. Create a virtual environment

```bash
python -m venv venv
```

Activate:

### Windows

```bash
venv\Scripts\activate
```

### Linux / macOS

```bash
source venv/bin/activate
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Launch Jupyter Notebook

```bash
jupyter notebook
```

---

# 📷 Sample Outputs

Examples generated during Phase 1 include:

- Position Gain/Loss Chart
- Lap Time Evolution
- Fastest Lap Telemetry Comparison
- Weather Trend Analysis

*(Screenshots available in `docs/phase_01/screenshots/`.)*

---

# 🧪 Testing

Run the automated tests:

```bash
python -m pytest
```

Example output:

```text
===========================
3 passed
===========================
```

---

# 🛣️ Roadmap

## ✅ Phase 1 — FastF1 Data Foundation

- FastF1 integration
- Session loading
- Telemetry analysis
- Weather analysis
- Documentation
- Testing

## 🔄 Phase 2 — Data Engineering

- SQLite database
- ETL pipeline
- Historical race data storage
- Data validation

## 🔄 Phase 3 — Text-to-SQL

- Natural language query system
- Benchmark dataset
- SQL generation

## 🔄 Phase 4 — Machine Learning

- Race strategy analysis
- Position prediction
- Driver performance modeling

## 🔄 Phase 5 — AI Analytics Platform

- Agentic workflows
- Interactive dashboard
- Intelligent race insights

---

# 📚 Documentation

Detailed Phase 1 documentation is available in:

```
docs/phase_01/
```

including:

- Learnings
- Findings
- Challenges
- Engineering Summary

---

# 📖 Data Source

This project uses the **FastF1** library, which provides access to official Formula 1 timing and telemetry data.

---

# 📄 License

This project is intended for educational, research, and portfolio purposes.