"""Malha dos municípios e UFs do Brasil em caminhos SVG já projetados, para o mapa do painel.

Fonte: API de malhas do IBGE, qualidade mínima (servicodados.ibge.gov.br/api/v3/malhas).
Sem ladrilhos de mapa de fundo: o Thomas usa os do OpenStreetMap, e a política deles
pede provedor próprio para tráfego alto — numa noite de eleição, é o caso.

Projeção equiretangular com a longitude encolhida por cos(15°S), coordenadas
relativas (comando `l`) com uma casa decimal: o arquivo sai uma fração do GeoJSON.
Cada município é chaveado pelo código do TSE (a ligação IBGE↔TSE é a do
municipios_ibge.py).

    python mapa.py
"""
import json
import math
import sys
from pathlib import Path

import pandas as pd
import requests

RAW = Path("data/raw/ibge")
WEB = Path("web/dados")
API = "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
LARG = 1000.0
LON0, LAT0 = -74.0, 5.3
KX = math.cos(math.radians(15))


def baixar(nivel):
    arq = RAW / f"malha_{nivel}_BR.json"
    if not arq.exists():
        r = requests.get(API, params={"formato": "application/vnd.geo+json", "qualidade": "minima",
                                      "intrarregiao": {"municipios": "municipio", "ufs": "UF"}[nivel]}, timeout=120)
        r.raise_for_status()
        arq.write_bytes(r.content)
    return json.loads(arq.read_text(encoding="utf-8"))


ESC = LARG / ((-34.7 - LON0) * KX)


def proj(lon, lat):
    return (lon - LON0) * KX * ESC, (LAT0 - lat) * ESC


def caminho(geom):
    polis = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    partes = []
    for poli in polis:
        for anel in poli:
            pts = [proj(*p) for p in anel]
            x0, y0 = pts[0]
            s = [f"M{x0:.1f} {y0:.1f}"]
            px, py = round(x0, 1), round(y0, 1)
            rel = []
            for x, y in pts[1:]:
                x, y = round(x, 1), round(y, 1)
                dx, dy = round(x - px, 1), round(y - py, 1)
                if dx or dy:
                    rel.append(f"{dx:g} {dy:g}")
                px, py = x, y
            partes.append(s[0] + "l" + " ".join(rel) + "z")
    return "".join(partes)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    mun = baixar("municipios")
    ufs = baixar("ufs")
    liga = pd.read_parquet(RAW / "municipios_BR.parquet", columns=["municipio", "CD_MUN"]).dropna()
    ibge_tse = dict(zip(liga.CD_MUN.astype(str), liga.municipio.astype(int)))
    UF = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA",
          "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
          "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
          "51": "MT", "52": "GO", "53": "DF"}
    saida = {"w": LARG, "h": round((LAT0 + 33.8) * ESC, 1), "mun": {}, "uf": {}}
    sem = 0
    for f in mun["features"]:
        cod = f["properties"]["codarea"]
        t = ibge_tse.get(cod)
        if t is None:
            sem += 1
            continue
        saida["mun"][str(t)] = caminho(f["geometry"])
    for f in ufs["features"]:
        saida["uf"][UF[f["properties"]["codarea"]]] = caminho(f["geometry"])
    WEB.mkdir(parents=True, exist_ok=True)
    arq = WEB / "mapa_br.json"
    arq.write_text(json.dumps(saida, separators=(",", ":")), encoding="utf-8")
    print(f"{arq}: {arq.stat().st_size / 1e6:.2f} MB; {len(saida['mun']):,} municípios, {len(saida['uf'])} UFs; "
          f"sem código do TSE: {sem}")


if __name__ == "__main__":
    main()
