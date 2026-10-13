"""Servidor local (somente stdlib). Abre em http://127.0.0.1:8765"""
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import db, horse, site_import
from .calc import calculate

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(HERE, "static")
DB_PATH = os.environ.get("MOE_DB", os.path.join(ROOT, "data", "moe.db"))
LOCK = threading.Lock()
CON = None


def j(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def search_items(q):
    sql, args = ["SELECT DISTINCT i.* FROM items i"], []
    where = []
    if q.get("material"):
        sql.append("JOIN recipes rm ON rm.output_key=i.key JOIN recipe_ingredients ri ON ri.recipe_key=rm.key "
                   "JOIN items mat ON mat.key=ri.ingredient_key")
        m = f"%{q['material']}%"
        where.append("(mat.key LIKE ? OR mat.name_pt LIKE ? OR mat.name_en LIKE ? OR mat.name_zh LIKE ? "
                     "OR mat.name_orig LIKE ?)")
        args += [m] * 5
    if q.get("station"):
        sql.append("JOIN recipes rs ON rs.output_key=i.key")
        where.append("rs.station LIKE ?")
        args.append(f"%{q['station']}%")
    if q.get("text"):
        t = f"%{q['text']}%"
        where.append("(i.name_pt LIKE ? OR i.name_en LIKE ? OR i.name_zh LIKE ? OR i.name_orig LIKE ? "
                     "OR i.orig_id LIKE ? OR i.key LIKE ?)")
        args += [t] * 6
    for f in ("category", "civilization", "dlc", "season"):
        if q.get(f):
            where.append(f"i.{f} LIKE ?")
            args.append(f"%{q[f]}%")
    if q.get("status"):
        where.append("i.validation_status=?")
        args.append(q["status"])
    if q.get("perk"):
        p = CON.execute("SELECT affects_category FROM perks WHERE key=?", (q["perk"],)).fetchone()
        where.append("i.category = ?")
        args.append((p[0] if p else None) or "\0")
    if where:
        sql.append("WHERE " + " AND ".join(where))
    limit = max(1, min(int(q.get("limit") or 500), 5000))
    sql.append(f"ORDER BY i.name_pt, i.name_orig LIMIT {limit}")
    return db.rows(CON, " ".join(sql), args)


def item_detail(key):
    it = CON.execute("SELECT * FROM items WHERE key=?", (key,)).fetchone()
    if not it:
        return None
    it = dict(it)
    recs = db.rows(CON, "SELECT * FROM recipes WHERE output_key=? ORDER BY id", (key,))
    for r in recs:
        r["ingredients"] = db.rows(CON, """SELECT ri.ingredient_key AS item, ri.qty,
            COALESCE(t.name_pt,t.name_orig,t.name_en,ri.ingredient_key) AS name
            FROM recipe_ingredients ri LEFT JOIN items t ON t.key=ri.ingredient_key WHERE ri.recipe_key=?""",
                                   (r["key"],))
    used = db.rows(CON, """SELECT DISTINCT r.output_key AS item, COALESCE(t.name_pt,t.name_orig,r.output_key) AS name
        FROM recipe_ingredients ri JOIN recipes r ON r.key=ri.recipe_key LEFT JOIN items t ON t.key=r.output_key
        WHERE ri.ingredient_key=?""", (key,))
    perks = db.rows(CON, "SELECT key,name_pt,name_orig,effect_kind,value_pct,formula_confirmed FROM perks "
                         "WHERE affects_category=? AND ?<>''", (it.get("category") or "\0", it.get("category") or ""))
    return {"item": it, "recipes": recs, "used_in": used, "perks": perks}


def do_calc(body):
    items, recipes = db.load_calc_data(CON)
    stock = {}
    for sid in body.get("stock_ids", []):
        for r in CON.execute("SELECT item_key, qty FROM stock_items WHERE stock_id=?", (sid,)):
            stock[r[0]] = stock.get(r[0], 0) + r[1]
    for k, q in (body.get("extra_stock") or {}).items():
        stock[k] = stock.get(k, 0) + float(q)
    bonus, ignored, confirmed = {}, [], set()
    sel = body.get("perks", [])
    for key in sel:
        p = CON.execute("SELECT * FROM perks WHERE key=?", (key,)).fetchone()
        if not p:
            continue
        name = p["name_pt"] or p["name_orig"] or key
        if p["formula_confirmed"] and p["effect_kind"] == "rendimento" and p["value_pct"]:
            for ik, info in items.items():
                if not p["affects_category"] or p["affects_category"] == info.get("category"):
                    bonus[ik] = bonus.get(ik, 0) + p["value_pct"]
                    confirmed.add(ik)
        else:
            ignored.append({"perk": name, "motivo": "sem fórmula confirmada de rendimento "
                            f"(efeito: {p['effect_kind']}); não altera materiais"})
    manual = body.get("manual_bonus") or {}
    manual_used = False
    for k, pct in manual.items():
        pct = float(pct or 0)
        if not pct:
            continue
        manual_used = True
        for ik in (items if k == "*" else [k]):
            bonus[ik] = bonus.get(ik, 0) + pct
            confirmed.discard(ik)  # bônus manual torna o item uma estimativa
    targets = {k: float(v) for k, v in (body.get("targets") or {}).items() if float(v) > 0}
    for k in targets:
        items.setdefault(k, {"name": k, "obtain": "desconhecido"})
    res = calculate(targets, recipes, items, stock, body.get("choices") or {}, bonus, confirmed)
    res["options"] = {it: [{"key": r["key"], "station": r["station"]} for r in recipes[it]]
                      for it in {s["item"] for s in res["steps"]} if it in recipes}
    res["perks_nao_aplicados"] = ignored
    res["bonus_manual_experimental"] = manual_used
    # (has_estimate já vem da calculadora: só itens com bônus não confirmado)
    res["alerta_validacao"] = sorted({s["recipe"] for s in res["steps"]
                                      if _rec_status(recipes, s["item"], s["recipe"]) in
                                      ("pendente", "conflitante", "traducao_nao_confirmada", "jogo_original",
                                       "comunitaria", None)})
    return res


def _rec_status(recipes, item, rkey):
    for r in recipes.get(item, []):
        if r["key"] == rkey:
            return r.get("validation_status")
    return None


MAP_LABELS = {  # nomes PROVISÓRIOS derivados do ID interno; os nomes oficiais estão nos dados criptografados
    "LV_Battlefield_Island_Main": "Ilha do Campo de Batalha",
    "LargeTerrain_Central_Main": "Terreno Grande — Central",
    "LargeTerrain_Central2_Main": "Terreno Grande — Central 2",
    "LargeTerrain_Desert_Main": "Terreno Grande — Deserto",
}


def maps_info():
    mf = os.path.join(ROOT, "data", "maps", "tile_manifest.json")
    if not os.path.isfile(mf):
        return []
    tiles = json.load(open(mf, encoding="utf-8"))["tiles"]
    out = {}
    for key in tiles:
        mid, z, x, y = key[:-4].split("/")
        m = out.setdefault(mid, {"id": mid, "label": MAP_LABELS.get(mid, mid), "zooms": {}})
        zi = m["zooms"].setdefault(int(z), {"total": 0, "present": 0})
        zi["total"] += 1
        if os.path.isfile(os.path.join(STATIC, "maps", "tiles", mid, z, x, y + ".png")):
            zi["present"] += 1
    res = []
    for m in out.values():
        m["zooms"] = [{"z": z, **v} for z, v in sorted(m["zooms"].items())]
        m["total"] = sum(v["total"] for v in m["zooms"])
        m["present"] = sum(v["present"] for v in m["zooms"])
        res.append(m)
    mm = os.path.join(ROOT, "data", "maps", "moemap_maps.json")
    if os.path.isfile(mm):
        for g in json.load(open(mm, encoding="utf-8")):
            d = os.path.join(STATIC, "maps", "tiles", g["id"], str(g["z"]))
            pres = sum(os.path.isfile(os.path.join(d, str(x), str(y) + ".png")) for x in range(4) for y in range(4))
            res.append({"id": g["id"], "label": g["label"], "grid": {"z": g["z"], "f": g["f"]}, "total": 16, "present": pres,
                        "zooms": [{"z": g["z"], "total": 16, "present": pres}]})
    return sorted(res, key=lambda m: m["id"])


def horse_awakenings():
    out = []
    for r in CON.execute("SELECT name_orig, extra FROM perks WHERE tree='HorsePerk' AND extra IS NOT NULL"):
        try:
            p = json.loads(r["extra"])
        except Exception:
            continue
        if p.get("RealName"):
            out.append({"name": p.get("name") or r["name_orig"], "RealName": p["RealName"]})
    return out


def horse_perks():
    out = []
    for r in CON.execute("SELECT key, name_orig, name_pt, extra FROM perks WHERE tree='HorsePerk'"):
        try:
            p = json.loads(r["extra"] or "{}")
        except Exception:
            p = {}
        out.append({"key": r["key"], "name": r["name_pt"] or r["name_orig"],
                    "mods": p.get("AttributeCorrectionModify"), "has_realname": bool(p.get("RealName"))})
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode("utf-8") if n else ""

    def _route(self, method):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        if not p.startswith("/api/"):
            return self._static(p)
        with LOCK:
            try:
                out = self._api(method, p, q)
                if isinstance(out, tuple):
                    self._send(200, out[1].encode("utf-8"), out[0], out[2] if len(out) > 2 else None)
                else:
                    CON.commit()
                    self._send(200, j(out))
            except Exception as e:  # erro legível para a interface
                CON.rollback()
                self._send(400, j({"erro": str(e)}))

    def _static(self, p):
        if p == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        p = "/index.html" if p in ("/", "") else p
        f = os.path.realpath(os.path.join(STATIC, p.lstrip("/")))
        if not f.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(f):
            return self._send(404, b"nao encontrado", "text/plain")
        self._send(200, open(f, "rb").read(), mimetypes.guess_type(f)[0] or "application/octet-stream")

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_DELETE(self):
        self._route("DELETE")

    # ------------------------------------------------------------------
    def _api(self, m, p, q):
        if p == "/api/meta":
            return {"validation": db.VALIDATION, "obtain": db.OBTAIN, "effect_kinds": db.EFFECT_KINDS,
                    "stats": db.stats(CON),
                    "categories": [r[0] for r in CON.execute(
                        "SELECT DISTINCT category FROM items WHERE category IS NOT NULL ORDER BY 1")],
                    "stations": [r[0] for r in CON.execute(
                        "SELECT DISTINCT station FROM recipes WHERE station IS NOT NULL ORDER BY 1")]}
        if p == "/api/items" and m == "GET":
            return search_items(q)
        if p == "/api/item":
            if m == "GET":
                return item_detail(q["key"]) or {"erro": "item não encontrado"}
            if m == "DELETE":
                CON.execute("DELETE FROM items WHERE key=?", (q["key"],))
                return {"ok": True}
            return {"key": db.upsert_item(CON, json.loads(self._body()))}
        if p == "/api/recipe":
            if m == "DELETE":
                CON.execute("DELETE FROM recipe_ingredients WHERE recipe_key=?", (q["key"],))
                CON.execute("DELETE FROM recipes WHERE key=?", (q["key"],))
                return {"ok": True}
            b = json.loads(self._body())
            return {"key": db.upsert_recipe(CON, b, b.get("ingredients", []))}
        if p == "/api/perks":
            sql, a, w = "SELECT * FROM perks", [], []
            if q.get("text"):
                w.append("(name_pt LIKE ? OR name_orig LIKE ? OR name_alt LIKE ? OR effect_text LIKE ?)")
                a += [f"%{q['text']}%"] * 4
            for f in ("tree", "category", "effect_kind", "level_req"):
                if q.get(f):
                    w.append(f"{f} LIKE ?")
                    a.append(f"%{q[f]}%")
            if w:
                sql += " WHERE " + " AND ".join(w)
            return db.rows(CON, sql + " ORDER BY tree, level_req, name_pt LIMIT 1000", a)
        if p == "/api/perk" and m == "POST":
            return {"key": db.upsert_perk(CON, json.loads(self._body()))}
        if p == "/api/stocks":
            if m == "GET":
                return db.rows(CON, "SELECT s.*, (SELECT COUNT(*) FROM stock_items WHERE stock_id=s.id) AS n "
                                    "FROM stocks s ORDER BY name")
            if m == "DELETE":
                CON.execute("DELETE FROM stock_items WHERE stock_id=?", (q["id"],))
                CON.execute("DELETE FROM stocks WHERE id=?", (q["id"],))
                return {"ok": True}
            name = json.loads(self._body())["name"].strip()
            CON.execute("INSERT INTO stocks(name) VALUES(?)", (name,))
            return {"ok": True}
        if p == "/api/stock":
            if m == "GET":
                return {k: v for k, v in CON.execute("SELECT item_key, qty FROM stock_items WHERE stock_id=?",
                                                     (q["id"],))}
            b = json.loads(self._body())
            CON.execute("DELETE FROM stock_items WHERE stock_id=?", (b["id"],))
            for k, v in b["items"].items():
                if float(v) > 0:
                    CON.execute("INSERT INTO stock_items VALUES(?,?,?)", (b["id"], k, float(v)))
            return {"ok": True}
        if p == "/api/plans":
            if m == "DELETE":
                CON.execute("DELETE FROM plans WHERE id=?", (q["id"],))
                return {"ok": True}
            return db.rows(CON, "SELECT id,name,updated_at FROM plans ORDER BY updated_at DESC")
        if p == "/api/plan":
            if m == "GET":
                r = CON.execute("SELECT * FROM plans WHERE id=?", (q["id"],)).fetchone()
                return {"id": r["id"], "name": r["name"], "data": json.loads(r["data"])}
            b = json.loads(self._body())
            data = json.dumps(b["data"], ensure_ascii=False)
            if b.get("id"):
                CON.execute("UPDATE plans SET name=?, data=?, updated_at=? WHERE id=?",
                            (b["name"], data, db.now(), b["id"]))
                return {"id": b["id"]}
            cur = CON.execute("INSERT INTO plans(name,data,updated_at) VALUES(?,?,?)", (b["name"], data, db.now()))
            return {"id": cur.lastrowid}
        if p == "/api/plan/duplicate":
            r = CON.execute("SELECT * FROM plans WHERE id=?", (json.loads(self._body())["id"],)).fetchone()
            cur = CON.execute("INSERT INTO plans(name,data,updated_at) VALUES(?,?,?)",
                              (r["name"] + " (cópia)", r["data"], db.now()))
            return {"id": cur.lastrowid}
        if p == "/api/calc":
            return do_calc(json.loads(self._body()))
        if p == "/api/maps":
            return maps_info()
        if p == "/api/site_layers":
            return db.rows(CON, "SELECT layer, category, COUNT(*) n FROM site_markers WHERE map_id=? AND edition=? "
                                "GROUP BY layer, category ORDER BY n DESC", (q["map"], q["edition"]))
        if p == "/api/site_markers":
            return db.rows(CON, "SELECT x,y,label,icon,layer,category FROM site_markers WHERE map_id=? AND edition=? "
                                "AND (layer=? OR ?='*') LIMIT 4000", (q["map"], q["edition"], q["layer"], q["layer"]))
        if p == "/api/markers":
            if m == "DELETE":
                CON.execute("DELETE FROM map_markers WHERE id=?", (q["id"],))
                return {"ok": True}
            if m == "POST":
                b = json.loads(self._body())
                if not str(b.get("label", "")).strip():
                    raise ValueError("marcador sem nome")
                CON.execute("INSERT INTO map_markers(map_id,x,y,label,kind,note,created_at) VALUES(?,?,?,?,?,?,?)",
                            (b["map_id"], float(b["x"]), float(b["y"]), b["label"].strip(), b.get("kind"),
                             b.get("note"), db.now()))
                return {"ok": True}
            return db.rows(CON, "SELECT * FROM map_markers WHERE map_id=? ORDER BY id", (q["map"],))
        if p == "/api/horse/meta":
            return {"attrs": horse.ATTRS, "factor": horse.FACTOR, "perks": horse_perks(),
                    "colors": sorted({a["RealName"].get("color") for a in horse_awakenings() if a["RealName"].get("color")})}
        if p == "/api/horse/calc" and m == "POST":
            b = json.loads(self._body())
            mods = [x for x in (b.get("manual_mods") or []) if x]
            for key in b.get("perks", []):
                r = CON.execute("SELECT extra FROM perks WHERE key=?", (key,)).fetchone()
                if r and r["extra"]:
                    mm = json.loads(r["extra"]).get("AttributeCorrectionModify")
                    if mm:
                        mods.append(mm)
            return horse.calc(b.get("panel") or [], mods, horse_awakenings(), b.get("color"))
        if p == "/api/horses":
            if m == "DELETE":
                CON.execute("DELETE FROM horses WHERE id=?", (q["id"],))
                return {"ok": True}
            if m == "POST":
                b = json.loads(self._body())
                if not str(b.get("name", "")).strip():
                    raise ValueError("dê um nome ao cavalo")
                CON.execute("INSERT INTO horses(name,color,attrs,perks,note,updated_at) VALUES(?,?,?,?,?,?)",
                            (b["name"].strip(), b.get("color"), json.dumps(b.get("attrs") or {}),
                             json.dumps(b.get("perks") or []), b.get("note"), db.now()))
                return {"ok": True}
            hs = db.rows(CON, "SELECT * FROM horses ORDER BY name")
            for h in hs:
                h["attrs"] = json.loads(h["attrs"])
                h["perks"] = json.loads(h["perks"])
            return hs
        if p == "/api/site_inventory":
            return json.load(open(os.path.join(ROOT, "data", "site_inventory.json"), encoding="utf-8"))
        if p == "/api/import_site" and m == "POST":
            conv = site_import.load(q["kind"], self._body(), db.now()[:10])
            return db.import_catalog(CON, conv)
        if p == "/api/duplicates":
            return db.find_duplicates(CON)
        if p.startswith("/api/export/"):
            name = p.rsplit("/", 1)[1]
            dl = lambda fn: {"Content-Disposition": f'attachment; filename="{fn}"'}
            if name.endswith(".csv"):
                return ("text/csv; charset=utf-8", db.export_csv(CON, name[:-4]), dl(name))
            if name == "catalog.json":
                return ("application/json; charset=utf-8",
                        json.dumps(db.export_catalog(CON), ensure_ascii=False, indent=1), dl(name))
            if name == "backup.json":
                return ("application/json; charset=utf-8",
                        json.dumps(db.export_backup(CON), ensure_ascii=False, indent=1), dl(name))
        if p == "/api/import" and m == "POST":
            return db.import_catalog(CON, json.loads(self._body()))
        if p == "/api/import_csv" and m == "POST":
            return db.import_csv(CON, q["table"], self._body())
        raise ValueError("rota desconhecida: " + p)


def main(open_browser=True):
    global CON
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    CON = db.connect(DB_PATH)
    seed = os.path.join(ROOT, "data", "catalog.json")
    if CON.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0 and os.path.isfile(seed):
        db.import_catalog(CON, json.load(open(seed, encoding="utf-8")))
    port = int(os.environ.get("MOE_PORT", "8765"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}"
    print(f"MOE Thrones Assistente rodando em {url}  (Ctrl+C para sair)\nBanco: {DB_PATH}")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main("--no-browser" not in sys.argv)
