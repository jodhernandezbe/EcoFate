"""Batch assessment tools: the exposure chain for many facilities at once."""

from __future__ import annotations

from langchain_core.tools import BaseTool

from tools.assessment.facilities import assess_facilities, run_assessment_job

TOOLS: list[BaseTool] = [assess_facilities]

__all__ = ["TOOLS", "assess_facilities", "run_assessment_job"]
