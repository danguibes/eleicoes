"""Painel do 2º turno, por município: o 1º turno, o 2º turno da eleição anterior, o apurado e o projetado.

A projeção é a do segundo.py: cada município compara o 2º turno das seções que já
chegaram com o 1º turno DELAS MESMAS, e prevê as que faltam pelo 1º turno delas.
Quais seções chegaram vem do índice de cada UF (indices.py): as `st` primeiras pela
hora de chegada, `st` do arquivo `u` do município (nacional.py).

Sai no formato do painel do Brasil (painel_brasil.py), para a página reaproveitar
filtros, quintis, mapa, bolhas e chances. Comparação: "1º turno" é o 1º turno da
mesma eleição; "2º turno" é o 2º turno da eleição anterior.

    python painel_2t.py --modo ensaio2t --frac 0.25   # 2022 simulado, sem rede
    python painel_2t.py --modo 2026t2                  # noite: lê nacional.py e indices.py
    python painel_2t.py --modo 2026t2 --base 2022      # ensaio contra o tse_falso.py (serve 2022)
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import municipal as mu
import projecao as pj
import segundo as sg
import transicao as tr
from painel_brasil import REGIAO, VARS, _limpo, nomes_municipios

RAW = Path("data/raw")
WEB = Path("web/dados")
PISO = 0.2   # meia-largura mínima do intervalo de 90%, em pontos (ver montar)
L26 = ["lula", "flavio", "cury", "renan", "caiado", "zema", "outros", "branco", "nulo", "abst"]
NOMES_26 = {"lula": "Lula", "flavio": "Flávio Bolsonaro", "cury": "Augusto Cury", "renan": "Renan Santos",
            "caiado": "Ronaldo Caiado", "zema": "Romeu Zema", "outros": "outros"}
NOMES_22 = {"lula": "Lula", "bolsonaro": "Bolsonaro", "tebet": "Tebet", "ciro": "Ciro", "soraya": "Soraya",
            "davila": "D'Avila", "menores": "outros"}


def base(ano):
    """1º turno por seção: (tabela, linhas, adversário). Zona sem o prefixo de UF, como no índice."""
    if ano == "2026":
        s = pd.read_parquet(RAW / "2026" / "secoes_1t_brasil.parquet")
        return s[["uf", "municipio", "zona", "secao", "aptos"] + L26], L26, "flavio"
    s = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet")
    s = s.assign(zona=s.zona % 10000)
    return s, tr.LINHAS, "bolsonaro"


def chegou_por_indice(sec, idx, st):
    """Marca, em cada município, as `st` primeiras seções do índice (pela hora de chegada)."""
    i = idx.sort_values("t")
    i["ordem"] = i.groupby("municipio").cumcount()
    i = i[i.ordem < i.municipio.map(st).fillna(0)]
    marca = sec[["municipio", "zona", "secao"]].merge(i[["municipio", "zona", "secao"]].assign(ok=1.0),
                                                      on=["municipio", "zona", "secao"], how="left")
    return marca.ok.fillna(0).to_numpy()


def anterior_2t(ano_base):
    """2º turno da eleição anterior à da base, por município."""
    if ano_base == "2026":
        s = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet")
        g = s.groupby("municipio")[["lula_2t", "bolsonaro_2t", "branco_2t", "nulo_2t"]].sum()
        return pd.DataFrame({"lula22_2t": g.lula_2t, "bolsonaro22_2t": g.bolsonaro_2t,
                             "bn_2t": g.branco_2t + g.nulo_2t}), {"lula": "lula22_2t", "flavio": "bolsonaro22_2t"}, "2022"
    t = mu.por_municipio("2018", {13: "haddad18_2t", 17: "bolsonaro18_2t"}, turno="2").set_index("municipio")
    return t[["haddad18_2t", "bolsonaro18_2t", "bn"]].rename(columns={"bn": "bn_2t"}), \
        {"lula": "haddad18_2t", "bolsonaro": "bolsonaro18_2t"}, "2018"


def montar(modo, frac=0.25, ano_base=None, n_boot=40, pleito="2026_2t", saida=None):
    ano_base = ano_base or ("2022" if modo == "ensaio2t" else "2026")
    sec, linhas, adv = base(ano_base)
    cats = ["lula", adv, "bn"]
    if modo == "ensaio2t":
        # o 2º turno de 2022 na ordem real de chegada, como se viesse do TSE
        s2 = sec[sec.t_2t.notna()].sort_values("t_2t").reset_index(drop=True)
        ch = s2.iloc[: int(frac * len(s2))]
        u = ch.groupby("municipio").agg(st=("secao", "count"), est=("aptos_2t", "sum"), abst=("abst_2t", "sum"),
                                        n13=("lula_2t", "sum"), n22=("bolsonaro_2t", "sum"),
                                        vb=("branco_2t", "sum"), vn=("nulo_2t", "sum"))
        u["c"] = u.est - u.abst
        tot2 = sec.groupby("municipio").agg(ts=("secao", "count"), te=("aptos_2t", "sum"))
        u = tot2.join(u, how="left").fillna(0)
        idx = ch[["municipio", "zona", "secao", "t_2t"]].rename(columns={"t_2t": "t"})
        hora = ch.t_2t.max().strftime("%H:%M")
    else:
        arq_u = RAW / pleito / "nacional" / "municipios.parquet"
        if arq_u.exists():
            u = pd.read_parquet(arq_u).set_index("municipio")
        else:   # antes da apuração: nada apurado, o painel mostra só as comparações
            u = pd.DataFrame(0, index=pd.Index(sec.municipio.unique(), name="municipio"),
                             columns=["st", "ts", "est", "te", "c", "n13", "n22", "vb", "vn"])
        arq_idx = RAW / pleito / "indices" / "chegadas.parquet"
        idx = pd.read_parquet(arq_idx) if arq_idx.exists() else pd.DataFrame(columns=["municipio", "zona", "secao", "t"])
        hora = datetime.now().strftime("%H:%M")
    chegou = chegou_por_indice(sec, idx, u.st)
    M = sg.por_municipio(sec, linhas, chegou)
    M = M.join(u[["st", "ts", "est", "te", "c", "n13", "n22", "vb", "vn"]], how="left").fillna(
        {k: 0 for k in ["st", "est", "c", "n13", "n22", "vb", "vn"]})
    # quantas seções o índice deixou de explicar (índice atrás do arquivo u): fica no log
    rep_idx = pd.Series(chegou, index=sec.municipio).groupby(level=0).sum()
    falta_idx = int((M.st - rep_idx.reindex(M.index).fillna(0)).clip(lower=0).sum())
    M["ap_lula"], M["ap_adv"], M["ap_bn"] = M.n13, M.n22, M.vb + M.vn
    M["aptos_ap"], M["abst_ap"] = M.est, (M.est - M.c).clip(lower=0)
    M["aptos"] = M.te.where(M.te > 0, M.aptos1)
    M["secoes"] = M.ts.where(M.ts > 0, sec.groupby("municipio").size().reindex(M.index))
    M = M.reset_index()
    temAp = M.aptos_ap.sum() > 0
    # anterior: 1º turno da mesma eleição, por município
    nomes = NOMES_26 if ano_base == "2026" else NOMES_22
    um_t = {f"{c}_1t": M[c] for c in linhas if c not in ("branco", "nulo", "abst")}
    um_t["bn_1t"] = M.branco + M.nulo
    for k, v in um_t.items():
        M[k] = v
    cats_ant = list(um_t)
    pares = {"lula": "lula_1t", adv: f"{adv}_1t"}
    a2, pares_2t, ano_ant2 = anterior_2t(ano_base)
    if adv != "flavio" and "flavio" in pares_2t:
        pares_2t[adv] = pares_2t.pop("flavio")
    M = M.merge(a2, left_on="municipio", right_index=True, how="left")
    cats_2t = list(a2.columns)
    for c in cats_2t:
        M[c] = M[c].fillna(0)
    perfil = pd.read_parquet(RAW / "ibge" / "municipios_BR.parquet").drop(columns=["CD_MUN"])
    M = M.merge(perfil, on="municipio", how="left")
    cortes = {}
    for v in VARS:
        dd = M[[v, "aptos"]].dropna().sort_values(v)
        acum = (dd.aptos.cumsum() / dd.aptos.sum()).to_numpy()
        cortes[v] = [float(dd[v].iloc[np.searchsorted(acum, q)]) for q in (0.2, 0.4, 0.6, 0.8)]
        x = M[v].to_numpy(float)
        M[f"q_{v}"] = np.where(np.isnan(x), 0, 1 + np.searchsorted(cortes[v], x, side="right")).astype(int)
    M["regiao"] = M.uf.map(REGIAO).fillna("Exterior")
    ic, amostras_q, amostras_pct, amostras_uf = {}, {}, {}, {}
    for c, k in zip(cats, ["ap_lula", "ap_adv", "ap_bn"]):
        M[f"ap_{c}"] = M[k]
    if temAp:
        central, amostras = sg.projetar(M, linhas, n_boot=n_boot)
        for j, c in enumerate(cats):
            M[f"pj_{c}"] = central[:, j]
        L = np.concatenate([central[None], amostras])[:, :, :2]       # B+1 × municípios × (lula, adv)
        grupos = {"total": np.zeros(len(M), int), "regiao": pd.factorize(M.regiao)[0], "uf": pd.factorize(M.uf)[0]}
        nomes_g = {"total": ["total"], "regiao": list(pd.factorize(M.regiao)[1]), "uf": list(pd.factorize(M.uf)[1])}
        for k, cod in grupos.items():
            G = cod.max() + 1
            s_ = np.stack([np.stack([np.bincount(cod, Lb[:, j], G) for j in range(2)], axis=1) for Lb in L])   # B+1,G,2
            pv = s_ / np.maximum(s_.sum(2, keepdims=True), 1e-9) * 100
            p5, p95 = np.percentile(pv[1:], [5, 95], axis=0)
            meia = (p95 - p5) / 2 * sg.FATOR
            # piso: no ensaio de 2022 a meia-largura caía a ±0,05 ponto com metade das seções, e a projeção
            # tinha +0,1 a favor de Lula entre 10% e 25%; 2026 pode ter migrações menos homogêneas
            escala = np.maximum(1, PISO / np.maximum(meia, 1e-9))
            meia = np.maximum(meia, PISO)
            lo, hi = pv[0] - meia, pv[0] + meia
            ic[k] = {nomes_g[k][g]: {c: [round(float(lo[g, j]), 2), round(float(hi[g, j]), 2)] for j, c in enumerate(cats[:2])}
                     for g in range(G)}
            larg = pv[0] + sg.FATOR * escala * (pv[1:] - np.median(pv[1:], axis=0))
            amostras_pct[k] = {nomes_g[k][g]: np.round(larg[:, g, :], 2).tolist() for g in range(G)}
        for v in VARS:
            q = np.maximum(M[f"q_{v}"].to_numpy(int), 0)
            amostras_q[v] = np.rint(np.stack([np.stack([np.bincount(q, Lb[:, j], 6) for j in range(2)], axis=1)
                                              for Lb in L[1:]])).astype(int).tolist()
        # votos de cada reamostragem por UF: a página soma qualquer conjunto de UFs ("Brasil sem o Sudeste")
        uf_cod, uf_nomes = pd.factorize(M.uf)
        S_uf = np.stack([np.stack([np.bincount(uf_cod, Lb[:, j], len(uf_nomes)) for j in range(2)], axis=1) for Lb in L[1:]])
        amostras_uf = {uf_nomes[g]: np.rint(S_uf[:, g, :]).astype(int).tolist() for g in range(len(uf_nomes))}
    col = lambda cs: {c: [round(float(x), 1) if isinstance(x, (float, np.floating)) else (x if isinstance(x, str) else int(x))
                          for x in M[c].fillna(0)] for c in cs}
    M["apuradas"] = M.st
    M["comp_ap"] = M.c
    cols = ["municipio", "uf", "regiao", "aptos", "secoes", "apuradas", "aptos_ap", "comp_ap"] + \
           [f"ap_{c}" for c in cats] + ([f"pj_{c}" for c in cats] if temAp else []) + cats_ant + cats_2t + [f"q_{v}" for v in VARS]
    nomes_cat = {**{f"{c}_1t": n for c, n in nomes.items()}, "bn_1t": "brancos e nulos"}
    ano_at = "2026" if ano_base == "2026" else "2022"
    dados = {
        "meta": {"modo": modo, "escopo": "brasil", "cargo": "presidente", "turno": 2,
                 "anterior": f"{ano_at}, 1º turno", "atual": f"{ano_at}, 2º turno",
                 "rotulos_anterior": {"1": f"1º turno de {ano_at}", "2": f"2º turno de {ano_ant2}"},
                 "hora": hora, "gerado": datetime.now().strftime("%d/%m/%Y %H:%M"),
                 "cats": cats, "cats_anterior": cats_ant, "pares": pares, "fator_ic": sg.FATOR, "piso_ic": PISO,
                 "cats_anterior_2t": cats_2t, "pares_2t": pares_2t, "cortes": cortes, "nomes": nomes_cat,
                 "secoes": int(M.secoes.sum()), "apuradas": int(M.apuradas.sum()), "indice_falta": falta_idx,
                 "municipios": nomes_municipios()},
        "mun": col(cols),
        "ic": ic,
        "amostras_q": amostras_q,
        "amostras_pct": amostras_pct,
        "amostras_uf": amostras_uf,
    }
    WEB.mkdir(parents=True, exist_ok=True)
    nome = WEB / f"{saida or modo}_brasil_presidente.json"   # ensaio contra o tse_falso: arquivo próprio
    nome.write_text(json.dumps(_limpo(dados), allow_nan=False, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    t = ic.get("total", {}).get("total", {})
    print(f"{nome}: {nome.stat().st_size / 1e6:.1f} MB; {dados['meta']['apuradas']:,}/{dados['meta']['secoes']:,} seções; "
          f"Lula {t.get('lula')}; seções sem índice {falta_idx}", flush=True)
    return dados


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["ensaio2t", "2026t2"], default="ensaio2t")
    ap.add_argument("--frac", type=float, default=0.25)
    ap.add_argument("--base", choices=["2022", "2026"])
    ap.add_argument("--boot", type=int, default=40)
    ap.add_argument("--pleito", default="2026_2t")
    a = ap.parse_args()
    montar(a.modo, a.frac, a.base, a.boot, a.pleito)
