"""Voto por grupo (idade, sexo), com o comparecimento real no lugar do estimado.

A inferência ecológica pura errou o comparecimento por grupo em até 10 pontos
(ei_busca.py). O comparecimento por perfil é **dado** — o TSE publica por zona —,
então ele entra como dado:

  votantes_{s,r} = eleitores_{s,r} × taxa_real_{zona(s),r}, reescalado para que
  a soma bata com o comparecimento do BU da seção s

e a inferência só divide os votantes entre as candidaturas. Em 2026, na noite,
a taxa por perfil ainda não existe: usa-se a de 2022 por zona e grupo, e a
conferência é a soma prevista contra o comparecimento real de cada BU.

Só idade (5 faixas, 60+ junto) e sexo: foram as que passaram na régua do
comparecimento. Escolaridade foi reprovada em todas as variantes e não é
estimada aqui. O intervalo publicado é o da reamostragem por zona **alargado em
±4 pontos**, o erro máximo medido na régua para a idade.

    python grupos.py
"""
import sys
import time

import numpy as np
import pandas as pd

import ei
from ei_busca import JUNTOS

ERRO_MEDIDO = {"idade": 4.4, "sexo": 1.2}  # erro máximo na régua do comparecimento (pontos)
CATS = {13: "lula", 22: "bolsonaro", 15: "tebet", 12: "ciro"}


def taxas_reais(var):
    r = pd.read_parquet("data/raw/tse/comparecimento_2022_SP.parquet")
    r = r[(r.CD_MUNICIPIO == "71072") & (r.NR_TURNO == "1")]
    for c in ("QT_APTOS", "QT_COMPARECIMENTO"):
        r[c] = r[c].astype(int)
    r["grupo"] = ei.grupo_de(r, var)
    if var in JUNTOS:
        r["grupo"] = r.grupo.map(lambda c: JUNTOS[var].get(c, c))
    r["zona"] = r.NR_ZONA.astype(int)
    t = r.groupby(["zona", "grupo"])[["QT_APTOS", "QT_COMPARECIMENTO"]].sum()
    return (t.QT_COMPARECIMENTO / t.QT_APTOS).unstack()


def votantes(var):
    comp = ei.composicao_secoes("2022", var)
    if var in JUNTOS:
        comp = comp.T.groupby(lambda c: JUNTOS[var].get(c, c), sort=False).sum().T
    tx = taxas_reais(var)
    z = comp.index.get_level_values("zona")
    V = comp.to_numpy() * tx.reindex(z)[comp.columns].fillna(tx.mean()).to_numpy()
    return pd.DataFrame(V, index=comp.index, columns=comp.columns)


def main(n_boot=20):
    sys.stdout.reconfigure(encoding="utf-8")
    v = pd.read_parquet("data/raw/2022/sp/votos.parquet")
    v = v[(v.cargo == "presidente") & (v.municipio == 71072)]
    v["cat"] = v.codigo.map(CATS)
    v.loc[v.tipo.isin(["branco", "nulo"]), "cat"] = "bn"
    v["cat"] = v.cat.fillna("outros")
    N = v.pivot_table(index=["zona", "secao"], columns="cat", values="votos", aggfunc="sum").fillna(0)
    cats = list(CATS.values()) + ["outros", "bn"]
    N = N[cats]
    linhas = []
    for var in ("idade", "sexo"):
        Vt = votantes(var)
        j = Vt.join(N, how="inner")
        G = j[Vt.columns].to_numpy()
        comp_bu = j[cats].sum(1).to_numpy()
        prev = G.sum(1)
        # conferência da premissa: votantes previstos pela taxa real × comparecimento do BU
        err = np.abs(prev - comp_bu).sum() / comp_bu.sum()
        G = G * (comp_bu / prev)[:, None]  # reescala para bater com o BU
        t = time.time()
        ponto, boot = ei.com_reamostragem(G, j[cats].to_numpy(),
                                          j.index.get_level_values("zona").to_numpy(), n_boot=n_boot)
        print(f"{var}: {len(j):,} seções, votantes previstos × BU desviam {err:.1%} "
              f"(soma absoluta por seção), {time.time() - t:.0f} s", flush=True)
        validos = [i for i, c in enumerate(cats) if c != "bn"]
        for gi, g in enumerate(Vt.columns):
            pv = ponto[gi, validos] / ponto[gi, validos].sum() * 100
            bv = boot[:, gi, validos] / boot[:, gi, validos].sum(1, keepdims=True) * 100
            lo, hi = np.percentile(bv, [5, 95], axis=0)
            for k, ci in enumerate(validos):
                meia = (hi[k] - lo[k]) / 2 + ERRO_MEDIDO[var]
                linhas.append({"ano": 2022, "variavel": var, "grupo": g, "cat": cats[ci],
                               "estimado": pv[k], "lo90": pv[k] - meia, "hi90": pv[k] + meia,
                               "votantes": float(G[:, gi].sum())})
            print(f"   {g:8s} " + "  ".join(f"{cats[ci]} {pv[k]:5.1f}" for k, ci in enumerate(validos)),
                  flush=True)
    r = pd.DataFrame(linhas)
    r.to_csv("out/voto_por_grupo_2022.csv", index=False, float_format="%.3f")


if __name__ == "__main__":
    main()
