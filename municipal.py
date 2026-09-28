"""Camada rápida da noite: projeção nacional a partir dos totais parciais por MUNICÍPIO.

Baixar os ~470 mil boletins do país leva a noite toda (simulado com a chegada
real de 2022: a 70 req/s, 25 min de atraso típico e 1 h no pico). O TSE publica,
para cada município, o resultado parcial das seções já totalizadas — ~5.700
arquivos, que se varrem inteiros em poucos minutos. Esta camada projeta o país
com eles; os boletins urna a urna (SP primeiro) refinam depois.

Por município m, no momento t:
  - apurado: votos das seções já totalizadas, e a fração f_m das seções;
  - resto:   (aptos ainda não apurados) × comparecimento previsto × parcelas previstas.

As parcelas previstas do resto vêm de uma regressão entre municípios — parcela
apurada (razão log centrada) contra a da eleição anterior no mesmo município, com
efeito de UF encolhido —, mais o desvio do próprio município encolhido pelo
tamanho do que já foi apurado nele (o parcial é informativo sobre o resto, mas
não é amostra aleatória dele).

    python municipal.py --ensaio      # 2022 na ordem real de chegada, base 2018 por município
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import projecao as pj

RAW = Path("data/raw/tse")
OUT = Path("out")
K_ENCOLHE = 3000   # votos apurados com que o desvio do próprio município vale metade
# Quanto o parcial do município vale para prever o resto dele. Pelo volume de votos
# (w/(w+K)) uma capital com 5% apurado já confiava quase inteiramente no parcial — e
# as primeiras urnas de uma cidade grande também não são aleatórias.
PESO_PARCIAL = lambda w, f: w / (w + K_ENCOLHE)
REAMOSTRA = "uf"
# Ensaio 2018→2022 (35 conferências): reamostrando UFs, cobertura 77% com fator 1,
# 91% com 1,25, 97% com 1,5. O viés que sobra (~−0,9 ponto para Lula de 10% a 50%)
# é o mesmo do modelo por seção: as urnas tardias de 2022 foram mais Lula do que a
# eleição anterior e a UF explicam.
FATOR_MUN = 1.25
# 2º turno da eleição anterior como covariável: medido no ensaio 2018→2022, PIOROU
# (erro médio 0,282 contra 0,260 sem ele). 2026 pode ter cara de 2º turno, mas não
# há evidência a favor; fica desligado, e o painel usa o 2º turno só para comparar.
USAR_2T = False


def por_municipio(ano, cats, turno="1"):
    v = pd.read_parquet(RAW / f"votacao_{ano}_BR.parquet",
                        columns=["NR_TURNO", "CD_CARGO", "SG_UF", "CD_MUNICIPIO", "NR_VOTAVEL", "QT_VOTOS"])
    v = v[(v.NR_TURNO == turno) & (v.CD_CARGO == "1")]
    v["cat"] = v.NR_VOTAVEL.astype(int).map(cats).fillna(
        v.NR_VOTAVEL.astype(int).map({95: "bn", 96: "bn"})).fillna("outros")
    v["votos"] = v.QT_VOTOS.astype(int)
    t = v.pivot_table(index=["SG_UF", "CD_MUNICIPIO"], columns="cat", values="votos",
                      aggfunc="sum", fill_value=0).reset_index()
    t["municipio"] = t.CD_MUNICIPIO.astype(int)
    return t.rename(columns={"SG_UF": "uf"}).drop(columns="CD_MUNICIPIO")


def secoes_2022(cats):
    """Seções de 2022 com votos por categoria, aptos, comparecimento e hora de chegada."""
    import brasil as br
    t, cs = br.votos_secao("2022", cats)
    d = br.detalhe_2022()
    return t.merge(d, on=["zona", "secao"], how="inner"), cs


def projetar_mun(M, cats, n_boot=200, seed=0, guardar_linhas=False):
    """M: um município por linha, com ap_<cat> (apurado), aptos_ap, comp_ap, aptos (total),
    b_<cat> (base, parcelas), b_comp, uf. Devolve (amostras B×C dos votos no país, por_mun)."""
    rng = np.random.default_rng(seed)
    ap = M[[f"ap_{c}" for c in cats]].to_numpy(float)
    tem = ap.sum(1) > 0
    Xb = np.c_[pj.clr(M[[f"b_{c}" for c in cats]].to_numpy(float) * 1000), pj.logit(M.b_comp.to_numpy(float))]
    if USAR_2T and "b2_a" in M:
        # 2º turno da eleição anterior: a parcela do primeiro contra o segundo
        s2 = (M.b2_a / (M.b2_a + M.b2_b)).clip(0.02, 0.98).fillna(0.5).to_numpy(float)
        Xb = np.c_[Xb, pj.logit(s2)]
    mu, sd = Xb[tem].mean(0), Xb[tem].std(0) + 1e-9
    Xb = (Xb - mu) / sd
    Y = np.c_[pj.clr(ap), pj.logit((M.comp_ap / M.aptos_ap.replace(0, np.nan)).fillna(0.8).to_numpy(float))]
    w = ap.sum(1)
    ufs = M.uf.to_numpy()
    ufu = np.unique(ufs)
    cod = pd.Series(range(len(ufu)), index=ufu)[ufs].to_numpy()
    resto = (M.aptos - M.aptos_ap).clip(lower=0).to_numpy(float)
    frac = (M.aptos_ap / M.aptos).clip(0, 1).to_numpy(float)
    o = np.where(tem)[0]
    # municípios por UF, para reamostrar dentro de cada UF
    grupos = {u: o[ufs[o] == u] for u in np.unique(ufs[o])}
    amostras, por_mun, linhas = [], None, []
    for b in range(n_boot):
        if b == 0:
            idx = o
        elif REAMOSTRA == "uf":
            # UFs inteiras: o erro da projeção é regional, e reamostrar município a
            # município dentro da UF não o enxerga (ensaio: cobertura de 23%)
            us = rng.choice(list(grupos), len(grupos), replace=True)
            idx = np.concatenate([grupos[u] for u in us])
        else:
            idx = np.concatenate([rng.choice(g, len(g), replace=True) for g in grupos.values()])
        coef = pj.ajustar(Xb[idx], Y[idx], w[idx], cod[idx], np.arange(len(ufu)), lam=w[idx].mean() * 2)
        P = pj.prever(coef, Xb, cod, np.arange(len(ufu)))
        # desvio do próprio município, encolhido pelo que já foi apurado nele
        lam = PESO_PARCIAL(w, frac)[:, None]
        P = np.where(tem[:, None], P + lam * (Y - P), P)
        if b > 0:
            k = 1 + Xb.shape[1]
            ez = coef[k:]
            vistas = np.isin(np.arange(len(ufu)), cod[idx])
            if vistas.sum() > 2:
                sz = ez[vistas].std(0)
                sem = ~np.isin(cod, cod[idx])
                P[sem] += rng.normal(0, 1, (len(ufu), ez.shape[1]))[cod[sem]] * sz
        partes = np.exp(P[:, :-1]); partes /= partes.sum(1, keepdims=True)
        tc = 1 / (1 + np.exp(-P[:, -1]))
        linha = ap + partes * (tc * resto)[:, None]
        if b == 0:
            por_mun = linha
        if guardar_linhas:
            linhas.append(linha)
        amostras.append(linha.sum(0))
    if guardar_linhas:
        return np.array(amostras), linhas   # linhas[0] é a projeção central
    return np.array(amostras), por_mun


def ensaio(pontos=(0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90), n_boot=200):
    cats_alvo = {13: "lula", 22: "bolsonaro", 15: "tebet", 12: "ciro"}
    s, cats = secoes_2022(cats_alvo)
    base = por_municipio("2018", {17: "bolsonaro18", 13: "haddad18", 12: "ciro18", 45: "alckmin18", 30: "amoedo18"})
    cb = ["bolsonaro18", "haddad18", "ciro18", "alckmin18", "amoedo18", "outros", "bn"]
    base["tot"] = base[cb].sum(axis=1)
    # a base precisa do mesmo número de categorias do alvo para a razão log: usa as 5 da base
    # como covariáveis e prevê as 6 do alvo — as colunas b_ são as da base, renomeadas
    total = s.groupby("municipio").agg(uf=("uf", "first"), aptos=("aptos", "sum")).reset_index()
    total = total.merge(base.drop(columns="uf"), on="municipio", how="left")
    print(f"municípios {len(total):,}; sem base de 2018: {total.bolsonaro18.isna().sum()}", flush=True)
    for c in cb:
        total[c] = total[c].fillna(total[c].mean())
    total["b_comp"] = (total[cb].sum(axis=1) / total.aptos).clip(0.3, 0.98)
    t2 = por_municipio("2018", {13: "b2_a", 17: "b2_b"}, turno="2")[["municipio", "b2_a", "b2_b"]]
    validos = [c for c in cats if c != "bn"]
    real = s[validos].sum(); real = real / real.sum() * 100
    s = s.sort_values("t")
    linhas = []
    for q in pontos:
        chegou = s.iloc[: int(q * len(s))]
        hora = chegou.t.max().strftime("%H:%M")
        a = chegou.groupby("municipio").agg(**{f"ap_{c}": (c, "sum") for c in cats},
                                           aptos_ap=("aptos", "sum"), comp_ap=("comparecimento", "sum"))
        M = total.merge(a, on="municipio", how="left").fillna({f"ap_{c}": 0 for c in cats} | {"aptos_ap": 0, "comp_ap": 0})
        # base: as parcelas de 2018 entram como b_<cat do alvo> por posição — o que importa
        # é o vetor, não o nome
        for cb_, ca in zip(["haddad18", "bolsonaro18", "alckmin18", "ciro18", "amoedo18", "bn"], cats):
            M[f"b_{ca}"] = M[cb_]
        M = M.merge(t2, on="municipio", how="left")
        amostras, _ = projetar_mun(M, cats, n_boot=n_boot)
        av = amostras[:, [cats.index(c) for c in validos]]
        pv = av / av.sum(1, keepdims=True) * 100
        lo, hi = pj.intervalo(pv[1:], pv[0], 1.0)   # fator 1 aqui: o CSV serve para calibrar
        cont = chegou[validos].sum(); cont = cont / cont.sum() * 100
        for j, c in enumerate(validos):
            linhas.append({"frac": q, "hora": hora, "cat": c, "real": real[c], "contagem": cont[c],
                           "projecao": pv[0, j], "lo90": lo[j], "hi90": hi[j]})
        L, B = validos.index("lula"), validos.index("bolsonaro")
        print(f"{q:4.0%} {hora}  contagem L−B {cont['lula'] - cont['bolsonaro']:+6.2f}  "
              f"projeção {pv[0, L] - pv[0, B]:+6.2f}  final {real['lula'] - real['bolsonaro']:+6.2f}  "
              f"| Lula {pv[0, L]:.2f} [{lo[L]:.2f}, {hi[L]:.2f}] real {real['lula']:.2f}", flush=True)
    r = pd.DataFrame(linhas)
    meia = (r.hi90 - r.lo90) / 2
    z = (r.real - r.projecao).abs() / meia
    print(f"erro médio: contagem {np.abs(r.contagem - r.real).mean():.2f} pt, projeção "
          f"{np.abs(r.projecao - r.real).mean():.2f} pt; cobertura com fator 1: {(z <= 1).mean():.0%}, "
          f"2: {(z <= 2).mean():.0%}, 3: {(z <= 3).mean():.0%}")
    r.to_csv(OUT / "ensaio_municipal_2018_2022_BR.csv", index=False, float_format="%.3f")
    return r


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true")
    a = ap.parse_args()
    if a.ensaio:
        ensaio()
