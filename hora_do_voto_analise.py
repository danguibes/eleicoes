"""Quantos votaram depois das 17h (de Brasília): a amostra de logs (hora_do_voto.py) e o
encerramento de todas as urnas com boletim (data/raw/<pleito>/<uf>/secoes.jsonl).

    python hora_do_voto_analise.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw")
D = RAW / "2026_2t" / "hora_do_voto"
DIA = {"1t": "04/10/2026", "2t": "25/10/2026"}
CORTES = ["17:00:00", "17:05:00", "17:15:00", "17:30:00", "18:00:00"]


def fuso(abertura):
    """Horas a somar à hora local para chegar à de Brasília: a urna abre às 8h de Brasília."""
    return 8 - int(abertura[9:11])


def segundos(h):
    return int(h[:2]) * 3600 + int(h[3:5]) * 60 + int(h[6:8])


def tabela_log():
    a = pd.read_parquet(D / "amostra.parquet")
    chave = set(zip(a.uf, a.zona, a.secao))
    peso = {(u, z, s): p for u, z, s, p in zip(a.uf, a.zona, a.secao, a.peso)}
    linhas = []
    for ln in open(D / "votos.jsonl", encoding="utf-8"):
        r = json.loads(ln)
        k = (r["uf"], r["zona"], r["secao"])
        if k not in chave or "votos" not in r:
            continue
        off = fuso(r["abertura"]) * 3600
        for t, dia in DIA.items():
            seg = [segundos(v[11:]) + off for v in r["votos"] if v.startswith(dia)]
            if not seg:
                continue
            linhas.append({"uf": r["uf"], "zona": r["zona"], "secao": r["secao"], "turno": t, "peso": peso[k], "n": len(seg),
                           **{c: sum(s >= segundos(c) for s in seg) for c in CORTES},
                           "ultimo": max(seg), "seg": seg})
    return pd.DataFrame(linhas)


def parte(df, c, rng=None):
    w = df.peso.to_numpy()
    if rng is not None:   # reamostra seções dentro de cada UF
        idx = np.concatenate([rng.choice(ii, len(ii)) for ii in df.groupby("uf").indices.values()])
        df, w = df.iloc[idx], df.peso.to_numpy()[idx]
    return 100 * (w * df[c].to_numpy()).sum() / (w * df.n.to_numpy()).sum()


def encerramento(pleito):
    """Encerramento de cada urna com boletim, em hora de Brasília."""
    L = []
    for f in RAW.glob(f"{pleito}/*/secoes.jsonl"):
        uf = f.parent.name.upper()
        if uf == "ZZ":
            continue
        vis = {}
        for ln in open(f, encoding="utf-8"):
            s = json.loads(ln)
            vis[(s["zona"], s["secao"])] = s
        for s in vis.values():
            if s.get("abertura") and s.get("encerramento"):
                co = next((c["comparecimento"] for e in s.get("eleicoes", []) for c in e["cargos"] if c["cargo"] == "presidente"), 0)
                L.append((uf, segundos(s["encerramento"][9:11] + ":" + s["encerramento"][11:13] + ":" + s["encerramento"][13:15]) + fuso(s["abertura"]) * 3600, co))
    return pd.DataFrame(L, columns=["uf", "enc", "co"])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    df = tabela_log()
    rng = np.random.default_rng(1)
    co = {"1t": 125_274_513, "2t": 128_236_074}   # comparecimento no país (arquivos u do TSE)
    out = {"amostra": {}, "encerramento": {}}
    for t in ("1t", "2t"):
        g = df[df.turno == t]
        print(f"\n{t}: {len(g):,} urnas na amostra, {g.n.sum():,} votos no log", flush=True)
        res = {}
        for c in CORTES:
            p = parte(g, c)
            b = sorted(parte(g, c, rng) for _ in range(300))
            res[c[:5]] = {"pct": round(p, 3), "ic": [round(b[7], 3), round(b[292], 3)], "eleitores": int(round(p / 100 * co[t], -3))}
            print(f"  votou às {c[:5]} ou depois: {p:5.2f}% (IC 95% {b[7]:.2f}–{b[292]:.2f}) ≈ {p / 100 * co[t] / 1e6:.2f} milhão de eleitores", flush=True)
        # por UF e o perfil por faixa de 15 min depois das 16h
        uf = {u: round(float(parte(x, "17:00:00")), 2) for u, x in g.groupby("uf")}
        faixas = {}
        for s0 in range(8 * 3600, 20 * 3600, 900):
            n = sum(w * sum(s0 <= s < s0 + 900 for s in seg) for w, seg in zip(g.peso, g.seg))
            faixas[f"{s0 // 3600:02d}:{s0 % 3600 // 60:02d}"] = round(float(100 * n / (g.peso * g.n).sum()), 3)
        res["por_uf"], res["faixas_15min"], res["urnas"] = uf, faixas, int(len(g))
        print("  por UF:", dict(sorted(uf.items(), key=lambda x: -x[1])), flush=True)
        print("  faixas:", faixas, flush=True)
        out["amostra"][t] = res
    for pl, t in (("2026", "1t"), ("2026_2t", "2t")):
        e = encerramento(pl)
        r = {}
        for c in CORTES:
            m = e.enc > segundos(c) + 59   # fechou depois do minuto: teve gente votando depois
            r[c[:5]] = round(float(100 * m.mean()), 1)
        out["encerramento"][t] = {"urnas": int(len(e)), "pct_urnas_fecharam_depois": r,
                                  "p99": f"{int(e.enc.quantile(.99)) // 3600:02d}:{int(e.enc.quantile(.99)) % 3600 // 60:02d}"}
        print(f"encerramento {t}: {len(e):,} urnas; fecharam depois de: {r}; p99 {out['encerramento'][t]['p99']}", flush=True)
    out["tardias"] = tardias()
    out["meta"] = {"gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"), "comparecimento": co}
    (D / "resumo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    Path("web/dados/hora_do_voto.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def tardias():
    """As urnas com boletim que fecharam depois das 17:15 (hora_do_voto_tardias.py), contadas voto a voto, e a
    extrapolação para as seções sem boletim baixado: proporcional à cobertura de boletins do município."""
    from painel_brasil import nomes_municipios
    arq = D / "tardias.jsonl"
    if not arq.exists():
        return None
    t = pd.DataFrame([json.loads(l) for l in open(arq, encoding="utf-8")])
    t = t[t.votos.notna()]
    tot = pd.read_parquet(RAW / "2026" / "secoes_1t_brasil.parquet", columns=["municipio"]).municipio.value_counts()
    bu = {}
    for f in RAW.glob("2026_2t/*/secoes.jsonl"):
        for k in {(r["municipio"], r["zona"], r["secao"]) for r in map(json.loads, open(f, encoding="utf-8"))}:
            bu[k[0]] = bu.get(k[0], 0) + 1
    cols = ["depois_17", "depois_1705", "depois_18"]
    g = t.groupby(["uf", "municipio"]).agg(urnas=("votos", "size"), com_voto=("depois_1705", lambda x: int((x > 0).sum())),
                                          **{c: (c, "sum") for c in cols}).reset_index()
    g["fator"] = g.municipio.map(tot) / g.municipio.map(pd.Series(bu))
    nomes = nomes_municipios()
    top = g.sort_values("depois_1705", ascending=False).head(15)
    return {"urnas": int(len(t)), "urnas_com_voto_1705": int((t.depois_1705 > 0).sum()), "urnas_com_voto_18": int((t.depois_18 > 0).sum()),
            "contados": {c: int(t[c].sum()) for c in cols}, "estimados": {c: int(round((g[c] * g.fator).sum())) for c in cols},
            "ultimo": int(t.ultimo.max()), "cobertura": round(sum(bu.values()) / int(tot.drop(index=[m for m in tot.index if m not in bu], errors="ignore").sum() or 1), 3),
            "municipios": [{"uf": r.uf, "nome": nomes.get(int(r.municipio), str(r.municipio)), "urnas": int(r.urnas), "com_voto": int(r.com_voto),
                            "depois_1705": int(r.depois_1705), "depois_18": int(r.depois_18), "fator": round(float(r.fator), 2)} for r in top.itertuples()]}


if __name__ == "__main__":
    main()
