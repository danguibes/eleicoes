"""Índices de seções das 28 UFs, a cada rodada: QUAIS seções chegaram e quando.

É a metade "urna a urna" da noite do 2º turno sem baixar boletins: o arquivo `u` de
cada município dá a soma das seções totalizadas, e o índice da UF diz quais são (as
`st` primeiras pela hora de chegada — conferir_indice.py). São 28 arquivos, com GET
condicional; o que não mudou volta 304. Cada versão nova fica guardada (a série é a
noite), e a última vira data/raw/<pleito>/indices/chegadas.parquet:
uf, municipio, zona, secao, t.

    python indices.py --pleito 2026_2t --intervalo 30
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from tse import Bloqueado, Cliente, obter

RAW = Path("data/raw")
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb",
       "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to", "zz"]


def chegadas(cs, uf):
    out = []
    for ab in cs.get("abr", []):
        for mu in ab.get("mu", []):
            for z in mu.get("zon", []):
                for s in z.get("sec", []):
                    if s.get("da") and "nsp" not in s:   # agregada: os votos vêm na principal
                        out.append((uf.upper(), int(mu["cd"]), int(z["cd"]), int(s["ns"]), f"{s['da']} {s['ha']}"))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", default="2026_2t")
    ap.add_argument("--taxa", type=float, default=5)
    ap.add_argument("--intervalo", type=int, default=30)
    a = ap.parse_args()
    p = obter(a.pleito)
    cli = Cliente(taxa=a.taxa)
    d = RAW / a.pleito / "indices"
    d.mkdir(parents=True, exist_ok=True)
    etags, linhas = {}, {}
    try:
        while True:
            t0, mudou = time.time(), 0
            for uf in UFS:
                st, corpo, etag = cli.get(p.url_cs(uf), etags.get(uf))
                if st == 200:
                    etags[uf] = etag
                    cs = json.loads(corpo)
                    (d / uf).mkdir(exist_ok=True)
                    (d / uf / f"{cs.get('idg', int(time.time()))}.json").write_bytes(corpo)
                    linhas[uf] = chegadas(cs, uf)
                    mudou += 1
                elif st == 404 and not linhas:
                    break   # antes da publicação: um 404 por rodada, não 28
            if mudou:
                t = pd.DataFrame([x for v in linhas.values() for x in v], columns=["uf", "municipio", "zona", "secao", "t"])
                t["t"] = pd.to_datetime(t.t, format="%d/%m/%Y %H:%M:%S")
                tmp = d / "chegadas.tmp.parquet"
                t.to_parquet(tmp, index=False)
                tmp.replace(d / "chegadas.parquet")
            print(f"{datetime.now():%H:%M:%S}  {mudou} índices novos; {sum(len(v) for v in linhas.values()):,} seções chegadas; "
                  f"{cli.contagem}", flush=True)
            time.sleep(max(5, a.intervalo - (time.time() - t0)))
    except Bloqueado as e:
        sys.exit(f"PARADO: {e}. Espere 10 minutos antes de tentar de novo.")


if __name__ == "__main__":
    main()
