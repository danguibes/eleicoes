"""Para onde foram os votos do 1º turno no 2º: a matriz de transição de 2022, seção a seção.

O voto é secreto; ninguém sabe o que um eleitor de Tebet fez no 2º turno. O que se
observa é cada seção nos dois turnos: a mesma urna, os mesmos aptos, composições
diferentes. Se a seção com mais Tebet no 1º turno teve mais Lula no 2º, isso informa
a transferência — é regressão ecológica (Goodman), com as linhas da matriz restritas a
somar 100% e sem negativos. Pressupõe que a transferência é a mesma em todas as
seções do grupo; por isso também se estima por região, UF e quintil de perfil, e se
mede quanto a previsão erra em municípios que ficaram de fora do ajuste.

Linhas (1º turno, frações dos aptos): Lula, Bolsonaro, Tebet, Ciro, Soraya, D'Avila,
os 5 menores, branco, nulo, abstenção. Colunas (2º turno): Lula, Bolsonaro, branco,
nulo, abstenção.

    python transicao.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import brasil as br

RAW = Path("data/raw")
OUT = Path("out")
L1 = {13: "lula", 22: "bolsonaro", 15: "tebet", 12: "ciro", 44: "soraya", 30: "davila"}
LINHAS = list(L1.values()) + ["menores", "branco", "nulo", "abst"]
COLS = ["lula", "bolsonaro", "branco", "nulo", "abst"]
VARS = ["renda", "catolicos", "evangelicos", "sem_religiao", "preta_parda", "superior", "jovens", "idosos"]


def painel_2022():
    """Uma linha por seção: frações do 1º e do 2º turno sobre os aptos."""
    v = pd.read_parquet(RAW / "tse" / "votacao_2022_BR.parquet",
                        columns=["NR_TURNO", "CD_CARGO", "SG_UF", "NR_ZONA", "NR_SECAO", "NR_VOTAVEL", "QT_VOTOS"])
    v = v[v.CD_CARGO == "1"]
    cod = v.NR_VOTAVEL.astype(int)
    v = v.assign(zona=br.zg(v.SG_UF, v.NR_ZONA), secao=v.NR_SECAO.astype(int), votos=v.QT_VOTOS.astype(int),
                 cat=cod.map({**L1, 95: "branco", 96: "nulo"}).fillna("menores"))
    t = v.pivot_table(index=["NR_TURNO", "zona", "secao"], columns="cat", values="votos", aggfunc="sum", fill_value=0)
    d = pd.read_parquet(RAW / "tse" / "detalhe_2022_BR.parquet",
                        columns=["NR_TURNO", "CD_CARGO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "QT_APTOS",
                                 "QT_COMPARECIMENTO", "DT_RECEBIMENTO_BU_HOR_TSE"])
    d = d[d.CD_CARGO == "1"]
    d = d.assign(zona=br.zg(d.SG_UF, d.NR_ZONA), secao=d.NR_SECAO.astype(int), aptos=d.QT_APTOS.astype(int),
                 comp=d.QT_COMPARECIMENTO.astype(int), municipio=d.CD_MUNICIPIO.astype(int),
                 t=pd.to_datetime(d.DT_RECEBIMENTO_BU_HOR_TSE, format="%d/%m/%Y %H:%M:%S", errors="coerce"))
    p1 = t.loc["1"].join(d[d.NR_TURNO == "1"].set_index(["zona", "secao"])[["SG_UF", "municipio", "aptos", "comp", "t"]], how="inner")
    p2 = t.loc["2"][["lula", "bolsonaro", "branco", "nulo"]].join(
        d[d.NR_TURNO == "2"].set_index(["zona", "secao"])[["aptos", "comp", "t"]], how="inner")
    p1["abst"] = p1.aptos - p1.comp
    p2["abst"] = p2.aptos - p2.comp
    for c in LINHAS:
        if c not in p1:
            p1[c] = 0
    s = p1[["SG_UF", "municipio", "aptos", "t"] + LINHAS].join(p2[COLS + ["aptos", "t"]], rsuffix="_2t", how="inner")
    s = s.reset_index()   # rsuffix já deu _2t às colunas do 2º turno
    return s[(s.aptos > 0) & (s.aptos_2t > 0)].rename(columns={"SG_UF": "uf"})


def simplex(v):
    """Projeção de cada linha de v no simplex (soma 1, não negativa) — Duchi et al. 2008."""
    u = -np.sort(-v, axis=1)
    css = np.cumsum(u, axis=1) - 1
    k = np.arange(1, v.shape[1] + 1)
    cond = u - css / k > 0
    r = cond.shape[1] - 1 - np.argmax(cond[:, ::-1], axis=1)
    theta = css[np.arange(len(v)), r] / (r + 1)
    return np.maximum(v - theta[:, None], 0)


def estimar(X, Y, w, iters=3000):
    """min Σ w ||Y − X T||² com cada linha de T no simplex. Só precisa de X'WX e X'WY."""
    A = (X * w[:, None]).T @ X
    B = (X * w[:, None]).T @ Y
    T = np.full((X.shape[1], Y.shape[1]), 1 / Y.shape[1])
    passo = 1 / (np.linalg.eigvalsh(A).max() + 1e-12)
    for _ in range(iters):
        T = simplex(T - passo * (A @ T - B))
    return T


def matrizes(s):
    X = s[LINHAS].to_numpy(float) / s.aptos.to_numpy(float)[:, None]
    Y = s[[f"{c}_2t" for c in COLS]].to_numpy(float) / s.aptos_2t.to_numpy(float)[:, None]
    return X, Y, s.aptos.to_numpy(float)


def tabela(T):
    return {l: {c: round(float(T[i, j]) * 100, 1) for j, c in enumerate(COLS)} for i, l in enumerate(LINHAS)}


def validar(s, grupo=None, seed=0):
    """Ajusta em metade dos municípios e prevê o 2º turno da outra metade (Lula entre os
    válidos, por município). Comparado com o ingênuo: a parcela de Lula entre Lula+Bolsonaro
    do 1º turno."""
    rng = np.random.default_rng(seed)
    mun = s.municipio.unique()
    treino = set(rng.choice(mun, len(mun) // 2, replace=False))
    m = s.municipio.isin(treino).to_numpy()
    X, Y, w = matrizes(s)
    P = np.zeros_like(Y)
    if grupo is None:
        T = estimar(X[m], Y[m], w[m])
        P = X @ T
    else:
        g = s[grupo].to_numpy()
        Tg = estimar(X[m], Y[m], w[m])
        for k in np.unique(g):
            mk = (g == k)
            T = estimar(X[m & mk], Y[m & mk], w[m & mk]) if (m & mk).sum() > 200 else Tg
            P[mk] = X[mk] @ T
    t = s[~m].assign(pl=P[~m, 0] * s.aptos_2t[~m], pb=P[~m, 1] * s.aptos_2t[~m])
    g = t.groupby("municipio")[["pl", "pb", "lula_2t", "bolsonaro_2t", "lula", "bolsonaro", "aptos_2t"]].sum()
    real = 100 * g.lula_2t / (g.lula_2t + g.bolsonaro_2t)
    prev = 100 * g.pl / (g.pl + g.pb)
    ingenuo = 100 * g.lula / (g.lula + g.bolsonaro)
    wm = g.aptos_2t / g.aptos_2t.sum()
    erro = lambda p: float((wm * (p - real).abs()).sum())
    tot = lambda a, b: float(100 * g[a].sum() / (g[a].sum() + g[b].sum()))
    return {"erro_mun_modelo": round(erro(prev), 2), "erro_mun_ingenuo": round(erro(ingenuo), 2),
            "lula_real": round(tot("lula_2t", "bolsonaro_2t"), 2), "lula_previsto": round(tot("pl", "pb"), 2),
            "lula_ingenuo": round(tot("lula", "bolsonaro"), 2)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    s = painel_2022()
    print(f"{len(s):,} seções nos dois turnos; aptos {s.aptos.sum():,} / {s.aptos_2t.sum():,}", flush=True)
    X, Y, w = matrizes(s)
    out = {"secoes": int(len(s)), "linhas": LINHAS, "colunas": COLS}
    T = estimar(X, Y, w)
    out["brasil"] = tabela(T)
    print(pd.DataFrame(out["brasil"]).T.to_string(), flush=True)
    # o ajuste reproduz o total do país?
    P = X @ T
    out["ajuste_brasil"] = {c: [round(float((P[:, j] * s.aptos_2t).sum() / s.aptos_2t.sum() * 100), 2),
                                round(float((Y[:, j] * s.aptos_2t).sum() / s.aptos_2t.sum() * 100), 2)]
                            for j, c in enumerate(COLS)}
    print("previsto × real (% dos aptos):", out["ajuste_brasil"], flush=True)
    s["regiao"] = s.uf.map(__import__("painel_brasil").REGIAO)
    out["regiao"] = {}
    for r, g in s.groupby("regiao"):
        Xg, Yg, wg = matrizes(g)
        out["regiao"][r] = tabela(estimar(Xg, Yg, wg))
    perfil = pd.read_parquet(RAW / "ibge" / "municipios_BR.parquet")
    s = s.merge(perfil[["municipio"] + VARS], on="municipio", how="left")
    out["quintis"] = {}
    for v in VARS:
        d = s[[v, "aptos"]].dropna().sort_values(v)
        ac = (d.aptos.cumsum() / d.aptos.sum()).to_numpy()
        cortes = [float(d[v].iloc[np.searchsorted(ac, q)]) for q in (0.2, 0.4, 0.6, 0.8)]
        s[f"q_{v}"] = np.where(s[v].isna(), 0, 1 + np.searchsorted(cortes, s[v].to_numpy(float), side="right"))
        out["quintis"][v] = {"cortes": cortes}
        for q in range(1, 6):
            g = s[s[f"q_{v}"] == q]
            Xg, Yg, wg = matrizes(g)
            out["quintis"][v][str(q)] = tabela(estimar(Xg, Yg, wg))
        print(v, "Tebet→Lula por quintil:", [out["quintis"][v][str(q)]["tebet"]["lula"] for q in range(1, 6)], flush=True)
    out["validacao"] = {"global": validar(s), "por_uf": validar(s, "uf")}
    print("validação:", out["validacao"], flush=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "transicao_2022.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    s.to_parquet(RAW / "tse" / "painel_2t_2022.parquet", index=False)


if __name__ == "__main__" and "--municipios" not in sys.argv:
    main()


# ---------------------------------------------------------------- por município
def estimar_prior(X, Y, w, T0, lam, iters=1500):
    """Como estimar(), puxado para T0 com peso lam (ridge em direção à matriz da UF)."""
    A = (X * w[:, None]).T @ X + lam * np.eye(X.shape[1])
    B = (X * w[:, None]).T @ Y + lam * T0
    T = T0.copy()
    passo = 1 / (np.linalg.eigvalsh(A).max() + 1e-12)
    for _ in range(iters):
        T = simplex(T - passo * (A @ T - B))
    return T


KAPPA = 0.1


def por_municipio(s, kappa=KAPPA):
    """Uma matriz por município, estimada só com as seções dele e puxada para a da UF.

    A regressão entre seções de lugares diferentes confunde composição com contexto (a
    estimativa nacional dava branco→Bolsonaro 43,5%). Dentro do município o contexto é
    o mesmo para todas as seções. Medido em 05/10/2026: com κ 0,02, 0,1 e 0,5 a matriz
    nacional que sai daqui muda menos de 1 ponto em qualquer célula — mas difere da
    estimativa entre municípios em até 14 pontos (Ciro→Lula: 36 contra 50). Município com
    menos de 5 seções fica com a da UF."""
    X, Y, w = matrizes(s)
    uf, mun = s.uf.to_numpy(), s.municipio.to_numpy()
    Tuf = {u: estimar(X[uf == u], Y[uf == u], w[uf == u]) for u in np.unique(uf)}
    linhas = []
    for m_, ii in pd.Series(np.arange(len(s))).groupby(mun):
        ii = ii.to_numpy()
        u = uf[ii[0]]
        if len(ii) >= 5:
            A = (X[ii] * w[ii, None]).T @ X[ii]
            T = estimar_prior(X[ii], Y[ii], w[ii], Tuf[u], kappa * np.trace(A) / X.shape[1] + 1e-9)
        else:
            T = Tuf[u]
        votos = (X[ii] * w[ii, None]).sum(0)
        for i, l in enumerate(LINHAS):
            linhas.append({"municipio": int(m_), "uf": u, "linha": l, "origem": float(votos[i]),
                           **{c: float(T[i, j]) for j, c in enumerate(COLS)}})
    return pd.DataFrame(linhas)


if __name__ == "__main__" and "--municipios" in sys.argv:
    sys.stdout.reconfigure(encoding="utf-8")
    t = por_municipio(pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet"))
    t.to_parquet(OUT / "transicao_mun_2022.parquet", index=False)
    g = t.assign(**{c: t[c] * t.origem for c in COLS}).groupby("linha")[COLS + ["origem"]].sum()
    print((g[COLS].div(g.origem, axis=0) * 100).round(1).loc[LINHAS].to_string())
