"""A que horas se votou: amostra de logs de urna do 2º turno de 2026 (e o 1º turno, no mesmo log).

O boletim só diz quando a urna fechou. O log da urna (`-log.jez`, um zip com `logd.dat`) registra
cada "O voto do eleitor foi computado" com data e hora — sem dizer em quem, claro. Cada log tem
~200 KB; o país inteiro passaria de 100 GB, então: amostra aleatória de seções com boletim do 2º
turno já baixado, proporcional ao número de seções de cada UF.

A hora do log é a LOCAL da urna. Todas abrem às 8h de Brasília, então o fuso de cada urna sai da
própria abertura (08:00 em Brasília, 07:00 no Amazonas, 06:00 no Acre).

    python hora_do_voto.py --n 2000
"""
import argparse
import io
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import tse

RAW = Path("data/raw")
SAIDA = RAW / "2026_2t" / "hora_do_voto"
VOTO = "O voto do eleitor foi computado"


def amostra(n, seed=0):
    tot = pd.read_parquet(RAW / "2026" / "secoes_1t_brasil.parquet", columns=["uf"]).uf.value_counts()
    tot = tot.drop("ZZ", errors="ignore")
    linhas = []
    for f in sorted(RAW.glob("2026_2t/*/secoes.jsonl")):
        uf = f.parent.name.upper()
        if uf == "ZZ":
            continue
        vis = {}
        for ln in open(f, encoding="utf-8"):
            s = json.loads(ln)
            vis[(s["zona"], s["secao"])] = s
        for s in vis.values():
            linhas.append({"uf": uf, "municipio": s["municipio"], "zona": s["zona"], "secao": s["secao"], "hash": s["hash"],
                           "abertura": s.get("abertura")})
    d = pd.DataFrame(linhas)
    rng = np.random.default_rng(seed)
    cota = (n * tot / tot.sum()).round().astype(int).clip(lower=10)   # proporcional, pelo menos 10 por UF
    partes = [g.sample(min(len(g), cota[uf]), random_state=int(rng.integers(1e9))) for uf, g in d.groupby("uf")]
    a = pd.concat(partes, ignore_index=True)
    a["peso"] = a.uf.map(tot) / a.uf.map(a.uf.value_counts())   # seções da UF que cada uma representa
    return a


def votos_do_log(conteudo):
    """(data, hora local) de cada voto computado no log."""
    z = zipfile.ZipFile(io.BytesIO(conteudo))
    t = z.read("logd.dat").decode("latin-1")
    out = []
    for l in t.splitlines():
        if VOTO in l:
            out.append(l[:19])   # "25/10/2026 17:03:12"
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--taxa", type=float, default=15)
    a_ = ap.parse_args()
    p = tse.obter("2026_2t")
    cli = tse.Cliente(taxa=a_.taxa, max_404=30)
    SAIDA.mkdir(parents=True, exist_ok=True)
    arq = SAIDA / "votos.jsonl"
    feitos = set()
    if arq.exists():
        for ln in open(arq, encoding="utf-8"):
            r = json.loads(ln)
            feitos.add((r["uf"], r["zona"], r["secao"]))
    a = amostra(a_.n)
    a.to_parquet(SAIDA / "amostra.parquet")
    falta = a[[(u, z, s) not in feitos for u, z, s in zip(a.uf, a.zona, a.secao)]]
    print(f"amostra de {len(a):,} seções; {len(falta):,} a baixar", flush=True)
    from concurrent.futures import ThreadPoolExecutor
    def um(r):
        uf = r.uf.lower(); mun, zona, sec = f"{r.municipio:05d}", f"{r.zona:04d}", f"{r.secao:04d}"
        nome = f"o{p.pleito:05d}{uf}{mun}{zona}{sec}-log.jez"
        st, b, _ = cli.get(p.url_arquivo(uf, mun, zona, sec, r.hash, nome))
        if st != 200:
            return {"uf": r.uf, "zona": int(r.zona), "secao": int(r.secao), "erro": st}
        return {"uf": r.uf, "municipio": int(r.municipio), "zona": int(r.zona), "secao": int(r.secao), "abertura": r.abertura,
                "votos": votos_do_log(b)}
    with open(arq, "a", encoding="utf-8") as f, ThreadPoolExecutor(8) as ex:
        for i, res in enumerate(ex.map(um, [r for r in falta.itertuples()]), 1):
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
            if i % 200 == 0:
                print(f"{datetime.now():%H:%M:%S}  {i:,}/{len(falta):,}  {cli.contagem}", flush=True)
    print("pronto", cli.contagem, flush=True)


if __name__ == "__main__":
    main()
