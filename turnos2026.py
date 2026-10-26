"""Do 1º para o 2º turno de 2026: quem ganhou e perdeu voto, onde, e para onde foram os demais.

Gera web/dados/turnos2026.json para a página turnos2026.html.

Por município (diferenças absolutas e em pontos): os arquivos `u` do TSE dos dois turnos
(data/raw/2026/nacional e data/raw/2026_2t/nacional), completos e da mesma fonte.

Migração (de quem votou em cada um no 1º turno, quanto foi a Lula, Flávio, branco/nulo ou
abstenção no 2º): estimada DENTRO de cada município, seção a seção, como transicao.por_municipio.
Entre municípios a regressão confunde composição com contexto (em 2022 errava células em até
14 pontos). As seções do 2º turno são as com boletim baixado (coletor.py / coletor_brasil_noite.py,
ordem sorteada dentro da UF: uma amostra); a matriz de cada município vale para todas as seções
dele, e a soma em votos dá o país, as regiões e as UFs. Município sem 5 seções com boletim fica
com a matriz da UF.

    python turnos2026.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from naovotos import boletins
from painel_brasil import REGIAO, nomes_municipios
from transicao import estimar, estimar_prior

RAW = Path("data/raw")
PL2T = "2026_2t"
SAIDA = Path("web/dados/turnos2026.json")
ORIGENS = ["lula", "flavio", "cury", "renan", "caiado", "zema", "outros", "branco", "nulo", "abst"]
DESTINOS = ["lula", "flavio", "bn", "abst"]
KAPPA = 0.1
MIN_SEC = 5


def municipios():
    """1º e 2º turnos por município, dos arquivos u do TSE."""
    def ler(p):
        u = pd.read_parquet(RAW / p / "nacional" / "municipios.parquet")
        return pd.DataFrame({"uf": u.uf.str.upper(), "municipio": u.municipio.astype(int), "ap": u.est, "co": u.c,
                             "bn": u.vb + u.vn, "br": u.vb, "nu": u.vn, "lu": u.n13, "fl": u.n22})
    a, b = ler("2026"), ler(PL2T)
    m = a.merge(b.drop(columns="uf"), on="municipio", suffixes=("1", "2"))
    m["de1"] = m.co1 - m.bn1 - m.lu1 - m.fl1          # os demais válidos do 1º turno
    return m


def secoes_pareadas():
    """Seções com boletim do 2º turno, casadas com o 1º turno (mesma seção, mesmo cadastro)."""
    s = pd.read_parquet(RAW / "2026" / "secoes_1t_brasil.parquet")
    partes = []
    for uf, g in s.groupby("uf"):
        b = boletins(PL2T, uf.lower())
        if b is not None and len(b):
            partes.append(g.merge(b, on=["zona", "secao"]))
    p = pd.concat(partes, ignore_index=True)
    p = p[(p.aptos > 0) & (p["26b_ap"] > 0) & ((p["26b_ap"] - p.aptos).abs() <= 0.05 * p.aptos)]
    return s, p


def matrizes(p):
    X = p[ORIGENS].to_numpy(float) / p.aptos.to_numpy(float)[:, None]
    ap2 = p["26b_ap"].to_numpy(float)
    Y = np.column_stack([p["26b_lu"], p["26b_ad"], p["26b_br"] + p["26b_nu"], p["26b_ap"] - p["26b_co"]]).astype(float) / ap2[:, None]
    return X, Y, p.aptos.to_numpy(float)


def ajustar(p, kappa=KAPPA, iters=800):
    """Matriz por UF (entre seções da UF) e por município (puxada para a da UF)."""
    X, Y, w = matrizes(p)
    uf, mun = p.uf.to_numpy(), p.municipio.to_numpy()
    Tuf = {u: estimar(X[uf == u], Y[uf == u], w[uf == u], iters=2000) for u in np.unique(uf)}
    Tm = {}
    for m_, ii in pd.Series(np.arange(len(p))).groupby(mun):
        ii = ii.to_numpy()
        if len(ii) >= MIN_SEC:
            A = (X[ii] * w[ii, None]).T @ X[ii]
            Tm[int(m_)] = estimar_prior(X[ii], Y[ii], w[ii], Tuf[uf[ii[0]]], kappa * np.trace(A) / X.shape[1] + 1e-9, iters=iters)
    return Tuf, Tm


def fluxos(s, Tuf, Tm):
    """Votos de cada origem (todas as seções do município) vezes a matriz do município: fluxos por município."""
    g = s.groupby(["uf", "municipio"])[ORIGENS].sum().reset_index()
    F = np.zeros((len(g), len(ORIGENS), len(DESTINOS)))
    propria = np.zeros(len(g), bool)
    for i, (uf, m_) in enumerate(zip(g.uf, g.municipio)):
        T = Tm.get(int(m_))
        propria[i] = T is not None
        if T is None:
            T = Tuf.get(uf)
        if T is None:
            continue
        F[i] = g.loc[g.index[i], ORIGENS].to_numpy(float)[:, None] * T
    return g, F, propria


def resumir(F, mask):
    """Fluxos somados (votos) e a matriz em % de cada origem."""
    f = F[mask].sum(0)
    tot = f.sum(1, keepdims=True)
    pct = np.divide(100 * f, tot, out=np.zeros_like(f), where=tot > 0)
    return {"votos": [[int(round(x)) for x in l] for l in f], "pct": [[round(float(x), 1) for x in l] for l in pct]}


def validar(p, seed=0):
    """Ajusta com metade das seções de cada município e prevê a outra metade: Lula entre os dois,
    por município, comparado com o ingênuo (a parte de Lula entre os dois no 1º turno)."""
    rng = np.random.default_rng(seed)
    treino = rng.random(len(p)) < 0.5
    Tuf, Tm = ajustar(p[treino])
    X, Y, w = matrizes(p)
    P = np.zeros_like(Y)
    for i, (uf, m_) in enumerate(zip(p.uf.to_numpy(), p.municipio.to_numpy())):
        T = Tm.get(int(m_), Tuf.get(uf))
        if T is not None:
            P[i] = X[i] @ T
    t = p[~treino].assign(pl=P[~treino, 0] * p["26b_ap"][~treino], pf=P[~treino, 1] * p["26b_ap"][~treino])
    g = t.groupby("municipio")[["pl", "pf", "26b_lu", "26b_ad", "lula", "flavio", "26b_ap"]].sum()
    g = g[g["26b_lu"] + g["26b_ad"] > 0]
    real = 100 * g["26b_lu"] / (g["26b_lu"] + g["26b_ad"])
    wm = g["26b_ap"] / g["26b_ap"].sum()
    erro = lambda prev: round(float((wm * (prev - real).abs()).sum()), 2)
    return {"municipios": int(len(g)), "erro_modelo": erro(100 * g.pl / (g.pl + g.pf)),
            "erro_ingenuo": erro(100 * g.lula / (g.lula + g.flavio))}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    m = municipios()
    nomes = nomes_municipios()
    s, p = secoes_pareadas()
    print(f"{len(p):,} seções com boletim do 2º turno casadas com o 1º ({100 * len(p) / len(s):.1f}%)", flush=True)
    Tuf, Tm = ajustar(p)
    g, F, propria = fluxos(s, Tuf, Tm)
    reg = np.array([REGIAO.get(u, "Exterior") for u in g.uf])
    origem_tot = g[ORIGENS].to_numpy(float).sum(1)
    mig = {"brasil": resumir(F, np.ones(len(g), bool)),
           "regiao": {r: resumir(F, reg == r) for r in sorted(set(reg))},
           "uf": {u: resumir(F, g.uf.to_numpy() == u) for u in sorted(g.uf.unique())}}
    # sensibilidade: a matriz do país com κ menor e maior (a da casa: muda menos de 1 ponto, 05/10/2026)
    sens = {}
    for k in (0.02, 0.5):
        Tu, Tk = ajustar(p, kappa=k)
        sens[str(k)] = resumir(fluxos(s, Tu, Tk)[1], np.ones(len(g), bool))["pct"]
    dif = max(abs(a - b) for k in sens for la, lb in zip(sens[k], mig["brasil"]["pct"]) for a, b in zip(la, lb))
    val = validar(p)
    # conferência: os fluxos somados reproduzem o 2º turno de verdade?
    prev = F.sum((0, 1))
    real = np.array([m.lu2.sum(), m.fl2.sum(), m.bn2.sum(), (m.ap2 - m.co2).sum()], float)
    cob = p.groupby("uf").size() / s.groupby("uf").size()
    print(f"matriz própria em {int(propria.sum()):,} municípios, com {100 * origem_tot[propria].sum() / origem_tot.sum():.1f}% dos eleitores; "
          f"sensibilidade a κ: até {dif:.1f} ponto; validação: modelo {val['erro_modelo']} × ingênuo {val['erro_ingenuo']} pontos", flush=True)
    for nome, a, b in zip(DESTINOS, prev, real):
        print(f"  {nome:6s} previsto {a / 1e6:7.2f} mi · real {b / 1e6:7.2f} mi", flush=True)
    for i, o in enumerate(ORIGENS):
        print(f"  {o:7s} → " + " · ".join(f"{d} {x:5.1f}%" for d, x in zip(DESTINOS, mig["brasil"]["pct"][i])), flush=True)
    dados = {
        "meta": {"gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"), "origens": ORIGENS, "destinos": DESTINOS,
                 "secoes_bu": int(len(p)), "secoes": int(len(s)), "cobertura_uf": {u: round(float(x), 3) for u, x in cob.items()},
                 "mun_propria": int(propria.sum()), "eleitores_propria": round(float(origem_tot[propria].sum() / origem_tot.sum()), 3),
                 "kappa": KAPPA, "min_sec": MIN_SEC, "sens_kappa": round(float(dif), 1), "validacao": val,
                 "conferencia": {d: [int(a), int(b)] for d, a, b in zip(DESTINOS, prev, real)}},
        "mun": {"municipio": m.municipio.tolist(), "uf": m.uf.tolist(), "nome": [nomes.get(int(x), str(x)) for x in m.municipio],
                **{c: m[c].astype(int).tolist() for c in ["ap1", "co1", "bn1", "lu1", "fl1", "de1", "ap2", "co2", "bn2", "lu2", "fl2"]}},
        "mig": mig,
    }
    SAIDA.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{SAIDA}: {SAIDA.stat().st_size / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
