# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**AulaGen** — a Portuguese-language lecture slide generator for Brazilian university courses. Professors define a course (*disciplina*) and topic, the LLM (Ollama, local) generates structured slide JSON, and the tool renders and saves self-contained HTML presentations to disk.

## Running the server

```bash
python3 server.py          # default port 8000
python3 server.py 9000     # custom port
```

Open `http://localhost:8000` in a browser — the server serves `gerador-aulas.html` as the root.

**Dependencies**: Python stdlib only (no pip install needed). Requires [Ollama](https://ollama.ai) running at `http://localhost:11434`.

## Architecture

The project is intentionally minimal: two files carry all the logic.

### `server.py` — Python stdlib HTTP server

Three responsibilities in one file:

1. **REST API** for the two database entities:
   - `disciplinas` (courses): CRUD at `/disciplinas`, `/disciplinas/{id}`
   - `aulas` (lessons): CRUD at `/aulas`, `/disciplinas/{id}/aulas`, `/disciplinas/{id}/contexto`
2. **Ollama proxy** — forwards `/api/*` and `/ollama/*` requests to `http://localhost:11434`, streaming chunked responses back to the browser
3. **Static file server** — serves `gerador-aulas.html` at `/` and generated HTML slides from disk

**Session persistence**: `GET /session/load` and `POST /session/save` read/write `session.json` to restore UI state across page reloads.

**Async AI summaries**: After a lesson is saved, `gerar_resumo_async()` calls Ollama in a background thread to extract a `resumo` and `topicos` list and writes them back to the DB. These are used by `build_contexto()` to inject prior lesson summaries into new generation prompts (so the LLM avoids repeating covered material).

**HTML slide output**: `salvar_html_aula()` writes the rendered HTML to `{SIGLA}/{numero:02d}/index.html` relative to the project root (e.g., `DAD/16/index.html`). The `sigla` field on `disciplinas` controls the folder name.

### `gerador-aulas.html` — Single-page frontend (vanilla JS)

All UI, slide rendering, and LLM orchestration lives here. Key JS sections:

- **`ollamaChat()`** — streaming chat with Ollama, handles thinking-mode (`<answer>` tag extraction)
- **`gerarAula()`** — main workflow: fetches course context → calls Ollama for a slide index → calls Ollama per slide → assembles HTML → saves to backend
- **`systemPromptIndice()` / `systemPromptSlide()`** — LLM prompts that define slide JSON schema
- **`montarHtmlFinal()`** — assembles the self-contained presentation HTML from slide JSON
- **Slide block types**: `paragrafo`, `lista`, `focus_box`, `quest_list`, `codigo`, `exercicio`, `capa`, `exercicios` — handled in the `blocos` map

The frontend talks to the backend at `http://localhost:{server_port}` and also directly to Ollama at `http://localhost:11434` (via the server proxy).

## Database

SQLite at `aulagem.db`. Two tables:

```
disciplinas: id, nome, sigla, descricao, link_header, pasta, criada_em
aulas:       id, disciplina_id, numero, tema, resumo, topicos, slides_json, caminho_html, criada_em, atualizada_em
```

`init_db()` uses `ALTER TABLE ... ADD COLUMN` with `try/except` for idempotent migrations — new columns can be added this way.

## Environment

`ANTHROPIC_API_KEY` in `.env` is present but not currently used by the server. The server uses Ollama exclusively for LLM calls.
