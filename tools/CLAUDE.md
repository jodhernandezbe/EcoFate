# tools/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `tools/`.

- Tools must not import from `agent/`, and must not call an LLM.
- Tools must not import other tool subfolders; shared types go in `tools/schemas.py`. The one
  exception is `tools/assessment/`, the batch assessment: it composes the other folders' tools
  (invoking them, or the public functions of their tool modules, never their helpers) and adds
  only the selection, the stack-source order and the summary; only the registry imports it.
- Never import a provider package (`langchain_openai`, ...) in `tools/`, with two exceptions:
  `tools/emissions/rag/embeddings.py` builds the default embeddings for the SCC retrieval
  (lazily, chosen by `[embeddings].provider`), and
  `tools/informatics/helpers/read_across/moldeberta.py` loads the MolDeBERTa SMILES encoder
  (lazily; the only module that imports `torch` or `transformers`). Everything else takes
  `Embeddings` or a `SmilesEmbedder` injected.
- A tool that calls a provider or service itself gets its key per call from `tools/credentials.py`
  (`PROVIDER_KEY`, `CENSUS_KEY`, `COMPTOX_KEY`, set by the web program or the CLI for one run)
  before its environment variable, and never stores the key on an object that outlives the call.
- Every tool uses `@tool`, has full type hints on inputs and outputs (TypedDicts,
  not bare `dict`), and a rich docstring: purpose, `Args:`, `Returns:` with units.
  The docstring is what the LLM sees, so keep it accurate.
- Helpers live in `<tool folder>/helpers/`, grouped in subfolders by what they do (for example
  `emissions/helpers/inventory/` and `stack/`, `exposure/helpers/meteorology/` and `population/`);
  a helper used by the whole folder stays at the `helpers/` root. Tests mirror this layout.
- New tools are added to the folder's `TOOLS` list and `tools/registry.py`, and
  to `tests/tools/test_registry.py` and add a test under the tool's folder in `tests/tools/`.
- A heavy tool (`[worker].heavy_tools`) also has a job runner in `tools.registry.JOB_RUNNERS`
  (`JobRunner`: stored input, `StopCheck` -> `(content, artifact)`; `tools/assessment/facilities.py`
  `run_assessment_job`). It validates its untrusted input (`InvalidJobInputError`) and asks the
  injected `StopCheck` between tiers (default never stops); it never imports `app`.
- `tools/jobs/` is how a heavy tool runs in the background: `heavy_submitter(tool, preflight)` (the
  registry wraps each `[worker].heavy_tools` entry: same name, schema and docstring, unchanged: a description
  saying the call "does not run the work" made the model assess facilities one by one, so the
  guidance on a running job is the `note` of its queued answer; a call settles `preflight` (invalid input, missing values: the tool's own
  result, no job) and otherwise queues a job through the `JobPort` the program provides for the turn),
  `check_job_status` (quick tool, registered only when a tool is heavy) and `port.py` (`JobPort`,
  the context variable and `job_scope`). The job's user and thread come only from the run's config
  (`job_owner_id`/`job_thread_id`, set by the turn runner from the authenticated session), never from
  tool arguments; with no port (command line, evaluations) the tool runs itself as before.
- A tool whose result is too large for the model returns `(content, artifact)` with `response_format="content_and_artifact"`: the model reads a ranked, capped `content` that says what was left out, and the program (the web workspace) reads the complete `artifact`. Never rely on the model to sort or filter a long list.
