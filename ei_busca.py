"""Busca a variante da inferência ecológica que reproduz o comparecimento real por grupo.

O comparecimento por perfil é dado do TSE, e é a régua: método que erra ali não
vai para o voto. O modelo de base (voto do grupo variando por zona) errou até 10
pontos e inverteu a ordem da escolaridade (28/09/2026). As variantes:

  nível   em que o comportamento do grupo pode variar: zona (57) ou local de
          votação (~2.000). Por local, a comparação passa a ser entre seções da
          mesma escola — mesmo bairro, composições diferentes (o TSE numera as
          seções por ordem de inscrição) — e o bairro deixa de se misturar com o grupo.
  grupos  finos (6 idades, 4 escolaridades) ou juntos onde o modelo não separa
          (60+ inteiro; 3 escolaridades).

    python ei_busca.py
"""
import sys
import time

import numpy as np
import pandas as pd

import ei

JUNTOS = {
    "idade": {"60-69": "60+", "70+": "60+"},
    "escolaridade": {"fund. completo / médio incompleto": "fund. completo a sup. incompleto",
                     "médio completo / sup. incompleto": "fund. completo a sup. incompleto"},
}


def dados():
    v = pd.read_parquet("data/raw/2022/sp/votos.parquet")
    v = v[(v.cargo == "presidente") & (v.municipio == 71072)]
    s = v.drop_duplicates(["zona", "secao"]).set_index(["zona", "secao"])
    real = pd.read_parquet("data/raw/tse/comparecimento_2022_SP.parquet")
    real = real[(real.CD_MUNICIPIO == "71072") & (real.NR_TURNO == "1")]
    for c in ("QT_APTOS", "QT_COMPARECIMENTO"):
        real[c] = real[c].astype(int)
    return s, real


def rodar(s, real, var, nivel, juntar):
    comp = ei.composicao_secoes("2022", var)
    if juntar:
        comp = comp.T.groupby(lambda c: JUNTOS[var].get(c, c), sort=False).sum().T
    j = comp.join(s[["aptos", "comparecimento", "local"]], how="inner")
    z = j.index.get_level_values("zona").to_numpy()
    reg = z if nivel == "zona" else z * 100_000 + j.local.to_numpy()
    t = time.time()
    b = ei.ajustar(j[comp.columns].to_numpy(), np.c_[j.comparecimento, j.aptos - j.comparecimento],
                   reg, amostras=100).mean(0)
    real["g"] = ei.grupo_de(real, var)
    if juntar:
        real["g"] = real.g.map(lambda c: JUNTOS[var].get(c, c))
    rg = real.groupby("g")[["QT_APTOS", "QT_COMPARECIMENTO"]].sum()
    out = []
    for i, g in enumerate(comp.columns):
        r = 100 * rg.loc[g].QT_COMPARECIMENTO / rg.loc[g].QT_APTOS
        out.append({"variavel": var, "nivel": nivel, "grupos": "juntos" if juntar else "finos",
                    "grupo": g, "real": r, "estimado": 100 * b[i, 0]})
    # a ordem entre os grupos é o que mais importa: inverter é pior que errar o nível
    e = pd.DataFrame(out)
    ordem_ok = (e.real.rank() == e.estimado.rank()).all()
    print(f"{var:13s} {nivel:5s} {'juntos' if juntar else 'finos':6s} {time.time() - t:4.0f}s  "
          f"erro médio {np.abs(e.estimado - e.real).mean():5.2f}  máx {np.abs(e.estimado - e.real).max():5.2f}  "
          f"ordem {'ok' if ordem_ok else 'INVERTIDA'}", flush=True)
    for x in out:
        print(f"      {x['grupo']:34s} real {x['real']:5.1f}  estimado {x['estimado']:5.1f}", flush=True)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    s, real = dados()
    linhas = []
    for var in ("escolaridade", "idade"):
        for nivel in ("zona", "local"):
            for juntar in (False, True):
                linhas += rodar(s, real, var, nivel, juntar)
    r = pd.DataFrame(linhas)
    r["erro"] = r.estimado - r.real
    r.to_csv("out/busca_ei_comparecimento_2022.csv", index=False, float_format="%.2f")


if __name__ == "__main__":
    main()
