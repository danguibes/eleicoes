"""Checagem sem modelo da migração de brancos e nulos, 2022 e 2026.

Dentro de cada município (desvio da média do município, em pontos dos aptos): as seções com mais
branco + nulo no 1º turno viram Lula ou o adversário crescer mais no 2º? Quintis de seções. Se a
matriz de migração diz "X% dos brancos e nulos foram a Lula", a inclinação aqui tem de ir junto.
Grava em web/dados/migracao2022.json (campo `checagem`).

    python checagem_brancos_nulos.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from naovotos import boletins

ARQ = Path("web/dados/migracao2022.json")


def quintis(m, bn, ap1, l1, f1, ap2, l2, f2):
    d = pd.DataFrame({"m": m, "bn": bn / ap1, "gl": l2 / ap2 - l1 / ap1, "gf": f2 / ap2 - f1 / ap1, "w": ap1})
    for c in ["bn", "gl", "gf"]:
        d[c] = d[c] - d.groupby("m")[c].transform("mean")
    d["q"] = pd.qcut(d.bn, 5, labels=False)
    out = []
    for q, x in d.groupby("q"):
        out.append([round(float(100 * np.average(x[c], weights=x.w)), 2) for c in ["bn", "gl", "gf"]])
    return out


def main():
    s = pd.read_parquet("data/raw/2026/secoes_1t_brasil.parquet")
    partes = []
    for uf, g in s.groupby("uf"):
        b = boletins("2026_2t", uf.lower())
        if b is not None:
            partes.append(g.merge(b, on=["zona", "secao"]))
    p = pd.concat(partes)
    p = p[(p.aptos > 0) & (p["26b_ap"] > 0)]
    a = pd.read_parquet("data/raw/tse/painel_2t_2022.parquet")
    a = a[(a.aptos > 0) & (a.aptos_2t > 0)]
    dados = json.loads(ARQ.read_text(encoding="utf-8"))
    dados["checagem"] = {
        "2026": quintis(p.municipio, p.branco + p.nulo, p.aptos, p.lula, p.flavio, p["26b_ap"], p["26b_lu"], p["26b_ad"]),
        "2022": quintis(a.municipio, a.branco + a.nulo, a.aptos, a.lula, a.bolsonaro, a.aptos_2t, a.lula_2t, a.bolsonaro_2t)}
    ARQ.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(dados["checagem"])


if __name__ == "__main__":
    main()
