"""Conversores dos formatos de arquivo do site moe.19970417.com para o catálogo local.

Os formatos abaixo foram deduzidos do JavaScript público capturado no HAR (nomes de campos).
Nenhum arquivo real desses formatos foi lido: os dados no HAR estão criptografados e corrompidos.
Quando você tiver craftingStructures.json / perk.json em mãos, estes conversores os importam.
Todos os registros entram como 'comunitaria' (edição Thrones NÃO confirmada).
"""
import json

SRC = "moe.19970417.com"
URL = "https://moe.19970417.com/"
CONF = "baixa: fonte comunitária; edição (Thrones/original) não confirmada"


def from_crafting_structures(data, consulted_at=None):
    """craftingStructures.json: {chave: {ItemName, ItemDescription, AddCraftQuantity, MaxAmount,
    BaseCraftResourceRequirements: [{FileName, ItemName, BaseResourceRequirement, bConsumesDurable}]}}"""
    if not isinstance(data, dict):
        raise ValueError("craftingStructures.json deve ser um objeto {chave: item}")
    items, recipes, seen = {}, [], set()

    def item(key, name, desc=None, craftable=False, extra=None):
        if key in items:
            if craftable:
                items[key]["obtain"] = "fabricar"
            return
        items[key] = {"key": key, "orig_id": key, "name_orig": name, "name_zh": name, "description": desc,
                      "obtain": "fabricar" if craftable else "desconhecido", "source": SRC, "source_url": URL,
                      "consulted_at": consulted_at, "validation_status": "comunitaria", "confidence": CONF,
                      "extra": extra}

    # 1º passo: todos os registros completos (assim um item citado antes como ingrediente não perde dados)
    for key, v in data.items():
        item(key, v.get("ItemName"), v.get("ItemDescription"), bool(v.get("BaseCraftResourceRequirements")),
             {"MaxAmount": v.get("MaxAmount")} if v.get("MaxAmount") is not None else None)
    # 2º passo: receitas e itens que só aparecem como ingrediente
    for key, v in data.items():
        reqs = v.get("BaseCraftResourceRequirements") or []
        if reqs:
            ings = []
            for r in reqs:
                item(r["FileName"], r.get("ItemName"))
                ings.append({"item": r["FileName"], "qty": r["BaseResourceRequirement"],
                             "consumes_durable": bool(r.get("bConsumesDurable"))})
            recipes.append({"key": f"r_{key}", "output_key": key, "yield_qty": max(1, v.get("AddCraftQuantity") or 1),
                            "is_default": 1, "source": SRC, "source_url": URL, "consulted_at": consulted_at,
                            "validation_status": "comunitaria", "confidence": CONF,
                            "note": "bancada não informada no arquivo de origem", "ingredients": ings})
    return {"items": list(items.values()), "recipes": recipes}


def from_perk_json(data, consulted_at=None):
    """perk.json: [{type, list: [ {quality, list:[perk]} | perk ]}]; perk tem name, description,
    AttributeCorrectionModify[5], RealName{...} etc. O objeto bruto fica em 'extra'."""
    if not isinstance(data, list):
        raise ValueError("perk.json deve ser uma lista de {type, list}")
    perks, used = [], set()
    for grp in data:
        typ = grp.get("type")
        flat = []
        for e in grp.get("list") or []:
            if isinstance(e, dict) and "quality" in e and isinstance(e.get("list"), list):
                flat += [(e["quality"], p) for p in e["list"]]
            else:
                flat.append((None, e))
        for quality, p in flat:
            name = p.get("name")
            key = f"{typ}:{name}"
            n = 2
            while key in used:
                key, n = f"{typ}:{name}#{n}", n + 1
            used.add(key)
            perks.append({"key": key, "name_orig": name, "tree": typ, "category": quality,
                          "level_req": p.get("RequiredCharacterLevel"), "effect_text": p.get("description"),
                          "effect_kind": "desconhecido", "formula_confirmed": 0, "source": SRC, "source_url": URL,
                          "consulted_at": consulted_at, "validation_status": "comunitaria", "confidence": CONF,
                          "extra": p})
    return {"perks": perks}


def load(kind, text, consulted_at=None):
    data = json.loads(text)
    if kind == "crafting":
        return from_crafting_structures(data, consulted_at)
    if kind == "perk":
        return from_perk_json(data, consulted_at)
    raise ValueError("tipo desconhecido: " + kind)
