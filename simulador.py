"""Dados do simulador do 2º turno de 2026: 1º turno por município + migrações de partida aprendidas em 2022.

Cada eleitor do 1º turno de 2026 — de cada candidato, de branco, de nulo, ou que se
absteve — vai, no 2º turno, para Lula, para Flávio, ou para branco/nulo/abstenção. O
ponto de partida dessas migrações vem de 2022, seção a seção (transicao.py):

  - Lula, Flávio, branco, nulo e abstenção herdam as taxas de 2022 da mesma linha
    (Flávio herda as de Bolsonaro);
  - os candidatos novos herdam, por ANALOGIA escolhida pelo Danilo em 05/10/2026, as de
    um candidato de 2022: Cury ← Tebet, Renan ← Ciro, Caiado ← Soraya, Zema ← D'Avila;
    os demais, as dos menores de 2022.

Duas versões da partida, porque a regressão ecológica não identifica bem cada célula
(ver transicao.py): "dentro" (padrão: matriz de cada município, só com as seções dele,
puxada para a da UF) e "entre" (uma matriz por UF, entre as seções da UF inteira). Onde
as duas discordam, o dado não decide — e o simulador mostra isso.

    python simulador.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import transicao as tr
from painel_brasil import REGIAO, VARS, nomes_municipios

RAW = Path("data/raw")
OUT = Path("out")
WEB = Path("web/dados")
LINHAS_26 = ["lula", "flavio", "cury", "renan", "caiado", "zema", "outros", "branco", "nulo", "abst"]
NUM_26 = {13: "lula", 22: "flavio", 70: "cury", 14: "renan", 55: "caiado", 30: "zema"}
ANALOGIA = {"lula": "lula", "flavio": "bolsonaro", "cury": "tebet", "renan": "ciro", "caiado": "soraya",
            "zema": "davila", "outros": "menores", "branco": "branco", "nulo": "nulo", "abst": "abst"}
NOMES = {"lula": "Lula", "flavio": "Flávio Bolsonaro", "cury": "Augusto Cury", "renan": "Renan Santos",
         "caiado": "Ronaldo Caiado", "zema": "Romeu Zema", "outros": "demais candidatos",
         "branco": "votou branco", "nulo": "votou nulo", "abst": "não votou"}
NOMES_22 = {"lula": "Lula", "bolsonaro": "Bolsonaro", "tebet": "Tebet", "ciro": "Ciro", "soraya": "Soraya",
            "davila": "D'Avila", "menores": "menores de 2022", "branco": "branco", "nulo": "nulo", "abst": "abstenção"}


def primeiro_turno_2026():
    m = pd.read_parquet(RAW / "2026" / "nacional" / "municipios.parquet")
    cand = [c for c in m.columns if c.startswith("n") and c[1:].isdigit()]
    out = pd.DataFrame({"municipio": m.municipio, "uf": m.uf, "aptos": m.te})
    for c in LINHAS_26:
        out[c] = 0.0
    for c in cand:
        out[NUM_26.get(int(c[1:]), "outros")] += m[c].fillna(0).to_numpy()
    out["branco"] = m.vb
    out["nulo"] = m.vn
    out["abst"] = (m.te - m.c).clip(lower=0)
    return out


def matrizes_entre(s):
    """Uma matriz por UF, entre as seções da UF inteira."""
    X, Y, w = tr.matrizes(s)
    uf = s.uf.to_numpy()
    return {u: tr.estimar(X[uf == u], Y[uf == u], w[uf == u]) for u in np.unique(uf)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = primeiro_turno_2026()
    s = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet")
    dentro = pd.read_parquet(OUT / "transicao_mun_2022.parquet")
    entre = matrizes_entre(s)
    li = {l: i for i, l in enumerate(tr.LINHAS)}
    # 2º turno de 2022 por município, para comparar
    t22 = s.groupby("municipio")[["lula_2t", "bolsonaro_2t", "aptos_2t", "abst_2t"]].sum()
    p = p.merge(t22, left_on="municipio", right_index=True, how="left")
    perfil = pd.read_parquet(RAW / "ibge" / "municipios_BR.parquet")
    p = p.merge(perfil[["municipio"] + VARS], on="municipio", how="left")
    cortes = {}
    for v in VARS:   # quintis do país pesados pelo eleitorado de 2026, como no painel
        d = p[[v, "aptos"]].dropna().sort_values(v)
        ac = (d.aptos.cumsum() / d.aptos.sum()).to_numpy()
        cortes[v] = [float(d[v].iloc[np.searchsorted(ac, q)]) for q in (0.2, 0.4, 0.6, 0.8)]
        x = p[v].to_numpy(float)
        p[f"q_{v}"] = np.where(np.isnan(x), 0, 1 + np.searchsorted(cortes[v], x, side="right")).astype(int)
    # matriz de partida de cada município, linhas de 2026 pela analogia
    D = {m_: g.set_index("linha")[tr.COLS].to_numpy() for m_, g in dentro.groupby("municipio")}
    ordem = [li[ANALOGIA[l]] for l in LINHAS_26]
    ufs_d = dentro.groupby(["uf", "linha"])[tr.COLS].mean()
    Mdentro, Mentre, sem = [], [], 0
    for m_, u in zip(p.municipio, p.uf):
        if m_ in D:
            T = D[m_][ordem]   # linhas gravadas na ordem de tr.LINHAS
        else:   # município novo em 2026 (ou exterior sem par): média da UF
            sem += 1
            T = ufs_d.loc[u].loc[[tr.LINHAS[i] for i in ordem]].to_numpy() if u in ufs_d.index.get_level_values(0) \
                else np.mean([entre[k] for k in entre], axis=0)[ordem]
        Mdentro.append(T)
        Mentre.append((entre[u] if u in entre else np.mean([entre[k] for k in entre], axis=0))[ordem])
    r3 = lambda a: np.round(np.asarray(a), 3).tolist()
    dados = {
        "meta": {"linhas": LINHAS_26, "colunas": tr.COLS, "nomes": NOMES, "analogia": ANALOGIA, "nomes_2022": NOMES_22,
                 "cortes": cortes, "sem_matriz_propria": sem, "municipios": nomes_municipios(),
                 "gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M")},
        "mun": {"municipio": p.municipio.astype(int).tolist(), "uf": p.uf.tolist(),
                "regiao": p.uf.map(REGIAO).fillna("Exterior").tolist(), "aptos": p.aptos.astype(int).tolist(),
                **{c: p[c].fillna(0).astype(int).tolist() for c in LINHAS_26},
                "lula22": p.lula_2t.fillna(0).astype(int).tolist(), "bolsonaro22": p.bolsonaro_2t.fillna(0).astype(int).tolist(),
                **{f"q_{v}": p[f"q_{v}"].tolist() for v in VARS}},
        "dentro": r3(Mdentro), "entre": r3(Mentre),
    }
    WEB.mkdir(parents=True, exist_ok=True)
    arq = WEB / "simulador_2t.json"
    arq.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # conferência: o ponto de partida no Brasil
    for nome, Ms in (("dentro", Mdentro), ("entre", Mentre)):
        Ms = np.array(Ms)
        N = p[LINHAS_26].to_numpy(float)
        R = np.einsum("mr,mrc->c", N, Ms)
        print(f"{nome}: Lula {100 * R[0] / (R[0] + R[1]):.2f}% dos votos em um dos dois; "
              f"comparecimento {100 * (1 - R[4] / R.sum()):.1f}%", flush=True)
    print(f"{arq}: {arq.stat().st_size / 1e6:.1f} MB; {len(p):,} municípios ({sem} sem matriz própria)", flush=True)


if __name__ == "__main__":
    main()
