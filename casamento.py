"""Casa cada local de votação com a população do entorno (setores do Censo 2022).

O eleitor não vota necessariamente onde mora, então isto é uma aproximação — e
por isso não se escolhe o método: mede-se. A régua é o que as duas bases têm em
comum. O TSE diz a idade e o sexo de quem está inscrito em cada local; o Censo
diz a idade e o sexo de quem mora em volta. O método que casar melhor essas duas
distribuições é o que usamos para as variáveis que só o Censo tem (cor, renda,
alfabetização, religião).

Dois métodos:

  voronoi  cada setor vai inteiro para o local mais próximo do seu centroide
           (é o diagrama de Voronoi dos locais, avaliado nos centroides). Nenhum
           setor é contado duas vezes; locais vizinhos não se sobrepõem.
  raio     cada local pega todos os setores num raio R, com peso que cai com a
           distância (exp(-d/h)) — o método da Folha nas "ilhas ideológicas".
           Locais vizinhos se sobrepõem, o que suaviza.

A distância é medida em SIRGAS 2000 / UTM 23S (EPSG:31983), em metros.

    python casamento.py --ano 2022 --uf SP --mun 71072
"""
import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

RAW = Path("data/raw")
UTM = 31983

# Faixas comuns às duas bases. O Censo começa em 15-19 e o TSE em 16; a faixa
# mais nova do Censo é reduzida a 4/5 (16-19) — aproximação registrada.
FAIXAS = ["16-19", "20-24", "25-29", "30-39", "40-49", "50-59", "60-69", "70+"]
CENSO_IDADE = {  # ambos os sexos
    "16-19": ["V01034"], "20-24": ["V01035"], "25-29": ["V01036"], "30-39": ["V01037"],
    "40-49": ["V01038"], "50-59": ["V01039"], "60-69": ["V01040"], "70+": ["V01041"],
}
CENSO_HOMENS_ADULTOS = [f"V{i:05d}" for i in range(1012, 1020)]   # 15+ masculino
CENSO_MULHERES_ADULTAS = [f"V{i:05d}" for i in range(1023, 1031)]  # 15+ feminino


def faixa_tse(ds):
    """Converte DS_FAIXA_ETARIA do TSE ('16 anos', '21 a 24 anos', '100 anos ou mais')."""
    ds = str(ds).strip().lower()
    if not ds or ds.startswith("inv"):
        return None
    ini = int(ds.split()[0])
    if ini < 16:
        return None
    for f, (a, b) in {"16-19": (16, 19), "20-24": (20, 24), "25-29": (25, 29),
                      "30-39": (30, 39), "40-49": (40, 49), "50-59": (50, 59),
                      "60-69": (60, 69)}.items():
        if a <= ini <= b:
            return f
    return "70+"


def carregar_locais(ano, uf, mun):
    loc = pd.read_parquet(RAW / "tse" / f"locais_{ano}_{uf}.parquet")
    loc = loc[loc.CD_MUNICIPIO == mun]
    if "NR_TURNO" in loc:
        loc = loc[loc.NR_TURNO == "1"]
    for c in ("NR_LATITUDE", "NR_LONGITUDE"):
        loc[c] = pd.to_numeric(loc[c].str.replace(",", ".", regex=False), errors="coerce")
    loc["QT_ELEITOR_SECAO"] = pd.to_numeric(loc.QT_ELEITOR_SECAO, errors="coerce")
    g = (loc.groupby(["NR_ZONA", "NR_LOCAL_VOTACAO"])
         .agg(lat=("NR_LATITUDE", "first"), lon=("NR_LONGITUDE", "first"),
              nome=("NM_LOCAL_VOTACAO", "first"), bairro=("NM_BAIRRO", "first"),
              eleitores=("QT_ELEITOR_SECAO", "sum"), secoes=("NR_SECAO", "nunique"))
         .reset_index())
    sem = (g.lat == -1) | g.lat.isna()
    print(f"locais: {len(g)}; sem coordenada (-1/-1): {sem.sum()} "
          f"({g.eleitores[sem].sum():,} eleitores)")
    return g[~sem].reset_index(drop=True), g[sem]


def carregar_setores(uf_ibge, cd_mun_ibge):
    st = pd.read_parquet(RAW / "ibge" / f"setores_{uf_ibge}.parquet")
    st = st[st.CD_MUN == cd_mun_ibge]
    geo = gpd.read_file(RAW / "ibge" / f"setores_{uf_ibge_sigla(uf_ibge)}.gpkg",
                        columns=["CD_SETOR"], where=f"CD_MUN = '{cd_mun_ibge}'")
    geo = geo.to_crs(UTM)
    geo["x"] = geo.geometry.centroid.x
    geo["y"] = geo.geometry.centroid.y
    st = st.merge(geo[["CD_SETOR", "x", "y"]], on="CD_SETOR", how="inner")
    return st[st.V01006.fillna(0) > 0].reset_index(drop=True)


def uf_ibge_sigla(cod):
    return {"35": "SP"}[cod]


