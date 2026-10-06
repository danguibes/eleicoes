"""Painel do 2º turno de SP por local de votação: boletim a boletim, cada seção comparada com ela mesma no 1º turno.

Aqui não é preciso o índice para saber quais seções chegaram: cada boletim do 2º turno
baixado (coletor.py) é uma seção apurada, com os votos dela. Para as que faltam:

  1. a matriz de transição 1º → 2º turno (transicao.py) é aprendida entre as seções
     já apuradas do estado — uma do estado e uma por zona eleitoral, puxada para a
     do estado;
  2. cada seção que falta recebe o 1º turno dela mesma × a matriz da zona, mais o
     desvio médio das seções já apuradas do mesmo local de votação, encolhido pelo
     tamanho delas.

Intervalo: reamostragem de zonas inteiras, com fator calibrado no ensaio (2º turno
de 2022 em SP, na ordem real de chegada). Sai no formato do painel por local do 1º
turno (painel.py), que a página já sabe desenhar.

    python painel_2t_sp.py --ensaio           # calibra: 2022 em vários momentos da noite
    python painel_2t_sp.py --modo ensaio2t    # o painel de ensaio, com 25% das seções
    python painel_2t_sp.py --modo 2026t2      # a noite: lê data/raw/2026_2t/sp/secoes.jsonl
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import projecao as pj
import transicao as tr
from painel import VARS, _limpo, cortes_quintis, quintil

RAW = Path("data/raw")
WEB = Path("web/dados")
OUT = Path("out")
L26 = ["lula", "flavio", "cury", "renan", "caiado", "zema", "outros", "branco", "nulo", "abst"]
NOMES_26 = {"lula": "Lula", "flavio": "Flávio Bolsonaro", "cury": "Augusto Cury", "renan": "Renan Santos",
            "caiado": "Ronaldo Caiado", "zema": "Romeu Zema", "outros": "outros"}
NOMES_22 = {"lula": "Lula", "bolsonaro": "Bolsonaro", "tebet": "Tebet", "ciro": "Ciro", "soraya": "Soraya",
            "davila": "D'Avila", "menores": "outros"}
K_LOCAL = 1500     # aptos apurados com que o desvio do local vale metade
KAPPA_ZONA = 0.5
FATOR = 1.5        # calibrado em --ensaio
PISO = 0.2         # meia-largura mínima do intervalo do estado, em pontos (como no painel_2t.py)


# ---------------------------------------------------------------- dados
def boletins_2t(pleito):
    """2º turno de SP por seção, dos boletins (só Presidente)."""
    vistos = {}
    arq = RAW / pleito / "sp" / "secoes.jsonl"
    if not arq.exists():
        return pd.DataFrame(columns=["zona", "secao", "lula2", "adv2", "bn2", "comp2", "aptos2"])
    with open(arq, encoding="utf-8") as f:
        for ln in f:
            s = json.loads(ln)
            vistos[(int(s["zona"]), int(s["secao"]))] = s
    linhas = []
    for (zona, secao), s in vistos.items():
        for e in s.get("eleicoes", []):
            for c in e["cargos"]:
                if c["cargo"] != "presidente":
                    continue
                r = {"zona": zona, "secao": secao, "lula2": 0, "adv2": 0, "bn2": 0,
                     "comp2": c["comparecimento"], "aptos2": e["aptos"]}
                for tipo, codigo, n in c["votos"]:
                    if tipo in ("branco", "nulo"):
                        r["bn2"] += n
                    elif int(codigo) == 13:
                        r["lula2"] += n
                    elif int(codigo) == 22:
                        r["adv2"] += n
                linhas.append(r)
    return pd.DataFrame(linhas)


def dados(modo, frac=0.25, pleito="2026_2t"):
    """(seções, linhas do 1º turno, adversário, hora, 2º turno da eleição anterior por seção, atributos dos locais)."""
    if modo == "2026t2":
        s = pd.read_parquet(RAW / "2026" / "secoes_1t_brasil.parquet")
        s = s[s.uf == "SP"][["municipio", "zona", "secao", "local", "aptos"] + L26].reset_index(drop=True)
        b = boletins_2t(pleito)
        s = s.merge(b, on=["zona", "secao"], how="left")
        s["chegou"] = s.lula2.notna()
        p22 = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet")
        p22 = p22[p22.uf == "SP"].assign(zona=lambda d: d.zona % 10000)
        a2 = p22[["zona", "secao", "lula_2t", "bolsonaro_2t"]].assign(bn_2t=p22.branco_2t + p22.nulo_2t)
        a2 = a2.rename(columns={"lula_2t": "lula22_2t", "bolsonaro_2t": "bolsonaro22_2t"})
        la = pd.read_parquet(RAW / "locais_atributos_2026.parquet")
        return s, L26, "flavio", datetime.now().strftime("%H:%M"), a2, {"lula": "lula22_2t", "flavio": "bolsonaro22_2t"}, la
    # ensaio: o 2º turno de 2022 em SP, na ordem real de chegada
    s = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet")
    s = s[s.uf == "SP"].assign(zona=lambda d: d.zona % 10000).reset_index(drop=True)
    pr = pj.principal_de("2022", None)[["zona", "secao", "local"]].drop_duplicates(["zona", "secao"])
    s = s.merge(pr, on=["zona", "secao"], how="left")
    s["local"] = s.local.fillna(-1).astype(int)
    ordem = s.t_2t.rank(method="first")
    s["chegou"] = ordem <= int(frac * s.t_2t.notna().sum())
    s["lula2"], s["adv2"], s["bn2"] = s.lula_2t, s.bolsonaro_2t, s.branco_2t + s.nulo_2t
    s["comp2"], s["aptos2"] = s.aptos_2t - s.abst_2t, s.aptos_2t
    for c in ["lula2", "adv2", "bn2", "comp2", "aptos2"]:
        s[c] = s[c].where(s.chegou)
    hora = s.loc[s.chegou, "t_2t"].max().strftime("%H:%M")
    la = pd.read_parquet(RAW / "locais_atributos_2022.parquet")
    return s, tr.LINHAS, "bolsonaro", hora, None, {}, la


# ---------------------------------------------------------------- projeção
def projetar(s, linhas, n_boot=30, seed=0):
    """Votos de cada seção no 2º turno (lula, adv, bn, abst): reais nas apuradas, previstos nas outras.
    Devolve (central S×4, amostras B×S×4)."""
    rng = np.random.default_rng(seed)
    X = s[linhas].to_numpy(float) / np.maximum(s.aptos.to_numpy(float), 1)[:, None]
    ch = s.chegou.to_numpy()
    real = np.c_[s.lula2, s.adv2, s.bn2, s.aptos2 - s.comp2].astype(float)
    Y = real / np.maximum(s.aptos2.to_numpy(float), 1)[:, None]
    w = s.aptos.to_numpy(float)
    zona = s.zona.to_numpy()
    local = (s.zona * 100000 + s.local).to_numpy()
    zonas = np.unique(zona)

    def ajustar(idx, T0=None, iters=1500):
        Te = tr.estimar(X[idx], Y[idx], w[idx], iters=iters) if T0 is None else \
            tr.estimar_prior(X[idx], Y[idx], w[idx], T0, 1e-9, iters=iters)
        Tz = {}
        zi = zona[idx]
        for z in np.unique(zi):
            m = idx[zi == z]
            if len(m) < 5:
                continue
            A = (X[m] * w[m, None]).T @ X[m]
            Tz[z] = tr.estimar_prior(X[m], Y[m], w[m], Te, KAPPA_ZONA * np.trace(A) / X.shape[1] + 1e-12, iters=iters // 3)
        return Te, Tz

    def prever(Te, Tz):
        P = np.empty((len(s), 4))
        for z in zonas:
            m = zona == z
            P[m] = X[m] @ Tz.get(z, Te)
        # desvio do local: média das apuradas do mesmo local, encolhida
        r = np.where(ch[:, None], Y - P, 0) * np.where(ch, w, 0)[:, None]
        cod, inv = np.unique(local, return_inverse=True)
        soma = np.zeros((len(cod), 4))
        np.add.at(soma, inv, r)
        peso = np.bincount(inv, np.where(ch, w, 0), len(cod))
        desvio = soma / np.maximum(peso, 1)[:, None]
        lam = (peso / (peso + K_LOCAL))[:, None]
        P = np.clip(P + (lam * desvio)[inv], 0, None)
        P /= np.maximum(P.sum(1, keepdims=True), 1e-12)
        return np.where(ch[:, None], real, P * s.aptos.to_numpy(float)[:, None])

    a = np.where(ch)[0]
    if len(a) < 20:
        return None, None
    Te, Tz = ajustar(a)
    central = prever(Te, Tz)
    grupos = {z: a[zona[a] == z] for z in np.unique(zona[a])}
    amostras = []
    for _ in range(n_boot):
        zs = rng.choice(list(grupos), len(grupos), replace=True)       # zonas inteiras: o erro é regional
        idx = np.concatenate([grupos[z] for z in zs])
        # só a matriz do estado se reajusta; cada zona guarda o próprio desvio da central. Reajustar as
        # ~400 zonas em cada reamostragem levava ~8 s cada, e travaria o publicador na noite
        Tb = tr.estimar_prior(X[idx], Y[idx], w[idx], Te, 1e-9, iters=300)
        amostras.append(prever(Tb, {z: np.clip(Tb + (Tz[z] - Te), 0, None) for z in Tz}))
    return central, np.array(amostras)


# ---------------------------------------------------------------- painel
def montar(modo, frac=0.25, n_boot=30, pleito="2026_2t"):
    s, linhas, adv, hora, a2, pares_2t, la = dados(modo, frac, pleito)
    cats = ["lula", adv, "bn"]
    ano = "2026" if modo == "2026t2" else "2022"
    nomes = NOMES_26 if ano == "2026" else NOMES_22
    # 1º turno da mesma eleição, nas mesmas seções
    ant = {f"{c}_1t": s[c] for c in linhas if c not in ("branco", "nulo", "abst")}
    ant["bn_1t"] = s.branco + s.nulo
    for k, v in ant.items():
        s[k] = v
    cats_ant = list(ant)
    cats_2t = []
    if a2 is not None:
        s = s.merge(a2, on=["zona", "secao"], how="left")
        cats_2t = ["lula22_2t", "bolsonaro22_2t", "bn_2t"]
        for c in cats_2t:
            s[c] = s[c].fillna(0)
    # perfil do LOCAL (entorno e eleitorado), não o do município que o painel_2t_2022 já traz
    s = s.drop(columns=[v for v in VARS if v in s]).merge(la[["zona", "local"] + VARS], on=["zona", "local"], how="left")
    loc = s.groupby(["zona", "local"]).agg(aptos=("aptos", "sum"), **{v: (v, "first") for v in VARS}).reset_index()
    cortes = cortes_quintis(loc, "aptos")
    for v in VARS:
        s[f"q_{v}"] = quintil(s[v].to_numpy(float), cortes[v])
    central, amostras = projetar(s, linhas, n_boot=n_boot)
    temAp = central is not None
    ch = s.chegou.to_numpy()
    for j, c in enumerate(cats):
        s[f"ap_{c}"] = np.where(ch, [s.lula2, s.adv2, s.bn2][j], 0)
        if temAp:
            s[f"pj_{c}"] = central[:, j]
    s["apurada"] = ch.astype(int)
    s["aptos_ap"] = np.where(ch, s.aptos2, 0)
    s["comp_ap"] = np.where(ch, s.comp2, 0)
    ic, amostras_q, amostras_pct = {}, {}, {}
    if temAp:
        L = np.concatenate([central[None], amostras])[:, :, :2]
        grupos = {"total": np.zeros(len(s), int), "mun": pd.factorize(s.municipio)[0], "zona": pd.factorize(s.zona)[0],
                  **{f"q_{v}": s[f"q_{v}"].to_numpy() for v in VARS}}
        nomes_g = {"total": ["total"], "mun": [str(x) for x in pd.factorize(s.municipio)[1]],
                   "zona": [str(x) for x in pd.factorize(s.zona)[1]], **{f"q_{v}": [str(q) for q in range(6)] for v in VARS}}
        for k, cod in grupos.items():
            G = max(int(cod.max()) + 1, 6 if k.startswith("q_") else 0)
            sg_ = np.stack([np.stack([np.bincount(cod, Lb[:, j], G) for j in range(2)], axis=1) for Lb in L])
            pv = sg_ / np.maximum(sg_.sum(2, keepdims=True), 1e-9) * 100
            p5, p95 = np.percentile(pv[1:], [5, 95], axis=0)
            meia = (p95 - p5) / 2 * FATOR
            if k == "total":
                meia = np.maximum(meia, PISO)
            ic[k] = {nomes_g[k][g]: {c: [round(float(pv[0, g, j] - meia[g, j]), 2), round(float(pv[0, g, j] + meia[g, j]), 2)]
                                     for j, c in enumerate(cats[:2])} for g in range(G) if sg_[0, g].sum() > 0}
            if k == "total":
                esc = np.maximum(1, PISO / np.maximum((p95 - p5) / 2 * FATOR, 1e-9))
                larg = pv[0] + FATOR * esc * (pv[1:] - np.median(pv[1:], axis=0))
                amostras_pct = {"total": {"total": np.round(larg[:, 0, :], 2).tolist()}}
            if k.startswith("q_"):
                amostras_q[k[2:]] = np.rint(sg_[1:]).astype(int).tolist()
    chave = ["municipio", "zona", "local"]
    num = ["aptos", "apurada", "aptos_ap", "comp_ap"] + [f"ap_{c}" for c in cats] + ([f"pj_{c}" for c in cats] if temAp else [])
    at = s.groupby(chave).agg(**{c: (c, "sum") for c in num}, secoes=("secao", "count"),
                              **{f"q_{v}": (f"q_{v}", "first") for v in VARS}).reset_index()
    s["comparecimento"] = s[cats_ant].sum(axis=1)
    an = s.groupby(chave).agg(**{c: (c, "sum") for c in cats_ant + cats_2t + ["comparecimento", "aptos"]},
                              **{f"q_{v}": (f"q_{v}", "first") for v in VARS}).reset_index()
    nm = (pd.read_parquet(RAW / "tse" / f"locais_{ano}_SP.parquet", columns=["CD_MUNICIPIO", "NM_MUNICIPIO"])
          .drop_duplicates("CD_MUNICIPIO"))
    col = lambda df, cs: {c: [round(float(x), 1) if isinstance(x, (float, np.floating)) else int(x) for x in df[c].fillna(0)] for c in cs}
    dados_ = {
        "meta": {"modo": modo, "cargo": "presidente", "turno": 2, "anterior": f"{ano}, 1º turno", "atual": f"{ano}, 2º turno",
                 "rotulos_anterior": {"1": f"1º turno de {ano}", "2": "2º turno de 2022"},
                 "hora": hora, "gerado": datetime.now().strftime("%d/%m/%Y %H:%M"),
                 "secoes": int(len(s)), "apuradas": int(ch.sum()),
                 "cats": cats, "cats_anterior": cats_ant, "pares": {"lula": "lula_1t", adv: f"{adv}_1t"},
                 "cats_anterior_2t": cats_2t, "pares_2t": pares_2t, "cortes": cortes, "fator_ic": FATOR,
                 "nomes": {**{f"{c}_1t": n for c, n in nomes.items()}, "bn_1t": "brancos e nulos"},
                 "municipios": {int(r.CD_MUNICIPIO): r.NM_MUNICIPIO for r in nm.itertuples()}},
        "atual": col(at, chave + ["secoes"] + num + [f"q_{v}" for v in VARS]),
        "anterior": col(an, chave + cats_ant + cats_2t + ["comparecimento", "aptos"] + [f"q_{v}" for v in VARS]),
        "ic": ic, "amostras_q": amostras_q, "amostras_pct": amostras_pct,
    }
    WEB.mkdir(parents=True, exist_ok=True)
    arq = WEB / f"{modo}_presidente.json"
    arq.write_text(json.dumps(_limpo(dados_), allow_nan=False, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{arq}: {arq.stat().st_size / 1e6:.1f} MB; {len(at):,} locais; {int(ch.sum()):,}/{len(s):,} seções; "
          f"Lula {ic.get('total', {}).get('total', {}).get('lula')}", flush=True)
    return dados_


def ensaio(pontos=(0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90), n_boot=30):
    linhas_res = []
    for f in pontos:
        s, linhas, adv, hora, *_ = dados("ensaio2t", f)
        real = 100 * s.lula_2t.sum() / (s.lula_2t.sum() + s.bolsonaro_2t.sum())
        central, amostras = projetar(s, linhas, n_boot=n_boot)
        pc = 100 * central[:, 0].sum() / central[:, :2].sum()
        pb = 100 * amostras[:, :, 0].sum(1) / amostras[:, :, :2].sum((1, 2))
        lo, hi = np.percentile(pb, [5, 95])
        meia = (hi - lo) / 2
        ch = s[s.chegou]
        cont = 100 * ch.lula2.sum() / (ch.lula2.sum() + ch.adv2.sum())
        linhas_res.append({"frac": f, "hora": hora, "contagem": cont, "projecao": pc, "meia90": meia, "real": real})
        print(f"{f:4.0%} {hora}  contagem {cont:6.2f}  projeção {pc:6.2f} ± {meia:.2f}  real {real:.2f}  "
              f"erro {pc - real:+.2f} ({abs(pc - real) / max(meia, 1e-9):.1f} meias)", flush=True)
    r = pd.DataFrame(linhas_res)
    z = (r.projecao - r.real).abs() / r.meia90
    print(f"erro médio {np.abs(r.projecao - r.real).mean():.3f} pt; cobertura com fator 1: {(z <= 1).mean():.0%}, "
          f"1,5: {(z <= 1.5).mean():.0%}, 2: {(z <= 2).mean():.0%}, 3: {(z <= 3).mean():.0%}", flush=True)
    OUT.mkdir(exist_ok=True)
    r.to_csv(OUT / "ensaio_segundo_sp_2022.csv", index=False, float_format="%.3f")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ensaio", action="store_true")
    ap.add_argument("--modo", choices=["ensaio2t", "2026t2"])
    ap.add_argument("--frac", type=float, default=0.25)
    ap.add_argument("--boot", type=int, default=30)
    ap.add_argument("--pleito", default="2026_2t")
    a = ap.parse_args()
    if a.ensaio:
        ensaio(n_boot=a.boot)
    elif a.modo:
        montar(a.modo, a.frac, a.boot, a.pleito)
