"""O voto real das urnas, agrupado pelo perfil do lugar — sem inferência.

A inferência ecológica não passou na régua para escolaridade, e renda, cor e
religião nem têm régua (o TSE não publica comparecimento por elas). Então a
pergunta muda: não "como votaram os evangélicos", mas **"como votaram as urnas
dos lugares com mais evangélicos"**. É dado, não estimativa — e a diferença vai
escrita em cada gráfico.

Cada seção ganha um valor em cada variável e cai num quintil (cinco grupos com o
mesmo número de votantes); a votação do quintil é a soma real das suas urnas.

  superior       % de eleitores com superior completo NA SEÇÃO (TSE)
  preta_parda    % de pretos e pardos entre moradores de 15+ no entorno (Censo 2022)
  renda          rendimento médio do responsável pelo domicílio no entorno (Censo 2022)
  evangelicos    % de evangélicos entre moradores de 10+ no entorno (Censo 2022,
                 amostra, por área de ponderação — o recorte mais fino publicado)
  idosos         % de eleitores com 60+ na seção (TSE)

Entorno = setores num raio de 1,5 km do local de votação, peso exp(−d/600 m) —
o método que casou melhor idade e sexo entre TSE e Censo (casamento.py, r=0,59).

    python bairros.py
"""
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

import casamento as cz

PRETA = ["V01378", "V01383", "V01388"]
PARDA = ["V01380", "V01385", "V01390"]
ADULTOS = [f"V{i:05d}" for i in range(1377, 1392)]  # 15+ por cor
CATS = {13: "lula", 22: "bolsonaro", 15: "tebet", 12: "ciro"}


def entorno_locais(ano="2022", mun="71072", mun_ibge="3550308"):
    locais, _ = cz.carregar_locais(ano, "SP", mun)
    locais = gpd.GeoDataFrame(locais, geometry=gpd.points_from_xy(locais.lon, locais.lat),
                              crs=4674).to_crs(cz.UTM)
    locais["x"], locais["y"] = locais.geometry.x, locais.geometry.y
    st = cz.carregar_setores("35", mun_ibge)
    rel = pd.read_parquet("data/raw/ibge/religiao_ap_35.parquet").set_index("CD_AP")
    st["evang_share"] = st.CD_AP.map(rel.evangelica / rel.total).fillna(0)
    st["evang"] = st.evang_share * st.V01006          # aproximação: aplica a parcela da área ao setor
    st["catol"] = st.CD_AP.map(rel.catolica / rel.total).fillna(0) * st.V01006
    st["semrel"] = st.CD_AP.map(rel.sem_religiao / rel.total).fillna(0) * st.V01006
    st["renda_x_resp"] = st.V06004.fillna(0) * st.V06001.fillna(0)
    st["resp"] = st.V06001.where(st.V06004.notna(), 0).fillna(0)
    st["preta"] = st[PRETA].sum(axis=1)
    st["parda"] = st[PARDA].sum(axis=1)
    st["adultos"] = st[ADULTOS].sum(axis=1)
    w = cz.pesos("raio", locais, st, raio=1500, h=600)
    e = cz.entorno(w, st, ["preta", "parda", "adultos", "evang", "catol", "semrel", "V01006", "renda_x_resp", "resp"])
    out = locais.loc[e.index, ["NR_ZONA", "NR_LOCAL_VOTACAO"]].copy()
    out["preta_parda"] = 100 * (e.preta + e.parda) / e.adultos
    out["renda"] = e.renda_x_resp / e.resp
    out["evangelicos"] = 100 * e.evang / e.V01006
    out["catolicos"] = 100 * e.catol / e.V01006
    out["sem_religiao"] = 100 * e.semrel / e.V01006
    out["zona"] = out.NR_ZONA.astype(int)
    out["local"] = out.NR_LOCAL_VOTACAO.astype(int)
    return out[["zona", "local", "preta_parda", "renda", "evangelicos", "catolicos", "sem_religiao"]]


def perfil_tse(ano="2022"):
    import projecao
    p = projecao.perfil_secoes(ano, "71072")
    p["superior"] *= 100
    p["idosos"] = 100 * p.idoso
    return p[["zona", "secao", "superior", "idosos"]]


def quintis(tab, var, cats):
    t = tab.dropna(subset=[var]).sort_values(var)
    acum = t.comparecimento.cumsum() / t.comparecimento.sum()
    t["q"] = np.minimum((acum * 5).clip(lower=1e-9).apply(np.ceil), 5).astype(int)
    linhas = []
    validos = [c for c in cats if c != "bn"]
    for q, g in t.groupby("q"):
        s = g[validos].sum()
        linhas.append({"variavel": var, "quintil": int(q), "de": float(g[var].min()),
                       "ate": float(g[var].max()), "secoes": len(g),
                       "comparecimento": float(g.comparecimento.sum() / g.aptos.sum() * 100),
                       **{c: float(s[c] / s.sum() * 100) for c in validos}})
    return linhas


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    import projecao
    t, cats = projecao.alvo_bu("2022", CATS, 71072)
    t = t.merge(perfil_tse(), on=["zona", "secao"], how="left")
    t = t.merge(entorno_locais(), on=["zona", "local"], how="left")
    print(f"seções {len(t):,}; sem entorno do Censo: {t.renda.isna().sum()}", flush=True)
    linhas = []
    for var in ["superior", "renda", "preta_parda", "catolicos", "evangelicos", "sem_religiao", "idosos"]:
        linhas += quintis(t, var, cats)
    r = pd.DataFrame(linhas)
    r.to_csv("out/quintis_2022.csv", index=False, float_format="%.2f")
    # religião dentro da mesma renda: o quadro geral mistura religião com renda
    t2 = t.dropna(subset=["renda"]).copy()
    t2["q_renda"] = pd.qcut(t2.renda.rank(method="first"), 5, labels=False) + 1
    cruz = []
    for rel in ["catolicos", "evangelicos", "sem_religiao"]:
        for q, g in t2.groupby("q_renda"):
            g = g.copy()
            g["terco"] = pd.qcut(g[rel].rank(method="first"), 3, labels=["menos", "meio", "mais"])
            for tc, h in g.groupby("terco", observed=True):
                v = h[["lula", "bolsonaro", "tebet", "ciro", "outros"]].sum()
                cruz.append({"religiao": rel, "renda": int(q), "terco": tc, "media": h[rel].mean(),
                             "lula": 100 * v.lula / v.sum(), "bolsonaro": 100 * v.bolsonaro / v.sum()})
    pd.DataFrame(cruz).to_csv("out/renda_x_religiao_2022.csv", index=False, float_format="%.2f")
    for var, g in r.groupby("variavel", sort=False):
        print(f"\n{var}")
        print(g[["quintil", "de", "ate", "secoes", "comparecimento", "lula", "bolsonaro"]]
              .round(1).to_string(index=False))


if __name__ == "__main__":
    main()
