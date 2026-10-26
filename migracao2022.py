"""A mesma matriz de migração de turnos2026.py, para 2022: do 1º para o 2º turno, dentro de cada município.

Mesmo método (transicao.estimar / estimar_prior, κ 0,1, matriz própria com 5+ seções), mesmas colunas
de destino (Lula, Bolsonaro, branco/nulo, abstenção), para comparar com 2026 célula a célula. Em 2022
há boletim de todas as seções dos dois turnos (data/raw/tse/painel_2t_2022.parquet): nada de amostra.

Saída: web/dados/migracao2022.json, no formato do campo `mig` de turnos2026.json.

    python migracao2022.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from painel_brasil import REGIAO
from transicao import estimar, estimar_prior

ORIGENS = ["lula", "bolsonaro", "tebet", "ciro", "soraya", "davila", "menores", "branco", "nulo", "abst"]
DESTINOS = ["lula", "flavio", "bn", "abst"]   # "flavio" = o adversário (Bolsonaro): o mesmo campo da página
KAPPA, MIN_SEC = 0.1, 5
SAIDA = Path("web/dados/migracao2022.json")


def matrizes(p):
    X = p[ORIGENS].to_numpy(float) / p.aptos.to_numpy(float)[:, None]
    Y = np.column_stack([p.lula_2t, p.bolsonaro_2t, p.branco_2t + p.nulo_2t, p.abst_2t]).astype(float) / p.aptos_2t.to_numpy(float)[:, None]
    return X, Y, p.aptos.to_numpy(float)


def ajustar(p, kappa=KAPPA):
    X, Y, w = matrizes(p)
    uf, mun = p.uf.to_numpy(), p.municipio.to_numpy()
    Tuf = {u: estimar(X[uf == u], Y[uf == u], w[uf == u], iters=2000) for u in np.unique(uf)}
    Tm = {}
    for m_, ii in pd.Series(np.arange(len(p))).groupby(mun):
        ii = ii.to_numpy()
        if len(ii) >= MIN_SEC:
            A = (X[ii] * w[ii, None]).T @ X[ii]
            Tm[int(m_)] = estimar_prior(X[ii], Y[ii], w[ii], Tuf[uf[ii[0]]], kappa * np.trace(A) / X.shape[1] + 1e-9, iters=800)
    return Tuf, Tm


def resumir(F, mask):
    f = F[mask].sum(0)
    tot = f.sum(1, keepdims=True)
    pct = np.divide(100 * f, tot, out=np.zeros_like(f), where=tot > 0)
    return {"votos": [[int(round(x)) for x in l] for l in f], "pct": [[round(float(x), 1) for x in l] for l in pct]}


def validar(p, seed=0):
    rng = np.random.default_rng(seed)
    treino = rng.random(len(p)) < 0.5
    Tuf, Tm = ajustar(p[treino])
    X, Y, w = matrizes(p)
    P = np.array([X[i] @ Tm.get(int(m), Tuf[u]) for i, (u, m) in enumerate(zip(p.uf.to_numpy(), p.municipio.to_numpy()))])
    t = p[~treino].assign(pl=P[~treino, 0] * p.aptos_2t[~treino], pf=P[~treino, 1] * p.aptos_2t[~treino])
    g = t.groupby("municipio")[["pl", "pf", "lula_2t", "bolsonaro_2t", "lula", "bolsonaro", "aptos_2t"]].sum()
    g = g[g.lula_2t + g.bolsonaro_2t > 0]
    real = 100 * g.lula_2t / (g.lula_2t + g.bolsonaro_2t)
    wm = g.aptos_2t / g.aptos_2t.sum()
    erro = lambda prev: round(float((wm * (prev - real).abs()).sum()), 2)
    return {"municipios": int(len(g)), "erro_modelo": erro(100 * g.pl / (g.pl + g.pf)), "erro_ingenuo": erro(100 * g.lula / (g.lula + g.bolsonaro))}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = pd.read_parquet(Path("data/raw/tse/painel_2t_2022.parquet"))
    p = p[(p.aptos > 0) & (p.aptos_2t > 0)]
    Tuf, Tm = ajustar(p)
    g = p.groupby(["uf", "municipio"])[ORIGENS].sum().reset_index()
    F = np.array([g.loc[i, ORIGENS].to_numpy(float)[:, None] * Tm.get(int(m), Tuf[u]) for i, (u, m) in enumerate(zip(g.uf, g.municipio))])
    reg = np.array([REGIAO.get(u, "Exterior") for u in g.uf])
    mig = {"brasil": resumir(F, np.ones(len(g), bool)), "regiao": {r: resumir(F, reg == r) for r in sorted(set(reg))},
           "uf": {u: resumir(F, g.uf.to_numpy() == u) for u in sorted(g.uf.unique())}}
    sens = {k: resumir(np.array([g.loc[i, ORIGENS].to_numpy(float)[:, None] * Tk.get(int(m), Tu[u]) for i, (u, m) in enumerate(zip(g.uf, g.municipio))]),
                       np.ones(len(g), bool))["pct"] for k, (Tu, Tk) in ((k, ajustar(p, k)) for k in (0.02, 0.5))}
    dif = max(abs(a - b) for k in sens for la, lb in zip(sens[k], mig["brasil"]["pct"]) for a, b in zip(la, lb))
    val = validar(p)
    prev = F.sum((0, 1))
    real = np.array([p.lula_2t.sum(), p.bolsonaro_2t.sum(), (p.branco_2t + p.nulo_2t).sum(), p.abst_2t.sum()], float)
    origem = g[ORIGENS].to_numpy(float).sum(1)
    propria = np.array([int(m) in Tm for m in g.municipio])
    print(f"{len(p):,} seções; matriz própria em {propria.sum():,} municípios ({100 * origem[propria].sum() / origem.sum():.1f}% dos eleitores); "
          f"sensibilidade até {dif:.1f} ponto; validação: modelo {val['erro_modelo']} × ingênuo {val['erro_ingenuo']}", flush=True)
    for n, a, b in zip(DESTINOS, prev, real):
        print(f"  {n:6s} previsto {a / 1e6:6.2f} mi · real {b / 1e6:6.2f} mi", flush=True)
    for i, o in enumerate(ORIGENS):
        print(f"  {o:9s} → " + " · ".join(f"{d} {x:5.1f}%" for d, x in zip(DESTINOS, mig["brasil"]["pct"][i])), flush=True)
    SAIDA.write_text(json.dumps({"meta": {"origens": ORIGENS, "destinos": DESTINOS, "secoes": int(len(p)), "mun_propria": int(propria.sum()),
                                          "eleitores_propria": round(float(origem[propria].sum() / origem.sum()), 3), "sens_kappa": round(float(dif), 1),
                                          "validacao": val, "conferencia": {d: [int(a), int(b)] for d, a, b in zip(DESTINOS, prev, real)}},
                                 "mig": mig}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(SAIDA, flush=True)


if __name__ == "__main__":
    main()
