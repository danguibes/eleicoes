"""Projeção do resultado a partir das urnas que já chegaram, urna a urna contra a eleição anterior.

As urnas não chegam em ordem aleatória (em 2022, com 25% das seções, a soma
simples errava a distância Lula − Bolsonaro em 3 pontos). A projeção não usa a
ordem: cada urna do alvo é comparada com o **local de votação da eleição
anterior mais próximo dela** (por coordenada — o local é estável entre eleições;
o número da seção nem tanto, e o eleitorado dentro dela é remexido).

Para cada categoria (candidato, "outros", branco+nulo) e para o comparecimento:

    y_s = X_s · b + u_zona + e_s

  y  razão log centrada da parcela da categoria na urna s (e logit do
     comparecimento), no alvo
  X  as mesmas razões log do local-base mais próximo, o comparecimento-base, e o
     perfil do eleitorado da própria seção no alvo (idade, escolaridade, sexo)
  u  efeito da zona eleitoral, encolhido para zero (ridge): zona sem nenhuma urna
     apurada fica com o efeito médio, e a incerteza disso entra no intervalo

Ajuste por mínimos quadrados ponderados pelos votos. As urnas que faltam recebem
a previsão; as que chegaram entram com o voto real. A incerteza vem de
reamostrar **zonas inteiras** entre as apuradas (urnas vizinhas erram juntas;
reamostrar urna a urna daria uma confiança falsa), sortear o efeito das zonas
ainda sem urna, e somar o resíduo de cada urna.

    python projecao.py --ensaio        # alvo 2022, base 2018, na ordem real de 2022
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

RAW = Path("data/raw")
OUT = Path("out")
EPS = 0.5  # voto somado antes do log, para urna com zero numa categoria


# ---------------------------------------------------------------- coordenadas
def locais_coord(ano, mun="71072"):
    """(zona, local) -> x, y em metros (projeção plana; basta para vizinhança).
    mun=None: a UF inteira — número de zona é único na UF, e local é único na zona."""
    l = pd.read_parquet(RAW / "tse" / f"locais_{ano}_SP.parquet")
    if mun:
        l = l[l.CD_MUNICIPIO == str(mun)]
    if "NR_TURNO" in l:
        l = l[l.NR_TURNO == "1"]
    for c in ("NR_LATITUDE", "NR_LONGITUDE"):
        l[c] = pd.to_numeric(l[c].str.replace(",", ".", regex=False), errors="coerce")
    l = l[(l.NR_LATITUDE != -1) & l.NR_LATITUDE.notna()]
    g = (l.groupby(["NR_ZONA", "NR_LOCAL_VOTACAO"])
         .agg(lat=("NR_LATITUDE", "first"), lon=("NR_LONGITUDE", "first")).reset_index())
    g["zona"] = g.NR_ZONA.astype(int)
    g["local"] = g.NR_LOCAL_VOTACAO.astype(int)
    g["x"] = (g.lon + 46.63) * 102_000
    g["y"] = (g.lat + 23.55) * 111_000
    return g[["zona", "local", "x", "y"]]


def principal_de(ano, mun="71072"):
    """Seção agregada -> seção principal, para somar perfil e eleitores."""
    l = pd.read_parquet(RAW / "tse" / f"locais_{ano}_SP.parquet",
                        columns=["CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_SECAO_PRINCIPAL",
                                 "NR_LOCAL_VOTACAO", "QT_ELEITOR_SECAO"]
                        + (["NR_TURNO"] if ano != "2026" else []))
    if mun:
        l = l[l.CD_MUNICIPIO == str(mun)]
    if "NR_TURNO" in l:
        l = l[l.NR_TURNO == "1"]
    l = l.assign(zona=l.NR_ZONA.astype(int), secao=l.NR_SECAO.astype(int),
                 local=l.NR_LOCAL_VOTACAO.astype(int), municipio=l.CD_MUNICIPIO.astype(int),
                 eleitores=pd.to_numeric(l.QT_ELEITOR_SECAO))
    p = pd.to_numeric(l.NR_SECAO_PRINCIPAL)
    l["principal"] = np.where(p > 0, p, l.secao).astype(int)
    return l[["municipio", "zona", "secao", "principal", "local", "eleitores"]]


# ---------------------------------------------------------------- base
def base_2018(mun="71072"):
    v = pd.read_parquet(RAW / "tse" / "votacao_2018_SP.parquet",
                        columns=["CD_MUNICIPIO", "NR_TURNO", "NR_ZONA", "NR_LOCAL_VOTACAO",
                                 "NR_VOTAVEL", "QT_VOTOS"])
    v = v[(v.CD_MUNICIPIO == mun) & (v.NR_TURNO == "1")]
    v = v.assign(zona=v.NR_ZONA.astype(int), local=v.NR_LOCAL_VOTACAO.astype(int),
                 cod=v.NR_VOTAVEL.astype(int), votos=v.QT_VOTOS.astype(int))
    cats = {17: "bolsonaro18", 13: "haddad18", 12: "ciro18", 45: "alckmin18", 30: "amoedo18"}
    v["cat"] = v.cod.map(cats).fillna(v.cod.map({95: "bn", 96: "bn"})).fillna("outros")
    t = v.pivot_table(index=["zona", "local"], columns="cat", values="votos",
                      aggfunc="sum").fillna(0)
    e = principal_de("2018", mun).groupby(["zona", "local"]).eleitores.sum()
    t["comparecimento"] = t.sum(axis=1)
    t["aptos"] = e.reindex(t.index)
    return t.reset_index(), list(cats.values()) + ["outros", "bn"]


def _votos(pleito, cargo, mun, cats):
    v = pd.read_parquet(RAW / pleito / "sp" / "votos.parquet")
    v = v[v.cargo == cargo]
    if mun:
        v = v[v.municipio == int(mun)]
    if cats == "auto":
        # os mais votados até aqui viram categoria própria; o resto é "outros"
        top = (v[v.tipo == "nominal"].groupby("codigo").votos.sum()
               .sort_values(ascending=False).head(AUTO_K).index)
        cats = {int(k): f"n{int(k)}" for k in top}
    v["cat"] = v.codigo.map(cats)
    return v, cats


AUTO_K = 5


def base_bu(pleito, cats, mun=71072, cargo="presidente"):
    """Base tirada dos BUs do próprio coletor (2022 para domingo)."""
    v, cats = _votos(pleito, cargo, mun, cats)
    v.loc[v.tipo.isin(["branco", "nulo"]), "cat"] = "bn"
    v["cat"] = v.cat.fillna("outros")
    t = v.pivot_table(index=["zona", "local"], columns="cat", values="votos",
                      aggfunc="sum").fillna(0)
    s = v.drop_duplicates(["zona", "secao"]).groupby(["zona", "local"])
    t["comparecimento"] = s.comparecimento.sum()
    t["aptos"] = s.aptos.sum()
    return t.reset_index(), list(cats.values()) + ["outros", "bn"]


# ---------------------------------------------------------------- alvo
def perfil_secoes(ano, mun="71072"):
    """mun=None: a UF inteira."""
    col_n = "QT_ELEITORES_PERFIL" if ano == "2022" else "QT_ELEITORES"
    p = pd.read_parquet(RAW / "tse" / f"perfil_{ano}_SP.parquet",
                        columns=["CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "DS_GENERO",
                                 "DS_FAIXA_ETARIA", "DS_GRAU_ESCOLARIDADE", col_n])
    if mun:
        p = p[p.CD_MUNICIPIO == str(mun)]
    p = p.assign(zona=p.NR_ZONA.astype(int), secao=p.NR_SECAO.astype(int),
                 n=pd.to_numeric(p[col_n]))
    pr = principal_de(ano, mun)[["zona", "secao", "principal"]]
    p = p.merge(pr, on=["zona", "secao"], how="left")
    p["secao"] = p.principal.fillna(p.secao).astype(int)
    idade = p.DS_FAIXA_ETARIA.str.strip().str.split().str[0]
    idade = pd.to_numeric(idade, errors="coerce")
    esc = p.DS_GRAU_ESCOLARIDADE
    p["jovem"] = p.n * (idade <= 24)
    p["idoso"] = p.n * (idade >= 60)
    p["superior"] = p.n * esc.str.startswith("SUPERIOR")
    p["basica"] = p.n * esc.isin(["ANALFABETO", "LÊ E ESCREVE", "ENSINO FUNDAMENTAL INCOMPLETO"])
    p["mulher"] = p.n * (p.DS_GENERO == "FEMININO")
    g = p.groupby(["zona", "secao"])[["n", "jovem", "idoso", "superior", "basica", "mulher"]].sum()
    for c in ["jovem", "idoso", "superior", "basica", "mulher"]:
        g[c] = g[c] / g.n
    return g.rename(columns={"n": "eleitores_perfil"}).reset_index()


def alvo_bu(pleito, cats, mun=71072, cargo="presidente"):
    v, cats = _votos(pleito, cargo, mun, cats)
    v.loc[v.tipo.isin(["branco", "nulo"]), "cat"] = "bn"
    v["cat"] = v.cat.fillna("outros")
    t = v.pivot_table(index=["zona", "secao"], columns="cat", values="votos",
                      aggfunc="sum").fillna(0)
    s = v.drop_duplicates(["zona", "secao"]).set_index(["zona", "secao"])
    t["comparecimento"] = s.comparecimento
    t["aptos"] = s.aptos
    t["local"] = s.local
    return t.reset_index(), list(cats.values()) + ["outros", "bn"]


# ---------------------------------------------------------------- modelo
def clr(m):
    lm = np.log(m + EPS)
    return lm - lm.mean(axis=1, keepdims=True)


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def montar(universo, base, cats_base):
    """Casa cada seção do alvo com o local-base mais próximo e monta X."""
    b = base.dropna(subset=["x"]).reset_index(drop=True)
    d, i = cKDTree(np.c_[b.x, b.y]).query(np.c_[universo.x, universo.y])
    bb = b.iloc[i].reset_index(drop=True)
    X = pd.DataFrame(clr(bb[cats_base].to_numpy(float)), columns=[f"b_{c}" for c in cats_base])
    X["b_comp"] = logit((bb.comparecimento / bb.aptos).to_numpy(float))
    for c in ["jovem", "idoso", "superior", "basica", "mulher"]:
        X[c] = universo[c].fillna(universo[c].mean()).to_numpy()
    X["log_dist"] = np.log1p(d)
    return X, d


def ajustar(X, Y, w, zona, zonas, lam=50.0):
    """Mínimos quadrados ponderados; zonas com penalidade ridge, resto livre."""
    Z = (zona[:, None] == zonas[None, :]).astype(float)
    A = np.c_[np.ones(len(X)), X, Z]
    pen = np.r_[np.zeros(1 + X.shape[1]), np.full(len(zonas), lam)]
    sw = np.sqrt(w)[:, None]
    Aw = A * sw
    coef = np.linalg.solve(Aw.T @ Aw + np.diag(pen) + 1e-6 * np.eye(A.shape[1]), Aw.T @ (Y * sw))
    return coef


def prever(coef, X, zona, zonas):
    Z = (zona[:, None] == zonas[None, :]).astype(float)
    return np.c_[np.ones(len(X)), X, Z] @ coef


def projetar(univ, X, obs_mask, cats, n_boot=200, seed=0):
    """Devolve amostras (n_boot × categorias) dos votos totais projetados no município."""
    rng = np.random.default_rng(seed)
    V = univ[cats].to_numpy(float)
    comp = univ.comparecimento.to_numpy(float)
    aptos = univ.aptos.to_numpy(float)
    zona = univ.zona.to_numpy()
    zonas = np.unique(zona)
    Xn = X.to_numpy(float)
    mu, sd = Xn[obs_mask].mean(0), Xn[obs_mask].std(0) + 1e-9
    Xn = (Xn - mu) / sd
    Y = np.c_[clr(V), logit(comp / aptos)]
    o = np.where(obs_mask)[0]
    f = np.where(~obs_mask)[0]
    real = V[o].sum(0)
    zo = np.unique(zona[o])
    amostras = []
    for bi in range(n_boot):
        if bi == 0:
            idx = o
        else:  # reamostra zonas inteiras entre as apuradas
            zs = rng.choice(zo, size=len(zo), replace=True)
            idx = np.concatenate([o[zona[o] == z] for z in zs])
        coef = ajustar(Xn[idx], Y[idx], comp[idx], zona[idx], zonas)
        P = prever(coef, Xn[f], zona[f], zonas)
        if bi > 0:
            # zona sem nenhuma urna apurada: efeito sorteado da dispersão das que têm
            k = 1 + Xn.shape[1]
            ez = coef[k:]
            vistas = np.isin(zonas, zona[idx])
            sz = ez[vistas].std(0) if vistas.sum() > 2 else np.zeros(ez.shape[1])
            nao = ~np.isin(zona[f], zona[idx])
            P[nao] += rng.normal(0, 1, (nao.sum(), ez.shape[1])) * sz
            # O resíduo de cada urna NÃO entra: somado na escala log e depois
            # exponenciado, puxava todas as amostras para o mesmo lado (Jensen) —
            # medido no ensaio, o IC de 90% cobria o real em 46% dos casos e às
            # vezes nem continha a própria projeção. Somado sobre milhares de
            # urnas, esse ruído se anula; o que não se anula é o erro por zona.
        partes = np.exp(P[:, :-1])
        partes /= partes.sum(1, keepdims=True)
        tc = 1 / (1 + np.exp(-P[:, -1]))
        amostras.append(real + (partes * (tc * aptos[f])[:, None]).sum(0))
    return np.array(amostras)


# Intervalo: centrado na projeção, meia-largura do bootstrap × FATOR.
# Os percentis crus do bootstrap são assimétricos em relação à projeção e, no
# ensaio 2018→2022, cobriam o real em 71% dos casos; centrados, 89%; × 1,25,
# 100% (35 conferências, 7 momentos × 5 categorias). Calibrado numa eleição
# só — e 2026 muda mais que 2022 (dois dos três primeiros são estreantes).
FATOR = 1.25


def intervalo(amostras, ponto):
    lo, hi = np.percentile(amostras, [5, 95], axis=0)
    meia = (hi - lo) / 2 * FATOR
    return ponto - meia, ponto + meia


# ---------------------------------------------------------------- ensaio
def ensaio(pontos=(0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90)):
    cats_alvo = {13: "lula", 22: "bolsonaro", 15: "tebet", 12: "ciro"}
    univ, cats = alvo_bu("2022", cats_alvo)
    coords = locais_coord("2022")
    univ = univ.merge(coords, on=["zona", "local"], how="left")
    sem = univ.x.isna()
    # local sem coordenada (-1/-1 no cadastro): usa o centro dos locais da zona
    cz = coords.groupby("zona")[["x", "y"]].mean()
    univ.loc[sem, ["x", "y"]] = cz.reindex(univ.loc[sem, "zona"]).to_numpy()
    univ = univ.merge(perfil_secoes("2022"), on=["zona", "secao"], how="left")
    base, cats_base = base_2018()
    base = base.merge(locais_coord("2018"), on=["zona", "local"], how="left")
    X, dist = montar(univ, base, cats_base)
    print(f"seções-alvo {len(univ):,} ({sem.sum()} sem coordenada, na média da zona); "
          f"distância até o local-base: mediana {np.median(dist):.0f} m, "
          f"p90 {np.percentile(dist, 90):.0f} m, >1 km {(dist > 1000).mean():.1%}")

    ch = pd.read_csv(RAW / "2022" / "sp" / "chegadas.csv", dtype=str)
    ch["t"] = pd.to_datetime(ch.recebido, format="%d/%m/%Y %H:%M:%S")
    ch = ch.assign(zona=ch.zona.astype(int), secao=ch.secao.astype(int))
    ordem = univ[["zona", "secao"]].merge(ch[["zona", "secao", "t"]], how="left").t.rank(method="first")
    validos = [c for c in cats if c != "bn"]
    total = univ[validos].sum()
    verdade = total / total.sum() * 100
    linhas = []
    for q in pontos:
        obs = (ordem <= q * len(univ)).to_numpy()
        hora = ch.t.sort_values().iloc[int(q * len(univ)) - 1].strftime("%H:%M")
        a = projetar(univ, X, obs, cats)
        av = a[:, [cats.index(c) for c in validos]]
        pv = av / av.sum(1, keepdims=True) * 100
        soma = univ.loc[obs, validos].sum()
        ingenuo = soma / soma.sum() * 100
        los, his = intervalo(pv[1:], pv[0])
        for j, c in enumerate(validos):
            lo, hi = los[j], his[j]
            linhas.append({"frac": q, "hora": hora, "cat": c, "real": verdade[c],
                           "contagem": ingenuo[c], "projecao": pv[0, j],
                           "lo90": lo, "hi90": hi})
        l, b = (next(x for x in linhas[-len(validos):] if x["cat"] == k) for k in ("lula", "bolsonaro"))
        print(f"{q:4.0%} {hora}  contagem L−B {l['contagem'] - b['contagem']:+5.2f}  "
              f"projeção {l['projecao'] - b['projecao']:+5.2f}  final {l['real'] - b['real']:+5.2f}  "
              f"| Lula proj {l['projecao']:.2f} [{l['lo90']:.2f}, {l['hi90']:.2f}] real {l['real']:.2f}",
              flush=True)
    r = pd.DataFrame(linhas)
    r["cobre"] = (r.real >= r.lo90) & (r.real <= r.hi90)
    OUT.mkdir(exist_ok=True)
    r.to_csv(OUT / "ensaio_projecao_2018_2022.csv", index=False, float_format="%.3f")
    print(f"\nerro médio absoluto: contagem {np.abs(r.contagem - r.real).mean():.2f} pt, "
          f"projeção {np.abs(r.projecao - r.real).mean():.2f} pt; "
          f"IC90 cobre o real em {r.cobre.mean():.0%} dos casos")
    return r


# ---------------------------------------------------------------- noite da eleição
# Candidatos de 2026 pelo número de urna (consulta_cand_2026, conferido em 28/09).
# Os que ficam de fora caem em "outros"; branco e nulo em "bn".
CATS_2026 = {13: "lula", 22: "flavio", 70: "cury", 55: "caiado", 14: "renan", 30: "zema"}
BASE_2022 = {13: "lula22", 22: "bolsonaro22", 15: "tebet22", 12: "ciro22"}


def universo_cadastro(ano, mun="71072"):
    """Todas as seções principais do cadastro, com eleitores (somando agregadas),
    coordenada do local e perfil. É o denominador da noite: sabe-se de antemão
    quantas urnas existem e quantos eleitores cada uma tem."""
    pr = principal_de(ano, mun)
    u = (pr.groupby(["zona", "principal"])
         .agg(municipio=("municipio", "first"), local=("local", "first"),
              aptos=("eleitores", "sum")).reset_index()
         .rename(columns={"principal": "secao"}))
    coords = locais_coord(ano, mun)
    u = u.merge(coords, on=["zona", "local"], how="left")
    sem = u.x.isna()
    cz = coords.groupby("zona")[["x", "y"]].mean()
    u.loc[sem, ["x", "y"]] = cz.reindex(u.loc[sem, "zona"]).to_numpy()
    return u.merge(perfil_secoes(ano, mun), on=["zona", "secao"], how="left")


class Noite:
    """Estado pesado carregado uma vez (cadastro, base, X); cada rodada só cruza
    as urnas que chegaram e reajusta — segundos."""

    def __init__(self, pleito="2026", ano_cadastro="2026", base="2022", mun=71072,
                 cargo="presidente"):
        """mun=None: a UF inteira. cargo != presidente: candidatos escolhidos pelo
        voto ("auto" — os mais votados viram categoria), na base e no alvo."""
        self.pleito, self.mun, self.cargo = pleito, mun, cargo
        self.univ = universo_cadastro(ano_cadastro, mun)
        if base == "2018":
            b, self.cats_base = base_2018(str(mun))
        else:
            b, self.cats_base = base_bu(base, BASE_2022 if cargo == "presidente" else "auto",
                                        mun, cargo)
        b = b.merge(locais_coord(base, mun), on=["zona", "local"], how="left")
        self.X, self.dist = montar(self.univ, b, self.cats_base)
        if cargo != "presidente":
            self.cats_alvo = "auto"
        else:
            self.cats_alvo = CATS_2026 if pleito != "2022" else {13: "lula", 22: "bolsonaro",
                                                                  15: "tebet", 12: "ciro"}

    def rodada(self, n_boot=200, apenas=None):
        """apenas: conjunto de (zona, secao) — no ensaio, as que já teriam chegado."""
        arq = RAW / self.pleito / "sp" / "votos.parquet"
        obs, self.cats = (alvo_bu(self.pleito, self.cats_alvo, self.mun, self.cargo)
                          if arq.exists() else (None, None))
        if obs is not None and apenas is not None:
            obs = obs[[k in apenas for k in zip(obs.zona, obs.secao)]]
        if obs is None or obs.empty:
            return {"secoes": 0, "total": len(self.univ)}
        obs = obs.rename(columns={"aptos": "aptos_bu"}).drop(columns=["local"])
        u = self.univ.merge(obs, on=["zona", "secao"], how="left")
        m = u.comparecimento.notna().to_numpy()
        for c in self.cats + ["comparecimento"]:
            if c not in u:
                u[c] = 0.0
            u[c] = u[c].fillna(0)
        # onde a urna chegou, vale o apto do BU (o do cadastro é de semanas antes)
        u["aptos"] = np.where(m, u.aptos_bu, u.aptos)
        validos = [c for c in self.cats if c != "bn"]
        a = projetar(u, self.X, m, self.cats, n_boot=n_boot)
        av = a[:, [self.cats.index(c) for c in validos]]
        pv = av / av.sum(1, keepdims=True) * 100
        lo, hi = intervalo(pv[1:], pv[0])
        soma = u.loc[m, validos].sum()
        comp_proj = a[:, :].sum(1)
        return {
            "secoes": int(m.sum()), "total": len(u),
            "eleitores_apurados": float(u.aptos[m].sum() / u.aptos.sum()),
            "comparecimento_apurado": float(u.comparecimento[m].sum() / u.aptos[m].sum()),
            "comparecimento_projetado": float(comp_proj[0] / u.aptos.sum()),
            "candidatos": [{"cat": c, "contagem": float(soma[c] / soma.sum() * 100),
                            "projecao": float(pv[0, j]), "lo90": float(lo[j]), "hi90": float(hi[j])}
                           for j, c in enumerate(validos)],
        }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true")
    a = ap.parse_args()
    if a.ensaio:
        ensaio()
