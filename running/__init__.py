"""Running module: session analysis, race forecasts, training plans.

Pure logic over the warehouse tables -- no Streamlit imports here, so every
calculation can be tested and reused by ``analytics.py`` (materialised tables),
the ``views/run_*`` pages and the coach brief (``python -m running.coach``).

* ``units``    -- distances, pace/time conversion and parsing
* ``physio``   -- Daniels' oxygen-cost model, VDOT, training paces, HR anchors
* ``sessions`` -- run selection, workout classification, splits, best efforts
* ``forecast`` -- race-time model (several methods, interval, confidence)
* ``plan``     -- training-plan generator and plan-vs-actual matching
* ``store``    -- races and plans persisted as JSON under ``data/coach/``
* ``coach``    -- the data brief for an assistant + next-session suggestion
"""
