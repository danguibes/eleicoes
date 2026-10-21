"""A noite do 1º turno de 2026 de novo, com o método por seção: teria acertado a mediana?

Na noite de 04/10 a projeção (municipal.py, base 2022 por município) ficou sempre abaixo de Lula:
−0,9 ponto com 17% das urnas, diminuindo até o fim. É o viés das urnas tardias, o mesmo do ensaio
de 2022. O método do 2º turno (segundo.py) compara cada seção que chegou com ela mesma na eleição
anterior, e no ensaio do 2º turno de 2022 tirou o viés (erro de 0,04–0,07). Aqui ele é testado numa
SEGUNDA eleição, que ele nunca viu: o 1º turno de 2026, com o 1º turno de 2022 como base.

  - ordem de chegada: a hora em que o boletim de cada seção foi recebido pelo TSE (aux, `hr`);
  - base: a mesma seção no 1º turno de 2022 (92% casam pelo número; as outras herdam a média
    das casadas do município);
  - parcial de cada município: a soma das seções chegadas, como o arquivo `u` do TSE;
  - C: transição entre municípios, sem saber quais seções chegaram;
  - D: transição sabendo quais seções chegaram (o método do 2º turno).

    python ensaio_1t2026.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import municipal as mu
import transicao as tr

RAW = Path("data/raw")
SAIDA = ["lula", "flavio", "outros", "bn", "abst"]
PONTOS = (0.01, 0.05, 0.10, 0.17, 0.25, 0.38, 0.50, 0.75, 0.90)


def dados():
    s = pd.read_parquet(RAW / "2026" / "secoes_1t_brasil.parquet")
    s["outros"] = s[["cury", "renan", "caiado", "zema", "outros"]].sum(axis=1)
    s["bn"] = s.branco + s.nulo
    a = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet")
    a = a.assign(zona=a.zona % 10000)[["uf", "zona", "secao", "aptos"] + tr.LINHAS].rename(columns={"aptos": "aptos22"})
    a = a.rename(columns={c: f"b_{c}" for c in tr.LINHAS})
    s = s.merge(a, on=["uf", "zona", "secao"], how="left")
    bcols = [f"b_{c}" for c in tr.LINHAS]
    # base em frações; seção sem par em 2022 herda a média das casadas do município
    fr = s[bcols].div(s.aptos22, axis=0)
    media = fr.groupby(s.municipio).transform("mean")
    fr = fr.fillna(media).fillna(fr.mean())
    s[bcols] = fr.mul(s.aptos, axis=0)          # na escala dos aptos de 2026
    s = s[s.recebido.notna()].sort_values("recebido").reset_index(drop=True)
    return s, bcols


def projetar(s, bcols, chegou, sabe_quais):
    g = s.assign(**{f"r_{c}": s[c] * chegou for c in bcols + SAIDA}, aptos_r=s.aptos * chegou)
    M = g.groupby("municipio").agg(**{c: (c, "sum") for c in bcols + ["aptos"]},
                                   **{f"r_{c}": (f"r_{c}", "sum") for c in bcols + SAIDA}, aptos_r=("aptos_r", "sum"))
    tem = M.aptos_r.to_numpy() > 0
    tot = M[bcols].to_numpy(float)
    rep = M[[f"r_{c}" for c in bcols]].to_numpy(float) if sabe_quais else tot * (M.aptos_r / M.aptos).to_numpy()[:, None]
    ar = np.maximum(M.aptos_r.to_numpy(float), 1)
    resto = (M.aptos - M.aptos_r).clip(lower=0).to_numpy(float)
    Xr = rep / ar[:, None]
    Xf = (tot - rep) / np.maximum(resto, 1)[:, None] if sabe_quais else tot / M.aptos.to_numpy(float)[:, None]
    ap = M[[f"r_{c}" for c in SAIDA]].to_numpy(float)
    Y = ap / ar[:, None]
    T = tr.estimar(Xr[tem], Y[tem], M.aptos_r.to_numpy(float)[tem], iters=2000)
    votos = ap[:, :4].sum(1)
    lam = (votos / (votos + mu.K_ENCOLHE))[:, None]
    P = Xf @ T + np.where(tem[:, None], lam * (Y - Xr @ T), 0)
    P = np.clip(P, 0, None)
    P /= np.maximum(P.sum(1, keepdims=True), 1e-12)
    fim = ap + P * resto[:, None]
    v = fim[:, :3].sum()
    return 100 * fim[:, 0].sum() / v, 100 * fim[:, 1].sum() / v


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    s, bcols = dados()
    v = s[["lula", "flavio", "outros"]].sum()
    real_l, real_f = 100 * v.lula / v.sum(), 100 * v.flavio / v.sum()
    print(f"{len(s):,} seções com hora de chegada; final Lula {real_l:.2f} Flávio {real_f:.2f} (L−F {real_l - real_f:+.2f})", flush=True)
    linhas = []
    for f in PONTOS:
        n = int(f * len(s))
        chegou = (np.arange(len(s)) < n).astype(float)
        ch = s.iloc[:n]
        cv = ch[["lula", "flavio", "outros"]].sum()
        cont = (100 * cv.lula / cv.sum(), 100 * cv.flavio / cv.sum())
        c_ = projetar(s, bcols, chegou, sabe_quais=False)
        d_ = projetar(s, bcols, chegou, sabe_quais=True)
        hora = ch.recebido.max().strftime("%H:%M")
        linhas.append({"frac": f, "hora": hora, "cont_l": cont[0], "cont_f": cont[1], "C_l": c_[0], "C_f": c_[1], "D_l": d_[0], "D_f": d_[1]})
        print(f"{f:4.0%} {hora}  contagem L−F {cont[0] - cont[1]:+6.2f} | C L−F {c_[0] - c_[1]:+6.2f} (Lula {c_[0] - real_l:+.2f}) | "
              f"D L−F {d_[0] - d_[1]:+6.2f} (Lula {d_[0] - real_l:+.2f}, Flávio {d_[1] - real_f:+.2f})   final {real_l - real_f:+.2f}", flush=True)
    r = pd.DataFrame(linhas)
    for k in ("C", "D"):
        print(f"erro médio em Lula, {k}: {np.abs(r[f'{k}_l'] - real_l).mean():.3f} pt; viés {np.mean(r[f'{k}_l'] - real_l):+.3f}", flush=True)
    r.assign(real_l=real_l, real_f=real_f).to_csv("out/ensaio_1t2026.csv", index=False, float_format="%.3f")


if __name__ == "__main__":
    main()
