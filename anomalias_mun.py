"""Municípios fora do padrão entre os turnos — o caso de Campos dos Goytacazes (RJ), 2026.

Não é teste de integridade (integridade_2t.py: os boletins fecham e somam o oficial); é a busca
de comportamento político raro, para olhar de perto:

  1. o padrão de Campos: o adversário PERDE voto do 1º para o 2º turno e Lula cresce MAIS do que
     os votos que os demais candidatos tinham;
  2. o resíduo: o município contra o que a matriz da própria UF previa para ele (os votos de cada
     origem no 1º turno vezes a migração média da UF). Resíduo grande = o município fez algo
     diferente do resto do estado.

Os dois em 2026 e, com a mesma conta, em 2022 — a referência do que é normal entre turnos.

    python anomalias_mun.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from painel_brasil import nomes_municipios

W = Path("web/dados")


def base(ano):
    if ano == "2026":
        s = pd.read_parquet("data/raw/2026/secoes_1t_brasil.parquet")
        X = json.loads((W / "turnos2026.json").read_text(encoding="utf-8"))
        m = pd.DataFrame(X["mun"])
        o = X["meta"]["origens"]
        g = s.groupby(["uf", "municipio"])[o].sum().reset_index()
        m = m.merge(g, on=["uf", "municipio"])
        mig = X["mig"]["uf"]
        adv1, adv2, lu1, lu2 = m.fl1, m.fl2, m.lu1, m.lu2
        dem, bn1, bn2, ab1, ab2, ap = m.de1, m.bn1, m.bn2, m.ap1 - m.co1, m.ap2 - m.co2, m.ap2
    else:
        p = pd.read_parquet("data/raw/tse/painel_2t_2022.parquet")
        X = json.loads((W / "migracao2022.json").read_text(encoding="utf-8"))
        o = X["meta"]["origens"]
        m = p.groupby(["uf", "municipio"])[o + ["aptos", "aptos_2t", "lula_2t", "bolsonaro_2t", "branco_2t", "nulo_2t", "abst_2t"]].sum().reset_index()
        mig = X["mig"]["uf"]
        adv1, adv2, lu1, lu2 = m.bolsonaro, m.bolsonaro_2t, m.lula, m.lula_2t
        dem = m[["tebet", "ciro", "soraya", "davila", "menores"]].sum(1)
        bn1, bn2, ab1, ab2, ap = m.branco + m.nulo, m.branco_2t + m.nulo_2t, m.abst, m.abst_2t, m.aptos_2t
    # o que a matriz da UF previa para o município
    pv = np.zeros((len(m), 4))
    for i, uf in enumerate(m.uf):
        T = np.array(mig[uf]["pct"]) / 100
        pv[i] = m.loc[m.index[i], o].to_numpy(float) @ T
    d = pd.DataFrame({"uf": m.uf, "municipio": m.municipio, "aptos": ap, "d_lula": lu2 - lu1, "d_adv": adv2 - adv1, "demais": dem,
                      "d_bn": bn2 - bn1, "d_abst": ab2 - ab1, "adv1": adv1, "adv2": adv2, "lu1": lu1, "lu2": lu2,
                      "res_lula": lu2 - pv[:, 0], "res_adv": adv2 - pv[:, 1]})
    d["res_adv_pp"] = 100 * d.res_adv / d.aptos
    d["res_lula_pp"] = 100 * d.res_lula / d.aptos
    d["padrao_campos"] = (d.d_adv < 0) & (d.d_lula > d.demais)
    return d


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    nm = nomes_municipios()
    out = {}
    for ano in ("2022", "2026"):
        d = base(ano)
        d = d[d.uf != "ZZ"]
        g = d[d.aptos >= 10000]
        perdeu = d[d.d_adv < 0]
        print(f"\n== {ano}: {len(d):,} municípios", flush=True)
        print(f"  adversário perdeu voto: {len(perdeu):,} municípios ({100 * len(perdeu) / len(d):.1f}%), {perdeu.aptos.sum() / d.aptos.sum() * 100:.1f}% dos aptos;"
              f" soma {int(perdeu.d_adv.sum()):,} votos", flush=True)
        pc = d[d.padrao_campos]
        print(f"  padrão Campos (adversário perde E Lula cresce mais que os demais): {len(pc):,} municípios, {pc.aptos.sum() / d.aptos.sum() * 100:.2f}% dos aptos", flush=True)
        q = g.res_adv_pp.quantile([.001, .01, .05, .5, .95, .99]).round(2).to_dict()
        print(f"  resíduo do adversário (pontos dos aptos, municípios com 10 mil+ aptos): {q}", flush=True)
        for nome, ordem in (("mais abaixo do previsto (adversário)", True),):
            t = g.sort_values("res_adv_pp").head(15).assign(nome=lambda x: x.municipio.map(nm))
            print(f"  {nome}:", flush=True)
            print(t[["uf", "nome", "aptos", "d_adv", "d_lula", "demais", "d_bn", "res_adv", "res_adv_pp"]].round(2).to_string(index=False), flush=True)
        out[ano] = d.assign(nome=d.municipio.map(nm))
    pd.concat([out[a].assign(ano=a) for a in out]).to_parquet("data/raw/2026_2t/anomalias_mun.parquet")


if __name__ == "__main__":
    main()
