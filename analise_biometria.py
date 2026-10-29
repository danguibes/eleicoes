"""Biometria e relógio das urnas, 2026 — sobre biometria.parquet (biometria.py) e habilitacao.jsonl (hora_biometria.py).

  1. quanto se votou sem biometria (por biografia: a digital não conferiu; sem biometria: eleitor sem digital), por turno e UF;
  2. a mesma seção nos dois turnos: onde a parte não biométrica saltou;
  3. as seções com mais habilitação não biométrica votam diferente das vizinhas do mesmo município?
  4. o relógio da urna: a emissão do boletim (relógio da urna) contra a chegada no TSE (relógio do servidor);
  5. a hora do voto por tipo de habilitação (logs).

    python analise_biometria.py      # → web/dados/biometria.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from naovotos import boletins
from painel_brasil import nomes_municipios

RAW = Path("data/raw")


def hms(s):
    return int(s[9:11]) * 3600 + int(s[11:13]) * 60 + int(s[13:15])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    nm = nomes_municipios()
    d = pd.read_parquet(RAW / "2026_2t" / "biometria.parquet")
    d = d[d.uf != "ZZ"]
    d["nao_bio"] = d.por_biog + d.sem_bio
    out = {"meta": {"gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M")}}
    # 1. totais e UF
    tot = {}
    for t, g in d.groupby("turno"):
        c = g.comparec.sum()
        tot[t] = {"secoes": int(len(g)), "comparec": int(c), "por_bio": int(g.por_bio.sum()), "por_biog": int(g.por_biog.sum()), "sem_bio": int(g.sem_bio.sum()),
                  "confere": round(float(((g.por_bio + g.por_biog + g.sem_bio) == g.comparec).mean()), 5)}
        print(f"1. {t}: comparecimento {c:,}; biometria {100 * g.por_bio.sum() / c:.2f}% · biografia {100 * g.por_biog.sum() / c:.2f}% · sem biometria "
              f"{100 * g.sem_bio.sum() / c:.2f}% · soma confere em {100 * tot[t]['confere']:.3f}%", flush=True)
    out["total"] = tot
    uf = d.groupby(["turno", "uf"])[["comparec", "por_biog", "sem_bio"]].sum()
    out["uf"] = {u: {t: [round(float(100 * uf.loc[(t, u)].por_biog / uf.loc[(t, u)].comparec), 2), round(float(100 * uf.loc[(t, u)].sem_bio / uf.loc[(t, u)].comparec), 2)]
                     for t in ("1t", "2t")} for u in sorted(d.uf.unique())}
    # 2. a mesma seção nos dois turnos
    a = d[d.turno == "1t"].set_index(["uf", "zona", "secao"])
    b = d[d.turno == "2t"].set_index(["uf", "zona", "secao"])
    p = a[["municipio", "comparec", "nao_bio", "por_biog", "sem_bio"]].join(b[["comparec", "nao_bio", "por_biog", "sem_bio"]], rsuffix="2", how="inner").reset_index()
    p = p[(p.comparec >= 50) & (p.comparec2 >= 50)]
    p["pct1"], p["pct2"] = 100 * p.nao_bio / p.comparec, 100 * p.nao_bio2 / p.comparec2
    p["delta"] = p.pct2 - p.pct1
    q = p.delta.quantile([.001, .01, .5, .99, .999]).round(2).to_dict()
    salto = p[p.delta >= 20]
    print(f"2. {len(p):,} seções nos dois turnos; Δ da parte não biométrica (pontos): {q}; saltou 20+ pontos: {len(salto):,}", flush=True)
    top = salto.sort_values("delta", ascending=False).head(30).assign(nome=lambda x: x.municipio.map(nm))
    print(top[["uf", "nome", "zona", "secao", "comparec", "pct1", "comparec2", "pct2", "por_biog2", "sem_bio2"]].round(1).head(12).to_string(index=False), flush=True)
    out["secoes"] = {"pares": int(len(p)), "quantis_delta": {str(k): v for k, v in q.items()}, "saltos20": int(len(salto)),
                     "hist1": np.histogram(p.pct1, bins=np.arange(0, 101, 2))[0].tolist(), "hist2": np.histogram(p.pct2, bins=np.arange(0, 101, 2))[0].tolist(),
                     "top": top[["uf", "nome", "zona", "secao", "comparec", "pct1", "comparec2", "pct2", "por_biog2", "sem_bio2"]].round(1).to_dict("records")}
    # 3. voto × habilitação não biométrica, dentro do município (2º turno)
    vs = []
    for u in sorted(p.uf.unique()):
        bb = boletins("2026_2t", u.lower())
        if bb is not None:
            vs.append(bb.assign(uf=u))
    v = pd.concat(vs)
    s1 = pd.read_parquet(RAW / "2026" / "secoes_1t_brasil.parquet", columns=["uf", "zona", "secao", "lula", "flavio"])
    m = p.merge(v[["uf", "zona", "secao", "26b_lu", "26b_ad"]], on=["uf", "zona", "secao"]).merge(s1, on=["uf", "zona", "secao"])
    m["lula2"] = 100 * m["26b_lu"] / (m["26b_lu"] + m["26b_ad"]).clip(lower=1)
    m["dl"] = m.lula2 - 100 * m.lula / (m.lula + m.flavio).clip(lower=1)
    for c in ["pct2", "lula2", "dl", "delta"]:
        m[c + "_d"] = m[c] - m.groupby("municipio")[c].transform("mean")
    m["q"] = pd.qcut(m.pct2_d, 5, labels=False)
    g = m.groupby("q")[["pct2_d", "lula2_d", "dl_d"]].mean().round(2)
    m["q2"] = pd.qcut(m.delta_d.rank(method="first"), 5, labels=False)
    g2 = m.groupby("q2")[["delta_d", "dl_d"]].mean().round(2)
    print("3. quintis de habilitação não biométrica no 2º turno (desvio da média do município):\n" + g.to_string(), flush=True)
    print("   quintis da MUDANÇA da parte não biométrica (1º→2º), contra a mudança de Lula:\n" + g2.to_string(), flush=True)
    out["voto"] = {"nivel": g.values.tolist(), "mudanca": g2.values.tolist(),
                   "corr_nivel": round(float(np.corrcoef(m.pct2_d, m.lula2_d)[0, 1]), 3), "corr_mudanca": round(float(np.corrcoef(m.delta_d, m.dl_d)[0, 1]), 3)}
    print(f"   correlação nível × Lula {out['voto']['corr_nivel']}; mudança × mudança de Lula {out['voto']['corr_mudanca']}", flush=True)
    # 4. relógio: emissão (urna, convertida a Brasília pela abertura) × chegada no TSE (servidor)
    r = d[(d.turno == "2t") & d.recebido.notna() & d.emissao.notna() & d.abertura.notna()].copy()
    off = 8 * 3600 - r.abertura.map(hms) // 3600 * 3600
    r["emi"] = r.emissao.map(hms) + off
    r["rec"] = r.recebido.map(lambda x: int(x[11:13]) * 3600 + int(x[14:16]) * 60 + int(x[17:19]))
    r["mesmo_dia"] = r.recebido.str[:10] == "25/10/2026"
    r = r[r.mesmo_dia]
    r["atraso"] = (r.rec - r.emi) / 60
    ab = r.abertura.map(hms) % 3600
    rel = {"urnas": int(len(r)), "atraso_quantis_min": {str(k): round(float(x), 1) for k, x in r.atraso.quantile([.001, .01, .1, .5, .9, .99]).items()},
           "chegou_antes_de_emitir": int((r.atraso < 0).sum()), "chegou_antes_1min": int((r.atraso < -1).sum()),
           "abertura_fora_de_8h05": int((ab > 300).sum()), "abertura_quantis_seg": {str(k): int(x) for k, x in ab.quantile([.5, .9, .99, .999]).items()}}
    print(f"4. relógio: {rel}", flush=True)
    out["relogio"] = rel
    # 5. hora × habilitação (logs)
    arq = RAW / "2026_2t" / "hora_do_voto" / "habilitacao.jsonl"
    if arq.exists():
        H = {}
        for ln in open(arq, encoding="utf-8"):
            x = json.loads(ln)
            if "faixas" not in x:
                continue
            gr = H.setdefault(x["grupo"], {})
            for f, tipos in x["faixas"].items():
                for t, n in tipos.items():
                    gr.setdefault(f, {}).setdefault(t, 0)
                    gr[f][t] += n
        out["hora"] = H
        for grupo, fx in H.items():
            depois = {t: sum(v.get(t, 0) for f, v in fx.items() if f >= "17:00") for t in {t for v in fx.values() for t in v}}
            antes = {t: sum(v.get(t, 0) for f, v in fx.items() if f < "17:00") for t in depois}
            print(f"5. {grupo}: depois das 17h {depois} · antes {antes}", flush=True)
    Path("web/dados/biometria.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=int), encoding="utf-8")


if __name__ == "__main__":
    main()
