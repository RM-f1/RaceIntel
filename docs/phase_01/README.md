# Phase 1 – FastF1 Data Foundation

## Objective

Build a reliable and reproducible data foundation using the FastF1 API for Formula 1 race analytics.

The objective is to understand the available data structures before introducing machine learning, SQL agents, Retrieval-Augmented Generation (RAG), or deployment.

---

## Scope

Included:

- FastF1 session loading
- Session metadata
- Race results
- Lap analysis
- Tyre stint analysis
- Telemetry comparison
- Weather analysis
- Local caching

Excluded:

- Machine Learning
- Text-to-SQL
- AI agents
- Database design
- Deployment

---

## Case Study

2024 British Grand Prix – Race Session

---

## Repository Structure

```text
notebooks/
docs/
src/
tests/
data/cache/
```

---

## Outputs

- Position Change Analysis
- Lap Time Evolution
- Tyre Stint Analysis
- Telemetry Comparison
- Weather Context

---

## Technologies

- Python
- FastF1
- Pandas
- NumPy
- Matplotlib
- Plotly

---

## Success Criteria

- Reproducible session loading
- Cached FastF1 data
- Documented engineering workflow
- Technical observations supported by data