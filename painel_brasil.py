"""Dados do painel nacional, por município: eleição anterior completa, atual apurada e projetada.

É a camada rápida (municipal.py) servida ao navegador: uma linha por município
(~5.700, com as cidades do exterior), com UF e região para os filtros. O
intervalo vem pré-calculado para o Brasil, cada região e cada UF. O detalhe por
local de votação, com quintis e três cargos, continua sendo o de SP (painel.py).

    python painel_brasil.py --modo ensaio --frac 0.25   # 2022 a partir de 2018
    python painel_brasil.py --modo 2026                 # noite: lê o que o nacional.py coletou
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


def _limpo(o):
    """NaN/inf viram null: json.dumps escreve NaN, que não é JSON válido, e a página
    inteira deixa de carregar. Acontece com grupo sem voto apurado ainda — no começo
    da noite, sempre. Pego no ensaio contra o TSE de mentira, 01/10/2026."""
    if isinstance(o, float):
        return o if np.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _limpo(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_limpo(v) for v in o]
    return o

import municipal as mu
import projecao as pj

RAW = Path("data/raw")
WEB = Path("web/dados")
REGIAO = {**{u: "Norte" for u in ["AC", "AM", "AP", "PA", "RO", "RR", "TO"]},
          **{u: "Nordeste" for u in ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"]},
          **{u: "Centro-Oeste" for u in ["DF", "GO", "MS", "MT"]},
          **{u: "Sudeste" for u in ["ES", "MG", "RJ", "SP"]},
          **{u: "Sul" for u in ["PR", "RS", "SC"]}, "ZZ": "Exterior"}
BASE22 = {13: "lula22", 22: "bolsonaro22", 15: "tebet22", 12: "ciro22"}
VARS = ["renda", "catolicos", "evangelicos", "sem_religiao", "preta_parda", "superior", "jovens", "idosos",
        # do município, de outras fontes públicas (perfil_extra.py): para recortar, não entram no modelo
        "bolsa_familia", "setor_publico", "agro", "pib_pc", "saneamento", "rural", "populacao"]


def detalhe_mun(ano="2022"):
    d = pd.read_parquet(RAW / "tse" / f"detalhe_{ano}_BR.parquet",
                        columns=["NR_TURNO", "CD_CARGO", "CD_MUNICIPIO", "QT_APTOS", "QT_COMPARECIMENTO"])
    d = d[(d.NR_TURNO == "1") & (d.CD_CARGO == "1")]
    g = d.assign(municipio=d.CD_MUNICIPIO.astype(int), aptos=d.QT_APTOS.astype(int),
                 comp=d.QT_COMPARECIMENTO.astype(int)).groupby("municipio")[["aptos", "comp"]].sum()
    return g


def nomes_municipios():
    l = pd.read_parquet(RAW / "tse" / "locais_2026_BR.parquet", columns=["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"])
    l = l.drop_duplicates("CD_MUNICIPIO")
    return {int(m): n.title() for m, n in zip(l.CD_MUNICIPIO, l.NM_MUNICIPIO)}


def cadastro_2026():
    l = pd.read_parquet(RAW / "tse" / "locais_2026_BR.parquet",
                        columns=["SG_UF", "CD_MUNICIPIO", "NR_SECAO_PRINCIPAL", "QT_ELEITOR_SECAO"])
    l = l.assign(municipio=l.CD_MUNICIPIO.astype(int), n=pd.to_numeric(l.QT_ELEITOR_SECAO, errors="coerce"),
                 principal=pd.to_numeric(l.NR_SECAO_PRINCIPAL, errors="coerce").fillna(-1) <= 0)
    return l.groupby("municipio").agg(uf=("SG_UF", "first"), aptos=("n", "sum"), secoes=("principal", "sum"))


def montar(modo, frac=0.25, n_boot=200):
    if modo == "ensaio":
        ano_ant, ano_at = "2018", "2022"
        cats_alvo = {13: "lula", 22: "bolsonaro", 15: "tebet", 12: "ciro"}
        s, cats = mu.secoes_2022(cats_alvo)
        cats_ant_map = {17: "bolsonaro18", 13: "haddad18", 12: "ciro18", 45: "alckmin18", 30: "amoedo18"}
        ant = mu.por_municipio("2018", cats_ant_map)
        cats_ant = list(cats_ant_map.values()) + ["outros", "bn"]
        t2 = mu.por_municipio("2018", {13: "haddad18_2t", 17: "bolsonaro18_2t"}, turno="2")
        cats_2t = ["haddad18_2t", "bolsonaro18_2t", "bn"]
        pares_2t = {"lula": "haddad18_2t", "bolsonaro": "bolsonaro18_2t"}
        tot = s.groupby("municipio").agg(uf=("uf", "first"), aptos=("aptos", "sum"),
                                         secoes=("secao", "count")).reset_index()
        s = s.sort_values("t")
        chegou = s.iloc[: int(frac * len(s))]
        hora = chegou.t.max().strftime("%H:%M")
        ap = chegou.groupby("municipio").agg(**{f"ap_{c}": (c, "sum") for c in cats},
                                             aptos_ap=("aptos", "sum"), comp_ap=("comparecimento", "sum"),
                                             apuradas=("secao", "count"))
        pares = {"lula": "haddad18", "bolsonaro": "bolsonaro18"}
        base_cols = ["haddad18", "bolsonaro18", "alckmin18", "ciro18", "amoedo18", "outros", "bn"]
        comp_ant = None
    else:
        ano_ant, ano_at = "2022", "2026"
        cats_alvo = pj.CATS_2026
        cats = list(cats_alvo.values()) + ["outros", "bn"]
        ant = mu.por_municipio("2022", BASE22)
        cats_ant = list(BASE22.values()) + ["outros", "bn"]
        t2 = mu.por_municipio("2022", {13: "lula22_2t", 22: "bolsonaro22_2t"}, turno="2")
        cats_2t = ["lula22_2t", "bolsonaro22_2t", "bn"]
        pares_2t = {"lula": "lula22_2t", "flavio": "bolsonaro22_2t"}
        tot = cadastro_2026().reset_index()
        arq = RAW / "2026" / "nacional" / "municipios.parquet"
        ap = None
        hora = datetime.now().strftime("%H:%M")
        if arq.exists():
            m = pd.read_parquet(arq)
            num = {f"n{k}": v for k, v in cats_alvo.items()}
            cand = [c for c in m.columns if c.startswith("n") and c[1:].isdigit()]
            for c in cats:
                m[f"ap_{c}"] = 0
            for c in cand:
                alvo = num.get(c, "outros")
                m[f"ap_{alvo}"] += m[c].fillna(0)
            m["ap_bn"] = m.vb + m.vn
            ap = m.set_index("municipio").rename(columns={"est": "aptos_ap", "c": "comp_ap", "st": "apuradas"})
            ap = ap[[f"ap_{c}" for c in cats] + ["aptos_ap", "comp_ap", "apuradas"]]
        pares = {"lula": "lula22", "flavio": "bolsonaro22"}
        base_cols = ["lula22", "bolsonaro22", "tebet22", "ciro22", "outros", "bn"]
    d = detalhe_mun("2022") if modo != "ensaio" else None
    M = tot.merge(ant.drop(columns="uf"), on="municipio", how="left")
    t2 = t2.rename(columns={"bn": "bn_2t"}).drop(columns=["uf", "outros"], errors="ignore")
    M = M.merge(t2, on="municipio", how="left")
    cats_2t = [c if c != "bn" else "bn_2t" for c in cats_2t]
    for c in cats_2t:
        M[c] = M[c].fillna(0)
    # perfil do município pelo Censo 2022 e quintis nacionais pesados pelo eleitorado
    perfil = pd.read_parquet(RAW / "ibge" / "municipios_BR.parquet").drop(columns=["CD_MUN"])
    M = M.merge(perfil, on="municipio", how="left")
    cortes = {}
    for v in VARS:
        dd = M[[v, "aptos"]].dropna().sort_values(v)
        acum = (dd.aptos.cumsum() / dd.aptos.sum()).to_numpy()
        cortes[v] = [float(dd[v].iloc[np.searchsorted(acum, q)]) for q in (0.2, 0.4, 0.6, 0.8)]
        x = M[v].to_numpy(float)
        M[f"q_{v}"] = np.where(np.isnan(x), 0, 1 + np.searchsorted(cortes[v], x, side="right")).astype(int)
    for c in cats_ant:
        M[c] = M[c].fillna(0)
    denom = (d.aptos.reindex(M.municipio).to_numpy() if d is not None else M.aptos.to_numpy())
    M["b_comp"] = (M[cats_ant].sum(axis=1) / np.maximum(denom, 1)).clip(0.3, 0.98)
    # município sem 2022 (7 criados ou novos no exterior): sem aptos de 2022, b_comp vira
    # NaN e contaminava a padronização do modelo inteiro — projeção zerada no país todo,
    # às 18h de domingo. Fica com a mediana.
    M["b_comp"] = M.b_comp.fillna(M.b_comp.median())
    for cb in base_cols:   # nomes próprios da eleição anterior — ver municipal.projetar_mun
        M[f"b_{cb}"] = M[cb] + 1
    if ap is not None and len(ap):
        M = M.merge(ap, left_on="municipio", right_index=True, how="left")
    for c in [f"ap_{c}" for c in cats] + ["aptos_ap", "comp_ap", "apuradas"]:
        if c not in M:
            M[c] = 0
        M[c] = M[c].fillna(0)
    M["regiao"] = M.uf.map(REGIAO)
    temAp = M[[f"ap_{c}" for c in cats]].to_numpy().sum() > 0
    ic, validos, amostras_q, amostras_pct, amostras_uf = {}, [c for c in cats if c != "bn"], {}, {}, {}
    if temAp:
        linha, por, por_nomes = projetar_grupos(M, cats, n_boot)
        for j, c in enumerate(cats):
            M[f"pj_{c}"] = linha[:, j]
        # intervalo por Brasil, região e UF; amostras por quintil para qualquer faixa
        iv = [cats.index(c) for c in validos]
        amostras_q = {v: np.rint(por[f"q_{v}"][1:][:, :, iv]).astype(int).tolist() for v in VARS}
        # votos de cada reamostragem por UF: a página soma qualquer conjunto de UFs ("Brasil sem o Sudeste")
        amostras_uf = {por_nomes["uf"][g]: np.rint(por["uf"][1:, g, :][:, iv]).astype(int).tolist()
                       for g in range(por["uf"].shape[1])}
        # reamostragens em % dos válidos, alargadas pelo fator em torno da projeção central —
        # é delas que saem as chances e as curvas da página
        amostras_pct = {}
        for k in ("total", "regiao", "uf"):
            s_ = por[k][:, :, iv]
            pv = s_ / np.maximum(s_.sum(2, keepdims=True), 1e-9) * 100          # B,G,C
            centro = pv[0]
            larg = centro + mu.FATOR_MUN * (pv[1:] - np.median(pv[1:], axis=0))
            amostras_pct[k] = {por_nomes[k][g]: np.round(larg[:, g, :], 2).tolist() for g in range(pv.shape[1])}
        for k, s_ in por.items():
            if k.startswith("q_"):
                continue
            pv = s_[:, :, iv] / np.maximum(s_[:, :, iv].sum(2, keepdims=True), 1e-9) * 100
            lo, hi = pj.intervalo(pv[1:], pv[0], mu.FATOR_MUN)
            nomes = por_nomes[k]
            ic[k] = {nomes[g]: {c: [round(float(lo[g, j]), 2), round(float(hi[g, j]), 2)] for j, c in enumerate(validos)}
                     for g in range(pv.shape[1])}
    col = lambda cs: {c: [round(float(x), 1) if isinstance(x, (float, np.floating)) else (x if isinstance(x, str) else int(x))
                          for x in M[c].fillna(0)] for c in cs}
    cols = ["municipio", "uf", "regiao", "aptos", "secoes", "apuradas", "aptos_ap", "comp_ap"] + \
           [f"ap_{c}" for c in cats] + ([f"pj_{c}" for c in cats] if temAp else []) + cats_ant + cats_2t + \
           [f"q_{v}" for v in VARS]
    dados = {
        "meta": {"modo": modo, "escopo": "brasil", "cargo": "presidente", "anterior": ano_ant, "atual": ano_at,
                 "hora": hora, "gerado": datetime.now().strftime("%d/%m/%Y %H:%M"),
                 "cats": cats, "cats_anterior": cats_ant, "pares": pares, "fator_ic": mu.FATOR_MUN,
                 "cats_anterior_2t": cats_2t, "pares_2t": pares_2t, "cortes": cortes,
                 "secoes": int(M.secoes.sum()), "apuradas": int(M.apuradas.sum()),
                 "municipios": nomes_municipios()},
        "mun": col(cols),
        "ic": ic,
        "amostras_q": amostras_q,
        "amostras_pct": amostras_pct,
        "amostras_uf": amostras_uf,
    }
    WEB.mkdir(parents=True, exist_ok=True)
    nome = WEB / f"{modo}_brasil_presidente.json"
    nome.write_text(json.dumps(_limpo(dados), allow_nan=False, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{nome}: {nome.stat().st_size / 1e6:.1f} MB; {len(M):,} municípios; "
          f"{dados['meta']['apuradas']:,}/{dados['meta']['secoes']:,} seções apuradas", flush=True)
    return dados


def projetar_grupos(M, cats, n_boot):
    """Projeção + somas de cada reamostragem por Brasil, região e UF."""
    grupos, nomes = {}, {}
    for k, serie in [("total", pd.Series(["total"] * len(M))), ("regiao", M.regiao.fillna("?")), ("uf", M.uf)]:
        cod, nm = pd.factorize(serie)
        grupos[k], nomes[k] = cod, list(nm)
    for v in VARS:
        grupos[f"q_{v}"] = np.maximum(M[f"q_{v}"].to_numpy(int), 0)
        nomes[f"q_{v}"] = list(range(6))
    amostras, linhas = mu.projetar_mun(M, cats, n_boot=n_boot, guardar_linhas=True)
    por = {k: np.stack([np.stack([np.bincount(cod, L[:, j], max(cod.max() + 1, 6 if k.startswith("q_") else 0)) for j in range(len(cats))], axis=1)
                        for L in linhas]) for k, cod in grupos.items()}
    return linhas[0], por, nomes


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["ensaio", "2026"], default="ensaio")
    ap.add_argument("--frac", type=float, default=0.25)
    ap.add_argument("--boot", type=int, default=200)
    a = ap.parse_args()
    montar(a.modo, a.frac, a.boot)
