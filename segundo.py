"""Projeção da noite do 2º turno: cada seção comparada com ela mesma no 1º turno.

Em cada momento da noite, para cada município, o TSE publica a soma das seções já
totalizadas (arquivo `u`: votos de Lula, do adversário, brancos, nulos, eleitores e
comparecimento dessas seções) e, no índice de seções da UF, QUAIS seções chegaram e
quando. As `st` primeiras do índice são as que estão na soma (conferido voto a voto no
1º turno de 2026: conferir_indice.py). Com o 1º turno de cada seção em mãos:

  1. a matriz de transição 1º → 2º turno (transicao.py) se aprende entre o 2º turno
     das seções chegadas e o 1º turno DELAS MESMAS, município a município, com uma
     matriz nacional e uma por UF puxada para ela;
  2. o resto de cada município se prevê pelo 1º turno das seções que FALTAM, mais o
     desvio do próprio município encolhido pelo tamanho do parcial.

Ensaio no 2º turno de 2022 (ensaio_2t.py): erro médio de 0,04 ponto, contra 0,27 sem
saber quais seções chegaram e 0,51 com o modelo do 1º turno.

    python segundo.py --ensaio      # 2022 de novo, com intervalo: calibra o fator
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import municipal as mu
import transicao as tr

RAW = Path("data/raw")
OUT = Path("out")
SAIDA = ["lula", "adv", "bn", "abst"]
KAPPA_UF = 0.5      # peso da matriz nacional na de cada UF, relativo ao traço de X'WX da UF
# Ensaio no 2º turno de 2022 (7 momentos, 1% a 90% das seções, 60 reamostragens por UF): cobertura
# do intervalo de 90% com fator 1: 71%; 1,5: 100%. Uma eleição só — e 2026 pode ter migrações menos
# homogêneas que 2022. Erro médio da projeção: 0,067 ponto.
FATOR = 1.5


def por_municipio(sec, linhas, chegou):
    """Somas do 1º turno por município: das seções chegadas e do total."""
    g = sec.assign(**{f"r_{c}": sec[c] * chegou for c in linhas}, aptos_r=sec.aptos * chegou)
    return g.groupby("municipio").agg(uf=("uf", "first"), aptos1=("aptos", "sum"), aptos1_r=("aptos_r", "sum"),
                                      **{c: (c, "sum") for c in linhas}, **{f"r_{c}": (f"r_{c}", "sum") for c in linhas})


def ajustar(Xr, Y, w, ufs, T0=None, iters=1500):
    """Matriz nacional e uma por UF, puxada para a nacional."""
    Tn = tr.estimar(Xr, Y, w, iters=iters) if T0 is None else tr.estimar_prior(Xr, Y, w, T0, 1e-9, iters=iters)
    Tuf = {}
    for u in np.unique(ufs):
        m = ufs == u
        if m.sum() < 3 or w[m].sum() <= 0:
            Tuf[u] = Tn
            continue
        A = (Xr[m] * w[m, None]).T @ Xr[m]
        Tuf[u] = tr.estimar_prior(Xr[m], Y[m], w[m], Tn, KAPPA_UF * np.trace(A) / Xr.shape[1] + 1e-12, iters=iters // 2)
    return Tn, Tuf


def projetar(M, linhas, n_boot=100, seed=0):
    """M: um município por linha, com o 1º turno total (linhas), o das chegadas (r_<linha>,
    aptos1_r), o 2º turno apurado (ap_lula, ap_adv, ap_bn, aptos_ap, abst_ap) e aptos (2º turno).
    Devolve (linhas por município: lula, adv, bn, abst — central —, amostras B×municípios×4)."""
    rng = np.random.default_rng(seed)
    tem = M.aptos_ap.to_numpy() > 0
    rep = M[[f"r_{c}" for c in linhas]].to_numpy(float)
    tot1 = M[linhas].to_numpy(float)
    Xr = rep / np.maximum(M.aptos1_r.to_numpy(float), 1)[:, None]
    Xf = (tot1 - rep) / np.maximum((M.aptos1 - M.aptos1_r).to_numpy(float), 1)[:, None]
    ap = M[["ap_lula", "ap_adv", "ap_bn", "abst_ap"]].to_numpy(float)
    Y = ap / np.maximum(M.aptos_ap.to_numpy(float), 1)[:, None]
    w = M.aptos_ap.to_numpy(float)
    resto = (M.aptos - M.aptos_ap).clip(lower=0).to_numpy(float)[:, None]
    ufs = M.uf.to_numpy()
    votos = ap[:, :3].sum(1)
    lam = (votos / (votos + mu.K_ENCOLHE))[:, None]

    def uma(idx, T0=None, iters=1500):
        Tn, Tuf = ajustar(Xr[idx], Y[idx], w[idx], ufs[idx], T0=T0, iters=iters)
        T = np.stack([Tuf.get(u, Tn) for u in ufs])                     # municípios × linhas × 4
        P = np.einsum("ml,mlc->mc", Xf, T) + np.where(tem[:, None], lam * (Y - np.einsum("ml,mlc->mc", Xr, T)), 0)
        P = np.clip(P, 0, None)
        P /= np.maximum(P.sum(1, keepdims=True), 1e-12)
        return ap + P * resto, Tn, Tuf

    o = np.where(tem)[0]
    central, Tn, Tuf = uma(o)
    projetar.ultima = (Tn, Tuf)      # para quem prevê seção a seção (o detalhe de SP)
    grupos = {u: o[ufs[o] == u] for u in np.unique(ufs[o])}
    amostras = []
    for _ in range(n_boot):
        us = rng.choice(list(grupos), len(grupos), replace=True)     # UFs inteiras: o erro é regional
        # partindo da matriz central: na noite, 60 reamostragens do zero levavam ~3 min
        amostras.append(uma(np.concatenate([grupos[u] for u in us]), T0=Tn, iters=400)[0])
    return central, np.array(amostras)


def ensaio(pontos=(0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90), n_boot=60):
    """2º turno de 2022 na ordem real de chegada, com o 1º turno de 2022 como base."""
    s = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet")
    s = s[s.t_2t.notna()].sort_values("t_2t").reset_index(drop=True)
    linhas = tr.LINHAS
    real = 100 * s.lula_2t.sum() / (s.lula_2t.sum() + s.bolsonaro_2t.sum())
    aptos2 = s.groupby("municipio").aptos_2t.sum()
    res = []
    for f in pontos:
        chegou = (np.arange(len(s)) < int(f * len(s))).astype(float)
        M = por_municipio(s, linhas, chegou)
        ch = s[chegou > 0]
        a = ch.groupby("municipio").agg(ap_lula=("lula_2t", "sum"), ap_adv=("bolsonaro_2t", "sum"),
                                        b=("branco_2t", "sum"), n=("nulo_2t", "sum"),
                                        aptos_ap=("aptos_2t", "sum"), abst_ap=("abst_2t", "sum"))
        a["ap_bn"] = a.b + a.n
        M = M.join(a[["ap_lula", "ap_adv", "ap_bn", "aptos_ap", "abst_ap"]], how="left").fillna(0)
        M["aptos"] = aptos2.reindex(M.index).fillna(M.aptos1)
        M = M.reset_index()
        central, amostras = projetar(M, linhas, n_boot=n_boot)
        pc = 100 * central[:, 0].sum() / central[:, :2].sum()
        pb = 100 * amostras[:, :, 0].sum(1) / amostras[:, :, :2].sum((1, 2))
        lo, hi = np.percentile(pb, [5, 95])
        meia = (hi - lo) / 2
        cont = 100 * ch.lula_2t.sum() / (ch.lula_2t.sum() + ch.bolsonaro_2t.sum())
        res.append({"frac": f, "hora": ch.t_2t.max().strftime("%H:%M"), "contagem": cont, "projecao": pc, "meia90": meia, "real": real})
        print(f"{f:4.0%} {res[-1]['hora']}  contagem {cont:6.2f}  projeção {pc:6.2f} ± {meia:.2f}  real {real:.2f}  "
              f"erro {pc - real:+.2f} ({abs(pc - real) / max(meia, 1e-9):.1f} meias)", flush=True)
    r = pd.DataFrame(res)
    z = (r.projecao - r.real).abs() / r.meia90
    print(f"erro médio {np.abs(r.projecao - r.real).mean():.3f} pt; cobertura com fator 1: {(z <= 1).mean():.0%}, "
          f"1,5: {(z <= 1.5).mean():.0%}, 2: {(z <= 2).mean():.0%}, 3: {(z <= 3).mean():.0%}", flush=True)
    OUT.mkdir(exist_ok=True)
    r.to_csv(OUT / "ensaio_segundo_2022.csv", index=False, float_format="%.3f")
    return r


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true")
    ap.add_argument("--boot", type=int, default=60)
    a = ap.parse_args()
    if a.ensaio:
        ensaio(n_boot=a.boot)
