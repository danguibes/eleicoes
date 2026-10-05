"""1º turno de 2026, Presidente, uma linha por seção do Brasil inteiro — dos boletins de urna.

É a base do 2º turno (cada seção comparada com ela mesma no 1º turno) e das
checagens de 2026. Sai de data/raw/2026/<uf>/secoes.jsonl (coletar_brasil.py e
coletor.py), com a hora de chegada do chegadas.csv de cada UF.

Teste de aceitação, como o do tabelar.py: a soma das seções de cada município tem
que bater voto a voto com o arquivo `u` do TSE (nacional.py). O que não bate é
seção sem boletim publicado — e fica contado.

    python base_secoes.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

RAW = Path("data/raw/2026")
NUM = {13: "lula", 22: "flavio", 70: "cury", 14: "renan", 55: "caiado", 30: "zema"}
COLS = list(NUM.values()) + ["outros", "branco", "nulo"]


def secoes_uf(uf):
    d = RAW / uf
    vistos = {}
    with open(d / "secoes.jsonl", encoding="utf-8") as f:
        for ln in f:
            s = json.loads(ln)
            vistos[(s["municipio"], s["zona"], s["secao"])] = s   # retransmitida: vale a última
    linhas = []
    for (mun, zona, secao), s in vistos.items():
        for e in s.get("eleicoes", []):
            for c in e["cargos"]:
                if c["cargo"] != "presidente":
                    continue
                r = {"uf": uf.upper(), "municipio": int(mun), "zona": int(zona), "secao": int(secao),
                     "local": s.get("local"), "aptos": e["aptos"], "comparecimento": c["comparecimento"],
                     **{k: 0 for k in COLS}}
                for tipo, codigo, n in c["votos"]:
                    if tipo in ("branco", "nulo"):
                        r[tipo] += n
                    else:
                        r[NUM.get(int(codigo), "outros")] += n
                linhas.append(r)
    t = pd.DataFrame(linhas)
    ch = d / "chegadas.csv"
    if ch.exists() and len(t):
        c = pd.read_csv(ch, dtype=str).drop_duplicates(["municipio", "zona", "secao"], keep="last")
        c = c.assign(municipio=c.municipio.astype(int), zona=c.zona.astype(int), secao=c.secao.astype(int),
                     recebido=pd.to_datetime(c.recebido, format="%d/%m/%Y %H:%M:%S", errors="coerce"))
        t = t.merge(c[["municipio", "zona", "secao", "recebido"]], on=["municipio", "zona", "secao"], how="left")
    return t


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cm = json.loads((RAW / "nacional" / "mun-cm.json").read_text(encoding="utf-8"))
    ufs = sorted(a["cd"] for a in cm["abr"])
    partes, faltam = [], []
    for uf in ufs:
        if not (RAW / uf / "secoes.jsonl").exists():
            faltam.append(uf)
            continue
        partes.append(secoes_uf(uf))
    s = pd.concat(partes, ignore_index=True)
    s["abst"] = (s.aptos - s.comparecimento).clip(lower=0)
    s.to_parquet(RAW / "secoes_1t_brasil.parquet", index=False)
    # aceitação: município a município contra o arquivo u
    u = pd.read_parquet(RAW / "nacional" / "municipios.parquet").set_index("municipio")
    g = s.groupby("municipio")[["lula", "flavio", "comparecimento"]].sum()
    c = g.join(u[["n13", "n22", "c", "uf"]], how="inner")
    exato = (c.lula == c.n13) & (c.flavio == c.n22) & (c.comparecimento == c.c)
    falta_votos = (c.n13 - c.lula).sum() + (c.n22 - c.flavio).sum()
    print(f"{len(s):,} seções de {s.uf.nunique()} UFs; UFs sem coleta: {faltam or 'nenhuma'}")
    print(f"aceitação: {exato.sum():,}/{len(c):,} municípios batem voto a voto com o TSE; "
          f"faltam {falta_votos:,.0f} votos de Lula+Flávio ({100 * falta_votos / (c.n13.sum() + c.n22.sum()):.2f}%), "
          f"das seções sem boletim publicado")
    print(c[~exato].groupby("uf").size().sort_values(ascending=False).head(10).to_string())


if __name__ == "__main__":
    main()
