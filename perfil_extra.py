"""Mais perfis de município, de dados públicos: para recortar o voto, não para prever.

Acrescenta colunas ao data/raw/ibge/municipios_BR.parquet (o mesmo arquivo dos quintis
do Censo), uma por variável, ligadas pelo código IBGE que ele já traz:

  bolsa_familia  % da população em famílias do Bolsa Família     MDS (VIS DATA), set/2026
  setor_publico  % do valor adicionado na administração pública  IBGE, PIB dos Municípios 2021 (tab. 5938)
  agro           % do valor adicionado na agropecuária           idem (2021: o último por setor na API)
  pib_pc         PIB per capita, R$                              PIB 2023 ÷ população do Censo 2022
  saneamento     % dos domicílios com esgoto em rede geral       Censo 2022 (tab. 6805)
  rural          % da população em situação rural                Censo 2022 (tab. 10211)
  populacao      habitantes                                      Censo 2022 (tab. 4714)

Funcionalismo público por município não existe no IBGE (o Cadastro Central de Empresas
por natureza jurídica só desce até UF; a RAIS só baixa pelo navegador): o peso da
administração pública no PIB do município faz esse papel, e o nome diz o que é.
IDH municipal oficial só existe para 2010 (Atlas Brasil, não baixável por script):
fica de fora.

    python perfil_extra.py
"""
import sys
from pathlib import Path

import pandas as pd
import requests

RAW = Path("data/raw")
ARQ = RAW / "ibge" / "municipios_BR.parquet"
API = "https://servicodados.ibge.gov.br/api/v3/agregados"
NOVAS = ["bolsa_familia", "setor_publico", "agro", "pib_pc", "saneamento", "rural", "populacao"]


def sidra(tabela, variaveis, periodo, classificacoes=""):
    """Uma tabela do IBGE por município (N6): DataFrame com cd (7 dígitos) e uma coluna por variável×categoria."""
    url = f"{API}/{tabela}/periodos/{periodo}/variaveis/{'|'.join(map(str, variaveis))}?localidades=N6[all]"
    if classificacoes:
        url += f"&classificacao={classificacoes}"
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    cols = {}
    for v in r.json():
        for res in v["resultados"]:
            cat = "_".join(str(k) for c in res["classificacoes"] for k in c["categoria"]) or "t"
            nome = f"v{v['id']}_{cat}"
            for s in res["series"]:
                x = s["serie"].get(str(periodo))
                # no IBGE, "-" é zero (nenhum morador rural, por exemplo); "..." e "X" seguem vazios
                cols.setdefault(nome, {})[s["localidade"]["id"]] = 0 if x == "-" else pd.to_numeric(x, errors="coerce")
    out = pd.DataFrame(cols)
    out.index.name = "cd"
    return out.reset_index().assign(cd=lambda d: d.cd.astype(int).astype("Int64"))


def bolsa_familia(anomes="202609"):
    url = ("https://aplicacoes.mds.gov.br/sagi/servicos/misocial?q=*:*&fq=anomes_s:" + anomes +
           "&fl=codigo_ibge,qtd_pessoas_beneficiarias_bolsa_familia_i,populacao_censo_2022_i&rows=6000&wt=json")
    docs = requests.get(url, timeout=120).json()["response"]["docs"]
    b = pd.DataFrame(docs)
    b["cd6"] = b.codigo_ibge.astype(int).astype("Int64")
    b["bolsa_familia"] = 100 * b.qtd_pessoas_beneficiarias_bolsa_familia_i / b.populacao_censo_2022_i
    print(f"Bolsa Família {anomes}: {len(b):,} municípios; {b.qtd_pessoas_beneficiarias_bolsa_familia_i.sum():,.0f} pessoas", flush=True)
    return b[["cd6", "bolsa_familia"]]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    m = pd.read_parquet(ARQ).drop(columns=NOVAS, errors="ignore")
    m["cd"] = pd.to_numeric(m.CD_MUN, errors="coerce").astype("Int64")   # Boa Esperança do Norte (MT) não tem: criado depois do Censo
    pib = sidra(5938, [37], 2023)
    # o valor adicionado por setor, por município, só vai até 2021 na API do IBGE (2022 e 2023 vêm "...")
    vab = sidra(5938, [498, 513, 525], 2021)
    pop = sidra(4714, [93], 2022)
    esg = sidra(6805, [381], 2022, "11558[46292,46290]")
    sit = sidra(10211, [93], 2022, "2661[32776]|1[6795,2]")
    t = pop.rename(columns={"v93_t": "populacao"})
    t = t.merge(pib, on="cd", how="left").merge(vab, on="cd", how="left").merge(esg, on="cd", how="left").merge(sit, on="cd", how="left")
    t["pib_pc"] = 1000 * t.v37_t / t.populacao                       # PIB em mil reais
    t["setor_publico"] = 100 * t.v525_t / t.v498_t
    t["agro"] = 100 * t.v513_t / t.v498_t
    t["saneamento"] = 100 * t.v381_46290 / t.v381_46292
    t["rural"] = 100 * t["v93_32776_2"] / t["v93_32776_6795"]
    t = t[["cd", "populacao", "pib_pc", "setor_publico", "agro", "saneamento", "rural"]]
    m = m.merge(t, on="cd", how="left")
    bf = bolsa_familia()
    m["cd6"] = m.cd // 10
    m = m.merge(bf, on="cd6", how="left").drop(columns=["cd", "cd6"])
    for v in NOVAS:
        print(f"{v:14s} {m[v].notna().sum():,}/{len(m):,} municípios; mediana {m[v].median():,.1f}; "
              f"5%–95% {m[v].quantile(.05):,.1f}–{m[v].quantile(.95):,.1f}", flush=True)
    m.to_parquet(ARQ, index=False)
    print(f"{ARQ}: {len(m):,} municípios, {len(m.columns)} colunas", flush=True)


if __name__ == "__main__":
    main()
