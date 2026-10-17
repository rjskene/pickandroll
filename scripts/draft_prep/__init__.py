"""Draft-prep commands for scripts/draft_day.py (#75-#77), one module each, registered by name in
the script's ``PREP_MODULES``.

A module gives ``HELP`` (its line in the help), ``LEAGUE`` (whether it needs a league id),
``add_arguments(parser)`` and ``run(runbook, args) -> exit code``. It may also give
``on_status(runbook, league)``, called by ``status``, and ``before_attach(runbook, league, args)``,
called by ``run`` just before the attach. ``runbook`` is the script itself (``DATA``, ``ROOT``,
``say``, ``Stop``, the exit codes, ``settings``), read when used.
"""
