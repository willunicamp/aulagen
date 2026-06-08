# AulaGen

Gerador de slides para aulas universitárias movido por LLM local (Ollama). O professor informa o tema, o número da aula e parâmetros de tempo; a IA produz um conjunto de slides estruturado, renderizado como apresentação HTML navegável e salvo automaticamente em disco.

## Funcionamento

```
Ollama (local) ←──── server.py ────→ gerador-aulas.html
                         │
                    aulagem.db (SQLite)
                         │
                  DAD/16/index.html  ← slides gerados
```

O `server.py` é um servidor HTTP puro (stdlib Python, sem frameworks) que serve três coisas ao mesmo tempo: a API REST, um proxy de streaming para o Ollama e os arquivos HTML estáticos gerados. O frontend é um único arquivo HTML com JS vanilla.

## Requisitos

- Python 3.10+
- [Ollama](https://ollama.ai) rodando em `http://localhost:11434`
- Um modelo instalado no Ollama (ex.: `ollama pull qwen3:14b`)

## Iniciando

```bash
python3 server.py          # porta padrão 8000
python3 server.py 9000     # porta customizada
```

Abra `http://localhost:8000` no navegador.

## Funcionalidades

**Disciplinas** — cada disciplina tem nome, sigla (vira o nome da pasta no disco), descrição e um link de cabeçalho exibido em cada slide. O contexto acumulado das aulas anteriores é injetado automaticamente no prompt para evitar repetição de conteúdo.

**Geração de aulas** — o fluxo segue duas etapas de LLM:
1. Gera um índice JSON com a lista de slides e seus tipos
2. Gera o conteúdo completo de cada slide em paralelo

**Tipos de slides suportados:**

| Tipo | Descrição |
|------|-----------|
| `capa` | Slide de abertura com título e subtítulo |
| `paragrafo` | Texto corrido |
| `lista` / `lista_numerada` | Itens com marcadores ou numerados |
| `codigo` | Bloco de código com syntax highlight e rótulo de arquivo opcional |
| `focus_box` | Caixa de destaque com ícone, título e lista |
| `grid_2` / `grid_3` | Cards lado a lado (2 ou 3 colunas) |
| `quest_list` | Lista de questões/desafios |
| `subtitulo` | Separador de seção |
| `exercicios` | Slide de encerramento com atividades práticas |

**Edição** — slides podem ser editados individualmente via LLM ou manualmente via JSON. É possível adicionar, remover e reordenar slides.

**Exportação** — o HTML gerado é um arquivo totalmente autossuficiente (CSS e navegação embutidos) salvo em `{SIGLA}/{numero:02d}/index.html` (ex.: `DAD/16/index.html`).

**Resumos automáticos** — após salvar, o servidor extrai resumo e tópicos de cada aula em background (via Ollama) para usar como contexto nas próximas gerações.

**Autosave** — o estado dos slides em edição é salvo automaticamente no banco a cada alteração.

## Estrutura

```
aulagem/
├── server.py           # Servidor HTTP + API REST + proxy Ollama
├── gerador-aulas.html  # SPA frontend (HTML + CSS + JS vanilla)
├── aulagem.db          # SQLite (disciplinas + aulas)
├── session.json        # Estado da última sessão (restaurado ao reabrir)
└── {SIGLA}/
    └── {NN}/
        └── index.html  # Slides gerados para cada aula
```

## API

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/disciplinas` | Lista todas as disciplinas |
| POST | `/disciplinas` | Cria disciplina (`nome`, `sigla`, `descricao`, `link_header`) |
| PUT | `/disciplinas/:id` | Atualiza disciplina |
| DELETE | `/disciplinas/:id` | Remove disciplina e suas aulas |
| GET | `/disciplinas/:id/aulas` | Lista aulas da disciplina |
| GET | `/disciplinas/:id/contexto` | Retorna resumo acumulado para injeção no prompt |
| GET/POST | `/aulas` | Cria ou atualiza aula (`disciplina_id`, `numero`, `tema`, `slides`, `html`) |
| PUT | `/aulas/:id` | Atualiza resumo/tópicos de uma aula |
| DELETE | `/aulas/:id` | Remove aula |
| POST/GET | `/session/save` `/session/load` | Persiste/restaura o estado da sessão |
| POST | `/api/chat` | Proxy de streaming para o Ollama |

## Configurações no frontend

- **Modelo**: qualquer modelo instalado no Ollama (padrão `qwen3:14b`)
- **Thinking mode**: ativa o raciocínio estendido do modelo (para modelos que suportam)
- **Temperatura** e **tokens**: ajustáveis por slider
- **Contexto (num_ctx)**: tamanho da janela de contexto enviada ao modelo
- **URL do Ollama**: personalizável caso o Ollama rode em outra porta ou host
