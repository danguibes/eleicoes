"""Governador e senador de SP por município: eleição anterior completa, atual apurada e projetada.

A camada por município (municipal.py) aplicada a SP, com o que o sp_municipios.py
coleta. Sai no formato do painel do Brasil (uma linha por município), para a página
reaproveitar filtros, quintis e chances. O detalhe por local de votação continua
vindo dos boletins (painel.py).

Duas adaptações para um estado só:
  - o efeito e a reamostragem por UF do modelo nacional viram efeito e reamostragem
    por **grupo de municípios vizinhos** (k-médias sobre o centro do município, 40
    grupos): reamostrar município a município cobre mal o erro, que é regional
    (ensaio nacional: 23% de cobertura contra 89% por UF);
  - no Senado de 2026, cada eleitor vota duas vezes.

O fator do intervalo é o FATOR_MUN do Brasil, **não calibrado para SP nem para
estes cargos** — o painel diz isso.

    python painel_sp_mun.py --cargo governador
"""
import argparse
import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import municipal as mu
import projecao as pj
from painel import nomes_candidatos
from painel_brasil import VARS, _limpo, cadastro_2026, nomes_municipios

RAW = Path("data/raw")
WEB = Path("web/dados")
COD = {"governador": 3, "senador": 5}
N_GRUPOS = 40
TOP_ANT, TOP_AT = 4, 5


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper()
    return "".join(ch for ch in s if ch.isalnum())


def grupos_vizinhos(municipios):
    """município TSE -> grupo de vizinhos (k-médias sobre lat/lon do IBGE)."""
    c = pd.read_parquet(RAW / "ibge" / "centros_municipios_35.parquet")
    pos = {_norm(n): (la, lo) for n, la, lo in zip(c.nome, c.lat, c.lon)}
    nomes = nomes_municipios()
    xy = np.array([pos.get(_norm(nomes.get(m, "")), (np.nan, np.nan)) for m in municipios], float)
    ok = np.isfinite(xy).all(1)
    rng = np.random.default_rng(0)
    cen = xy[ok][rng.choice(ok.sum(), N_GRUPOS, replace=False)]
    for _ in range(50):
        g = ((xy[ok][:, None, :] - cen[None]) ** 2).sum(2).argmin(1)
        cen = np.array([xy[ok][g == k].mean(0) if (g == k).any() else cen[k] for k in range(N_GRUPOS)])
    out = np.full(len(municipios), -1)
    out[ok] = g
    return np.array([f"g{x}" for x in out]), int((~ok).sum())


def base_2022(cargo):
    v = pd.read_parquet(RAW / "2022" / "sp" / "votos.parquet")
    v = v[v.cargo == cargo]
    top = (v[v.tipo == "nominal"].groupby("codigo").votos.sum().sort_values(ascending=False).head(TOP_ANT).index)
    mapa = {int(k): f"n{int(k)}_ant" for k in top}
    v["cat"] = v.codigo.map(mapa)
    v.loc[v.tipo.isin(["branco", "nulo"]), "cat"] = "bn"
    v["cat"] = v.cat.fillna("outros_ant")
    t = v.pivot_table(index="municipio", columns="cat", values="votos", aggfunc="sum", fill_value=0)
    s = v.drop_duplicates(["zona", "secao"]).groupby("municipio")[["aptos", "comparecimento"]].sum()
    t["aptos22"], t["comp22"] = s.aptos, s.comparecimento
    return t.reset_index(), list(mapa.values()) + ["outros_ant", "bn"]


