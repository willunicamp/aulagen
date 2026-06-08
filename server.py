#!/usr/bin/env python3
"""
AulaGen Server v3 — SQLite + sigla + autosave + caminho_html
Uso: python3 server.py [porta]
"""

import http.server
import json
import os
import re
import sqlite3
import sys
import threading
import urllib.request
import urllib.error
from pathlib import Path

PORT      = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
BASE_DIR  = Path(__file__).parent
OLLAMA    = "http://localhost:11434"
DB_PATH   = BASE_DIR / "aulagem.db"
SESSION_F = BASE_DIR / "session.json"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css",
    ".js":   "application/javascript",
    ".json": "application/json",
    ".ico":  "image/x-icon",
}

# ═══════════════════════════════════════════════════════════════════════════════
# BANCO DE DADOS
# ═══════════════════════════════════════════════════════════════════════════════
_db_lock = threading.Lock()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS disciplinas (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nome        TEXT NOT NULL UNIQUE,
                sigla       TEXT NOT NULL DEFAULT '',
                descricao   TEXT DEFAULT '',
                link_header TEXT DEFAULT '',
                pasta       TEXT NOT NULL DEFAULT '',
                criada_em   TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS aulas (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                disciplina_id  INTEGER NOT NULL REFERENCES disciplinas(id) ON DELETE CASCADE,
                numero         INTEGER NOT NULL,
                tema           TEXT NOT NULL,
                resumo         TEXT DEFAULT '',
                topicos        TEXT DEFAULT '',
                slides_json    TEXT DEFAULT '[]',
                caminho_html   TEXT DEFAULT '',
                criada_em      TEXT DEFAULT (datetime('now')),
                atualizada_em  TEXT DEFAULT (datetime('now')),
                UNIQUE(disciplina_id, numero)
            );
            CREATE INDEX IF NOT EXISTS idx_aulas_disc ON aulas(disciplina_id);
        """)
        for sql in [
            "ALTER TABLE disciplinas ADD COLUMN sigla TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE disciplinas ADD COLUMN pasta TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE aulas ADD COLUMN caminho_html TEXT DEFAULT ''",
            "ALTER TABLE aulas ADD COLUMN atualizada_em TEXT DEFAULT (datetime('now'))",
        ]:
            try: conn.execute(sql)
            except Exception: pass
    print(f"  DB: {DB_PATH}")

# ═══════════════════════════════════════════════════════════════════════════════
# RESUMO ASYNC
# ═══════════════════════════════════════════════════════════════════════════════
SYSTEM_RESUMO = """Você recebe slides de uma aula e extrai:
1. Um resumo conciso (2-3 frases)
2. Lista dos principais tópicos/conceitos

Responda APENAS com JSON:
{"resumo": "...", "topicos": ["t1", "t2", "t3"]}"""

def gerar_resumo_async(aula_id: int, slides_json: str, modelo: str):
    def _run():
        try:
            slides = json.loads(slides_json)
            textos = []
            for s in slides:
                if s.get("titulo_h1"): textos.append(s["titulo_h1"])
                if s.get("titulo_h2"): textos.append(s["titulo_h2"])
                for b in s.get("blocos", []):
                    t = b.get("tipo","")
                    if t == "paragrafo":  textos.append(re.sub(r'<[^>]+>','',b.get("texto","")))
                    elif t == "lista":    textos.extend(re.sub(r'<[^>]+>','',i) for i in b.get("itens",[])[:3])
                    elif t == "focus_box":textos.append(b.get("titulo",""))
                    elif t == "quest_list":textos.extend(re.sub(r'<[^>]+>','',q) for q in b.get("quests",[])[:2])
            payload = json.dumps({
                "model": modelo, "stream": False, "think": False,
                "options": {"temperature": 0.3, "num_predict": 500},
                "messages": [
                    {"role": "system", "content": SYSTEM_RESUMO},
                    {"role": "user",   "content": f"Slides:\n{chr(10).join(textos[:60])}"}
                ]
            }).encode()
            req = urllib.request.Request(f"{OLLAMA}/api/chat", data=payload,
                                          headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data    = json.loads(resp.read())
                content = data.get("message",{}).get("content","").strip()
                # Strip markdown code fences if present
                content = re.sub(r'^```(?:json)?\s*', '', content)
                content = re.sub(r'\s*```\s*$', '', content)
                # Extract first JSON object
                start = content.find('{')
                if start == -1:
                    raise ValueError(f"Nenhum JSON na resposta do modelo: {content[:200]}")
                content = content[start:]
                parsed  = json.loads(content)
                resumo  = parsed.get("resumo","")
                topicos = json.dumps(parsed.get("topicos",[]), ensure_ascii=False)
            with _db_lock, get_db() as conn:
                conn.execute("UPDATE aulas SET resumo=?, topicos=? WHERE id=?", (resumo, topicos, aula_id))
            print(f"  RESUMO aula #{aula_id}: ok")
        except Exception as e:
            print(f"  RESUMO aula #{aula_id}: erro — {e}")
    threading.Thread(target=_run, daemon=True).start()

# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXTO
# ═══════════════════════════════════════════════════════════════════════════════
def build_contexto(disciplina_id: int) -> str:
    with _db_lock, get_db() as conn:
        disc  = conn.execute("SELECT nome, descricao FROM disciplinas WHERE id=?", (disciplina_id,)).fetchone()
        if not disc: return ""
        aulas = conn.execute(
            "SELECT numero, tema, resumo, topicos FROM aulas WHERE disciplina_id=? AND resumo!='' ORDER BY numero",
            (disciplina_id,)
        ).fetchall()
    if not aulas:
        return f"DISCIPLINA: {disc['nome']}\n{disc['descricao'] or ''}"
    linhas = [f"DISCIPLINA: {disc['nome']}", disc['descricao'] or "", "", "AULAS JÁ MINISTRADAS:"]
    for a in aulas:
        tops = []
        try: tops = json.loads(a["topicos"] or "[]")
        except: pass
        l = f"  • Aula {a['numero']}: {a['tema']}"
        if a["resumo"]: l += f" — {a['resumo']}"
        if tops: l += f"\n    Tópicos: {', '.join(tops)}"
        linhas.append(l)
    linhas += ["", "INSTRUÇÕES:",
               "- NÃO repita conteúdo já abordado.",
               "- Referencie aulas anteriores quando relevante.",
               "- Construa sobre o conhecimento estabelecido."]
    return "\n".join(l for l in linhas if l is not None)

# ═══════════════════════════════════════════════════════════════════════════════
# DISCO
# ═══════════════════════════════════════════════════════════════════════════════
def slugify(s: str) -> str:
    s = s.lower().strip()
    for a, b in [('ã','a'),('â','a'),('á','a'),('à','a'),('ê','e'),('é','e'),
                 ('è','e'),('í','i'),('î','i'),('õ','o'),('ô','o'),('ó','o'),
                 ('ò','o'),('ú','u'),('û','u'),('ç','c'),('ñ','n')]:
        s = s.replace(a, b)
    s = re.sub(r'[^\w\s-]','',s)
    s = re.sub(r'[\s_]+','-',s)
    return re.sub(r'-+','-',s).strip('-') or 'disciplina'

def salvar_html_aula(disciplina_id: int, numero: int, html: str):
    with _db_lock, get_db() as conn:
        disc = conn.execute("SELECT sigla, pasta FROM disciplinas WHERE id=?", (disciplina_id,)).fetchone()
    chave = slugify((disc["sigla"] or disc["pasta"])) if disc else None
    if not chave: return None
    destino = BASE_DIR / chave / f"{int(numero):02d}"
    destino.mkdir(parents=True, exist_ok=True)
    index = destino / "index.html"
    index.write_text(html, encoding="utf-8")
    caminho = str(Path(chave) / f"{int(numero):02d}" / "index.html")
    print(f"  HTML → {index}")
    return caminho

# ═══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ═══════════════════════════════════════════════════════════════════════════════
class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.command:6}  {self.path}  →  {args[1] if len(args)>1 else ''}")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors(); self.end_headers(); self.wfile.write(data)

    def _body(self):
        n   = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b""
        return json.loads(raw) if raw else {}

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")

        if path == "/session/load":
            if SESSION_F.exists():
                try: self._json(200, {"ok": True, "session": json.loads(SESSION_F.read_text())})
                except Exception as e: self._json(500, {"ok": False, "error": str(e)})
            else: self._json(200, {"ok": False, "session": None})
            return

        if path == "/disciplinas":
            with _db_lock, get_db() as conn:
                rows = conn.execute(
                    """SELECT d.id, d.nome, d.sigla, d.descricao, d.link_header, d.pasta,
                              COUNT(a.id) as total_aulas
                       FROM disciplinas d LEFT JOIN aulas a ON a.disciplina_id=d.id
                       GROUP BY d.id ORDER BY d.nome"""
                ).fetchall()
            self._json(200, [dict(r) for r in rows]); return

        m = re.fullmatch(r"/disciplinas/(\d+)", path)
        if m:
            with _db_lock, get_db() as conn:
                row = conn.execute("SELECT * FROM disciplinas WHERE id=?", (int(m.group(1)),)).fetchone()
            if row:
                self._json(200, dict(row))
            else:
                self._json(404, {"error": "não encontrada"})
            return

        m = re.fullmatch(r"/disciplinas/(\d+)/aulas", path)
        if m:
            with _db_lock, get_db() as conn:
                rows = conn.execute(
                    "SELECT id,disciplina_id,numero,tema,resumo,topicos,caminho_html,criada_em,atualizada_em FROM aulas WHERE disciplina_id=? ORDER BY numero",
                    (int(m.group(1)),)
                ).fetchall()
            self._json(200, [dict(r) for r in rows]); return

        m = re.fullmatch(r"/disciplinas/(\d+)/contexto", path)
        if m:
            self._json(200, {"contexto": build_contexto(int(m.group(1)))}); return

        m = re.fullmatch(r"/aulas/(\d+)", path)
        if m:
            with _db_lock, get_db() as conn:
                row = conn.execute("SELECT * FROM aulas WHERE id=?", (int(m.group(1)),)).fetchone()
            if row:
                self._json(200, dict(row))
            else:
                self._json(404, {"error": "não encontrada"})
            return

        if path in ("", "/"):
            path = "/gerador-aulas.html"
        fp = (BASE_DIR / path.lstrip("/")).resolve()
        if not str(fp).startswith(str(BASE_DIR.resolve())):
            self._404(); return
        if fp.exists() and fp.is_file():
            raw = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type",   MIME.get(fp.suffix.lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(raw)))
            self._cors(); self.end_headers(); self.wfile.write(raw)
        else: self._404()

    # ── POST ─────────────────────────────────────────────────────────────────
    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")

        if path == "/session/save":
            try:
                tmp = SESSION_F.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._body(), indent=2, ensure_ascii=False))
                tmp.replace(SESSION_F)
                self._json(200, {"ok": True})
            except Exception as e: self._json(500, {"ok": False, "error": str(e)})
            return

        if path == "/disciplinas":
            try:
                body  = self._body()
                nome  = body.get("nome","").strip()
                sigla = body.get("sigla","").strip().upper()
                if not nome: self._json(400, {"error": "nome obrigatório"}); return
                if not sigla: sigla = nome[:6].upper().replace(" ","")
                pasta = sigla  # pasta usa a sigla diretamente
                (BASE_DIR / pasta).mkdir(parents=True, exist_ok=True)
                print(f"  Pasta criada: {BASE_DIR/pasta}")
                with _db_lock, get_db() as conn:
                    cur = conn.execute(
                        "INSERT INTO disciplinas (nome, sigla, descricao, link_header, pasta) VALUES (?,?,?,?,?)",
                        (nome, sigla, body.get("descricao",""), body.get("link_header",""), pasta)
                    )
                    row = conn.execute("SELECT * FROM disciplinas WHERE id=?", (cur.lastrowid,)).fetchone()
                self._json(201, dict(row))
            except sqlite3.IntegrityError: self._json(409, {"error": "Disciplina já existe"})
            except Exception as e: self._json(500, {"error": str(e)})
            return

        if path == "/aulas":
            try:
                body          = self._body()
                disciplina_id = body.get("disciplina_id")
                numero        = int(body.get("numero") or 0)
                tema          = body.get("tema","").strip()
                slides_json   = json.dumps(body.get("slides",[]), ensure_ascii=False)
                modelo        = body.get("modelo","qwen3:14b")
                html          = body.get("html","")
                if not all([disciplina_id, numero, tema]):
                    self._json(400, {"error": "disciplina_id, numero e tema obrigatórios"}); return

                caminho = salvar_html_aula(disciplina_id, numero, html) if html else ""

                with _db_lock, get_db() as conn:
                    conn.execute(
                        """INSERT INTO aulas (disciplina_id,numero,tema,slides_json,caminho_html)
                           VALUES (?,?,?,?,?)
                           ON CONFLICT(disciplina_id,numero) DO UPDATE SET
                             tema=excluded.tema,
                             slides_json=excluded.slides_json,
                             caminho_html=CASE WHEN excluded.caminho_html!='' THEN excluded.caminho_html ELSE caminho_html END,
                             atualizada_em=datetime('now')""",
                        (disciplina_id, numero, tema, slides_json, caminho or "")
                    )
                    row = conn.execute(
                        "SELECT * FROM aulas WHERE disciplina_id=? AND numero=?",
                        (disciplina_id, numero)
                    ).fetchone()
                    aula_id = row["id"]

                gerar_resumo_async(aula_id, slides_json, modelo)
                self._json(201, {"ok": True, "aula_id": aula_id, "caminho": caminho})
            except Exception as e: self._json(500, {"error": str(e)})
            return

        if path.startswith("/api/") or path.startswith("/ollama/"):
            self._proxy_ollama(path.replace("/ollama/","/api/",1) if path.startswith("/ollama/") else path)
            return

        self._404()

    # ── PUT ──────────────────────────────────────────────────────────────────
    def do_PUT(self):
        path = self.path.split("?")[0].rstrip("/")

        m = re.fullmatch(r"/disciplinas/(\d+)", path)
        if m:
            did = int(m.group(1))
            try:
                body  = self._body()
                sigla = body.get("sigla","").strip().upper() or None
                pasta = sigla if sigla else None
                if pasta: (BASE_DIR/pasta).mkdir(parents=True, exist_ok=True)
                with _db_lock, get_db() as conn:
                    conn.execute(
                        """UPDATE disciplinas SET
                           nome=COALESCE(?,nome), sigla=COALESCE(?,sigla),
                           descricao=COALESCE(?,descricao), link_header=COALESCE(?,link_header),
                           pasta=COALESCE(?,pasta) WHERE id=?""",
                        (body.get("nome"), sigla, body.get("descricao"), body.get("link_header"), pasta, did)
                    )
                    row = conn.execute("SELECT * FROM disciplinas WHERE id=?", (did,)).fetchone()
                if row:
                    self._json(200, dict(row))
                else:
                    self._json(404, {"error": "não encontrada"})
            except Exception as e: self._json(500, {"error": str(e)})
            return

        m = re.fullmatch(r"/aulas/(\d+)", path)
        if m:
            aid = int(m.group(1))
            try:
                body = self._body()
                with _db_lock, get_db() as conn:
                    conn.execute(
                        """UPDATE aulas SET
                           resumo=COALESCE(?,resumo),
                           topicos=COALESCE(?,topicos),
                           atualizada_em=datetime('now')
                           WHERE id=?""",
                        (body.get("resumo"),
                         json.dumps(body["topicos"], ensure_ascii=False) if "topicos" in body else None,
                         aid)
                    )
                    row = conn.execute("SELECT * FROM aulas WHERE id=?", (aid,)).fetchone()
                if row:
                    self._json(200, {"ok": True, **dict(row)})
                else:
                    self._json(404, {"error": "aula não encontrada"})
            except Exception as e: self._json(500, {"error": str(e)})
            return

        self._404()

    # ── DELETE ────────────────────────────────────────────────────────────────
    def do_DELETE(self):
        path = self.path.split("?")[0].rstrip("/")
        m = re.fullmatch(r"/disciplinas/(\d+)", path)
        if m:
            with _db_lock, get_db() as conn:
                conn.execute("DELETE FROM disciplinas WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok": True}); return
        m = re.fullmatch(r"/aulas/(\d+)", path)
        if m:
            with _db_lock, get_db() as conn:
                conn.execute("DELETE FROM aulas WHERE id=?", (int(m.group(1)),))
            self._json(200, {"ok": True}); return
        self._404()

    # ── PROXY OLLAMA ──────────────────────────────────────────────────────────
    def _proxy_ollama(self, ollama_path):
        n    = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else b""
        try:
            req = urllib.request.Request(f"{OLLAMA}{ollama_path}", data=body,
                                          headers={"Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=1800) as resp:
                self.send_response(200)
                self.send_header("Content-Type","application/x-ndjson")
                self.send_header("Transfer-Encoding","chunked")
                self._cors(); self.end_headers()
                while True:
                    chunk = resp.read(512)
                    if not chunk: break
                    self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
        except urllib.error.URLError as e:
            err = json.dumps({"error": f"Ollama inacessível: {e}"}, ensure_ascii=False).encode()
            self.send_response(502); self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(err))); self._cors(); self.end_headers(); self.wfile.write(err)
        except Exception as e:
            err = json.dumps({"error": str(e)}, ensure_ascii=False).encode()
            self.send_response(500); self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(err))); self._cors(); self.end_headers(); self.wfile.write(err)

    def _404(self):
        body = b"404 Not Found"
        self.send_response(404); self.send_header("Content-Type","text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors(); self.end_headers(); self.wfile.write(body)

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    os.chdir(BASE_DIR)
    init_db()
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"""
  ╔══════════════════════════════════════════╗
  ║       AulaGen Server v3                 ║
  ╠══════════════════════════════════════════╣
  ║  Local:   http://localhost:{PORT:<5}         ║
  ║  Ollama:  {OLLAMA:<31} ║
  ║  DB:      aulagem.db                    ║
  ╚══════════════════════════════════════════╝
  Ctrl+C para parar
""")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n  Servidor encerrado.")

if __name__ == "__main__":
    main()
