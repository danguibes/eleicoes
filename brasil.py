"""Projeção de Presidente para o Brasil inteiro, urna a urna contra a eleição anterior.

O mesmo modelo do projecao.py, com três diferenças que o país impõe:

  - **zona não é única no país**: há uma "zona 1" em cada UF. Aqui a zona vira
    `índice da UF × 10000 + zona`, e o resto do código segue com um inteiro;
  - **sem perfil do eleitorado** fora de SP (seriam 27 downloads grandes). Medido
    na capital: sem o perfil, o erro médio da projeção vai de 0,33 para 0,38
    ponto e o intervalo ainda cobre o real em 94% das conferências;
  - coordenada ausente cai na média dos locais do município, e, se o município
    inteiro não tiver, na da UF.

A fonte de 2022 não é a coleta de boletins (o ambiente oficial de 2022 saiu do
ar em 28/09/2026), e sim o Portal de Dados Abertos: votação por seção (_BR) e o
detalhe por seção, que traz aptos, comparecimento e a hora em que cada boletim
chegou ao TSE.

    python brasil.py --ensaio      # alvo 2022, base 2018, na ordem real de chegada
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from vizinho import mais_proximo   # SciPy se carregar; numpy se a DLL for bloqueada

import projecao as pj

RAW = Path("data/raw/tse")
OUT = Path("out")
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB",
       "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "ZZ"]
IUF = {u: i + 1 for i, u in enumerate(UFS)}


def zg(uf, zona):
    return uf.map(IUF).astype(int) * 10000 + zona.astype(int)


def coords(ano):
    l = pd.read_parquet(RAW / f"locais_{ano}_BR.parquet",
                        columns=["SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO", "NR_LATITUDE",
                                 "NR_LONGITUDE"] + (["NR_TURNO"] if ano != "2026" else []))
    if "NR_TURNO" in l:
        l = l[l.NR_TURNO == "1"]
    for c in ("NR_LATITUDE", "NR_LONGITUDE"):
        l[c] = pd.to_numeric(l[c].str.replace(",", ".", regex=False), errors="coerce")
    l.loc[l.NR_LATITUDE == -1, ["NR_LATITUDE", "NR_LONGITUDE"]] = np.nan
    g = (l.groupby(["SG_UF", "NR_ZONA", "NR_LOCAL_VOTACAO"])
         .agg(mun=("CD_MUNICIPIO", "first"), lat=("NR_LATITUDE", "first"), lon=("NR_LONGITUDE", "first"))
         .reset_index())
    for chave in ("mun", "SG_UF"):
        m = g.groupby(chave)[["lat", "lon"]].transform("mean")
        g["lat"] = g.lat.fillna(m.lat)
        g["lon"] = g.lon.fillna(m.lon)
    g["zona"] = zg(g.SG_UF, g.NR_ZONA)
    g["local"] = g.NR_LOCAL_VOTACAO.astype(int)
    # plano aproximado: 1 grau ≈ 111 km; a longitude encolhe com a latitude
    g["x"] = g.lon * 111_000 * np.cos(np.radians(g.lat.fillna(-15)))
    g["y"] = g.lat * 111_000
    g["municipio"] = g.mun.astype(int)
    fora_do_pais(g)
    return g[["SG_UF", "municipio", "zona", "local", "x", "y"]]


def fora_do_pais(t):
    """Exterior (UF "ZZ") não tem coordenada: cada cidade vira um ponto próprio, longe
    do Brasil e das outras cidades — a urna de Lisboa se compara com Lisboa, não
    com um bairro de Manaus. O código de município do TSE identifica a cidade."""
    m = t.x.isna() & (t.zona // 10000 == IUF["ZZ"])
    t.loc[m, "x"] = 5e8 + t.loc[m, "municipio"] * 1e5
    t.loc[m, "y"] = 0.0


def completar_xy(u, c):
    """Seção cujo (zona, local) não está no arquivo de locais — ~3 mil no país, número
    de local que muda entre arquivos: vai para o centro do município."""
    cm = c.groupby("municipio")[["x", "y"]].mean()
    sem = u.x.isna()
    u.loc[sem, "x"] = u.loc[sem, "municipio"].map(cm.x)
    u.loc[sem, "y"] = u.loc[sem, "municipio"].map(cm.y)
    fora_do_pais(u)
    ainda = u.x.isna()
    if ainda.any():   # município sem nenhum local com coordenada: centro da UF
        cu = c.groupby("SG_UF")[["x", "y"]].mean()
        u.loc[ainda, "x"] = u.loc[ainda, "uf"].map(cu.x)
        u.loc[ainda, "y"] = u.loc[ainda, "uf"].map(cu.y)
        print(f"coordenada pela UF: {ainda.sum()}", flush=True)
    print(f"coordenada pelo município: {sem.sum() - u.x.isna().sum():,}; ainda sem: {u.x.isna().sum()}", flush=True)
    return u


def votos_secao(ano, cats):
    v = pd.read_parquet(RAW / f"votacao_{ano}_BR.parquet",
                        columns=["NR_TURNO", "CD_CARGO", "SG_UF", "NR_ZONA", "NR_SECAO", "NR_LOCAL_VOTACAO",
                                 "NR_VOTAVEL", "QT_VOTOS"])
    v = v[(v.NR_TURNO == "1") & (v.CD_CARGO == "1")]
    v = v.assign(zona=zg(v.SG_UF, v.NR_ZONA), secao=v.NR_SECAO.astype(int),
                 local=v.NR_LOCAL_VOTACAO.astype(int), cod=v.NR_VOTAVEL.astype(int),
                 votos=v.QT_VOTOS.astype(int))
    v["cat"] = v.cod.map(cats).fillna(v.cod.map({95: "bn", 96: "bn"})).fillna("outros")
    t = v.pivot_table(index=["zona", "secao", "local"], columns="cat", values="votos",
                      aggfunc="sum", fill_value=0).reset_index()
    return t, list(cats.values()) + ["outros", "bn"]


def detalhe_2022():
    d = pd.read_parquet(RAW / "detalhe_2022_BR.parquet",
                        columns=["NR_TURNO", "CD_CARGO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
                                 "QT_APTOS", "QT_COMPARECIMENTO", "DT_RECEBIMENTO_BU_HOR_TSE"])
    d = d[(d.NR_TURNO == "1") & (d.CD_CARGO == "1")]
    return pd.DataFrame({
        "uf": d.SG_UF, "municipio": d.CD_MUNICIPIO.astype(int),
        "zona": zg(d.SG_UF, d.NR_ZONA), "secao": d.NR_SECAO.astype(int),
        "aptos": d.QT_APTOS.astype(int), "comparecimento": d.QT_COMPARECIMENTO.astype(int),
        "t": pd.to_datetime(d.DT_RECEBIMENTO_BU_HOR_TSE, format="%d/%m/%Y %H:%M:%S", errors="coerce")})


def base_local(ano, cats):
    """Eleição-base por local de votação: votos por categoria, comparecimento e aptos."""
    t, cs = votos_secao(ano, cats)
    b = t.groupby(["zona", "local"])[cs].sum()
    b["comparecimento"] = b[cs].sum(axis=1)
    e = pd.read_parquet(RAW / f"locais_{ano}_BR.parquet",
                        columns=["SG_UF", "NR_ZONA", "NR_LOCAL_VOTACAO", "QT_ELEITOR_SECAO"]
                        + (["NR_TURNO"] if ano != "2026" else []))
    if "NR_TURNO" in e:
        e = e[e.NR_TURNO == "1"]
    e = e.assign(zona=zg(e.SG_UF, e.NR_ZONA), local=e.NR_LOCAL_VOTACAO.astype(int),
                 n=pd.to_numeric(e.QT_ELEITOR_SECAO, errors="coerce"))
    b["aptos"] = e.groupby(["zona", "local"]).n.sum().reindex(b.index)
    b["aptos"] = b.aptos.fillna(b.comparecimento / 0.79)
    return b.reset_index(), cs


def montar_X(univ, base, cats_base):
    b = base.dropna(subset=["x"]).reset_index(drop=True)
    d, i = mais_proximo(np.c_[b.x, b.y], np.c_[univ.x, univ.y])
    bb = b.iloc[i].reset_index(drop=True)
    X = pd.DataFrame(pj.clr(bb[cats_base].to_numpy(float)), columns=[f"b_{c}" for c in cats_base])
    X["b_comp"] = pj.logit((bb.comparecimento / bb.aptos).clip(0.05, 0.99).to_numpy(float))
    X["log_dist"] = np.log1p(d)
    return X, d


def ensaio(pontos=(0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90), n_boot=100):
    cats_alvo = {13: "lula", 22: "bolsonaro", 15: "tebet", 12: "ciro"}
    cats_base = {17: "bolsonaro18", 13: "haddad18", 12: "ciro18", 45: "alckmin18", 30: "amoedo18"}
    alvo, cats = votos_secao("2022", cats_alvo)
    det = detalhe_2022()
    u = alvo.merge(det, on=["zona", "secao"], how="inner")
    c22 = coords("2022")
    u = completar_xy(u.merge(c22.drop(columns=["SG_UF", "municipio"]), on=["zona", "local"], how="left"), c22)
    base, cb = base_local("2018", cats_base)
    base = base.merge(coords("2018").drop(columns=["SG_UF", "municipio"]), on=["zona", "local"], how="left")
    X, d = montar_X(u, base, cb)
    print(f"seções {len(u):,} em {u.uf.nunique()} UFs; sem hora de chegada {u.t.isna().sum()}; "
          f"local-base a >1 km: {(d > 1000).mean():.1%}", flush=True)
    validos = [c for c in cats if c != "bn"]
    tot = u[validos].sum()
    real = tot / tot.sum() * 100
    ordem = u.t.rank(method="first", na_option="bottom").to_numpy()
    linhas = []
    for q in pontos:
        obs = ordem <= q * len(u)
        hora = u.t[obs].max().strftime("%H:%M")
        a = pj.projetar(u, X, obs, cats, n_boot=n_boot)
        av = a[:, [cats.index(c) for c in validos]]
        pv = av / av.sum(1, keepdims=True) * 100
        lo, hi = pj.intervalo(pv[1:], pv[0], pj.FATOR_UF)
        soma = u.loc[obs, validos].sum()
        cont = soma / soma.sum() * 100
        for j, c in enumerate(validos):
            linhas.append({"frac": q, "hora": hora, "cat": c, "real": real[c], "contagem": cont[c],
                           "projecao": pv[0, j], "lo90": lo[j], "hi90": hi[j]})
        L, B = validos.index("lula"), validos.index("bolsonaro")
        print(f"{q:4.0%} {hora}  contagem L−B {cont['lula'] - cont['bolsonaro']:+6.2f}  "
              f"projeção {pv[0, L] - pv[0, B]:+6.2f} [{lo[L] - hi[B]:+.2f}, {hi[L] - lo[B]:+.2f}]  "
              f"final {real['lula'] - real['bolsonaro']:+6.2f}", flush=True)
    r = pd.DataFrame(linhas)
    r["cobre"] = (r.real >= r.lo90) & (r.real <= r.hi90)
    r.to_csv(OUT / "ensaio_projecao_2018_2022_BR.csv", index=False, float_format="%.3f")
    print(f"erro médio: contagem {np.abs(r.contagem - r.real).mean():.2f} pt, projeção "
          f"{np.abs(r.projecao - r.real).mean():.2f} pt; IC90 (fator {pj.FATOR_UF}) cobre {r.cobre.mean():.0%}")
    return r


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true")
    a = ap.parse_args()
    if a.ensaio:
        ensaio()
