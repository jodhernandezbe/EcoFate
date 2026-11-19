"""The job port helpers: reading a queued-job answer."""

from __future__ import annotations


def test_is_queued_answer_reads_only_a_queued_job() -> None:
    from tools.jobs.port import is_queued_answer

    assert is_queued_answer('{"job_id": "j1", "status": "queued", "position": 0}')
    assert is_queued_answer({"job_id": "j1", "status": "queued"})
    assert not is_queued_answer('{"job_id": "j1", "status": "running"}')
    assert not is_queued_answer('{"status": "queued"}')  # no job id
    assert not is_queued_answer('{"job_id": 7, "status": "queued"}')
    assert not is_queued_answer("not json")
    assert not is_queued_answer(["queued"])
