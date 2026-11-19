[← Documentation index](../README.md#documentation) · [Architecture](../docs/architecture.md) · [Agent](../agent/README.md)

# prompts/

The prompt files, one Markdown file each, and the loader. Prompt text is never inlined in Python:
code calls `prompts.registry.load_prompt("<name>")`, which reads `prompts/<name>.md` (and raises
`FileNotFoundError` for an unknown name). Prompts are structured with XML tags (`<role>`,
`<context>`, `<instructions>`, `<output_format>`). Rules for coding agents: `prompts/CLAUDE.md`.

## Contents

- [Files](#files)
- [Design rule](#design-rule)
- [Loading](#loading)
- [Changing a prompt](#changing-a-prompt)

## Files

| File | Used by | Purpose |
|---|---|---|
| `agent_system.md` | `agent/graph.py` (default system prompt) | how an exposure assessor thinks and reports |
| `scope_addendum.md` | the web program (`app/web_turn.py`) | tells the agent about the overview and map beside the chat |
| `scope_classifier.md` | the scope guard | decides whether a message is about environmental exposure |
| `scope_redirect_fallback.md` | the scope guard | the short redirect shown when the classifier gives none |
| `completion_check.md` | the completion guard | decides whether an answer stopped early |
| `completion_nudge.md` | the completion guard | the message that sends the agent back to work |
| `catalogue_judge.md` | `evals/catalogue/judge.py` | the criteria of the LLM judge of catalogue answers |

The names the web and command-line programs load are listed in `[ui.prompts]` of
`config/settings.toml`.

## Design rule

The system prompt teaches reasoning, not tool order: it says how an assessor thinks and never
names a tool or a call order. The decisions about when to call a tool, how to read its result and
what follows live in each tool's docstring, which the model reads
([tools](../tools/README.md#tool-reference)).

## Loading

    from prompts.registry import load_prompt, list_prompts

    load_prompt("agent_system")     # the text of prompts/agent_system.md
    list_prompts()                  # the names of every prompt, sorted

## Changing a prompt

A prompt edit can change what the agent does, so it is measured, not assumed: run the agent
evaluations ([evals](../evals/README.md)) before and after, and for the judge prompt re-run
`uv run python -m evals judge <run-dir>` and read the disagreements
([judge iterations](../evals/docs/judge-tuning.md#judge-iterations)). Tests of the loader are in
`tests/prompts/`.
