"""Calculadora de chassi de cavalo.

FÓRMULA (lida no JavaScript público da página "horse" de moe.19970417.com, arquivo capturado no HAR):

    bônus_total[i] = soma, sobre as habilidades escolhidas, de AttributeCorrectionModify[i]
    modificador[i] = 0,16 × bônus_total[i]
    atributo_base[i] = valor_do_painel[i] − modificador[i]

Despertar ("RealName"): para a cor escolhida, as opções são ordenadas por qualidade (Excellence=3,
Good=2, demais=1) e vale a primeira em que, para TODO atributo exigido, atributo_base >= valor − 0,1.

NÃO existe aqui nenhuma regra de herança/cruzamento: ela não aparece em nenhum arquivo capturado.
"""

FACTOR = 0.16
TOLERANCE = 0.1
# ordem fixa dos 5 atributos = ordem do vetor AttributeCorrectionModify no jogo
ATTRS = [
    {"id": "Speed", "zh": "速度", "pt": "Velocidade"},
    {"id": "HP", "zh": "体质", "pt": "Constituição"},
    {"id": "Weight", "zh": "负重", "pt": "Carga"},
    {"id": "SP", "zh": "耐力", "pt": "Resistência"},
    {"id": "Operate", "zh": "操控", "pt": "Controle"},
]


def quality_rank(qtype):
    q = qtype or ""
    return 3 if "Excellence" in q else 2 if "Good" in q else 1


def chassis(panel, skill_mods):
    """panel: 5 valores (None = não informado). skill_mods: lista de vetores de 5 números."""
    out = []
    for i, a in enumerate(ATTRS):
        total = sum(float(m[i] or 0) for m in skill_mods if m and i < len(m))
        modifier = FACTOR * total
        cur = panel[i] if i < len(panel) else None
        cur = None if cur in (None, "") else float(cur)
        out.append({"id": a["id"], "zh": a["zh"], "pt": a["pt"], "panel": cur, "skill_total": total,
                    "modifier": modifier, "base": None if cur is None else cur - modifier})
    return out


def awakenings_for_color(awakenings, color):
    """awakenings: [{name, RealName:{color, QualityType, Attribute:[{id,key,value}], ...}}]"""
    lst = [a for a in awakenings if (a.get("RealName") or {}).get("color") == color]
    return sorted(lst, key=lambda a: -quality_rank((a["RealName"] or {}).get("QualityType")))


def match_awakening(base_by_id, awakenings, color):
    for a in awakenings_for_color(awakenings, color):
        reqs = (a["RealName"] or {}).get("Attribute") or []
        if all(base_by_id.get(r["id"]) is not None and base_by_id[r["id"]] >= float(r["value"]) - TOLERANCE
               for r in reqs):
            return a
    return None


def calc(panel, skill_mods, awakenings=None, color=None):
    attrs = chassis(panel, skill_mods)
    base = {a["id"]: a["base"] for a in attrs}
    m = match_awakening(base, awakenings, color) if awakenings and color else None
    return {"attrs": attrs, "match": m,
            "candidates": awakenings_for_color(awakenings or [], color) if color else []}
