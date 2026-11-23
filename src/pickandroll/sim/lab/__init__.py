"""SEASON SIM (#172, PR lab): the simulator's own small read-only app.

``model.py`` is pure (records and notes in, a dict out), ``records.py`` reads the records and
the notes, ``server.py`` serves the page (``static/``), the model and the explainer on one
address, GET only. ``python -m pickandroll.sim lab`` starts it; ``docs/sim/README.md``, "The
lab", says what it serves and what it never does.
"""
