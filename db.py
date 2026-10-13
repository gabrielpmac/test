"""Banco SQLite, importação/exportação JSON e CSV (CSV em UTF-8 com BOM, abre certo no Excel)."""
import csv
import io
import json
import re
import sqlite3
import unicodedata
from datetime import datetime

VALIDATION = [
    "verificado_thrones",       # Verificado em fonte específica de Thrones
    "corroborado",              # Corroborado por múltiplas fontes
    "jogo_original",            # Encontrado no jogo original (confirmar em Thrones)
    "comunitaria",              # Extraído de fonte comunitária
    "traducao_nao_confirmada",  # Nome/descrição precisa de revisão
    "pendente",                 # Sem evidência suficiente
    "conflitante",              # Fontes divergem
]
OBTAIN = ["fabricar", "coletar", "comprar", "drop", "desconhecido"]
EFFECT_KINDS = ["velocidade", "reducao_custo", "rendimento", "qualidade", "producao_extra",
                "coleta", "combate", "outro", "desconhecido"]

ITEM_COLS = ["key", "orig_id", "name_orig", "name_pt", "name_en", "name_zh", "category", "subcategory",
             "description", "item_type", "obtain", "level_req", "unlock_req", "game", "version", "season",
             "dlc", "civilization", "source", "source_url", "consulted_at", "validation_status", "confidence", "extra"]
RECIPE_COLS = ["key", "output_key", "station", "yield_qty", "is_default", "level_req", "unlock_req", "game",
               "version", "season", "dlc", "source", "source_url", "consulted_at", "validation_status",
               "confidence", "note"]
PERK_COLS = ["key", "orig_id", "name_orig", "name_pt", "name_alt", "tree", "category", "specialization",
             "level_req", "cost", "effect_text", "effect_kind", "value_pct", "condition", "prerequisites",
             "affects_category", "formula_confirmed", "game", "version", "season", "dlc", "source",
             "source_url", "consulted_at", "validation_status", "confidence", "extra"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL, orig_id TEXT, name_orig TEXT, name_pt TEXT,
  name_en TEXT, name_zh TEXT, category TEXT, subcategory TEXT, description TEXT, item_type TEXT,
  obtain TEXT DEFAULT 'desconhecido', level_req TEXT, unlock_req TEXT, game TEXT, version TEXT, season TEXT,
  dlc TEXT, civilization TEXT, source TEXT, source_url TEXT, consulted_at TEXT,
  validation_status TEXT DEFAULT 'pendente', confidence TEXT, extra TEXT);
CREATE TABLE IF NOT EXISTS recipes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL, output_key TEXT NOT NULL,
  station TEXT, yield_qty REAL DEFAULT 1, is_default INTEGER DEFAULT 0, level_req TEXT, unlock_req TEXT,
  game TEXT, version TEXT, season TEXT, dlc TEXT, source TEXT, source_url TEXT, consulted_at TEXT,
  validation_status TEXT DEFAULT 'pendente', confidence TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS recipe_ingredients(
  recipe_key TEXT NOT NULL, ingredient_key TEXT NOT NULL, qty REAL NOT NULL, consumes_durable INTEGER DEFAULT 0,
  PRIMARY KEY(recipe_key, ingredient_key));
CREATE TABLE IF NOT EXISTS horses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, color TEXT, attrs TEXT NOT NULL,
  perks TEXT NOT NULL DEFAULT '[]', note TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS map_markers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, map_id TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
  label TEXT NOT NULL, kind TEXT, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS site_markers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, edition TEXT, map_id TEXT, layer TEXT, category TEXT, x REAL, y REAL,
  label TEXT, icon TEXT, feature_id TEXT);
CREATE INDEX IF NOT EXISTS i_sm ON site_markers(map_id, edition, layer);
CREATE TABLE IF NOT EXISTS perks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE NOT NULL, orig_id TEXT, name_orig TEXT, name_pt TEXT,
  name_alt TEXT, tree TEXT, category TEXT, specialization TEXT, level_req TEXT, cost TEXT, effect_text TEXT,
  effect_kind TEXT DEFAULT 'desconhecido', value_pct REAL, condition TEXT, prerequisites TEXT,
  affects_category TEXT, formula_confirmed INTEGER DEFAULT 0, game TEXT, version TEXT, season TEXT, dlc TEXT,
  source TEXT, source_url TEXT, consulted_at TEXT, validation_status TEXT DEFAULT 'pendente', confidence TEXT,
  extra TEXT);
