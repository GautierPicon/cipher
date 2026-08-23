# AGENTS.md

## Commands

```bash
uv sync                                  # setup env (Python >=3.14)
uv run pytest                            # full suite
uv run pytest tests/test_tui.py -q       # one file
uv run pytest tests/test_tui.py::test_name   # single test (async tests need @pytest.mark.asyncio)
uvx ruff check <paths> --select I001,F,E,W   # lint (ruff is NOT a project dep; repo has no lint config — pre-existing violations exist elsewhere, don't fix them wholesale)
uv build                                 # wheel into dist/
```

## Layout & entrypoints

- src-layout package in `src/cipher/`; console script `cipher` = `cipher.cli:app` (typer).
- Bare `cipher` (no args) launches the TUI; `--help` shows the classic CLI. The typer command `tui` does the same explicitly.
- Layering: `crypto.py` (pure streaming AES-256-GCM/Argon2id, zero UI deps) → `service.py` (business logic shared by CLI and TUI: conflict resolution, staged tar extraction) → `cli.py` (typer + rich) and `tui/` (textual).
- Keep Rich/textual imports OUT of `crypto.py`. Progress reporting goes through the generic `on_progress(bytes_done)` callback — do not reintroduce rich Progress parameters.

## Gotchas

- **Release flow**: pushing to `main` triggers `.github/workflows/release.yml`, which tags `v<version>` whenever `version` in `pyproject.toml` changed. Bump version deliberately.
- **Textual Tree key bindings**: `Tree` natively binds `space` → `toggle_node`. `CipherTree` overrides it. When adding tree actions, NEVER name them after native action names (`select_cursor`, etc.) — an override silently changes what `Enter` does too.
- **Threads**: TUI operations run in worker threads (`_run_ops`). Widgets must only be touched from the event loop; use `call_from_thread` or the `_log()` helper (it handles both cases).
- **DirectoryTree**: `node.data` is a `DirEntry` (use `.path`), not a `Path`. Dotfiles are filtered via overridden `filter_paths()`.
- Command palette is disabled (`ENABLE_COMMAND_PALETTE = False`); `k` toggles the native HelpPanel instead.
- Tests use pytest-asyncio STRICT mode. For TUI tests, poll outcomes with the `_wait_for(predicate)` helper — asserting on transient state (e.g. the busy flag) right after dismissing a modal is racy because workers can finish between two loop iterations.

## Conventions

- No code comments in this codebase; docstrings only where they carry real information.
- File format CIPHER02 is self-contained (header embeds Argon2id params/salt/nonce). Any change to `crypto.py` chunking/header must stay backward-compatible — existing `.enc` files must decrypt forever.
