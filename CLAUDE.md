# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

LaTeXTrans is a multi-agent system that translates arXiv/LaTeX papers end-to-end (arXiv ID or local source → translated, compiled PDF) while preserving formulas, layout, and cross-references. It works by parsing raw LaTeX into structured JSON maps, translating the natural-language pieces via an LLM, validating that LaTeX integrity is preserved, and reconstructing + compiling a translated project.

## Commands

```bash
pip install -e .                       # install (registers `latextrans` and `latextrans-gui` console scripts)

latextrans --arxiv 2508.18791          # translate one arXiv paper (versioned IDs like 2508.18791v2 work)
latextrans --arxiv 2508.18791, 2407.01648   # batch (comma-separated)
latextrans --project path/to/src.tar.gz     # local archive (.zip/.tar/.tar.gz/.tgz) or extracted dir
latextrans --all-existing              # process every project already under `tex source/`
latextrans-gui                         # Streamlit GUI (or: streamlit run src/gui/streamlit_app.py)
```

CLI flags `--model`, `--url`, `--key`, `--output`, `--source`, `--config` override `config/default.toml`.

There is **no test suite, linter, or build step** in this repo. Verification is done by running an actual translation and inspecting the compiled PDF in `outputs/`.

## Prerequisites

- An LLM **backend** (`[llm_config] backend` in `config/default.toml`, or `--backend`):
  - `"api"` (default) — an OpenAI-compatible chat-completions API. Set `model`, `api_key`, `base_url`. The payload targets the `/v1/chat/completions` shape directly, so `base_url` must be the full completions endpoint, not just a host.
  - `"claude_code"` — the local `claude` CLI in headless mode; reuses your existing Claude Code login (OAuth, no API key). `model` is a claude alias (`opus`/`sonnet`, empty = CLI default); `api_key`/`base_url` are ignored.
- A TeX distribution (MiKTeX or TeX Live) on `PATH` for PDF compilation (`pdflatex`/`xelatex`). Translation produces JSON maps even without TeX; only the final `GeneratorAgent` step needs it.

## Architecture

### Workflow orchestration
`main.py` (CLI entry) resolves inputs into a list of project directories, then for each one constructs a `CoordinatorAgent` and calls `workflow_latextrans()`. `src/runtime.py` is a near-duplicate of `main.py`'s input-resolution logic, used by the Streamlit GUI with event callbacks for live progress.

`CoordinatorAgent.workflow_latextrans_async()` (`src/agents/coordinator_agent.py`) runs the fixed five-stage pipeline:

1. **ParserAgent** — parse the LaTeX project into JSON maps (`*_map.json`).
2. **TranslatorAgent** — translate sections/captions/envs concurrently via the LLM.
3. **ValidatorAgent** — check each translated part for LaTeX integrity; returns an `errors_report`.
4. **Retry loop** — if validation found errors, set `trans_mode = 1` and re-run TranslatorAgent → ValidatorAgent up to `MAX_RETRIES = 3` times, re-translating only the flagged parts.
5. **GeneratorAgent** — reconstruct the translated `.tex` project and compile to PDF.

All five agents subclass `BaseToolAgent` (`base_tool_agent.py`), which provides `log()`, `get_config()`, and `read_file()`/`save_file()` JSON helpers. Agents communicate **only through the JSON map files on disk** in the per-project output directory — there is no in-memory hand-off of parsed data between agents. Each agent re-reads the maps it needs and writes them back.

### The JSON map files (the central data contract)
Parsing produces five files in `outputs/<target_lang>_<project_name>/`. Every downstream agent reads/writes these:

- `sections_map.json` — document split into sections; each has `section` (number; `"-1"`/`"0"` are special non-translated buckets), `content`, and (after translation) `trans_content`.
- `captions_map.json` — figure/table captions, keyed by `placeholder`.
- `envs_map.json` — LaTeX environments, keyed by `placeholder`, with a `need_trans` flag.
- `inputs_map.json` — `\input`/`\include` structure with `begin`/`end` placeholders.
- `newcommands_map.json` — extracted `\newcommand` definitions.

**Placeholder mechanism (critical):** the parser replaces captions, environments, inputs, and newcommands with sentinel tokens like `<PLACEHOLDER_CAP_0>`, `<PLACEHOLDER_ENV_3>`, `<PLACEHOLDER_..._begin>/_end>` inside section content. This protects non-prose LaTeX from the translator and lets validation/reconstruction stitch everything back together. The translator registers all placeholders into its term dict as identity mappings (`add_placeholder()`) so the LLM leaves them untouched. `ValidatorAgent` flags any part where placeholders, LaTeX command counts, or bracket balance differ between `content` and `trans_content`.

### Translation modes (`trans_mode`)
Set from `config["mode"]` and toggled during the workflow:
- `0` — standard translation.
- `1` — re-translate only error parts using the validator's `errors_report` (used by the retry loop).
- `2` — terminology-aware translation using a glossary (`term_dict`); optionally extracts new terms when `update_term` is enabled.

### Terminology
`TranslatorAgent.build_term_dict()` loads a glossary CSV: a user-provided `user_term` file if set, otherwise an arXiv-category-matched file from `terms/` (e.g. `cs.AI.csv`, `cs.LG.csv`), falling back to `terms/default.csv`. Category is detected from the arXiv API in `main.py` via `get_arxiv_category`.

