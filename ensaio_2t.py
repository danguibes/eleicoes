"""A noite do 2º turno de 2022, de novo, na ordem real de chegada: qual projeção usar no 2º turno de 2026.

Camada por município (é a que acompanha a noite). Em cada momento, cada município
tem o parcial do 2º turno das seções que já chegaram, e o modelo prevê o resto.
Três bases para o resto:

  A  a eleição anterior (2º turno de 2018, por município) — o que a noite do 1º turno
     de 2026 fez, trocando a eleição;
  B  o 1º turno da MESMA eleição, no mesmo município, pelo mesmo modelo (razão log);
  C  a matriz de transição 1º→2º turno (transicao.py), reaprendida a cada momento com
     os municípios que já chegaram: para onde foram os votos de cada candidato do 1º
     turno, dos brancos, dos nulos e da abstenção. O desvio do próprio município entra
     encolhido pelo tamanho do parcial, como em A e B.

    python ensaio_2t.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import municipal as mu
import transicao as tr

RAW = Path("data/raw")
OUT = Path("out")
PONTOS = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90)
L1 = tr.LINHAS          # lula … nulo, abst (1º turno, frações dos aptos)
C2 = ["lula", "bolsonaro", "bn", "abst"]


def municipios(s):
    g = s.groupby("municipio").agg(uf=("uf", "first"), aptos=("aptos_2t", "sum"),
                                   **{c: (c, "sum") for c in L1})
    return g.reset_index()


def parcial(s, frac):
    s = s.sort_values("t_2t")
    ch = s.iloc[: int(frac * len(s))]
    a = ch.groupby("municipio").agg(ap_lula=("lula_2t", "sum"), ap_bolsonaro=("bolsonaro_2t", "sum"),
                                    ap_branco=("branco_2t", "sum"), ap_nulo=("nulo_2t", "sum"),
                                    aptos_ap=("aptos_2t", "sum"), abst_ap=("abst_2t", "sum"),
                                    # o 1º turno exatamente das seções que já chegaram (D)
                                    **{f"r1_{c}": (c, "sum") for c in L1})
    a["ap_bn"] = a.ap_branco + a.ap_nulo
    a["comp_ap"] = a.aptos_ap - a.abst_ap
    return a, ch.t_2t.max().strftime("%H:%M"), ch


def via_modelo(M, base_cols, comp):
    """A e B: o modelo da noite do 1º turno (municipal.projetar_mun)."""
    M = M.copy()
    for c in base_cols:
        M[f"b_{c}"] = M[c] + 1
    M["b_comp"] = comp.clip(0.3, 0.98)
    cats = ["lula", "bolsonaro", "bn"]
    _, linha = mu.projetar_mun(M, cats, n_boot=1)
    return linha[:, 0].sum(), linha[:, 1].sum()


def via_transicao(M):
    """C: Goodman entre os municípios que já chegaram, com a matriz restrita ao simplex."""
    tem = M.aptos_ap.to_numpy() > 0
    X = M[L1].to_numpy(float) / M.aptos.to_numpy(float)[:, None]
    ap = M[["ap_lula", "ap_bolsonaro", "ap_bn", "abst_ap"]].to_numpy(float)
    Y = ap / np.maximum(M.aptos_ap.to_numpy(float), 1)[:, None]
    w = M.aptos_ap.to_numpy(float)
    T = tr.estimar(X[tem], Y[tem], w[tem], iters=2000)
    P = X @ T
    votos = ap[:, :3].sum(1)
    lam = (votos / (votos + mu.K_ENCOLHE))[:, None]
    P = np.where(tem[:, None], P + lam * (Y - P), P)
    resto = (M.aptos - M.aptos_ap).clip(lower=0).to_numpy(float)[:, None]
    tot = ap + P * resto
    return tot[:, 0].sum(), tot[:, 1].sum()


def via_secoes(M):
    """D: como C, mas sabendo QUAIS seções chegaram (o índice de seções de cada UF diz).
    A transição se aprende entre o 2º turno das seções chegadas e o 1º turno delas mesmas;
    o resto se prevê pelo 1º turno das seções que faltam."""
    tem = M.aptos_ap.to_numpy() > 0
    rep = M[[f"r1_{c}" for c in L1]].to_numpy(float)
    tot1 = M[L1].to_numpy(float)
    ap_ = np.maximum(M.aptos_ap.to_numpy(float), 1)[:, None]
    resto_ap = (M.aptos - M.aptos_ap).clip(lower=0).to_numpy(float)
    Xr = rep / ap_
    Xf = (tot1 - rep) / np.maximum(resto_ap, 1)[:, None]
    ap = M[["ap_lula", "ap_bolsonaro", "ap_bn", "abst_ap"]].to_numpy(float)
    Y = ap / ap_
    w = M.aptos_ap.to_numpy(float)
    T = tr.estimar(Xr[tem], Y[tem], w[tem], iters=2000)
    votos = ap[:, :3].sum(1)
    lam = (votos / (votos + mu.K_ENCOLHE))[:, None]
    P = Xf @ T + np.where(tem[:, None], lam * (Y - Xr @ T), 0)
    tot = ap + np.clip(P, 0, None) * resto_ap[:, None]
    return tot[:, 0].sum(), tot[:, 1].sum()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    s = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet")
    s = s[s.t_2t.notna()]
    M0 = municipios(s)
    real = 100 * s.lula_2t.sum() / (s.lula_2t.sum() + s.bolsonaro_2t.sum())
    b18 = mu.por_municipio("2018", {13: "haddad18", 17: "bolsonaro18"}, turno="2")
    M0 = M0.merge(b18.drop(columns="uf"), on="municipio", how="left")
    for c in ["haddad18", "bolsonaro18", "bn"]:
        M0[c] = M0[c].fillna(M0[c].median())
    M0 = M0.rename(columns={"bn": "bn18"})
    comp18 = (M0[["haddad18", "bolsonaro18", "bn18"]].sum(1) / M0.aptos)
    comp22 = 1 - M0.abst / M0.aptos
    linhas = []
    for f in PONTOS:
        a, hora, ch = parcial(s, f)
        M = M0.merge(a, left_on="municipio", right_index=True, how="left")
        for c in a.columns:
            M[c] = M[c].fillna(0)
        cont = 100 * ch.lula_2t.sum() / (ch.lula_2t.sum() + ch.bolsonaro_2t.sum())
        r = {"frac": f, "hora": hora, "contagem": cont}
        for nome, (l, b) in {
            "A_2018": via_modelo(M, ["haddad18", "bolsonaro18", "bn18"], comp18),
            "B_1turno": via_modelo(M, ["lula", "bolsonaro", "tebet", "ciro", "soraya", "davila", "menores", "branco", "nulo"], comp22),
            "C_transicao": via_transicao(M),
            "D_secoes": via_secoes(M),
        }.items():
            r[nome] = 100 * l / (l + b)
        linhas.append(r)
        print(f"{f:4.0%} {hora}  contagem {cont:6.2f} | " + " | ".join(f"{k} {r[k]:6.2f} ({r[k] - real:+.2f})"
              for k in ("A_2018", "B_1turno", "C_transicao", "D_secoes")) + f"   real {real:.2f}", flush=True)
    t = pd.DataFrame(linhas)
    t["real"] = real
    for k in ("contagem", "A_2018", "B_1turno", "C_transicao", "D_secoes"):
        print(f"erro médio {k}: {np.abs(t[k] - real).mean():.2f} pt", flush=True)
    OUT.mkdir(exist_ok=True)
    t.to_csv(OUT / "ensaio_2t_2022.csv", index=False, float_format="%.3f")


if __name__ == "__main__":
    main()
