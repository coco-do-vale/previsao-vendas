"""
Previsão de Vendas — API Serverless (Vercel + Python)
Consulta SD2010 (itens NF saída) + SA1010 (clientes) do ERP Protheus.
"""

import json
import os
import calendar
import traceback
from datetime import date
from http.server import BaseHTTPRequestHandler

import pymssql

# ---------------------------------------------------------------------------
# Mapeamento de grupos de produto
# ---------------------------------------------------------------------------
GROUP_NAMES = {
    "AEET": "Água de Coco YUVIA 330ml",
    "RSCV": "Coco Ralado Flocos Úmido/Adoçado – CV (sachê)",
    "LSNG": "Leite de Coco RTG – Coco Chique PET 200ml",
    "ICVC": "CRD Coco do Vale a granel (5 kg)",
    "ISNC": "CRD Sabor Nordeste a granel (5×2 kg)",
    "RSSN": "Coco Ralado Sachê Nordeste",
    "LCVG": "Leite de Coco RTG – Coco do Vale (vidro 200ml)",
    "ANCV": "Água de Coco Natural – Coco do Vale",
    "LCVT": "Leite de Coco RTG TP",
    "ICVS": "CRD Flocos Úmido/Adoçado – CV (granel seco)",
    "OCCV": "Óleo de Coco Virgem",
    "SPOP": "Semiprocessado Óleo Virgem (B2B/industrial)",
    "4RE":  "Resíduos industriais",
    "TCO":  "Torta de Coco",
}

NUMERIC = {"VLR_3M", "VLR_3M_ANT", "VLR_12M", "QTD_3M", "QTD_12M"}

# ---------------------------------------------------------------------------
# Datas dinâmicas (sempre relativas a hoje)
# ---------------------------------------------------------------------------
def period_dates():
    today = date.today()

    def months_back(n):
        month = today.month - n
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        max_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(today.day, max_day)).strftime("%Y%m%d")

    return {
        "d_12m":  months_back(12),
        "d_6m":   months_back(6),
        "d_3m":   months_back(3),
        "d_today": today.strftime("%Y%m%d"),
        "label_3m":     f"{months_back(3)[:6]} → {today.strftime('%Y%m%d')}",
        "label_3m_ant": f"{months_back(6)[:6]} → {months_back(3)[:6]}",
    }

# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------
def connect():
    return pymssql.connect(
        server=os.environ["DB_SERVER"],
        port=int(os.environ.get("DB_PORT", "1433")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_DATABASE"],
        as_dict=True,
        timeout=25,
        login_timeout=10,
        tds_version="7.0",   # evita problemas de SSL/TLS com certificados auto-assinados
    )

# ---------------------------------------------------------------------------
# Cálculos
# ---------------------------------------------------------------------------
def trend_pct(v3m, v3m_ant):
    if v3m_ant and v3m_ant > 0:
        return round((v3m - v3m_ant) / v3m_ant * 100, 1)
    return None

def projection(v3m, v3m_ant):
    if v3m_ant and v3m_ant > 0:
        g = max(min((v3m - v3m_ant) / v3m_ant, 1.0), -0.80)
        return round(v3m * (1 + g * 0.6), 2)
    return round(float(v3m), 2)

def enrich(row):
    out = {}
    for k, v in row.items():
        if k in NUMERIC:
            out[k] = float(v) if v is not None else 0.0
        elif isinstance(v, str):
            out[k] = v.strip()
        else:
            out[k] = v
    grupo = out.get("GRUPO", "")
    out["DESCRICAO"] = GROUP_NAMES.get(grupo, grupo)
    out["TENDENCIA"]   = trend_pct(out.get("VLR_3M", 0), out.get("VLR_3M_ANT", 0))
    out["PROJECAO_3M"] = projection(out.get("VLR_3M", 0), out.get("VLR_3M_ANT", 0))
    return out

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
QUERY_GROUPS = """
SELECT
  RTRIM(sd.D2_GRUPO)                                                           AS GRUPO,
  SUM(CASE WHEN sd.D2_EMISSAO >= '{d_3m}'                            THEN sd.D2_TOTAL ELSE 0 END) AS VLR_3M,
  SUM(CASE WHEN sd.D2_EMISSAO >= '{d_6m}' AND sd.D2_EMISSAO < '{d_3m}'  THEN sd.D2_TOTAL ELSE 0 END) AS VLR_3M_ANT,
  SUM(sd.D2_TOTAL)                                                             AS VLR_12M,
  SUM(CASE WHEN sd.D2_EMISSAO >= '{d_3m}'                            THEN sd.D2_QUANT ELSE 0 END) AS QTD_3M,
  SUM(sd.D2_QUANT)                                                             AS QTD_12M
FROM SD2010 sd
WHERE sd.D_E_L_E_T_ = '' AND sd.D2_TIPO = 'N' AND sd.D2_EMISSAO >= '{d_12m}'
GROUP BY sd.D2_GRUPO
HAVING SUM(sd.D2_TOTAL) > 50000
ORDER BY VLR_12M DESC
"""

QUERY_CLIENTS = """
SELECT TOP 60
  RTRIM(sa.A1_NOME)  AS CLIENTE,
  RTRIM(sa.A1_EST)   AS UF,
  RTRIM(sd.D2_GRUPO) AS GRUPO,
  SUM(CASE WHEN sd.D2_EMISSAO >= '{d_3m}'                            THEN sd.D2_TOTAL ELSE 0 END) AS VLR_3M,
  SUM(CASE WHEN sd.D2_EMISSAO >= '{d_6m}' AND sd.D2_EMISSAO < '{d_3m}'  THEN sd.D2_TOTAL ELSE 0 END) AS VLR_3M_ANT,
  SUM(sd.D2_TOTAL)                                                             AS VLR_12M,
  SUM(CASE WHEN sd.D2_EMISSAO >= '{d_3m}'                            THEN sd.D2_QUANT ELSE 0 END) AS QTD_3M,
  SUM(sd.D2_QUANT)                                                             AS QTD_12M
FROM SD2010 sd
INNER JOIN SA1010 sa
    ON  RTRIM(sa.A1_COD)  = RTRIM(sd.D2_CLIENTE)
    AND RTRIM(sa.A1_LOJA) = RTRIM(sd.D2_LOJA)
    AND sa.D_E_L_E_T_ = ''
WHERE sd.D_E_L_E_T_ = '' AND sd.D2_TIPO = 'N' AND sd.D2_EMISSAO >= '{d_12m}'
GROUP BY sa.A1_NOME, sa.A1_EST, sd.D2_GRUPO
HAVING SUM(sd.D2_TOTAL) > 200000
ORDER BY VLR_12M DESC
"""

# ---------------------------------------------------------------------------
# Busca principal
# ---------------------------------------------------------------------------
def fetch_forecast():
    p = period_dates()

    conn = connect()
    try:
        cur = conn.cursor()

        cur.execute(QUERY_GROUPS.format(**p))
        groups = [enrich(r) for r in cur.fetchall()]

        cur.execute(QUERY_CLIENTS.format(**p))
        clients = [enrich(r) for r in cur.fetchall()]
    finally:
        conn.close()

    t12  = sum(g["VLR_12M"]     for g in groups)
    t3m  = sum(g["VLR_3M"]      for g in groups)
    tant = sum(g["VLR_3M_ANT"]  for g in groups)
    tprj = sum(g["PROJECAO_3M"] for g in groups)

    return {
        "updated_at": date.today().isoformat(),
        "period": p,
        "summary": {
            "total_12m":     round(t12,  2),
            "total_3m":      round(t3m,  2),
            "total_3m_ant":  round(tant, 2),
            "total_proj_3m": round(tprj, 2),
            "trend_pct":     trend_pct(t3m, tant),
        },
        "groups":  groups,
        "clients": clients,
    }

# ---------------------------------------------------------------------------
# Handler Vercel
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            data = fetch_forecast()
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "max-age=180, s-maxage=180")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            msg = json.dumps({
                "error":     str(exc),
                "traceback": traceback.format_exc(),
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(msg)

    def log_message(self, *_):
        pass
