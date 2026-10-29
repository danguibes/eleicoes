"""Hora × tipo de habilitação, voto a voto, no 2º turno de 2026 (logs de urna).

Para cada voto computado no log, o tipo de habilitação do eleitor que votou ("Tipo de habilitação do
eleitor [biométrica]" e os outros), e a faixa de 15 minutos em hora de Brasília. Urnas: a amostra
aleatória (hora_do_voto.py) e todas as que fecharam depois das 17:15 (hora_do_voto_tardias.py).

Grava data/raw/2026_2t/hora_do_voto/habilitacao.jsonl: por urna, {faixa: {tipo: votos}}.

    python hora_biometria.py
"""
import io
import json
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tse
from hora_do_voto_analise import fuso, segundos

RAW = Path("data/raw")
D = RAW / "2026_2t" / "hora_do_voto"
SAIDA = D / "habilitacao.jsonl"
TIPO = re.compile(r"Tipo de habilitação do eleitor \[(.+?)\]")


def contar(texto, off):
    """{faixa 'HH:MM' (15 min, Brasília): {tipo: votos}}, do log do dia 25/10."""
    out, tipo = {}, "não biométrica"   # o log só escreve o tipo quando é biométrica
    for l in texto.splitlines():
        if not l.startswith("25/10/2026"):
            continue
        m = TIPO.search(l)
        if m:
            tipo = m.group(1)
            continue
        if "O voto do eleitor foi computado" in l:
            s = segundos(l[11:19]) + off
            f = s // 900 * 900
            k = f"{f // 3600:02d}:{f % 3600 // 60:02d}"
            out.setdefault(k, {}).setdefault(tipo, 0)
            out[k][tipo] += 1
            tipo = "não biométrica"
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = tse.obter("2026_2t")
    cli = tse.Cliente(taxa=15, max_404=30)
    alvo = {}
    for ln in open(D / "tardias.jsonl", encoding="utf-8"):
        r = json.loads(ln)
        alvo[(r["uf"], r["zona"], r["secao"])] = "tardia"
    import pandas as pd
    a = pd.read_parquet(D / "amostra.parquet")
    for u, z, s in zip(a.uf, a.zona, a.secao):
        alvo.setdefault((u, int(z), int(s)), "amostra")
    feitos = set()
    if SAIDA.exists():
        feitos = {(r["uf"], r["zona"], r["secao"]) for r in map(json.loads, open(SAIDA, encoding="utf-8"))}
    secs = {}
    for uf in {k[0] for k in alvo}:
        for ln in open(RAW / "2026_2t" / uf.lower() / "secoes.jsonl", encoding="utf-8"):
            try:
                s = json.loads(ln)
            except json.JSONDecodeError:
                continue
            k = (uf, s["zona"], s["secao"])
            if k in alvo:
                secs[k] = s
    fila = [(k, secs[k]) for k in alvo if k in secs and k not in feitos]
    print(f"{len(fila):,} logs a baixar ({sum(v == 'tardia' for v in alvo.values()):,} tardias, {sum(v == 'amostra' for v in alvo.values()):,} da amostra)", flush=True)

    def um(x):
        (uf, z, sec), s = x
        u = uf.lower()
        mun, zz, ss = f"{s['municipio']:05d}", f"{z:04d}", f"{sec:04d}"
        st, b, _ = cli.get(p.url_arquivo(u, mun, zz, ss, s["hash"], f"o{p.pleito:05d}{u}{mun}{zz}{ss}-log.jez"))
        r = {"uf": uf, "zona": z, "secao": sec, "grupo": alvo[(uf, z, sec)]}
        if st != 200:
            return {**r, "erro": st}
        t = zipfile.ZipFile(io.BytesIO(b)).read("logd.dat").decode("latin-1")
        return {**r, "faixas": contar(t, fuso(s["abertura"]) * 3600)}

    with open(SAIDA, "a", encoding="utf-8") as f, ThreadPoolExecutor(8) as ex:
        for i, r in enumerate(ex.map(um, fila), 1):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if i % 500 == 0:
                print(f"  {i:,}/{len(fila):,} {cli.contagem}", flush=True)
    print("pronto", cli.contagem, flush=True)


if __name__ == "__main__":
    main()
