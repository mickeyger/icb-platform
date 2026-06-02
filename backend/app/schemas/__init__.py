"""Pydantic request/response schemas (WO v4.14 + v4.15, ADR 0008).

One module per API resource:
  * production_jobs (v4.14)
  * materials, stock_counts, discrepancies, po_suggestions, demand_lines,
    suppliers (v4.15 — Materials / Buying / Stores)

Responses are supersets (canonical columns + UI-friendly derived/enriched fields)
so the Phase 2C React wiring is a near drop-in for the mockup shapes.
"""
