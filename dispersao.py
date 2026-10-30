"""Dispersão Lula × adversário, município a município, 2022 e 2026 (a partir de anomalias_mun.py).

Grava web/dados/dispersao.json: por ano, os municípios (variação de cada um em votos, os votos do 1º turno
para a variação percentual, os demais e o eleitorado) e a contagem dos quadrantes e dos casos "fora do
padrão" para os dois lados.

    python dispersao.py
"""
import json
from pathlib import Path

import pandas as pd

d = pd.read_parquet("data/raw/2026_2t/anomalias_mun.parquet")
d = d[d.uf != "ZZ"]
out = {}
for ano, x in d.groupby("ano"):
    A = x.aptos.sum()
    conta = lambda m: [int(m.sum()), round(float(100 * x.aptos[m].sum() / A), 2)]
    out[ano] = {
        "mun": {"nome": x.nome.fillna("").tolist(), "uf": x.uf.tolist(), "aptos": x.aptos.astype(int).tolist(),
                "lu1": x.lu1.astype(int).tolist(), "adv1": x.adv1.astype(int).tolist(), "dl": x.d_lula.astype(int).tolist(),
                "da": x.d_adv.astype(int).tolist(), "dem": x.demais.astype(int).tolist()},
        "resumo": {"os_dois_crescem": conta((x.d_lula > 0) & (x.d_adv > 0)), "lula_cresce_adv_perde": conta((x.d_lula > 0) & (x.d_adv < 0)),
                   "adv_cresce_lula_perde": conta((x.d_lula < 0) & (x.d_adv > 0)), "os_dois_perdem": conta((x.d_lula < 0) & (x.d_adv < 0)),
                   "pro_lula": conta((x.d_adv < 0) & (x.d_lula > x.demais)), "pro_adv": conta((x.d_lula < 0) & (x.d_adv > x.demais)),
                   "lula_mais_que_demais": conta(x.d_lula > x.demais), "adv_mais_que_demais": conta(x.d_adv > x.demais)}}
Path("web/dados/dispersao.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print({a: v["resumo"] for a, v in out.items()})