def pesos(metodo, locais, setores, raio=1500, h=600):
    """Matriz esparsa em formato longo: (i_local, i_setor, peso). Para cada setor
    os pesos somam 1 entre os locais que o recebem (ninguém mora em dobro)."""
    xy_l = np.c_[locais.x, locais.y]
    xy_s = np.c_[setores.x, setores.y]
    if metodo == "voronoi":
        _, i = cKDTree(xy_l).query(xy_s)
        return pd.DataFrame({"l": i, "s": np.arange(len(setores)), "w": 1.0})
    arv = cKDTree(xy_s)
    linhas = []
    for li, viz in enumerate(arv.query_ball_point(xy_l, r=raio)):
        if not viz:
            continue
        d = np.hypot(*(xy_s[viz] - xy_l[li]).T)
        linhas.append(pd.DataFrame({"l": li, "s": viz, "w": np.exp(-d / h)}))
    w = pd.concat(linhas, ignore_index=True)
    w["w"] /= w.groupby("s").w.transform("sum")
    return w


def entorno(w, setores, colunas):
    """Soma ponderada das colunas do Censo para cada local."""
    v = setores[colunas].to_numpy(float)[w.s.to_numpy()] * w.w.to_numpy()[:, None]
    return (pd.DataFrame(v, columns=colunas).assign(l=w.l.to_numpy())
            .groupby("l").sum())


def perfil_tse_por_local(ano, uf, mun):
    p = pd.read_parquet(RAW / "tse" / f"perfil_{ano}_{uf}.parquet",
                        columns=["CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO",
                                 "DS_GENERO", "DS_FAIXA_ETARIA",
                                 "QT_ELEITORES_PERFIL" if ano == "2022" else "QT_ELEITORES"])
    p = p[p.CD_MUNICIPIO == mun].rename(columns={"QT_ELEITORES_PERFIL": "n", "QT_ELEITORES": "n"})
    p["n"] = pd.to_numeric(p.n)
    p["faixa"] = p.DS_FAIXA_ETARIA.map(faixa_tse)
    idade = (p.dropna(subset=["faixa"]).pivot_table(index=["NR_ZONA", "NR_LOCAL_VOTACAO"],
                                                     columns="faixa", values="n", aggfunc="sum")
             .reindex(columns=FAIXAS).fillna(0))
    sexo = p.pivot_table(index=["NR_ZONA", "NR_LOCAL_VOTACAO"], columns="DS_GENERO",
                         values="n", aggfunc="sum").fillna(0)
    idade["fem"] = sexo.get("FEMININO", 0) / sexo.sum(axis=1)
    return idade


def avaliar(metodo, locais, setores, tse, **kw):
    w = pesos(metodo, locais, setores, **kw)
    cols = sum(CENSO_IDADE.values(), []) + CENSO_HOMENS_ADULTOS + CENSO_MULHERES_ADULTAS
    e = entorno(w, setores, cols)
    ce = pd.DataFrame({f: e[c].sum(axis=1) for f, c in CENSO_IDADE.items()})
    ce["16-19"] *= 0.8
    ce["fem"] = e[CENSO_MULHERES_ADULTAS].sum(axis=1) / (
        e[CENSO_MULHERES_ADULTAS].sum(axis=1) + e[CENSO_HOMENS_ADULTOS].sum(axis=1))
    ce.index = pd.MultiIndex.from_frame(locais.loc[ce.index, ["NR_ZONA", "NR_LOCAL_VOTACAO"]])
    j = tse.join(ce, lsuffix="_tse", rsuffix="_censo", how="inner")
    a = j[[f"{f}_tse" for f in FAIXAS]].to_numpy()
    b = j[[f"{f}_censo" for f in FAIXAS]].to_numpy()
    a = a / a.sum(1, keepdims=True)
    b = b / b.sum(1, keepdims=True)
    vt = 0.5 * np.abs(a - b).sum(1)  # distância de variação total, 0 a 1
    peso = j[[f"{f}_tse" for f in FAIXAS]].sum(1).to_numpy()
    # o que a inferência usa não é o nível, é a VARIAÇÃO entre locais:
    # a correlação do % de 60+ e do % feminino entre as duas bases
    idoso = lambda m: m[:, 6] + m[:, 7]
    r_idoso = np.corrcoef(idoso(a), idoso(b))[0, 1]
    r_fem = np.corrcoef(j.fem_tse, j.fem_censo)[0, 1]
    return {"metodo": metodo, **kw, "locais": len(j),
            "dist_vt_media": float(np.average(vt, weights=peso)),
            "r_60mais": float(r_idoso), "r_feminino": float(r_fem),
            "setores_sem_local": int(len(setores) - w.s.nunique())}, w


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", default="2022")
    ap.add_argument("--uf", default="SP")
    ap.add_argument("--mun", default="71072", help="código TSE")
    ap.add_argument("--mun-ibge", default="3550308")
    a = ap.parse_args()
    locais, _ = carregar_locais(a.ano, a.uf, a.mun)
    locais = gpd.GeoDataFrame(locais, geometry=gpd.points_from_xy(locais.lon, locais.lat),
                              crs=4674).to_crs(UTM)
    locais["x"], locais["y"] = locais.geometry.x, locais.geometry.y
    setores = carregar_setores("35", a.mun_ibge)
    print(f"setores com moradores: {len(setores):,}")
    tse = perfil_tse_por_local(a.ano, a.uf, a.mun)
    res = []
    for m, kw in [("voronoi", {}),
                  ("raio", {"raio": 800, "h": 300}), ("raio", {"raio": 1500, "h": 600}),
                  ("raio", {"raio": 3000, "h": 1200})]:
        r, _ = avaliar(m, locais, setores, tse, **kw)
        res.append(r)
        print(r, flush=True)
    out = pd.DataFrame(res)
    Path("out").mkdir(exist_ok=True)
    out.to_csv(f"out/casamento_{a.ano}_{a.mun}.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
