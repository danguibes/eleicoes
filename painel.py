"""Dados do painel: por local de votação, a eleição anterior completa, a atual apurada e a atual projetada.

O navegador recebe uma linha por local de votação (~10 mil no estado) com os
atributos de filtro — município, zona e o quintil do lugar em renda, religião,
cor, escolaridade e idade — e soma o que o filtro deixar. Uma fonte só para
todos os gráficos: é o que impede um card de mostrar outro recorte.

O intervalo de 90% vem pré-calculado para o total e para cada recorte simples
(um município, uma zona, um quintil); combinação de filtros mostra a projeção
sem intervalo, e a página diz isso.

    python painel.py --modo ensaio --frac 0.25   # 2022 com 25% das urnas, anterior = 2018
    python painel.py --modo 2026                 # noite: anterior = 2022
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

import projecao as pj

RAW = Path("data/raw")
WEB = Path("web/dados")

PRETA = ["V01378", "V01383", "V01388"]
PARDA = ["V01380", "V01385", "V01390"]
ADULTOS = [f"V{i:05d}" for i in range(1377, 1392)]
VARS = ["renda", "catolicos", "evangelicos", "sem_religiao", "preta_parda", "superior", "idosos"]
# pares para comparar entre eleições: mesmo campo político, candidato diferente
PARES = {"2026": {"lula": "lula22", "flavio": "bolsonaro22"},
         "ensaio": {"lula": "haddad18", "bolsonaro": "bolsonaro18"}}


# ---------------------------------------------------------------- entorno (Censo)
def setores_uf():
    """Setores de SP com centroide na mesma projeção plana dos locais (cache)."""
    arq = RAW / "ibge" / "setores_35_centroide.parquet"
    if not arq.exists():
        import geopandas as gpd
        g = gpd.read_file(RAW / "ibge" / "setores_SP.gpkg", columns=["CD_SETOR"])
        c = g.geometry.to_crs(4674).centroid
        pd.DataFrame({"CD_SETOR": g.CD_SETOR, "lon": c.x, "lat": c.y}).to_parquet(arq, index=False)
    s = pd.read_parquet(RAW / "ibge" / "setores_35.parquet").merge(pd.read_parquet(arq), on="CD_SETOR")
    s = s[s.V01006.fillna(0) > 0].reset_index(drop=True)
    s["x"] = (s.lon + 46.63) * 102_000
    s["y"] = (s.lat + 23.55) * 111_000
    rel = pd.read_parquet(RAW / "ibge" / "religiao_ap_35.parquet").set_index("CD_AP")
    s["evang"] = s.CD_AP.map(rel.evangelica / rel.total).fillna(0) * s.V01006
    s["catol"] = s.CD_AP.map(rel.catolica / rel.total).fillna(0) * s.V01006
    s["semrel"] = s.CD_AP.map(rel.sem_religiao / rel.total).fillna(0) * s.V01006
    s["renda_x_resp"] = s.V06004.fillna(0) * s.V06001.fillna(0)
    s["resp"] = s.V06001.where(s.V06004.notna(), 0).fillna(0)
    s["pp"] = s[PRETA + PARDA].sum(axis=1)
    s["adultos"] = s[ADULTOS].sum(axis=1)
    return s


def entorno(locais, st, raio=1500, h=600):
    """Mesma regra do casamento.py (raio 1,5 km, peso exp(−d/600 m)); cada setor
    reparte seu peso entre os locais que o alcançam. Local sem setor no raio
    (zona rural esparsa) pega o setor mais próximo."""
    xy_s = np.c_[st.x, st.y]
    arv = cKDTree(xy_s)
    viz = arv.query_ball_point(np.c_[locais.x, locais.y], r=raio)
    li, si, dd = [], [], []
    for i, v in enumerate(viz):
        if not v:
            d, j = arv.query([locais.x.iloc[i], locais.y.iloc[i]])
            v, dist = [j], np.array([d])
        else:
            dist = np.hypot(*(xy_s[v] - [locais.x.iloc[i], locais.y.iloc[i]]).T)
        li += [i] * len(v); si += list(v); dd += list(dist)
    w = pd.DataFrame({"l": li, "s": si, "w": np.exp(-np.array(dd) / h)})
    w["w"] /= w.groupby("s").w.transform("sum")
    cols = ["pp", "adultos", "evang", "catol", "semrel", "V01006", "renda_x_resp", "resp"]
    v = st[cols].to_numpy(float)[w.s.to_numpy()] * w.w.to_numpy()[:, None]
    e = pd.DataFrame(v, columns=cols).assign(l=w.l.to_numpy()).groupby("l").sum()
    out = pd.DataFrame(index=range(len(locais)))
    out["renda"] = (e.renda_x_resp / e.resp.replace(0, np.nan)).reindex(out.index)
    out["evangelicos"] = (100 * e.evang / e.V01006).reindex(out.index)
    out["catolicos"] = (100 * e.catol / e.V01006).reindex(out.index)
    out["sem_religiao"] = (100 * e.semrel / e.V01006).reindex(out.index)
    out["preta_parda"] = (100 * e.pp / e.adultos.replace(0, np.nan)).reindex(out.index)
    return out


def locais_com_atributos(ano, st):
    arq = RAW / f"locais_atributos_{ano}.parquet"
    if arq.exists():
        return pd.read_parquet(arq)
    c = pj.locais_coord(ano, None)
    c = pd.concat([c.reset_index(drop=True), entorno(c.reset_index(drop=True), st)], axis=1)
    if not (RAW / "tse" / f"perfil_{ano}_SP.parquet").exists():
        # 2018 não tem perfil baixado: fica sem, e montar() copia do local mais próximo
        c.to_parquet(arq, index=False)
        return c
    p = pj.perfil_secoes(ano, None)
    pr = pj.principal_de(ano, None)[["zona", "secao", "local"]].drop_duplicates(["zona", "secao"])
    p = p.merge(pr, on=["zona", "secao"], how="left")
    p["n_sup"] = p.superior * p.eleitores_perfil
    p["n_ido"] = p.idoso * p.eleitores_perfil
    a = p.groupby(["zona", "local"])[["n_sup", "n_ido", "eleitores_perfil"]].sum()
    a["superior"] = 100 * a.n_sup / a.eleitores_perfil
    a["idosos"] = 100 * a.n_ido / a.eleitores_perfil
    c = c.merge(a[["superior", "idosos"]].reset_index(), on=["zona", "local"], how="left")
    c.to_parquet(arq, index=False)
    return c


def cortes_quintis(df, peso):
    """Pontos de corte com o mesmo número de eleitores em cada quintil (estado todo)."""
    out = {}
    for v in VARS:
        d = df[[v, peso]].dropna().sort_values(v)
        acum = d[peso].cumsum() / d[peso].sum()
        out[v] = [float(d[v].iloc[np.searchsorted(acum.to_numpy(), q)]) for q in (0.2, 0.4, 0.6, 0.8)]
    return out


def quintil(x, cortes):
    return np.where(np.isnan(x), 0, 1 + np.searchsorted(cortes, x, side="right")).astype(int)


# ---------------------------------------------------------------- nomes
DOWNLOADS = Path.home() / "Downloads"


def nomes_candidatos(ano, cargo):
    """Nome de urna por número, do consulta_cand_<ano>.zip do TSE (baixado no navegador:
    o CDN recusa script). Sem o arquivo, o painel mostra "nº 10" — nunca um nome suposto."""
    import io
    import zipfile
    for pasta in (RAW / "tse", DOWNLOADS):
        z = pasta / f"consulta_cand_{ano}.zip"
        if z.exists():
            break
    else:
        return {}
    uf = "BR" if cargo == "presidente" else "SP"
    with zipfile.ZipFile(z) as zz:
        m = next((n for n in zz.namelist() if n.endswith(f"_{uf}.csv")), None)
        if not m:
            return {}
        d = pd.read_csv(io.TextIOWrapper(zz.open(m), encoding="latin-1"), sep=";", dtype=str)
    d = d[d.DS_CARGO.str.upper().str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
          == {"presidente": "PRESIDENTE", "governador": "GOVERNADOR", "senador": "SENADOR"}[cargo]]
    # só número, nome de urna e partido: o arquivo traz CPF, e-mail e título, que não saem daqui
    return {f"n{int(r.NR_CANDIDATO)}": f"{r.NM_URNA_CANDIDATO.title()} ({r.SG_PARTIDO})"
            for r in d.itertuples()}


# ---------------------------------------------------------------- montagem
_CACHE = {}


def preparar(modo, cargo):
    """O que não muda entre rodadas da noite: cadastro, base, matriz do modelo,
    atributos dos locais. Carregado uma vez (~1 min) e reaproveitado."""
    k = (modo, cargo)
    if k in _CACHE:
        return _CACHE[k]
    st = setores_uf()
    if modo == "ensaio":
        ano_ant, ano_at, pleito = "2018", "2022", "2022"
        noite = pj.Noite(pleito="2022", ano_cadastro="2022", base="2018", mun=None)
        ant, cats_ant = pj.base_2018(None)
    else:
        ano_ant, ano_at, pleito = "2022", "2026", "2026"
        noite = pj.Noite(pleito="2026", ano_cadastro="2026", base="2022", mun=None, cargo=cargo)
        ant, cats_ant = pj.base_bu("2022", pj.BASE_2022 if cargo == "presidente" else "auto", None, cargo)
    la = locais_com_atributos(ano_at, st)
    lb = locais_com_atributos(ano_ant, st)
    _CACHE[k] = (ano_ant, ano_at, pleito, noite, ant, cats_ant, la, lb)
    return _CACHE[k]


def montar(modo, frac=None, cargo="presidente", n_boot=200):
    ano_ant, ano_at, pleito, noite, ant, cats_ant, la, lb = preparar(modo, cargo)
    lb = lb.copy()
    nomes_cand = {}
    if cargo != "presidente":
        # O mesmo número de urna muda de dono entre eleições (222 ao Senado: Marcos
        # Pontes em 2022, André do Prado em 2026). As chaves da anterior ganham
        # sufixo, senão os votos de 2022 sairiam com o nome de 2026.
        ren = {c: f"{c}_ant" for c in cats_ant if c != "bn"}
        ant = ant.rename(columns=ren)
        cats_ant = [ren.get(c, c) for c in cats_ant]
        nomes_cand = {**{f"{k}_ant": v for k, v in nomes_candidatos(ano_ant, cargo).items()},
                 **nomes_candidatos(ano_at, cargo)}
    # o cadastro já traz `superior` (fração da seção, usada no modelo); para o filtro
    # vale o do local, então o da seção sai antes da junção
    u = noite.univ.drop(columns=["superior"]).merge(la[["zona", "local"] + VARS],
                                                     on=["zona", "local"], how="left")
    cortes = cortes_quintis(u.groupby(["zona", "local"]).agg(
        **{v: (v, "first") for v in VARS}, aptos=("aptos", "sum")).reset_index(), "aptos")
    for v in VARS:
        u[f"q_{v}"] = quintil(u[v].to_numpy(float), cortes[v])

    # --- atual: apuradas até aqui (no ensaio, as que tinham chegado em `frac`)
    apenas = None
    if modo == "ensaio":
        ch = pd.read_csv(RAW / "2022" / "sp" / "chegadas.csv", dtype=str)
        ch["t"] = pd.to_datetime(ch.recebido, format="%d/%m/%Y %H:%M:%S")
        ch = ch.sort_values("t").iloc[: int(frac * len(ch))]
        apenas = set(zip(ch.zona.astype(int), ch.secao.astype(int)))
        hora = ch.t.iloc[-1].strftime("%H:%M")
    else:
        hora = datetime.now().strftime("%H:%M")
    arq = RAW / pleito / "sp" / "votos.parquet"
    obs, cats = (pj.alvo_bu(pleito, noite.cats_alvo, None, cargo) if arq.exists() else (None, None))
    if obs is not None and apenas is not None:
        obs = obs[[k in apenas for k in zip(obs.zona, obs.secao)]]
    tem = obs is not None and len(obs) > 0
    if tem:
        obs = obs.rename(columns={"aptos": "aptos_bu"}).drop(columns=["local"])
        u = u.merge(obs, on=["zona", "secao"], how="left")
        m = u.comparecimento.notna().to_numpy()
        for c in cats + ["comparecimento"]:
            u[c] = u.get(c, 0.0)
            u[c] = u[c].fillna(0)
        u["aptos"] = np.where(m, u.aptos_bu, u.aptos)
        validos = [c for c in cats if c != "bn"]
        # códigos dos recortes com intervalo
        u["cod_mun"] = pd.factorize(u.municipio)[0]
        u["cod_zona"] = pd.factorize(u.zona)[0]
        grupos = {"total": np.zeros(len(u), int), "mun": u.cod_mun.to_numpy(), "zona": u.cod_zona.to_numpy(),
                  **{f"q_{v}": u[f"q_{v}"].to_numpy() for v in VARS}}
        amostras, linha, pg = pj.projetar(u, noite.X, m, cats, n_boot=n_boot, grupos=grupos)
        fator = pj.FATOR_UF
        ic = {}
        mapas = {"total": {0: "total"}, "mun": dict(enumerate(pd.factorize(u.municipio)[1])),
                 "zona": dict(enumerate(pd.factorize(u.zona)[1])),
                 **{f"q_{v}": {q: q for q in range(6)} for v in VARS}}
        iv = [cats.index(c) for c in validos]
        for k, s in pg.items():
            pv = s[:, :, iv] / np.maximum(s[:, :, iv].sum(2, keepdims=True), 1e-9) * 100  # B,G,C
            lo, hi = pj.intervalo(pv[1:], pv[0], fator)
            ic[k] = {str(mapas[k][g]): {c: [round(float(lo[g, j]), 2), round(float(hi[g, j]), 2)]
                                        for j, c in enumerate(validos)}
                     for g in range(pv.shape[1]) if s[0, g, iv].sum() > 0}
        # amostras por quintil (votos, sem a projeção central): o navegador soma as de
        # uma faixa de quintis — 2º ao 4º, por exemplo — e tira o intervalo dela
        amostras_q = {v: np.rint(pg[f"q_{v}"][1:][:, :, iv]).astype(int).tolist() for v in VARS}
        for j, c in enumerate(cats):
            u[f"pj_{c}"] = linha[:, j]
            u[f"ap_{c}"] = np.where(m, u[c], 0)
        u["apurada"] = m.astype(int)
        u["aptos_ap"] = np.where(m, u.aptos, 0)
        u["comp_ap"] = np.where(m, u.comparecimento, 0)
    else:
        cats, ic = list(noite.cats_alvo.values()) + ["outros", "bn"] if isinstance(noite.cats_alvo, dict) else [], {}
        amostras_q = {}
        u["apurada"] = 0

    # --- por local de votação
    chave = ["municipio", "zona", "local"]
    num = ["aptos", "apurada"] + ([c for c in u.columns if c.startswith(("pj_", "ap_"))] + ["aptos_ap", "comp_ap"] if tem else [])
    at = u.groupby(chave).agg(**{c: (c, "sum") for c in num}, secoes=("secao", "count"),
                              **{f"q_{v}": (f"q_{v}", "first") for v in VARS}).reset_index()
    if "superior" not in lb:
        # perfil do TSE de um lugar muda pouco em quatro anos: vem do local atual mais próximo
        _, i = cKDTree(np.c_[la.x, la.y]).query(np.c_[lb.x, lb.y])
        lb["superior"] = la.superior.to_numpy()[i]
        lb["idosos"] = la.idosos.to_numpy()[i]
    lb = lb.drop(columns=["municipio"], errors="ignore")
    an = ant.merge(lb, on=["zona", "local"], how="left")
    zm = pj.principal_de(ano_ant, None).drop_duplicates(["zona", "local"])[["zona", "local", "municipio"]]
    an = an.merge(zm, on=["zona", "local"], how="left")
    for v in VARS:
        an[f"q_{v}"] = quintil(an[v].to_numpy(float), cortes[v])

    nomes = (pd.read_parquet(RAW / "tse" / f"locais_{ano_at}_SP.parquet", columns=["CD_MUNICIPIO", "NM_MUNICIPIO"])
             .drop_duplicates("CD_MUNICIPIO"))
    col = lambda df, cs: {c: [round(float(x), 1) if isinstance(x, (float, np.floating)) else int(x)
                              for x in df[c].fillna(0)] for c in cs}
    dados = {
        "meta": {"modo": modo, "cargo": cargo, "anterior": ano_ant, "atual": ano_at, "hora": hora,
                 "gerado": datetime.now().strftime("%d/%m/%Y %H:%M"),
                 "secoes": int(len(u)), "apuradas": int(u.apurada.sum()),
                 "cats": cats, "cats_anterior": cats_ant, "pares": PARES["ensaio" if modo == "ensaio" else "2026"],
                 "cortes": cortes, "fator_ic": pj.FATOR_UF,
                 "nomes": nomes_cand,
                 "municipios": {int(r.CD_MUNICIPIO): r.NM_MUNICIPIO for r in nomes.itertuples()}},
        "atual": col(at, chave + ["secoes"] + num + [f"q_{v}" for v in VARS]),
        "anterior": col(an, chave + cats_ant + ["comparecimento", "aptos"] + [f"q_{v}" for v in VARS]),
        "ic": ic,
        "amostras_q": amostras_q,
    }
    WEB.mkdir(parents=True, exist_ok=True)
    nome = f"{modo}_{cargo}.json"
    (WEB / nome).write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{WEB / nome}: {(WEB / nome).stat().st_size / 1e6:.1f} MB; {len(at):,} locais atuais, "
          f"{len(an):,} anteriores; {dados['meta']['apuradas']:,}/{dados['meta']['secoes']:,} seções apuradas",
          flush=True)
    return dados


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["ensaio", "2026"], default="ensaio")
    ap.add_argument("--frac", type=float, default=0.25)
    ap.add_argument("--cargo", default="presidente")
    ap.add_argument("--boot", type=int, default=200)
    a = ap.parse_args()
    montar(a.modo, a.frac, a.cargo, a.boot)
