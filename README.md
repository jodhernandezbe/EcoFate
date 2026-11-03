# EcoFate

EcoFate turns fragmented environmental data into screening-level chemical exposure risk profiles.

## Overview

### The problem

Public health researchers, environmental risk assessors, and community advocates often struggle to rapidly evaluate localized chemical exposure risks because critical data on industrial releases, chemical properties, and environmental transport variables are siloed across multiple disparate databases.

### What it does

EcoFate unifies public datasets, such as the EPA Toxics Release Inventory (TRI), with phenomenological transport models to automate screening-level exposure assessments. A user provides a location, facility, or chemical of interest, and the system pulls together release data, chemical properties, and transport modeling to return an actionable risk profile: a starting point for further investigation.

The intended tool flow for an assessment is: chemical properties -> emissions inventory -> stack parameters -> meteorology and population -> exposure metrics. All tools are implemented (see [Tools](#tools)).

## Quick start

1. Install uv if you don't have it yet: https://docs.astral.sh/uv/getting-started/installation/

2. Clone this repository (or download the zip and extract it).

3. Create a `.env` file from the template and add your API key:

       cp .env.example .env

4. Install dependencies:

       uv sync

5. Verify the setup:

       uv run pytest

## Using EcoFate

### Command line

The chat model is configured in one place, `[agent]` in `config/settings.toml` (provider, model, API-key variable, timeout, step limit). The program and the evaluations both build it from there with `app/chat_model.py`, so they always run the same model.

```bash
uv run python -m app "Assess CAS 71-43-2"
```

### Web interface

A local split-screen app: the assessment overview and facility map on the left, the copilot chat on the right. `frontend/` (React) talks only to `api/` (FastAPI), which runs the same agent.

```bash
npm --prefix frontend ci && npm --prefix frontend run build   # once, and after frontend changes
uv run python -m api                                           # http://127.0.0.1:8000
```

For frontend work with hot reload, run `uv run python -m api` in one terminal and `npm --prefix frontend run dev` in another, then open http://localhost:5173.

The left rail has four entries:

- **Workspace**: the analysis view.
- **Clear workspace**: asks first, then discards the conversation, overview, charts and map (on the server too).
- **Generate report**: downloads a Word document laid out like an EPA screening-level assessment (summary, chemical properties, data sources, releases, exposure, risk, uncertainties, and the assistant's last answer labelled as model-generated). Every value in it comes from the dashboard.
- **Monitoring**: lists recorded agent sessions (see [Monitoring](#monitoring)).

#### API keys

Open the page, click the gear (top right) and save your keys: the OpenAI key (required, it runs the assistant), and the Census and CompTox keys (the tools need them to count the people around a facility and to look up chemical properties). Each goes to the OS keychain (macOS Keychain, Linux Secret Service, Windows Credential Locker) and nowhere else: never to a file or the browser. It reaches the model and tools only for the turn that uses it. The command line program uses the same stored keys.

For any key not stored, the environment variable is the fallback (`OPENAI_API_KEY`, `CENSUS_API_KEY`, `COMPTOX_API_KEY`, also read from `.env`). The server listens on loopback only (`[ui]` in `config/settings.toml`).

#### What the workspace shows (and does not)

The left pane is built only from what the tools returned; a value no tool reported reads "not reported", never zero. A scope check keeps the chat on environmental exposure and answers off-topic requests with a short redirect, without running the agent.

- **Summary cards:** highest worst-case and representative hazard quotient and lifetime cancer risk with a status (below, near or above the thresholds in `[ui.thresholds]`, each said in words), the chemical with its read-across provenance, the residents and age bands within the radius, and the weather.
- **Map:** a marker per facility from the inventory, coloured by risk status and sized by emission rate; hover or focus (Tab) a marker for its inspector. Facilities, buffers and results that cannot be tied to exactly one facility are listed as unattributed, not guessed.
- **Limits, stated on screen:** the shaded wedge is a *schematic* downwind sector (the half-angle in `[ui.map]` is a drawing choice), not a modelled plume footprint; stacks have three tiers (NEI, PSTK by SCC, EPA global default); the inventory gives the TRI document control number, not a TRI facility ID; the queried chemical's name is not shown (only its CAS and any surrogate's name); the weather arrow is one downwind direction, not a wind rose.
- **Cost:** the header shows session tokens and an estimated cost from the list prices in `[ui.pricing]` (with the date they were read).

### Monitoring

Every run of the agent can be recorded as a trace in [Pydantic Logfire](https://logfire.pydantic.dev): one session per command-line run, or per chat turn of the web interface (tagged with the conversation). A session holds every model call (prompt, answer, tokens) and every tool call (name, arguments, result, duration), plus the run's tokens and estimated cost. The cost uses the same prices as the chat's usage meter (`[ui.pricing]`), and `uv run python -m app "..."` prints it after the answer (on stderr, so the answer can still be piped).

Set up once, by whoever installs the app, in `.env` (never entered in the interface). Both tokens come from one Logfire project (Settings -> Write tokens / Read tokens):

    LOGFIRE_TOKEN=...        # lets runs send their traces; without it nothing leaves the machine
    LOGFIRE_READ_TOKEN=...   # lets the Monitoring view read them back

To check a trace, run `uv run python -m app "What is the molecular weight of benzene, CAS 71-43-2?"`, then open the project in Logfire (Live view), or open **Monitoring** in the web interface. It lists the recorded sessions with their model calls, tool calls, tokens, estimated cost and duration; a session opens into its calls in order, with a link to the trace in Logfire. If Logfire cannot be reached, or no read token is set, the view says so and shows nothing else.

When a write token is set, questions, tool arguments and results (chemical identifiers, facility data) are sent to Logfire. API keys and tokens are scrubbed from every span. Turn monitoring off with `enabled = false` in `[telemetry]` (`config/settings.toml`). The tests never send anything.

### Evaluation

`uv run pytest -m eval` runs the agent with the `[agent]` model on the scenarios in `evals/scenarios.py`, checks its tool calls in code, and scores its reply with an LLM judge (`[evaluation].judge_model`) through Evidently. An HTML report is written to `evals/reports/`. Network tools are replayed from `evals/cassettes/` (a missing recording fails closed). Evaluations need `OPENAI_API_KEY`, cost tokens, and are excluded from the default `pytest` run.

```bash
uv run python -m evals run                     # all unblocked scenarios: PASS/FAIL + reasons
uv run python -m evals run chemical-name-only  # one scenario
uv run python -m evals record full-assessment-with-nei-stacks  # re-record from live services
uv run python -m evals catalogue                # every question in evals/catalogue/scenarios.csv, live
```

Recording runs the scenario once against the live services (it needs the CompTox and Census keys too) and saves every network tool output; never edit a cassette by hand. Reports land in `evals/reports/<timestamp>/<scenario>.html`.

`catalogue` sends every question of `evals/catalogue/scenarios.csv` (50 reviewed questions: happy paths, varied phrasing, edge cases, out-of-scope and breaking) to the live agent, one turn each, by the same path as `python -m app` (stored keys, step limit, metered usage). It needs the OpenAI key and, for complete answers, the Census and CompTox keys, and it costs tokens for every row. Each answer is saved with its execution time, token counts and estimated cost (from `[ui.pricing]`) to `evals/reports/<timestamp>/catalogue.json`; a row that fails on the step limit or a service error is recorded with the error and the run continues.

## Architecture

The code is split into packages with one-way dependencies: `agent` -> `tools` -> `models`, and `agent` -> `prompts`. `models` knows nothing about LLMs or LangChain.

    agent/                   graph.py (build_agent(model, ...) -> compiled LangGraph), state.py (AgentState)
    commons/                 generic pure utilities shared across layers (units.py: Pint)
    models/                  pure NumPy physics, no LLM/LangChain imports, grouped by what they model
      transport/             dispersion.py (sigmas, Gaussian plume), plume_rise.py, wind_profile.py,
                             screening.py (SCREEN3-style worst case over weather and distance)
      weather/               stability.py (Pasquill-Gifford class), meteorology.py (hourly summary)
      receptors/             population.py (areal scaling, age bands)
      exposure/              dose.py (ADD, LADD), inhalation.py (exposure concentration, doses,
                             HQ and cancer risk), risk.py (emission rate, risk ratios)
      chemistry/             similarity.py (cosine, Tanimoto, hybrid read-across score)
    prompts/
      registry.py            load_prompt(name) reads prompts/<name>.md
      agent_system.md        system prompt (XML-tagged sections; names no tool)
    tools/                   one module per tool (or small family), helpers in same-named helpers/ folders
      registry.py            ToolRegistry + ALL_TOOLS / get_all_tools()
      schemas.py             TypedDicts shared by tool inputs/outputs
      informatics/           properties.py, read_across.py, helpers/ (comptox, read_across/)
      emissions/             inventory.py, industry.py, process.py, stack.py, rag/, helpers/
      exposure/              meteorology.py, population.py, metrics.py, helpers/
      http.py, digits.py     shared by the tool folders (retrying JSON client, digit-string ids)
    tests/                   pytest suite, mirrors the package layout

### Tools

Each tool's docstring says when to use it and how to read its results. Behaviour, data sources and limits:

- **`fetch_chemical_properties`**: CAS -> SMILES -> CompTox, with Pint unit conversion to fixed units. When CompTox leaves molecular weight, vapor pressure or density empty, PubChem PUG View (no key, at most 5 requests a second, answers cached in `.cache/pubchem/`, `[pubchem]` in `config/settings.toml`) is asked for just those fields. Only a record that lists the requested CAS number is used, only a statement with one number and one unit counts (for vapor pressure, a temperature of 20-25 degC too), several statements must agree within a factor of 2, and the value is labelled `PubChem` in `sources` with a warning. PubChem never supplies the name or a toxicity value. Chronic RfD and RfC come first from CompTox's IRIS endpoint (`[comptox.iris]`; a text value is read only if it is one number and one expected unit, and a disagreement with ToxVal's copy of IRIS is a warning), then from ToxVal in the order of `source_priority`.
- **`query_emissions_inventory`**: CAS -> EPA TRI facilities with their latest reported stack-air release, location and an average emission rate in g/s at 8760 operating hours per year (configurable in `config/settings.toml`). Only the last 2 published TRI reporting years are read (`[tri] recent_years`; TRI for year N is released by June of N + 1). Each record carries the `doc_ctrl_num` and the primary NAICS code of its TRI submission, and only each submission's primary row is kept, so nothing is counted twice. The model is told only the largest `[tri] max_listed` facilities (highest emission rate first, with totals and optional `state` and `city` filters), because a widely reported chemical can have over a thousand and a model cannot rank them by eye; the complete list goes to the map as a tool artifact. Facilities whose TRI rows lack coordinates get them from EPA's FRS best-pick lookup (`[frs_point]`) in a few bulk requests.
- **`fetch_facility_industry`**: takes a TRI control number and returns the submission's primary NAICS code and its title in words (Envirofacts `tri_submission_naics` with `primary_ind = 1`, titles from `REF_NAICS`), saying whether the facility reported the code or EPA assigned it.
- **`lookup_scc_process_description`**: NAICS text -> candidate SCC process descriptions by semantic search over `data/epa_scc_to_epa_emission_sector.csv.gz` (a compact copy of the EPA table, Point rows only; rebuild from `data/raw/` with `uv run python -m scripts.compact_scc_table`). Uses OpenAI embeddings (`OPENAI_API_KEY`); the index is cached in `.cache/scc_index` and can be pre-built with `uv run python -m scripts.build_scc_index`. A bare NAICS code is refused; the title is what it needs.
- **`fetch_stack_parameters_from_nei`** (tier 1): takes a facility's FRS ID, finds its EIS facility ID(s) with the Envirofacts `FRS_PROGRAM_FACILITY` table, and returns the facility's distinct NEI stacks as candidates (real records, never averaged; near-identical ones merged, lowest stack first, at most `[stack.nei].max_candidates`). The agent passes them together to one exposure calculation. With none, it falls back to the SCC tool. The stacks come from `data/nei_stacks/` (gzip CSV shards, about 1.4 MB), built from the 2023 NEI SMOKE point flat file: put `nei_smoke_point_2023.zip` in `data/raw/` (git-ignored) and run `uv run python -m scripts.compact_nei_stacks`. Shard values are in SMOKE FF10 units (`[stack.nei.units]`) and are converted with Pint. Roughly a quarter of TRI facilities have NEI stack data.
- **`fetch_stack_parameters_from_scc`** (tier 2): EPA PSTK stack defaults for an SCC (a PSTK CSV is expected at `[stack.pstk].path`), falling back to the AirToxScreen global point-source default.
- **`get_meteorological_boundary`** (latitude, longitude, optional year): one year of hourly ERA5 reanalysis from the Open-Meteo historical archive (no API key; `[meteorology]`). Returns the annual mean 10 m wind speed (not below a configured minimum), the prevailing wind direction (most frequent 10 degree sector), the most frequent Pasquill-Gifford class (EPA's SRDT key by day and Turner's key at night, EPA-454/R-99-005) and the annual mean temperature in K. These are annual representatives on a roughly 25 km grid, not worst-case conditions. When inputs are invalid or the archive cannot be used, it returns a configured screening default labelled `source: "screening default"` with a warning. The free Open-Meteo tier is for non-commercial use (under 10,000 calls a day) and requires attribution (CC BY 4.0).
- **`get_population_receptors`** (latitude, longitude, optional radius in km, default one mile): estimates residents around a point and their age mix (0-4, 5-17, 18-64, 65+, in percent). It finds the census tracts that intersect the circle (Census TIGERweb), reads their ACS 5-year counts (Census Data API, vintage in `[population]`) and scales the total by circle area over tract land area, which assumes people are spread evenly over the tracts. **The Census Data API needs a free key** (https://api.census.gov/data/key_signup.html): set `CENSUS_API_KEY` in `.env`; without it every request is redirected to a "Missing Key" page. Tracts with missing ACS estimates are left out and counted in `warnings`. Invalid input, a missing or refused key, a failed service, or no census tract (open water, outside the United States) gives a labelled screening default. ACS sampling error is not propagated.
- **`calculate_exposure_metrics`**: turns a facility's candidate stacks (all in one call, so the per-stack loop runs in code rather than in the model), the emission rate, the weather, the population and the toxicity values into a screening air concentration, dose per age band, hazard quotient and cancer risk for each stack, plus the range over the stacks with the stack behind each end. The method is EPA's SCREEN3 (EPA-454/B-95-004): the worst case is the highest ground-level concentration over 54 combinations of stability class and 10 m wind speed, and over distances from 100 m to 10 km (the Briggs dispersion coefficients in `models/transport/dispersion.py` are valid only to 10 km), with Briggs plume rise, stack-tip downwash, the wind-profile power law and the 1-hour to annual factor 0.08 (EPA-454/R-92-019). A `representative` result uses the weather of the meteorology tool. Exposure factors are the EPA RSL resident-air defaults; age-band inhalation rates and body weights come from the 2011 Exposure Factors Handbook. Every constant is in the `[exposure]` table with its source. When a stack is generic (the EPA global default), the result says so, since it gives much higher concentrations. Limits: flat terrain, rural dispersion, no building downwash, no mixing-height limit, so it can understate unstable-weather impacts; the maximum may be where nobody lives. Anything it cannot compute is null with a warning; nothing is defaulted.
- **`find_tri_read_across_surrogate`** (CAS number, optional IRIS-benchmark and NAICS-prefix filters): finds the TRI chemical closest in structure to a chemical that is not on the TRI list or has no inhalation benchmark, following EPA's Generalized Read-Across (GenRA) idea. It scores every TRI chemical by alpha x the cosine of their MolDeBERTa embeddings (`SaeedLab/MolDeBERTa-base-123M-mtr`, mean-pooled, pinned revision) plus (1 - alpha) x the Tanimoto similarity of their ECFP4 fingerprints (RDKit Morgan, radius 2, 1024 bits), with alpha 0.55. It calls the best match inside the applicability domain when the score is at least 0.60 (`[read_across]`). The cosine is taken after subtracting the catalog's mean embedding, because raw vectors occupy a narrow cone (the lowest raw cosine between any two TRI chemicals is 0.424); centering restores the ranking and brings the in-domain share from 94.7% to 66%. The 0.60 threshold is calibrated from the catalog's leave-one-out nearest-neighbour distribution (p33 = 0.597, median 0.687), and is deliberately conservative: a homologue such as n-heptane scores 0.938 and is in domain, but a branched isomer such as isohexane scores 0.554 and is reported as outside it. Treat the surrogate as a ranked candidate and read both component scores, not the flag alone. A score is relative to the catalog it was computed against. It reports the query/surrogate molecular-weight ratio but never applies it, and never returns toxicity values. The catalog (`data/tri_chemicals/`, one parquet shard per leading CAS digit) is built with `uv run python -m scripts.build_tri_embeddings` (about a minute on rebuilds; about 4 minutes from scratch). **The model (about 500 MB) is downloaded from Hugging Face on first use**, and its licence (CC BY-NC-ND 4.0) allows non-commercial use only.

## Extending

### Swapping the LLM provider

Change `[agent]` in `config/settings.toml` (a new provider is an entry in `app/chat_model.py`). Underneath, `build_agent` accepts any `langchain_core.language_models.BaseChatModel` that supports tool calling. It never imports a provider, so you construct the model and inject it:

```python
from agent import build_agent

# OpenAI
from langchain_openai import ChatOpenAI

agent = build_agent(ChatOpenAI(model="gpt-4.1"))

# Anthropic
from langchain_anthropic import ChatAnthropic

agent = build_agent(ChatAnthropic(model="claude-sonnet-5-5"))

# Vertex AI
from langchain_google_vertexai import ChatVertexAI

agent = build_agent(ChatVertexAI(model="gemini-2.5-pro"))

agent.invoke({"messages": [("user", "Assess benzene (71-43-2) emissions")]})
```

Install the matching integration package yourself (e.g. `uv add langchain-anthropic`); none is a hard dependency.

### Adding a tool

0. Put any equations in `models/` first (pure functions with units in the docstring) and have the tool call them.
1. Add a typed `@tool` function in the matching concern folder (or a new folder), e.g. `tools/emissions/my_tool.py`. Put shared payload types in `tools/schemas.py`. Write a rich docstring (purpose, `Args:`, `Returns:`): the model reads it to decide when and how to call the tool.
2. Add it to the `TOOLS` list in that folder's `__init__.py`.
3. For a new folder, import its `TOOLS` in `tools/registry.py` and register it in `_build_default_registry`.
4. Add the tool name to `tests/tools/test_registry.py` and add a test in the matching `tests/tools/<concern>/` folder.

Tool names must be unique; the registry raises `ValueError` on duplicates.

## Development

    uv run pytest          # tests
    uv run ruff check .    # lint
    uv run ruff format .   # format
    uv run pyright         # strict type check
    uv run pre-commit install        # one-time: enable git hooks
    uv run pre-commit run --all-files

Pre-commit runs on every commit: file hygiene, ruff (lint + format), `uv lock` check, detect-secrets, strict pyright, bandit (security lint) and pytest. If detect-secrets flags a false positive, review it and update the baseline with `uv run detect-secrets scan > .secrets.baseline` (after checking the diff). Dependency CVEs: `uv run pip-audit`.