### LaTeX format layer (`src/formats/latex/`)
- `parser.py` (`LatexParser`) — finds the main `.tex`, merges `\input`s, strips comments, extracts newcommands, splits into sections, inserts placeholders.
- `reconstruct.py` (`LatexConstructor`) — reverses parsing: substitutes `trans_content` back into placeholders to rebuild a compilable project.
- `compile.py` (`LaTexCompiler`) — compiles with `pdflatex`, falling back to `xelatex`; has a separate `compile_ja` path for Japanese.
- `prompts.py` — all LLM system prompts. **`init_prompts(source_lang, target_lang)` must be called before prompts are used** (the agents do this); it rewrites the module-level prompt strings for the language pair. Language adaptation is most complete for English→Chinese; other targets may produce compile errors. After `init_prompts`, agents apply two optional override layers (only listed keys change; `{SOURCE_LANG}`/`{TARGET_LANG}` are substituted via plain string-replace so LaTeX braces survive): **`apply_user_prompts(user_prompt_file, ...)`** loads a TOML file (`[user_prompt_file]` config / `--prompt-file`) — it **must use single-quoted `'''literal'''` TOML strings** so LaTeX backslashes survive (see `config/prompts.example.toml`); then **`apply_prompt_overrides(config["prompt_overrides"], ...)`** applies an in-memory `{name: text}` dict (used by the GUI's single TOML editor, which pre-fills all 17 prompts from `config/prompts.example.toml` via `get_default_prompts()`, with Save-to-file / Restore-defaults buttons; only prompts that differ from default are applied). `_KNOWN_PROMPTS` lists the 17 overridable names. NOTE: the prompt definitions in `init_prompts` use **raw f-strings (`rf"""`)** so LaTeX backslash commands (`\ref`, `\textbf`, `\begin`, ...) survive — a plain `f"""` silently corrupts them via `\r`/`\t`/`\b`/`\v` escapes.
- `utils.py` — arXiv download, archive extraction, project discovery, text extraction.

### LLM backend layer (`src/llm/`)
All LLM calls go through a pluggable backend (`create_backend(config)` in `src/llm/__init__.py`). A backend turns OpenAI-style `messages` into one completion via `acomplete()` (async) / `complete()` (sync), performing **exactly one attempt** and raising `LLMBackendError` on failure — retry and fail-tracking stay in the agents.
- `ApiBackend` (`api_backend.py`) — the original HTTP path; payload is `{"model", "messages", **params}` so callers pass `temperature`/`max_new_tokens`/`max_tokens` verbatim.
- `ClaudeCodeBackend` (`claude_code_backend.py`) — spawns `claude -p --system-prompt <sys> --disallowedTools ... --output-format text` with the user content on stdin, in a temp cwd (so it won't auto-read this repo's `CLAUDE.md`). `model` (a claude alias like opus/sonnet) maps to `--model` and `effort` (low/medium/high/xhigh/max) to `--effort`; `temperature` etc. are ignored (no CLI equivalent). The GUI exposes Model + Reasoning-effort dropdowns only in claude_code mode.
- `CodexBackend` (`codex_backend.py`) — local OpenAI `codex` CLI via `codex exec --skip-git-repo-check --ephemeral --color never -s read-only -o <file> [--model M]`, with the **prompt fed on stdin** and the translation read from the **`-o` output-last-message file** (stdout carries a "codex"/"tokens used" banner, so it isn't parsed). Reuses the ChatGPT login (no key); system+user are merged into one prompt (codex has no system-prompt flag). `effort` maps to `-c model_reasoning_effort=<level>` (minimal/low/medium/high). Verified end-to-end on codex-cli 0.139.0.
- `max_concurrency` is backend-defined (api=10, claude_code/codex=4) and drives the TranslatorAgent semaphore; override with `[llm_config] concurrency`.

When adding a new LLM call site, build `messages` and call the agent's `self.backend`, then keep the per-call retry/fail-tracking loop around it — don't construct payloads or hit HTTP directly.

### Async + concurrency
TranslatorAgent is async (`aiohttp`); the Coordinator manages a dedicated event loop per project (with Windows-specific asyncgen cleanup). Section translation fans out under an `asyncio.Semaphore(self.backend.max_concurrency)`. Each LLM request retries 3× with backoff; on final failure the **original text is returned** and the part is recorded in `fail_section_nums`/`fail_caption_phs`/`fail_env_phs` for a separate fail-retry pass.

### Progress UI shim (`src/utils/progress.py`)
The code imports `st` from `src.utils.progress`, **not** Streamlit directly. This is a Streamlit-compatible shim (`progress`, `empty`, `text`, `success`, `error`, etc.) that renders to the terminal for CLI runs and is swapped for real Streamlit in the GUI. This is why agent code is littered with `sys.stderr = open(os.devnull, 'w')` guards around progress calls — keep that pattern when editing progress output.

## Conventions & gotchas

- **Paths:** relative paths in config are resolved against the project root (`PROJECT_ROOT` in `main.py`/`runtime.py`). Downloaded/extracted sources go under `tex source/`; results under `outputs/`.
- When `--arxiv` or `--project` is given, existing folders under `tex source/` are ignored; use `--all-existing` to reprocess them.
- Output directory naming: `outputs/<target_language>_<project_basename>/`, with the final PDF named `<target_language>_<project_basename>.pdf`.
- Special section numbers `"-1"` and `"0"` are never translated — preserve this check when touching section logic.