def montar(cargo, n_boot=200):
    ant, cats_ant = base_2022(cargo)
    tot = cadastro_2026().reset_index()
    tot = tot[tot.uf == "SP"]
    arq = RAW / "2026" / f"sp_{cargo}" / "municipios.parquet"
    m = pd.read_parquet(arq) if arq.exists() else pd.DataFrame()
    cand = [c for c in m.columns if c.startswith("n") and c[1:].isdigit()]
    top = m[cand].sum().sort_values(ascending=False).head(TOP_AT).index.tolist() if len(m) else []
    cats = top + ["outros", "bn"]
    M = tot.merge(ant, on="municipio", how="left")
    if len(m):
        m = m.set_index("municipio")
        for c in top:
            m[f"ap_{c}"] = m[c].fillna(0)
        m["ap_outros"] = m[[c for c in cand if c not in top]].fillna(0).sum(1)
        m["ap_bn"] = m.vb + m.vn
        m = m.rename(columns={"est": "aptos_ap", "c": "comp_ap", "st": "apuradas", "te": "aptos_tse", "ts": "secoes_tse"})
        M = M.merge(m[[f"ap_{c}" for c in cats] + ["aptos_ap", "comp_ap", "apuradas", "aptos_tse", "secoes_tse"]],
                    left_on="municipio", right_index=True, how="left")
        # o total do próprio arquivo do TSE vale mais que o do cadastro baixado antes
        M["aptos"] = M.aptos_tse.fillna(M.aptos)
        M["secoes"] = M.secoes_tse.fillna(M.secoes)
    for c in [f"ap_{c}" for c in cats] + ["aptos_ap", "comp_ap", "apuradas"]:
        if c not in M:
            M[c] = 0
        M[c] = M[c].fillna(0)
    for c in cats_ant:
        M[c] = M[c].fillna(0)
    M["b_comp"] = (M.comp22 / M.aptos22.clip(lower=1)).clip(0.3, 0.98)
    M["b_comp"] = M.b_comp.fillna(M.b_comp.median())
    for c in cats_ant:
        M[f"b_{c}"] = M[c] + 1
    perfil = pd.read_parquet(RAW / "ibge" / "municipios_BR.parquet").drop(columns=["CD_MUN", "populacao"])
    M = M.merge(perfil, on="municipio", how="left")
    cortes = {}
    for v in VARS:   # quintis do estado, pesados pelo eleitorado de 2026
        dd = M[[v, "aptos"]].dropna().sort_values(v)
        acum = (dd.aptos.cumsum() / dd.aptos.sum()).to_numpy()
        cortes[v] = [float(dd[v].iloc[np.searchsorted(acum, q)]) for q in (0.2, 0.4, 0.6, 0.8)]
        x = M[v].to_numpy(float)
        M[f"q_{v}"] = np.where(np.isnan(x), 0, 1 + np.searchsorted(cortes[v], x, side="right")).astype(int)
    grupo, sem_pos = grupos_vizinhos(M.municipio.to_numpy())
    M["regiao"] = "Sudeste"
    validos = [c for c in cats if c != "bn"]
    ic, amostras_q, amostras_pct = {}, {}, {}
    temAp = len(top) > 0 and M[[f"ap_{c}" for c in cats]].to_numpy().sum() > 0
    if temAp:
        Mp = M.assign(uf=grupo)   # o "uf" do modelo nacional é o grupo de vizinhos aqui
        amostras, linhas = mu.projetar_mun(Mp, cats, n_boot=n_boot, guardar_linhas=True,
                                           votos_por=2 if cargo == "senador" else 1)
        for j, c in enumerate(cats):
            M[f"pj_{c}"] = linhas[0][:, j]
        iv = [cats.index(c) for c in validos]
        L = np.stack(linhas)                                   # B, municípios, C
        tv = L.sum(1)[:, iv]
        pv = tv / tv.sum(1, keepdims=True) * 100
        lo, hi = pj.intervalo(pv[1:][:, None, :], pv[0][None, :], mu.FATOR_MUN)
        ic["total"] = {"total": {c: [round(float(lo[0, j]), 2), round(float(hi[0, j]), 2)] for j, c in enumerate(validos)}}
        larg = pv[0] + mu.FATOR_MUN * (pv[1:] - np.median(pv[1:], axis=0))
        amostras_pct["total"] = {"total": np.round(larg, 2).tolist()}
        for v in VARS:
            q = np.maximum(M[f"q_{v}"].to_numpy(int), 0)
            s = np.stack([np.stack([np.bincount(q, Lb[:, j], 6) for j in iv], axis=1) for Lb in linhas[1:]])
            amostras_q[v] = np.rint(s).astype(int).tolist()
    nomes = {**{f"{k}_ant": v for k, v in nomes_candidatos("2022", cargo).items()}, **nomes_candidatos("2026", cargo)}
    hora = max([h for h in (m.hg.dropna().tolist() if len(m) and "hg" in m else []) if h] or [datetime.now().strftime("%H:%M")])[:5]
    col = lambda cs: {c: [round(float(x), 1) if isinstance(x, (float, np.floating)) else (x if isinstance(x, str) else int(x))
                          for x in M[c].fillna(0)] for c in cs}
    M["uf"] = "SP"
    cols = ["municipio", "uf", "regiao", "aptos", "secoes", "apuradas", "aptos_ap", "comp_ap"] + \
           [f"ap_{c}" for c in cats] + ([f"pj_{c}" for c in cats] if temAp else []) + cats_ant + [f"q_{v}" for v in VARS]
    dados = {
        "meta": {"modo": "2026", "escopo": "sp_mun", "cargo": cargo, "anterior": "2022", "atual": "2026",
                 "hora": hora, "gerado": datetime.now().strftime("%d/%m/%Y %H:%M"),
                 "cats": cats, "cats_anterior": cats_ant,
                 # mesmo número nas duas eleições = mesma linha da tabela (Tarcísio 10, Haddad 13); o
                 # número muda de dono às vezes (222 no Senado), e o nome ao lado mostra quem é quem
                 "pares": {c: f"{c}_ant" for c in top if f"{c}_ant" in cats_ant}, "fator_ic": mu.FATOR_MUN,
                 "cats_anterior_2t": [], "pares_2t": {}, "cortes": cortes, "nomes": nomes,
                 "secoes": int(M.secoes.sum()), "apuradas": int(M.apuradas.sum()),
                 "municipios": {int(k): v for k, v in nomes_municipios().items() if k in set(M.municipio)},
                 "grupos": N_GRUPOS, "sem_posicao": sem_pos},
        "mun": col(cols),
        "ic": ic,
        "amostras_q": amostras_q,
        "amostras_pct": amostras_pct,
    }
    WEB.mkdir(parents=True, exist_ok=True)
    nome = WEB / f"2026_sp_{cargo}.json"
    nome.write_text(json.dumps(_limpo(dados), allow_nan=False, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{nome}: {nome.stat().st_size / 1e6:.1f} MB; {len(M)} municípios ({sem_pos} sem posição); "
          f"{dados['meta']['apuradas']:,}/{dados['meta']['secoes']:,} seções apuradas", flush=True)
    return dados


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cargo", choices=list(COD), default="governador")
    ap.add_argument("--boot", type=int, default=200)
    a = ap.parse_args()
    montar(a.cargo, a.boot)
