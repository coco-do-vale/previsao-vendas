"""
Endpoint de diagnóstico — acesse /api/dbtest para ver o erro real.
REMOVA ou proteja este arquivo em produção.
"""

import json
import os
import traceback
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = {
            "python":          "ok",
            "pymssql":         None,
            "env_vars":        {},
            "db_connect":      None,
            "db_query":        None,
            "error":           None,
            "traceback":       None,
        }

        # 1 — variáveis de ambiente (senha omitida)
        result["env_vars"] = {
            "DB_SERVER":   os.environ.get("DB_SERVER",   "❌ NÃO CONFIGURADA"),
            "DB_PORT":     os.environ.get("DB_PORT",     "❌ NÃO CONFIGURADA"),
            "DB_DATABASE": os.environ.get("DB_DATABASE", "❌ NÃO CONFIGURADA"),
            "DB_USER":     os.environ.get("DB_USER",     "❌ NÃO CONFIGURADA"),
            "DB_PASSWORD": "***" if os.environ.get("DB_PASSWORD") else "❌ NÃO CONFIGURADA",
        }

        # 2 — importar pymssql
        try:
            import pymssql
            result["pymssql"] = pymssql.__version__
        except ImportError as e:
            result["error"] = f"Falha ao importar pymssql: {e}"
            result["traceback"] = traceback.format_exc()
            self._respond(result)
            return

        # 3 — conectar ao banco
        try:
            conn = pymssql.connect(
                server=os.environ["DB_SERVER"],
                port=int(os.environ.get("DB_PORT", "1433")),
                user=os.environ["DB_USER"],
                password=os.environ["DB_PASSWORD"],
                database=os.environ["DB_DATABASE"],
                as_dict=True,
                timeout=15,
                login_timeout=10,
                tds_version="7.0",
            )
            result["db_connect"] = "✅ conectado"
        except Exception as e:
            result["db_connect"] = "❌ falhou"
            result["error"]     = str(e)
            result["traceback"] = traceback.format_exc()
            self._respond(result)
            return

        # 4 — query simples
        try:
            cur = conn.cursor()
            cur.execute("SELECT DB_NAME() AS banco, GETDATE() AS agora, @@VERSION AS versao")
            row = cur.fetchone()
            conn.close()
            result["db_query"] = {
                "banco": row["banco"],
                "agora": str(row["agora"]),
                "versao": row["versao"][:80] + "…",
            }
        except Exception as e:
            result["db_query"] = "❌ falhou"
            result["error"]    = str(e)
            result["traceback"] = traceback.format_exc()

        self._respond(result)

    def _respond(self, data):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass
