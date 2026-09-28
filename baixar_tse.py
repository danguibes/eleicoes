"""Baixa os arquivos-base do Portal de Dados Abertos do TSE e recorta um município.

O `cdn.tse.jus.br` devolve 403 a script a partir da máquina de casa (medido em
28/09/2026; do navegador baixa). Por isso este script foi feito para rodar no
GitHub Actions, que sai por outro IP, e devolver só o recorte — em Parquet, como
artefato. Nada aqui tenta disfarçar o script de navegador.

O CSV nunca é extraído: é lido em blocos direto de dentro do zip e filtrado pelo
município, então o arquivo de 4,7 GB do perfil de 2026 não precisa caber em disco.

    python baixar_tse.py                 # todos, UF de SP inteira
    python baixar_tse.py --municipio 71072   # só a capital
    python baixar_tse.py --so perfil_2022
    python baixar_tse.py --pasta "C:/Users/Danilo Bessa/Downloads"   # zips baixados à mão

**Medido em 28/09/2026: o Actions também toma 403.** O bloqueio não é pelo IP de
casa — o CDN recusa cliente que não é navegador. Então o caminho que funciona é
baixar os zips no navegador e rodar com `--pasta`.
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
    # 2018 é a base do ensaio da projeção: alvo 2022, na ordem real de chegada
    "votacao_2018": (f"{ODS}/votacao_secao/votacao_secao_2018_BR.zip",
                     "votacao_secao_2018_BR.csv", "CD_MUNICIPIO"),
    "locais_2018": (f"{ODS}/eleitorado_locais_votacao/eleitorado_local_votacao_2018.zip",
                    "eleitorado_local_votacao_2018.csv", "CD_MUNICIPIO"),
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


def recortar(zip_path, membro, coluna, valor, saida):
    """Grava em blocos: o perfil de 2026 do estado tem 18,7 milhões de linhas, e
    juntá-las antes de gravar pediu 4 GB e estourou a memória (medido)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    with zipfile.ZipFile(zip_path) as z:
        nomes = z.namelist()
        if membro not in nomes:
            sys.exit(f"{membro} não está no zip; há: {nomes[:40]}")
        escritor, lidas, gravadas = None, 0, 0
        with z.open(membro) as bruto:
            txt = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
            for bloco in pd.read_csv(txt, sep=";", dtype=str, chunksize=1_000_000):
                lidas += len(bloco)
                bloco = bloco[bloco[coluna] == valor]
                if bloco.empty:
                    continue
                if escritor is None:
                    # tudo texto: com esquema inferido, uma coluna vazia no 1º
                    # bloco viraria tipo nulo e os blocos seguintes falhariam
                    esquema = pa.schema([(c, pa.string()) for c in bloco.columns])
                    escritor = pq.ParquetWriter(saida, esquema)
                t = pa.Table.from_pandas(bloco, schema=escritor.schema, preserve_index=False)
                escritor.write_table(t.cast(escritor.schema))
                gravadas += len(bloco)
        if escritor:
            escritor.close()
    print(f"  {lidas:,} linhas lidas, {gravadas:,} de {coluna}={valor} -> {saida} "
          f"({saida.stat().st_size / 1e6:.1f} MB)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--municipio", help="código TSE; sem ele, recorta a UF inteira")
    ap.add_argument("--uf", default="SP")
    ap.add_argument("--so", nargs="*")
    ap.add_argument("--saida", default="data/raw/tse")
    ap.add_argument("--pasta", help="lê os zips já baixados daqui (ex.: a pasta Downloads) em vez de baixar")
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
        nome_zip = url.rsplit("/", 1)[1]
        if a.pasta:
            zp = Path(a.pasta) / nome_zip
            if not zp.exists():
                print(f"  falta {zp}; pulando", flush=True)
                continue
        else:
            zp = tmp / nome_zip
            if not zp.exists():
                baixar(url, zp)
        col, valor = (col, a.municipio) if a.municipio else ("SG_UF", a.uf)
        recortar(zp, membro, col, valor, out / f"{nome}_{valor}.parquet")
        if not a.pasta:
            zp.unlink()  # o runner tem ~14 GB; não acumula
        print(f"  {time.time() - t:.0f} s", flush=True)


if __name__ == "__main__":
    main()
