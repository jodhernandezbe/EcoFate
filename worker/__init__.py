"""The background worker of the web program: a Celery worker that runs queued chat turns.

``celery -A worker.celery_app worker`` starts it. Each task runs one turn segment through
``app.turns.job.run_background_turn``; the worker imports only ``app``, ``agent``, ``config``,
``storage`` and ``tools.credentials``, never ``api``, and nothing imports it.
"""
