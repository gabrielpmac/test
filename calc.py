"""Calculadora de crafting recursivo (pura, sem banco de dados).

Entradas
--------
targets        {item_key: quantidade}
recipes        {item_key: [receita, ...]}  receita = {"key", "station", "yield", "ingredients": [(item_key, qtd)], "is_default"}
items          {item_key: {"name": str, "obtain": str}}   (obtain: coletar/comprar/drop/desconhecido/fabricar)
stock          {item_key: quantidade disponível}
choices        {item_key: recipe_key | "__coletar__"}   receita escolhida; "__coletar__" trata o item como material bruto
yield_bonus    {item_key: percentual}  bônus de rendimento (ex.: 10 = +10%); é ESTIMATIVA
                se vier de perk sem fórmula confirmada ou de valor manual.

Método
------
1. Escolhe uma receita por item (escolha do usuário, senão a marcada como padrão, senão a primeira).
2. Percorre o grafo em profundidade, detectando ciclos.
3. Processa os itens em ordem topológica (todos os consumidores antes do item), de modo que a
   demanda de intermediários compartilhados seja somada ANTES de arredondar os lotes.
4. Para cada item: desconta o estoque, calcula lotes = ceil(necessário / rendimento efetivo),
   registra o excedente e soma a demanda dos ingredientes.
"""
from fractions import Fraction
from math import ceil

COLETAR = "__coletar__"


def _num(x):
    x = Fraction(x).limit_denominator(10**6)
    return int(x) if x.denominator == 1 else float(x)


def pick_recipe(item, recipes, choices):
    opts = recipes.get(item) or []
    want = (choices or {}).get(item)
    if want == COLETAR or not opts:
        return None
    if want:
        for r in opts:
            if r["key"] == want:
                return r
    for r in opts:
        if r.get("is_default"):
            return r
    return opts[0]


def calculate(targets, recipes, items=None, stock=None, choices=None, yield_bonus=None, confirmed_items=None):
    """confirmed_items: itens cujo bônus vem só de fórmula confirmada (não contam como estimativa)."""
    confirmed_items = set(confirmed_items or ())
    items = items or {}
    stock = {k: Fraction(v) for k, v in (stock or {}).items()}
    choices = choices or {}
    yield_bonus = yield_bonus or {}

    chosen, cycles, missing_targets = {}, [], []
    color, order, stack = {}, [], []

    def visit(it):
        color[it] = 1
        stack.append(it)
        r = pick_recipe(it, recipes, choices)
        chosen[it] = r
        if r:
            for ing, _q in r["ingredients"]:
                c = color.get(ing, 0)
                if c == 0:
                    visit(ing)
                elif c == 1:  # ciclo: ing já está na pilha
                    path = stack[stack.index(ing):] + [ing]
                    if path not in cycles:
                        cycles.append(path)
        stack.pop()
        color[it] = 2
        order.append(it)

    for t, q in targets.items():
        if Fraction(q) <= 0:
            continue
        if t not in color:
            visit(t)
    order.reverse()  # consumidores antes dos ingredientes

    cyc_items = {i for c in cycles for i in c}
    demand = {}
    for t, q in targets.items():
        if Fraction(q) > 0:
            demand[t] = demand.get(t, Fraction(0)) + Fraction(q)

    steps, leaves, surplus = [], [], []
    missing_recipe, unknown_obtain = [], []
    for it in order:
        total = demand.get(it, Fraction(0))
        if total <= 0:
            continue
        have = min(stock.get(it, Fraction(0)), total)
        need = total - have
        name = (items.get(it) or {}).get("name", it)
        r = chosen.get(it)
        if r:
            bonus = Fraction(str(yield_bonus.get(it, 0)))
            eff = Fraction(r["yield"]) * (1 + bonus / 100)
            batches = ceil(need / eff) if need > 0 else 0
            produced = batches * eff
            extra = produced - need
            ing_rows = []
            for ing, q in r["ingredients"]:
                # quantidade física: arredonda para cima por ingrediente (mesma regra observada no site)
                amt = Fraction(ceil(batches * Fraction(q)))
                # evita somar de volta um ingrediente que fecha ciclo
                if it in cyc_items and ing in cyc_items and _closes_cycle(cycles, it, ing):
                    continue
                demand[ing] = demand.get(ing, Fraction(0)) + amt
                ing_rows.append({"item": ing, "name": (items.get(ing) or {}).get("name", ing),
                                 "per_batch": _num(q), "total": _num(amt)})
            steps.append({"item": it, "name": name, "recipe": r["key"], "station": r.get("station"),
                          "required": _num(total), "from_stock": _num(have), "to_craft": _num(need),
                          "yield_per_batch": _num(eff), "batches": batches,
                          "produced": _num(produced), "surplus": _num(extra),
                          "yield_bonus_pct": _num(bonus),
                          "estimate": bonus != 0 and it not in confirmed_items,
                          "ingredients": ing_rows})
            if extra > 0:
                surplus.append({"item": it, "name": name, "qty": _num(extra)})
        else:
            info = items.get(it) or {}
            obtain = info.get("obtain", "desconhecido")
            leaves.append({"item": it, "name": name, "required": _num(total), "have": _num(have),
                           "missing": _num(need), "obtain": obtain})
            if not recipes.get(it):
                if obtain == "fabricar":
                    missing_recipe.append(it)  # marcado como fabricável, mas sem receita cadastrada
                elif obtain == "desconhecido":
                    unknown_obtain.append(it)  # sem receita e sem origem conhecida
    return {
        "steps": steps,
        "materials": sorted(leaves, key=lambda x: x["name"]),
        "surplus": surplus,
        "cycles": cycles,
        "missing_recipe": missing_recipe,
        "unknown_obtain": unknown_obtain,
        "has_estimate": any(s["estimate"] for s in steps),
        "complete": not cycles and not missing_recipe,
    }


def _closes_cycle(cycles, it, ing):
    for c in cycles:
        for a, b in zip(c, c[1:]):
            if a == it and b == ing:
                return True
    return False
