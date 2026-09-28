"""Perfil de cada município do Brasil pelo Censo 2022, para os filtros e quintis do painel nacional.

Fora de SP não há perfil do eleitorado (TSE) baixado, então tudo sai do Censo:

  renda         rendimento médio do responsável (setores, média ponderada pelos responsáveis)
  preta_parda   % de pretos e pardos entre moradores de 15+ (setores, cor × idade)
  idosos        % de 60+ entre moradores de 15+ (setores, demografia)
  catolicos, evangelicos, sem_religiao   % entre moradores de 10+ (amostra, Tab 4.1 por área
                de ponderação, somada por município)
  superior      % com superior completo entre moradores de 25+ (amostra, Tab 2.2, idem)

O código de município do IBGE não é o do TSE. A ligação é por UF + nome sem acento
e sem pontuação; o que não casa é contado e dito.

    python municipios_ibge.py
"""
import io
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw")
IBGE = RAW / "ibge"
UF_COD = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA",
          "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
          "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
          "51": "MT", "52": "GO", "53": "DF"}


def chave(nome):
    s = unicodedata.normalize("NFKD", str(nome).upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", s)


def setores(nome, cols):
    with zipfile.ZipFile(IBGE / nome) as z:
        txt = io.TextIOWrapper(z.open(z.namelist()[0]), encoding="latin-1", newline="")
        partes = []
        for bl in pd.read_csv(txt, sep=";", dtype=str, chunksize=300_000):
            bl.columns = [c.upper() if c.lower() == "cd_setor" else c for c in bl.columns]
            bl = bl[["CD_SETOR"] + cols]
            for c in cols:
                bl[c] = pd.to_numeric(bl[c].str.replace(",", ".", regex=False).replace("X", None), errors="coerce")
            partes.append(bl)
    d = pd.concat(partes, ignore_index=True)
    d["CD_MUN"] = d.CD_SETOR.str[:7]
    return d


def tabela_ap(nome_tab, colunas):
    with zipfile.ZipFile(IBGE / "tabelas_ap.zip") as z:
        m = next(n for n in z.namelist() if n.endswith(nome_tab))
        t = pd.read_excel(z.open(m), header=2, dtype=str)
    t = t.iloc[:, : 4 + len(colunas)]
    t.columns = ["CD_MUN", "NM_MUN", "CD_AP", "NM_AP"] + colunas
    t = t[t.CD_MUN.str.fullmatch(r"\d{7}", na=False)]
    for c in colunas:
        t[c] = pd.to_numeric(t[c].replace("-", "0"), errors="coerce").fillna(0)
    return t.groupby("CD_MUN")[colunas].sum()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ren = setores("renda.zip", ["V06001", "V06004"])
    ren["rx"] = ren.V06001.fillna(0) * ren.V06004.fillna(0)
    ren["r"] = ren.V06001.where(ren.V06004.notna(), 0).fillna(0)
    g = ren.groupby("CD_MUN")[["rx", "r"]].sum()
    out = pd.DataFrame({"renda": g.rx / g.r.replace(0, np.nan)})
    cor = setores("cor_ou_raca.zip", [f"V{i:05d}" for i in range(1377, 1392)])
    c = cor.groupby("CD_MUN").sum(numeric_only=True)
    pp = c[["V01378", "V01383", "V01388", "V01380", "V01385", "V01390"]].sum(axis=1)
    out["preta_parda"] = 100 * pp / c.sum(axis=1)
    dem = setores("demografia.zip", [f"V{i:05d}" for i in range(1034, 1042)])
    d = dem.groupby("CD_MUN").sum(numeric_only=True)
    out["idosos"] = 100 * (d.V01040 + d.V01041) / d.sum(axis=1)
    # 15 a 24 entre os de 15+: o Censo agrupa os 15 anos junto; o eleitorado começa aos 16
    out["jovens"] = 100 * (d.V01034 + d.V01035) / d.sum(axis=1)
    rel = tabela_ap("Tab4_1.xlsx", ["total", "catolica", "evangelica", "espirita", "umbanda", "indigena",
                                    "outras", "sem_religiao", "nao_sabe", "sem_declaracao"])
    out["catolicos"] = 100 * rel.catolica / rel.total
    out["evangelicos"] = 100 * rel.evangelica / rel.total
    out["sem_religiao"] = 100 * rel.sem_religiao / rel.total
    ins = tabela_ap("Tab2_2.xlsx", ["total", "fund_inc", "fund_comp", "medio_comp", "superior"])
    out["superior"] = 100 * ins.superior / ins.total
    out["populacao"] = d.sum(axis=1)
    # nome do município pelo básico, para casar com o TSE
    with zipfile.ZipFile(IBGE / "basico.zip") as z:
        b = pd.read_csv(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="latin-1"), sep=";", dtype=str,
                        usecols=["CD_MUN", "NM_MUN", "CD_UF"]).drop_duplicates("CD_MUN").set_index("CD_MUN")
    out = out.join(b, how="left")
    out["uf"] = out.CD_UF.map(UF_COD)
    out["k"] = out.uf + "|" + out.NM_MUN.map(chave)
    tse = pd.read_parquet(RAW / "tse" / "locais_2026_BR.parquet", columns=["SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO"])
    tse = tse[tse.SG_UF != "ZZ"].drop_duplicates("CD_MUNICIPIO")
    tse["k"] = tse.SG_UF + "|" + tse.NM_MUNICIPIO.map(chave)
    casa = tse.merge(out.reset_index(), on="k", how="left")
    # grafias diferentes entre TSE e IBGE, conferidas uma a uma em 28/09/2026 (par mais
    # parecido na mesma UF + conferência do código). Boa Esperança do Norte (MT) foi
    # criado depois do Censo 2022 e fica sem perfil, de propósito.
    ALIAS = {"BA|UNA": "2932507", "GO|BOMJESUS": "5203500", "MG|SAOTHOMEDASLETRAS": "3165206",
             "MG|BARAODEMONTEALTO": "3105509", "MG|DONAEUSEBIA": "3122900",
             "MT|SANTOANTONIODOLEVERGER": "5107800", "PA|ELDORADODOSCARAJAS": "1502954",
             "PR|MUNHOZDEMELLO": "4116307", "RN|ASSU": "2400208", "RN|AREZ": "2401206",
             "RN|BOASAUDE": "2405306", "RO|ESPIGAODOOESTE": "1100098", "RO|ALVORADADOOESTE": "1100346",
             "SE|AMPARODESAOFRANCISCO": "2800100", "SP|SAOLUISDOPARAITINGA": "3550001"}
    sem = casa.CD_MUN.isna() & casa.k.isin(ALIAS)
    if sem.any():
        o2 = out.reset_index()
        pares = casa.loc[sem, ["k"]].assign(CD_MUN=lambda x: x.k.map(ALIAS)).merge(o2.drop(columns="k"), on="CD_MUN")
        casa = pd.concat([casa[~sem], tse[tse.k.isin(pares.k)].merge(pares, on="k")], ignore_index=True)
    falta = casa[casa.CD_MUN.isna()]
    print(f"municípios TSE {len(tse):,}; casados com o IBGE {casa.CD_MUN.notna().sum():,}; "
          f"sem par: {len(falta)}", flush=True)
    if len(falta):
        print("   ", falta[["SG_UF", "NM_MUNICIPIO"]].head(40).to_string(index=False))
    casa["municipio"] = casa.CD_MUNICIPIO.astype(int)
    cols = ["municipio", "CD_MUN", "renda", "catolicos", "evangelicos", "sem_religiao", "preta_parda",
            "superior", "jovens", "idosos", "populacao"]
    casa[cols].to_parquet(IBGE / "municipios_BR.parquet", index=False)
    print(casa[cols[2:]].describe().round(1).to_string())


if __name__ == "__main__":
    main()
