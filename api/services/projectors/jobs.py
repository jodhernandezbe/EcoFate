"""The projector of ``check_job_status``: a job's status puts nothing on the workspace."""

from __future__ import annotations

from api.services.projectors.ledger import Ledger, ToolExchange


def project_job_status(exchange: ToolExchange, ledger: Ledger) -> None:
    """File nothing: a status names no chemical, facility or value; the job's result reaches the
    workspace with its follow-up turn (as the ``assess_facilities`` result it is)."""
