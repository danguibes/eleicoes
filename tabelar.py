"""Transforma o secoes.jsonl do coletor em tabelas, e confere contra o total oficial.

Sai data/raw/<pleito>/<uf>/votos.parquet, formato longo — uma linha por
(seção, cargo, votável) —, com aptos e comparecimento repetidos em cada linha.
Branco e nulo têm `codigo` nulo e `tipo` "branco"/"nulo".

A conferência é o teste de aceitação do coletor: a soma das seções de um
município tem que bater voto a voto com o JSON municipal do próprio TSE. Se não
bater, falta seção ou sobra retransmissão, e nada depois disso presta.

    python tabelar.py --pleito 2022 --uf sp --conferir 71072
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from tse import PLEITOS, Cliente


def tabelar(pleito, uf, cargos=None):
    d = Path("data/raw") / pleito / uf
    linhas = []
    vistos = {}
    with open(d / "secoes.jsonl", encoding="utf-8") as f:
        for ln in f:
            s = json.loads(ln)
            # uma seção retransmitida aparece de novo: vale a última
            vistos[(s["municipio"], s["zona"], s["secao"])] = s
    for (mun, zona, secao), s in vistos.items():
        for e in s["eleicoes"]:
            for c in e["cargos"]:
                if cargos and c["cargo"] not in cargos:
                    continue  # na noite só Presidente: a tabela inteira do estado é lenta
                for tipo, codigo, n in c["votos"]:
                    linhas.append((mun, zona, secao, s["local"], e["id"], c["cargo"],
                                   e["aptos"], c["comparecimento"], tipo, codigo, n))
    df = pd.DataFrame(linhas, columns=["municipio", "zona", "secao", "local", "eleicao",
                                       "cargo", "aptos", "comparecimento", "tipo",
                                       "codigo", "votos"])
    df["codigo"] = df.codigo.astype("Int64")  # nulo em branco/nulo; sem isso vira float
    df.to_parquet(d / "votos.parquet", index=False)
    print(f"{len(vistos):,} seções, {len(df):,} linhas -> {d / 'votos.parquet'}")
    return df


def conferir(df, pleito, uf, mun):
    p = PLEITOS[pleito]
    st, corpo, _ = Cliente(taxa=2).get(p.url_municipio(uf, mun))
    if st != 200:
        sys.exit(f"total oficial respondeu {st}")
    of = json.loads(corpo)["abr"][0]
    pres = df[(df.municipio == int(mun)) & (df.cargo == "presidente")]
    por_secao = pres.drop_duplicates(["zona", "secao"])
    nosso = {
        "seções": len(por_secao),
        "aptos": int(por_secao.aptos.sum()),
        "comparecimento": int(por_secao.comparecimento.sum()),
        "brancos": int(pres[pres.tipo == "branco"].votos.sum()),
        "nulos": int(pres[pres.tipo == "nulo"].votos.sum()),
    }
    oficial = {"seções": int(of["st"]), "aptos": int(of["e"]),
               "comparecimento": int(of["c"]), "brancos": int(of["vb"]),
               "nulos": int(of["tvn"])}
    cand = pres[pres.tipo == "nominal"].groupby("codigo").votos.sum()
    for c in of["cand"]:
        oficial[f"nº {c['n']}"] = int(c["vap"])
        nosso[f"nº {c['n']}"] = int(cand.get(int(c["n"]), 0))
    ok = True
    for k in oficial:
        dif = nosso[k] - oficial[k]
        ok &= dif == 0
        print(f"  {k:16s} oficial {oficial[k]:>10,}  seções {nosso[k]:>10,}  "
              f"{'ok' if dif == 0 else f'DIFERENÇA {dif:+,}'}")
    print("CONFERE voto a voto" if ok else "NÃO CONFERE")
    return ok


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", required=True, choices=sorted(PLEITOS))
    ap.add_argument("--uf", default="sp")
    ap.add_argument("--conferir", help="código TSE do município a conferir")
    a = ap.parse_args()
    df = tabelar(a.pleito, a.uf)
    if a.conferir and not conferir(df, a.pleito, a.uf, a.conferir):
        sys.exit(1)
