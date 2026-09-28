"""Baixa os arquivos-base do Portal de Dados Abertos do TSE e recorta um município.

O `cdn.tse.jus.br` devolve 403 a script a partir da máquina de casa (medido em
28/09/2026; do navegador baixa). Por isso este script foi feito para rodar no
GitHub Actions, que sai por outro IP, e devolver só o recorte — em Parquet, como
artefato. Nada aqui tenta disfarçar o script de navegador.

O CSV nunca é extraído: é lido em blocos direto de dentro do zip e filtrado pelo
município, então o arquivo de 4,7 GB do perfil de 2026 não precisa caber em disco.

    python baixar_tse.py                 # todos, município 71072 (São Paulo)
    python baixar_tse.py --so perfil_2022
"""
import argparse
import io
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

ODS = "https://cdn.tse.jus.br/estatistica/sead/odsele"

# nome -> (url do zip, membro do zip que interessa, coluna do município)
# Nomes de arquivo e de coluna conferidos no cabeçalho real em 28/09/2026.
ARQUIVOS = {
    "perfil_2022": (f"{ODS}/perfil_eleitor_secao/perfil_eleitor_secao_2022_SP.zip",
                    "perfil_eleitor_secao_2022_SP.csv", "CD_MUNICIPIO"),
    "perfil_2026": (f"{ODS}/perfil_eleitor_secao/perfil_eleitor_secao_2026_SP.zip",
                    "perfil_eleitor_secao_2026_SP.csv", "CD_MUNICIPIO"),
    "locais_2022": (f"{ODS}/eleitorado_locais_votacao/eleitorado_local_votacao_2022.zip",
                    "eleitorado_local_votacao_2022.csv", "CD_MUNICIPIO"),
    "locais_2026": (f"{ODS}/eleitorado_locais_votacao/eleitorado_local_votacao_2026.zip",
                    "eleitorado_local_votacao_2026_SP.csv", "CD_MUNICIPIO"),
    # Presidente de 2022 por seção só existe no _BR; o _SP traz os cargos estaduais
    "votacao_2022": (f"{ODS}/votacao_secao/votacao_secao_2022_BR.zip",
                     "votacao_secao_2022_BR.csv", "CD_MUNICIPIO"),
    "detalhe_2022": (f"{ODS}/detalhe_votacao_secao/detalhe_votacao_secao_2022.zip",
                     "detalhe_votacao_secao_2022_BR.csv", "CD_MUNICIPIO"),
    "comparecimento_2022": (f"{ODS}/perfil_comparecimento_abstencao/perfil_comparecimento_abstencao_2022.zip",
                            "perfil_comparecimento_abstencao_2022_SP.csv", "CD_MUNICIPIO"),
}


def baixar(url, destino):
    with requests.get(url, stream=True, timeout=60) as r:
        if r.status_code != 200:
            sys.exit(f"{r.status_code} em {url}")
        total = int(r.headers.get("Content-Length", 0))
        with open(destino, "wb") as f:
            for bloco in r.iter_content(1 << 20):
                f.write(bloco)
    print(f"  baixado {destino.stat().st_size / 1e6:.0f} MB (anunciado {total / 1e6:.0f})", flush=True)


def recortar(zip_path, membro, coluna, municipio, saida):
    with zipfile.ZipFile(zip_path) as z:
        nomes = z.namelist()
        if membro not in nomes:
            sys.exit(f"{membro} não está no zip; há: {nomes[:40]}")
        partes, lidas = [], 0
        with z.open(membro) as bruto:
            txt = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
            for bloco in pd.read_csv(txt, sep=";", dtype=str, chunksize=1_000_000):
                lidas += len(bloco)
                partes.append(bloco[bloco[coluna] == municipio])
    df = pd.concat(partes, ignore_index=True)
    df.to_parquet(saida, index=False)
    print(f"  {lidas:,} linhas lidas, {len(df):,} do município -> {saida} "
          f"({saida.stat().st_size / 1e6:.1f} MB)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--municipio", default="71072")
    ap.add_argument("--so", nargs="*")
    ap.add_argument("--saida", default="data/raw/tse")
    a = ap.parse_args()
    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path("data/raw/zips")
    tmp.mkdir(parents=True, exist_ok=True)
    for nome, (url, membro, col) in ARQUIVOS.items():
        if a.so and nome not in a.so:
            continue
        print(f"{nome}: {url}", flush=True)
        t = time.time()
        zp = tmp / url.rsplit("/", 1)[1]
        if not zp.exists():
            baixar(url, zp)
        recortar(zp, membro, col, a.municipio, out / f"{nome}_{a.municipio}.parquet")
        zp.unlink()  # o runner tem ~14 GB; não acumula
        print(f"  {time.time() - t:.0f} s", flush=True)


if __name__ == "__main__":
    main()
