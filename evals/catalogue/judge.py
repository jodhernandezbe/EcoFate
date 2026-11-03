"""An LLM judge for catalogue answers: question and answer in, a structured verdict out.

The judge sees only the question and the answer, never the human label, the row's category
or its type. The judge model is the one named in ``[evaluation]``, built through the program's
chat-model factory; its criteria are the prompt ``prompts/catalogue_judge.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, model_validator

from app.chat_model import build_named_chat_model
from config.evaluation import EvaluationSettings
from prompts.registry import load_prompt

PROMPT_NAME = "catalogue_judge"
FAILURES = ("hallucination", "rule-break", "wrong-scope", "incomplete", "incorrect", "other")
Failure = Literal["hallucination", "rule-break", "wrong-scope", "incomplete", "incorrect", "other"]
Label = Literal["good", "bad"]

# Failures of one judge call that are recorded for the row and let the next row be judged:
# provider errors (including timeouts) and a verdict that does not parse or validate.
JUDGE_ERRORS = (openai.APIError, ValueError)


class JudgeVerdict(BaseModel):
    """The judge's verdict on one answer; ``reasoning`` comes first so it is written first."""

    reasoning: str = Field(
        description="Step-by-step check of every criterion, in order, quoting the answer, "
        "then the conclusion.",
    )
    label: Label = Field(description="'good' when no BAD criterion applies; 'bad' otherwise.")
    failure: Failure | None = Field(
        default=None,
        description="The single category naming the main problem when the label is 'bad'; "
        "null when the label is 'good'.",
    )

    @model_validator(mode="after")
    def _consistent(self) -> JudgeVerdict:
        if self.label == "good" and self.failure is not None:
            raise ValueError("a good verdict carries no failure category")
        if self.label == "bad" and self.failure is None:
            self.failure = "other"
        return self


@dataclass(frozen=True)
class Answer:
    """One catalogue answer to judge.

    Attributes:
        index: Position of the row in the run's results (0-based).
        question: The user message sent to the agent.
        output: The agent's final answer.
    """

    index: int
    question: str
    output: str


@dataclass(frozen=True)
class JudgeResult:
    """What the judge said about one answer, or why it could not.

    Attributes:
        index: Position of the row in the run's results.
        question: The user message.
        label: The judge's label, or None when the call failed.
        failure: The judge's failure category, or None.
        reasoning: The judge's reasoning ('' when the call failed).
        error: Why the call failed, or None.
    """

    index: int
    question: str
    label: str | None
    failure: str | None
    reasoning: str
    error: str | None


Judge = Callable[[str, str], JudgeVerdict]
Progress = Callable[[str], None]


def judge_prompt(question: str, answer: str) -> str:
    """The user message for one row: the question and the answer, nothing else."""
    return f"Question:\n{question}\n\nAgent response:\n{answer}"


def model_judge(model: BaseChatModel, criteria: str | None = None) -> Judge:
    """A judge that asks ``model`` for a structured verdict under the judge prompt.

    Raises (from the returned judge): ``ValueError`` when the model returns no parseable
    verdict; provider errors as the model raises them.
    """
    structured = model.with_structured_output(JudgeVerdict, include_raw=True)
    system = SystemMessage(content=criteria if criteria is not None else load_prompt(PROMPT_NAME))

    def judge(question: str, answer: str) -> JudgeVerdict:
        messages = [system, HumanMessage(content=judge_prompt(question, answer))]
        result = cast(Mapping[str, object], structured.invoke(messages))
        verdict = result.get("parsed")
        if not isinstance(verdict, JudgeVerdict):
            raise ValueError(
                f"the judge returned no parseable verdict: {result.get('parsing_error')}",
            )
        return verdict

    return judge


def build_judge(settings: EvaluationSettings, environ: Mapping[str, str] | None = None) -> Judge:
    """The configured judge model, at the configured temperature, wrapped as a judge.

    Raises:
        RuntimeError: If the judge's API-key variable is unset (before any call is made).
    """
    model = build_named_chat_model(
        settings.judge_provider,
        settings.judge_model,
        settings.judge_api_key_env_var,
        settings.judge_timeout_seconds,
        environ,
        temperature=settings.judge_temperature,
    )
    return model_judge(model)


def judge_one(answer: Answer, judge: Judge) -> JudgeResult:
    """Judge one answer; an expected failure of the call becomes the row's error."""
    try:
        verdict = judge(answer.question, answer.output)
    except JUDGE_ERRORS as exc:
        error = f"{type(exc).__name__}: {exc}"
        return JudgeResult(answer.index, answer.question, None, None, "", error)
    return JudgeResult(
        answer.index,
        answer.question,
        verdict.label,
        verdict.failure,
        verdict.reasoning,
        None,
    )


def judge_rows(
    answers: Sequence[Answer],
    judge: Judge,
    progress: Progress = print,
) -> tuple[JudgeResult, ...]:
    """Judge ``answers`` in order, reporting each row before and its verdict after."""
    results: list[JudgeResult] = []
    for number, answer in enumerate(answers, start=1):
        progress(f"[{number}/{len(answers)}] {answer.question}")
        result = judge_one(answer, judge)
        results.append(result)
        progress(f"  {_outcome(result)}")
    return tuple(results)


def _outcome(result: JudgeResult) -> str:
    if result.error:
        return f"error: {result.error}"
    suffix = f" ({result.failure})" if result.failure else ""
    return f"{result.label}{suffix}"
