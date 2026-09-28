"""Baixa o Censo 2022 por setor censitário e a religião por área de ponderação, e recorta uma UF.

O FTP do IBGE aceita script (diferente do CDN do TSE). Nomes de arquivo e
códigos de variável conferidos na listagem do FTP e no dicionário em 28/09/2026.

Por setor (resultados do universo):
  - demografia   V01006 total, V01007 homens, V01008 mulheres; V01009–V01019
                 homens e V01020–V01030 mulheres por faixa (0-4 … 70+);
                 V01031–V01041 ambos os sexos
  - cor ou raça  V01317 branca, V01318 preta, V01319 amarela, V01320 parda,
                 V01321 indígena (a ordem é essa: amarela antes de parda);
                 V01372–V01391 cor × idade (0-14, 15-29, 30-59, 60+) — é daqui
                 que sai a cor da população adulta, a que vota
  - alfabetização V00644–V00656 pessoas de 15+ por faixa; V00748–V00760
                 alfabetizadas por faixa. Escolaridade por setor NÃO existe.
  - renda        V06001 responsáveis, V06004 rendimento médio do responsável,
                 V06006 mediana. Só média e mediana — sem faixas.
Religião: só na amostra, e o menor recorte público é a área de ponderação
(Tab4_1). A correspondência setor → área é exata.

Valor sigiloso vem como "X" e vira nulo.

    python baixar_ibge.py            # UF 35 (SP)
"""
import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

FTP = "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022"
AGR = f"{FTP}/Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv"
GEO = "https://geoftp.ibge.gov.br"

FONTES = {
    "basico.zip": f"{AGR}/Agregados_por_setores_basico_BR_20260520.zip",
    "demografia.zip": f"{AGR}/Agregados_por_setores_demografia_BR.zip",
    "cor_ou_raca.zip": f"{AGR}/Agregados_por_setores_cor_ou_raca_BR.zip",
    "alfabetizacao.zip": f"{AGR}/Agregados_por_setores_alfabetizacao_BR.zip",
    "renda.zip": f"{FTP}/Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/"
                 "Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip",
    "tabelas_ap.zip": f"{FTP}/Microdados_e_Areas_de_Ponderacao/Areas_de_Ponderacao/tabelas_xlsx.zip",
    "setores_SP.gpkg": f"{FTP}/Agregados_por_Setores_Censitarios/malha_com_atributos/setores/"
                       "gpkg/UF/SP/SP_setores_CD2022.gpkg",
    "depara_ap_SP.csv": f"{GEO}/recortes_para_fins_estatisticos/malha_de_areas_de_ponderacao/"
                        "censo_demografico_2022/DePara_SetorCensit22xAPOND22/CSV/"
                        "DePara_SetorCensit22xAPOND22_35_SP.csv",
    "ap_SP.gpkg": f"{GEO}/recortes_para_fins_estatisticos/malha_de_areas_de_ponderacao/"
                  "censo_demografico_2022/APONDs2022_Geometrias/APONDs2022_35_SP.gpkg",
}


def faixa(pre, a, b):
    return [f"{pre}{i:05d}" for i in range(a, b + 1)]


VARIAVEIS = {
    "demografia.zip": faixa("V", 1006, 1041),
    "cor_ou_raca.zip": faixa("V", 1317, 1321) + faixa("V", 1372, 1391),
    "alfabetizacao.zip": faixa("V", 644, 656) + faixa("V", 748, 760),
    "renda.zip": faixa("V", 6001, 6006),
}


def baixar(nome, raw):
    p = raw / nome
    if not p.exists():
        print(f"baixando {nome}", flush=True)
        with requests.get(FONTES[nome], stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(p, "wb") as f:
                for b in r.iter_content(1 << 20):
                    f.write(b)
    return p


def ler_setores(zp, uf, colunas=None):
    """Lê o CSV de dentro do zip em blocos, ficando só com os setores da UF."""
    with zipfile.ZipFile(zp) as z:
        membro = z.namelist()[0]
        with z.open(membro) as bruto:
            txt = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
            partes = []
            for bl in pd.read_csv(txt, sep=";", dtype=str, chunksize=200_000):
                bl.columns = [c.upper() if c.lower() == "cd_setor" else c for c in bl.columns]
                bl = bl[bl["CD_SETOR"].str.startswith(uf)]
                if colunas:
                    bl = bl[["CD_SETOR"] + colunas]
                partes.append(bl)
    return pd.concat(partes, ignore_index=True)


def numerico(df, colunas):
    for c in colunas:
        df[c] = pd.to_numeric(df[c].str.replace(",", ".", regex=False).replace("X", None),
                              errors="coerce")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uf", default="35")
    a = ap.parse_args()
    raw = Path("data/raw/ibge")
    raw.mkdir(parents=True, exist_ok=True)
    for nome in FONTES:
        baixar(nome, raw)

    base = ler_setores(raw / "basico.zip", a.uf)
    base = base[["CD_SETOR", "SITUACAO", "CD_MUN", "NM_MUN", "CD_DIST", "NM_DIST",
                 "AREA_KM2", "v0001", "v0002"]].rename(columns={"v0001": "pessoas",
                                                                 "v0002": "domicilios"})
    base = numerico(base, ["AREA_KM2", "pessoas", "domicilios"])
    for nome, cols in VARIAVEIS.items():
        t = numerico(ler_setores(raw / nome, a.uf, cols), cols)
        base = base.merge(t, on="CD_SETOR", how="left")
        print(f"{nome}: {len(t):,} setores", flush=True)
    dp = pd.read_csv(raw / "depara_ap_SP.csv", sep=";", dtype=str, encoding="utf-8-sig")
    base = base.merge(dp.rename(columns={"cd_apond": "CD_AP"}), on="CD_SETOR", how="left")
    print(f"setores {len(base):,}; sem área de ponderação: {base.CD_AP.isna().sum()}")
    base.to_parquet(raw / f"setores_{a.uf}.parquet", index=False)

    with zipfile.ZipFile(raw / "tabelas_ap.zip") as z:
        m = next(n for n in z.namelist() if n.endswith("Tab4_1.xlsx"))
        rel = pd.read_excel(z.open(m), header=2, dtype=str)
    rel.columns = ["CD_MUN", "NM_MUN", "CD_AP", "NM_AP", "total", "catolica", "evangelica",
                   "espirita", "umbanda_candomble", "tradicoes_indigenas", "outras",
                   "sem_religiao", "nao_sabe", "sem_declaracao"]
    rel = rel[rel.CD_AP.str.startswith(a.uf, na=False)]
    num = rel.columns[4:]
    # "-" é zero ou valor suprimido; tratamos como zero e registramos quantos
    print(f"religião: {len(rel)} áreas; células '-': {(rel[num] == '-').sum().sum()}")
    rel[num] = rel[num].replace("-", "0").apply(pd.to_numeric)
    rel.to_parquet(raw / f"religiao_ap_{a.uf}.parquet", index=False)


if __name__ == "__main__":
    main()