CREATE TABLE IF NOT EXISTS stocks(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS stock_items(stock_id INTEGER NOT NULL, item_key TEXT NOT NULL, qty REAL NOT NULL,
  PRIMARY KEY(stock_id, item_key));
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, data TEXT NOT NULL,
  updated_at TEXT);
CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, url TEXT, status TEXT,
  notes TEXT, consulted_at TEXT);
CREATE INDEX IF NOT EXISTS i_rec_out ON recipes(output_key);
CREATE INDEX IF NOT EXISTS i_ing ON recipe_ingredients(ingredient_key);
"""


def connect(path):
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def now():
    return datetime.now().isoformat(timespec="seconds")


def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args)]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    return re.sub(r"[^\w一-鿿]+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()


def slug(s):
    return re.sub(r"\s+", "_", norm(s)) or "sem_nome"


# ---------- upserts ----------
def _upsert(con, table, cols, d):
    d = {c: d.get(c) for c in cols}
    if not d.get("key"):
        raise ValueError("registro sem 'key'")
    if table == "items":
        d["obtain"] = d["obtain"] or "desconhecido"
        if d["obtain"] not in OBTAIN:
            raise ValueError(f"obtain inválido: {d['obtain']}")
    if d.get("validation_status") in (None, ""):
        d["validation_status"] = "pendente"
    if d["validation_status"] not in VALIDATION:
        raise ValueError(f"validation_status inválido: {d['validation_status']}")
    sets = ",".join(f"{c}=excluded.{c}" for c in cols if c != "key")
    con.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))}) "
                f"ON CONFLICT(key) DO UPDATE SET {sets}", [d[c] for c in cols])


def upsert_item(con, d):
    d = dict(d)
    if not d.get("key"):
        d["key"] = d.get("orig_id") or slug(d.get("name_orig") or d.get("name_en") or d.get("name_pt"))
    if isinstance(d.get("extra"), (dict, list)):
        d["extra"] = json.dumps(d["extra"], ensure_ascii=False)
    _upsert(con, "items", ITEM_COLS, d)
    return d["key"]


def upsert_recipe(con, d, ingredients=None):
    d = dict(d)
    d.setdefault("yield_qty", d.get("yield") or 1)
    if d.get("yield_qty") in (None, ""):
        d["yield_qty"] = 1
    if not d.get("key"):
        n = con.execute("SELECT COUNT(*) FROM recipes WHERE output_key=?", (d["output_key"],)).fetchone()[0]
        d["key"] = f"r_{d['output_key']}_{n + 1}"
    d["is_default"] = 1 if str(d.get("is_default")).lower() in ("1", "true", "sim", "yes") else 0
    _upsert(con, "recipes", RECIPE_COLS, d)
    if ingredients is not None:
        con.execute("DELETE FROM recipe_ingredients WHERE recipe_key=?", (d["key"],))
        for ing in ingredients:
            if isinstance(ing, dict):
                k, q, dur = ing["item"], ing["qty"], 1 if ing.get("consumes_durable") else 0
            else:
                (k, q), dur = ing[:2], 0
            con.execute("INSERT OR REPLACE INTO recipe_ingredients VALUES(?,?,?,?)", (d["key"], k, float(q), dur))
    return d["key"]


def upsert_perk(con, d):
    d = dict(d)
    if not d.get("key"):
        d["key"] = d.get("orig_id") or slug(d.get("name_orig") or d.get("name_pt"))
    d["formula_confirmed"] = 1 if str(d.get("formula_confirmed")).lower() in ("1", "true", "sim") else 0
    if d.get("effect_kind") in (None, ""):
        d["effect_kind"] = "desconhecido"
    if d["effect_kind"] not in EFFECT_KINDS:
        raise ValueError(f"effect_kind inválido: {d['effect_kind']}")
    if d.get("value_pct") in ("", None):
        d["value_pct"] = None
    if isinstance(d.get("extra"), (dict, list)):
        d["extra"] = json.dumps(d["extra"], ensure_ascii=False)
    _upsert(con, "perks", PERK_COLS, d)
    return d["key"]


# ---------- leitura para a calculadora ----------
def load_calc_data(con):
    items = {r["key"]: {"name": r["name_pt"] or r["name_orig"] or r["name_en"] or r["key"],
                        "obtain": r["obtain"], "category": r["category"]}
             for r in con.execute("SELECT * FROM items")}
    ing = {}
    for r in con.execute("SELECT * FROM recipe_ingredients"):
        ing.setdefault(r["recipe_key"], []).append((r["ingredient_key"], r["qty"]))
    recipes = {}
    for r in con.execute("SELECT * FROM recipes ORDER BY id"):
        recipes.setdefault(r["output_key"], []).append(
            {"key": r["key"], "station": r["station"], "yield": r["yield_qty"] or 1,
             "is_default": bool(r["is_default"]), "ingredients": ing.get(r["key"], []),
             "validation_status": r["validation_status"]})
    return items, recipes


# ---------- exportação ----------
def export_catalog(con):
    recs = []
    for r in rows(con, "SELECT * FROM recipes ORDER BY id"):
        r["ingredients"] = [{"item": x["ingredient_key"], "qty": x["qty"],
                             "consumes_durable": bool(x["consumes_durable"])} for x in
                            con.execute("SELECT * FROM recipe_ingredients WHERE recipe_key=?", (r["key"],))]
        recs.append(r)
    return {"format": "moe-thrones-catalog", "version": 1, "exported_at": now(),
            "items": rows(con, "SELECT * FROM items ORDER BY key"), "recipes": recs,
            "perks": rows(con, "SELECT * FROM perks ORDER BY key"),
            "sources": rows(con, "SELECT * FROM sources ORDER BY id")}


def export_backup(con):
    b = export_catalog(con)
    b["format"] = "moe-thrones-backup"
    stocks = []
    for s in rows(con, "SELECT * FROM stocks"):
        s["items"] = {x["item_key"]: x["qty"] for x in
                      con.execute("SELECT * FROM stock_items WHERE stock_id=?", (s["id"],))}
        stocks.append(s)
    b["stocks"] = stocks
    b["plans"] = [{"name": p["name"], "data": json.loads(p["data"]), "updated_at": p["updated_at"]}
                  for p in con.execute("SELECT * FROM plans")]
    return b


def to_csv(cols, data):
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(cols)
    for d in data:
        w.writerow(["" if d.get(c) is None else d.get(c) for c in cols])
    return "﻿" + buf.getvalue()  # BOM: Excel reconhece UTF-8 (acentos e chinês)


def export_csv(con, what):
    if what == "items":
        return to_csv(ITEM_COLS, rows(con, "SELECT * FROM items ORDER BY key"))
    if what == "recipes":
        return to_csv(RECIPE_COLS, rows(con, "SELECT * FROM recipes ORDER BY id"))
    if what == "recipe_ingredients":
        return to_csv(["recipe_key", "ingredient_key", "qty", "consumes_durable"],
                      rows(con, "SELECT * FROM recipe_ingredients"))
    if what == "perks":
        return to_csv(PERK_COLS, rows(con, "SELECT * FROM perks ORDER BY key"))
    raise ValueError(what)


# ---------- importação ----------
def import_catalog(con, data):
    rep = {"items": 0, "recipes": 0, "perks": 0, "sources": 0, "stocks": 0, "plans": 0, "erros": []}
    for tbl, fn in (("items", upsert_item), ("perks", upsert_perk)):
        for d in data.get(tbl, []):
            try:
                fn(con, d)
                rep[tbl] += 1
            except Exception as e:  # registra e continua
                rep["erros"].append(f"{tbl}:{d.get('key')}: {e}")
    for d in data.get("recipes", []):
        try:
            upsert_recipe(con, d, d.get("ingredients", []))
            rep["recipes"] += 1
        except Exception as e:
            rep["erros"].append(f"recipes:{d.get('key')}: {e}")
    ms = [m for m in data.get("markers", []) if abs(m["x"]) <= 300 and abs(m["y"]) <= 300]
    if data.get("markers"):
        con.execute("DELETE FROM site_markers")
        con.executemany("INSERT INTO site_markers(edition,map_id,layer,category,x,y,label,icon,feature_id) VALUES(?,?,?,?,?,?,?,?,?)",
                        [(m["edition"], m["map_id"], m["layer"], m["category"], m["x"], m["y"], m["label"], m["icon"], m["feature_id"]) for m in ms])
        rep["markers"] = len(ms)
        rep["markers_fora_do_mapa"] = len(data["markers"]) - len(ms)
    for s in data.get("sources", []):
        con.execute("INSERT INTO sources(name,url,status,notes,consulted_at) VALUES(?,?,?,?,?)",
                    (s.get("name"), s.get("url"), s.get("status"), s.get("notes"), s.get("consulted_at")))
        rep["sources"] += 1
    for s in data.get("stocks", []):
        con.execute("INSERT OR IGNORE INTO stocks(name) VALUES(?)", (s["name"],))
        sid = con.execute("SELECT id FROM stocks WHERE name=?", (s["name"],)).fetchone()[0]
        for k, q in (s.get("items") or {}).items():
            con.execute("INSERT OR REPLACE INTO stock_items VALUES(?,?,?)", (sid, k, q))
        rep["stocks"] += 1
    for p in data.get("plans", []):
        con.execute("INSERT INTO plans(name,data,updated_at) VALUES(?,?,?)",
                    (p["name"], json.dumps(p["data"], ensure_ascii=False), p.get("updated_at") or now()))
        rep["plans"] += 1
    con.commit()
    rep["avisos"] = integrity_warnings(con)
    return rep


def import_csv(con, table, text):
    text = text.lstrip("﻿")
    rd = list(csv.DictReader(io.StringIO(text)))
    rep = {"linhas": len(rd), "ok": 0, "erros": []}
    by_recipe = {}
    if table == "recipe_ingredients":
        for r in rd:
            try:
                con.execute("INSERT OR REPLACE INTO recipe_ingredients VALUES(?,?,?,?)",
                            (r["recipe_key"], r["ingredient_key"], float(r["qty"]),
                             1 if str(r.get("consumes_durable") or "").lower() in ("1", "true", "sim") else 0))
                rep["ok"] += 1
            except Exception as e:
                rep["erros"].append(f"{r}: {e}")
    else:
        fn = {"items": upsert_item, "perks": upsert_perk,
              "recipes": lambda c, d: upsert_recipe(c, d)}[table]
        for r in rd:
            try:
                fn(con, {k: (v if v != "" else None) for k, v in r.items()})
                rep["ok"] += 1
            except Exception as e:
                rep["erros"].append(f"{r.get('key')}: {e}")
    con.commit()
    rep["avisos"] = integrity_warnings(con)
    return rep


# ---------- qualidade ----------
def integrity_warnings(con):
    w = []
    for r in con.execute("""SELECT DISTINCT i.recipe_key, i.ingredient_key FROM recipe_ingredients i
                            LEFT JOIN items t ON t.key=i.ingredient_key WHERE t.key IS NULL"""):
        w.append(f"receita {r[0]}: ingrediente '{r[1]}' não existe em items")
    for r in con.execute("""SELECT r.key, r.output_key FROM recipes r LEFT JOIN items t ON t.key=r.output_key
                            WHERE t.key IS NULL"""):
        w.append(f"receita {r[0]}: item de saída '{r[1]}' não existe em items")
    for g in find_duplicates(con):
        w.append("possível duplicata (nome igual, chaves diferentes): " + ", ".join(g["keys"]) +
                 (" — receitas diferentes, mantidas separadas" if g["different_recipes"] else ""))
    return w


def find_duplicates(con):
    groups = {}
    for r in con.execute("SELECT key,name_orig,name_zh,name_en,name_pt FROM items"):
        for n in (r["name_orig"], r["name_zh"], r["name_en"]):
            if n:
                groups.setdefault(norm(n), set()).add(r["key"])
    out, seen = [], set()
    for name, keys in groups.items():
        if len(keys) > 1 and tuple(sorted(keys)) not in seen:
            seen.add(tuple(sorted(keys)))
            sigs = set()
            for k in keys:
                sig = tuple(sorted((x["ingredient_key"], x["qty"]) for x in con.execute(
                    "SELECT i.* FROM recipe_ingredients i JOIN recipes r ON r.key=i.recipe_key WHERE r.output_key=?",
                    (k,))))
                sigs.add(sig)
            out.append({"name": name, "keys": sorted(keys), "different_recipes": len(sigs) > 1})
    return out


def stats(con):
    one = lambda q: con.execute(q).fetchone()[0]
    return {"items": one("SELECT COUNT(*) FROM items"), "recipes": one("SELECT COUNT(*) FROM recipes"),
            "perks": one("SELECT COUNT(*) FROM perks"), "stocks": one("SELECT COUNT(*) FROM stocks"),
            "plans": one("SELECT COUNT(*) FROM plans"),
            "por_validacao": {r[0]: r[1] for r in con.execute(
                "SELECT validation_status, COUNT(*) FROM recipes GROUP BY 1")}}
