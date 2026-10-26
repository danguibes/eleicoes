"""2º turno de 2026: os resultados se contradizem em algum lugar? E os testes estatísticos de praxe.

Em ordem de força — os primeiros pegam erro de verdade, os últimos só levantam suspeita:

  1. Aritmética de cada boletim: Lula + Flávio + brancos + nulos = comparecimento ≤ aptos; e os aptos
     do 2º turno iguais aos do 1º na mesma seção (o cadastro fecha antes do 1º turno).
  2. Soma dos boletins = total oficial do TSE, por município (onde todos os boletins estão baixados).
  3. Log da urna = boletim: os "voto computado" do dia contra o comparecimento (logs baixados por
     hora_do_voto.py e hora_do_voto_tardias.py).
  4. Benford (1º e 2º dígitos) e último dígito, com a base certa: Benford puro não vale para votos
     por seção (50 a 400 eleitores não atravessam ordens de grandeza), então a comparação é com uma
     eleição limpa SIMULADA com os mesmos tamanhos e as mesmas preferências por zona, e com 2022.
  5. A "impressão digital" de Klimek (comparecimento × voto): enchimento de urna empurra seções
     para 100% de comparecimento E 100% para um candidato ao mesmo tempo.

    python integridade_2t.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw")
SAIDA = RAW / "2026_2t" / "integridade.json"
rng = np.random.default_rng(0)


def boletins_2t():
    L = []
    for f in sorted(RAW.glob("2026_2t/*/secoes.jsonl")):
        uf = f.parent.name.upper()
        vis = {}
        for ln in open(f, encoding="utf-8"):
            try:
                s = json.loads(ln)
            except json.JSONDecodeError:   # a última linha, se o coletor estiver gravando agora
                continue
            vis[(s["zona"], s["secao"])] = s
        for s in vis.values():
            for e in s.get("eleicoes", []):
                for c in e["cargos"]:
                    if c["cargo"] != "presidente":
                        continue
                    v = {"lula": 0, "flavio": 0, "branco": 0, "nulo": 0, "outro": 0}
                    for t, k, n in c["votos"]:
                        if t == "branco":
                            v["branco"] += n
                        elif t == "nulo":
                            v["nulo"] += n
                        elif int(k) == 13:
                            v["lula"] += n
                        elif int(k) == 22:
                            v["flavio"] += n
                        else:
                            v["outro"] += n
                    L.append({"uf": uf, "municipio": s["municipio"], "zona": s["zona"], "secao": s["secao"], "local": s.get("local"),
                              "aptos": e["aptos"], "comparecimento": c["comparecimento"], **v})
    return pd.DataFrame(L)


def aritmetica(b):
    soma = b.lula + b.flavio + b.branco + b.nulo + b.outro
    s1 = pd.read_parquet(RAW / "2026" / "secoes_1t_brasil.parquet", columns=["uf", "zona", "secao", "aptos"])
    m = b.merge(s1, on=["uf", "zona", "secao"], how="left", suffixes=("", "_1t"))
    return {"boletins": int(len(b)),
            "soma_diferente_do_comparecimento": int((soma != b.comparecimento).sum()),
            "comparecimento_maior_que_aptos": int((b.comparecimento > b.aptos).sum()),
            "voto_para_outro_numero": int((b.outro > 0).sum()),
            "sem_par_no_1t": int(m.aptos_1t.isna().sum()),
            "aptos_diferentes_do_1t": int((m.aptos_1t.notna() & (m.aptos != m.aptos_1t)).sum())}


def contra_oficial(b):
    """Município com todos os boletins baixados: a soma deles tem de ser o total oficial (arquivo u)."""
    u = pd.read_parquet(RAW / "2026_2t" / "nacional" / "municipios.parquet")
    u = u.assign(uf=u.uf.str.upper())
    g = b.groupby(["uf", "municipio"]).agg(n=("secao", "size"), co=("comparecimento", "sum"), lu=("lula", "sum"), fl=("flavio", "sum"),
                                          bn=("branco", "sum"), nu=("nulo", "sum")).reset_index()
    m = g.merge(u, on=["uf", "municipio"])
    cheio = m[m.n == m.ts]
    dif = cheio[(cheio.co != cheio.c) | (cheio.lu != cheio.n13) | (cheio.fl != cheio.n22) | (cheio.bn != cheio.vb) | (cheio.nu != cheio.vn)]
    return {"municipios_completos": int(len(cheio)), "secoes_neles": int(cheio.n.sum()), "votos_neles": int((cheio.lu + cheio.fl).sum()),
            "municipios_com_diferenca": int(len(dif)),
            "exemplos": dif[["uf", "municipio", "co", "c", "lu", "n13", "fl", "n22"]].head(10).astype(str).to_dict("records")}


def contra_log(b):
    """Votos computados no log (dia 25/10) contra o comparecimento do boletim da mesma seção."""
    L = []
    d = RAW / "2026_2t" / "hora_do_voto"
    for ln in open(d / "votos.jsonl", encoding="utf-8"):
        r = json.loads(ln)
        if "votos" in r:
            L.append((r["uf"], r["zona"], r["secao"], sum(v.startswith("25/10/2026") for v in r["votos"])))
    if (d / "tardias.jsonl").exists():
        for ln in open(d / "tardias.jsonl", encoding="utf-8"):
            r = json.loads(ln)
            if r.get("votos") is not None:
                L.append((r["uf"], r["zona"], r["secao"], r["votos"]))
    lg = pd.DataFrame(L, columns=["uf", "zona", "secao", "log"]).drop_duplicates(["uf", "zona", "secao"])
    m = lg.merge(b[["uf", "zona", "secao", "comparecimento"]], on=["uf", "zona", "secao"])
    dif = m[m.log != m.comparecimento]
    return {"secoes": int(len(m)), "iguais": int((m.log == m.comparecimento).sum()), "diferentes": int(len(dif)),
            "exemplos": dif.head(10).astype(str).to_dict("records")}


def digitos(x, pos):
    x = np.asarray(x, dtype=np.int64)
    x = x[x >= (10 if pos == 2 else 1)]
    if pos == 0:
        return x % 10
    e = np.floor(np.log10(x)).astype(np.int64)
    return (x // 10 ** e) if pos == 1 else (x // 10 ** (e - 1)) % 10


def dist(x, pos):
    d = digitos(x, pos)
    base = range(1, 10) if pos == 1 else range(10)
    v = np.bincount(d, minlength=10)[list(base)].astype(float)
    return v / v.sum()


BENFORD1 = np.log10(1 + 1 / np.arange(1, 10))
BENFORD2 = np.array([sum(np.log10(1 + 1 / (10 * k + d)) for k in range(1, 10)) for d in range(10)])


def simular(co, p):
    """Uma eleição limpa: cada eleitor da seção vota no candidato com a probabilidade da zona dele."""
    return rng.binomial(co.astype(int), np.clip(p, 0, 1))


def testes_digitos(df, cands, grupo):
    """df: seções com comparecimento e votos; grupo: chave das preferências (zona). Compara o observado
    com Benford e com 200 simulações limpas (a faixa de 95% do que o acaso produz)."""
    out = {}
    for c in cands:
        x = df[c].to_numpy(float)
        p = (df.groupby(grupo)[c].transform("sum") / df.groupby(grupo)["valido"].transform("sum")).to_numpy()
        v = df.valido.to_numpy()
        r = {}
        for pos, nome, ben in [(1, "primeiro", BENFORD1), (2, "segundo", BENFORD2), (0, "ultimo", np.full(10, .1))]:
            obs = dist(pd.Series(x[x >= 10] if pos == 0 else x), pos)
            sims = []
            for _ in range(200):
                xs = simular(v, p)
                sims.append(dist(pd.Series(xs[xs >= 10] if pos == 0 else xs), pos))
            sims = np.array(sims)
            lo, hi = np.percentile(sims, 2.5, axis=0), np.percentile(sims, 97.5, axis=0)
            # distância (soma dos quadrados) ao esperado pela simulação: o observado está dentro do que o acaso dá?
            mu = sims.mean(0)
            dist_obs = float(((obs - mu) ** 2).sum())
            dist_sim = ((sims - mu) ** 2).sum(1)
            r[nome] = {"observado": [round(float(a), 4) for a in obs], "benford": [round(float(a), 4) for a in ben],
                       "simulado": [round(float(a), 4) for a in mu], "sim_lo": [round(float(a), 4) for a in lo], "sim_hi": [round(float(a), 4) for a in hi],
                       "fora_da_faixa": int(((obs < lo) | (obs > hi)).sum()),
                       "dist_benford": round(float(((obs - ben) ** 2).sum()) * 1e4, 2), "dist_simulado": round(dist_obs * 1e4, 2),
                       "p_simulado": round(float((dist_sim >= dist_obs).mean()), 3)}
        out[c] = r
    return out


def klimek(co, ap, a, b):
    """Seções com comparecimento ≥ 95% e com ≥ 95% para um candidato; e o histograma 2D."""
    t = co / ap
    sa = a / np.maximum(a + b, 1)
    ok = (ap >= 100) & (a + b >= 50)
    t, sa = t[ok], sa[ok]
    H, _, _ = np.histogram2d(t, sa, bins=[np.linspace(0.4, 1, 31), np.linspace(0, 1, 51)])
    return {"secoes": int(ok.sum()), "comparec_95": round(float((t >= .95).mean() * 100), 3),
            "comparec_95_e_95_a": round(float(((t >= .95) & (sa >= .95)).mean() * 100), 4),
            "comparec_95_e_95_b": round(float(((t >= .95) & (sa <= .05)).mean() * 100), 4),
            "correlacao": round(float(np.corrcoef(t, sa)[0, 1]), 3), "hist": H.astype(int).tolist()}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    b = boletins_2t()
    out = {"aritmetica": aritmetica(b)}
    print("1. aritmética:", out["aritmetica"], flush=True)
    out["oficial"] = contra_oficial(b)
    print("2. soma dos boletins × total oficial:", {k: v for k, v in out["oficial"].items() if k != "exemplos"}, flush=True)
    out["log"] = contra_log(b)
    print("3. log × boletim:", {k: v for k, v in out["log"].items() if k != "exemplos"}, flush=True)
    # 4. dígitos: 2026 e 2022, a mesma conta
    b["valido"] = b.lula + b.flavio
    a = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet", columns=["uf", "zona", "aptos_2t", "abst_2t", "lula_2t", "bolsonaro_2t"])
    a = a.rename(columns={"lula_2t": "lula", "bolsonaro_2t": "bolsonaro"}).assign(valido=lambda x: x.lula + x.bolsonaro)
    a["zg"] = a.uf + a.zona.astype(str); b["zg"] = b.uf + b.zona.astype(str)
    out["digitos"] = {"2026": testes_digitos(b[b.valido > 0], ["lula", "flavio"], "zg"),
                      "2022": testes_digitos(a[a.valido > 0], ["lula", "bolsonaro"], "zg")}
    for ano, d in out["digitos"].items():
        for c, r in d.items():
            print(f"4. {ano} {c:9s} " + " · ".join(f"{k}: dist Benford {v['dist_benford']:7.1f} × simulado {v['dist_simulado']:6.2f} (p {v['p_simulado']})"
                                                for k, v in r.items()), flush=True)
    # 5. Klimek
    out["klimek"] = {"2026": klimek(b.comparecimento.to_numpy(float), b.aptos.to_numpy(float), b.lula.to_numpy(float), b.flavio.to_numpy(float)),
                     "2022": klimek((a.aptos_2t - a.abst_2t).to_numpy(float), a.aptos_2t.to_numpy(float), a.lula.to_numpy(float), a.bolsonaro.to_numpy(float))}
    for ano, k in out["klimek"].items():
        print(f"5. {ano}: {k['secoes']:,} seções; comparecimento ≥95%: {k['comparec_95']}%; e ≥95% Lula: {k['comparec_95_e_95_a']}%; "
              f"e ≥95% o adversário: {k['comparec_95_e_95_b']}%; correlação comparecimento × Lula {k['correlacao']}", flush=True)
    SAIDA.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
