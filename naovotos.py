"""Não-votos seção a seção: abstenção, brancos e nulos em 2022 (1º e 2º turnos) e 2026 (1º e 2º).

A página naovotos.html compara qualquer par dessas quatro eleições e ordena pelas maiores
diferenças, para pegar mudanças de padrão. Cada seção é a de 2026 (os boletins do 1º turno,
base_secoes.py), casada com a de 2022 por UF + zona + número.

O casamento não é perfeito: 92% das seções de 2026 têm par em 2022, e 7% das casadas mudaram
mais de 20% em eleitores aptos (renumeração, rezoneamento, seção dividida) — essas não são a
mesma urna, e numa lista de "maiores diferenças" ficariam todas no topo. Cada seção leva a marca
`comparavel` (aptos de 2022 a ±20% dos de 2026); entre os turnos de 2026 a seção é a mesma.

2º turno de 2026: na noite, por seção só onde há boletim baixado (SP, coletor.py); nas outras
UFs, por município (arquivo `u` do nacional.py, só das seções já apuradas). Por seção no país
inteiro, depois de `coletar_brasil.py --pleito 2026_2t` na manhã seguinte.

Saída em web/dados/naovotos/: um arquivo por UF com as seções de 2022 e do 1º turno de 2026 (fixo),
outro por UF só com o 2º turno de 2026 (<uf>_26b.json, o único que muda na noite — regravar os
7,7 MB de SP a cada publicação encheria o histórico do git), resumo.json (UFs e municípios) e
destaques.json (as maiores mudanças do país, por par e medida, sem o exterior).

    python naovotos.py            # tudo
    python naovotos.py --so-2t    # na noite: só o 2º turno, o resumo e os destaques
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from painel_brasil import REGIAO, nomes_municipios

RAW = Path("data/raw")
WEB = Path("web/dados/naovotos")
ELEICOES = {"22a": "1º turno de 2022", "22b": "2º turno de 2022", "26a": "1º turno de 2026", "26b": "2º turno de 2026"}
CAMPOS = ["ap", "co", "br", "nu"]          # aptos, comparecimento, brancos, nulos
TOL = 0.20                                 # variação de aptos com que a seção de 2022 ainda é "a mesma"
PARES = [("22a", "26a"), ("26a", "26b"), ("22b", "26b"), ("22a", "22b")]


def boletins(pleito, uf):
    """Seções de um pleito/UF, dos boletins baixados (só Presidente): aptos, comparecimento, brancos, nulos."""
    arq = RAW / pleito / uf / "secoes.jsonl"
    if not arq.exists():
        return None
    vistos = {}
    with open(arq, encoding="utf-8") as f:
        for ln in f:
            s = json.loads(ln)
            vistos[(int(s["zona"]), int(s["secao"]))] = s
    linhas = []
    for (zona, secao), s in vistos.items():
        for e in s.get("eleicoes", []):
            for c in e["cargos"]:
                if c["cargo"] != "presidente":
                    continue
                br = sum(n for t, _, n in c["votos"] if t == "branco")
                nu = sum(n for t, _, n in c["votos"] if t == "nulo")
                linhas.append((zona, secao, e["aptos"], c["comparecimento"], br, nu))
    return pd.DataFrame(linhas, columns=["zona", "secao", "26b_ap", "26b_co", "26b_br", "26b_nu"])


def secoes():
    s = pd.read_parquet(RAW / "2026" / "secoes_1t_brasil.parquet",
                        columns=["uf", "municipio", "zona", "secao", "local", "aptos", "comparecimento", "branco", "nulo"])
    s = s.rename(columns={"aptos": "26a_ap", "comparecimento": "26a_co", "branco": "26a_br", "nulo": "26a_nu"})
    a = pd.read_parquet(RAW / "tse" / "painel_2t_2022.parquet")
    a = pd.DataFrame({"uf": a.uf, "zona": a.zona % 10000, "secao": a.secao,
                      "22a_ap": a.aptos, "22a_co": a.aptos - a.abst, "22a_br": a.branco, "22a_nu": a.nulo,
                      "22b_ap": a.aptos_2t, "22b_co": a.aptos_2t - a.abst_2t, "22b_br": a.branco_2t, "22b_nu": a.nulo_2t})
    s = s.merge(a, on=["uf", "zona", "secao"], how="left")
    s["comparavel"] = ((s["22a_ap"] - s["26a_ap"]).abs() <= TOL * s["26a_ap"]).astype(int)
    partes = []
    for uf, g in s.groupby("uf"):
        b = boletins("2026_2t", uf.lower())
        partes.append(g.merge(b, on=["zona", "secao"], how="left") if b is not None else g)
    s = pd.concat(partes, ignore_index=True)
    for c in [f"26b_{k}" for k in CAMPOS]:
        if c not in s:
            s[c] = np.nan
    # quais seções já estão no 2º turno: com boletim, ou (UF sem boletins) as `st` primeiras do índice
    s["chegou2t"] = s["26b_ap"].notna()
    idx, u = RAW / "2026_2t" / "indices" / "chegadas.parquet", RAW / "2026_2t" / "nacional" / "municipios.parquet"
    if idx.exists() and u.exists():
        import painel_2t
        sem_bu = ~s.uf.isin(s.loc[s.chegou2t, "uf"].unique())
        st = pd.read_parquet(u).set_index("municipio").st
        marca = painel_2t.chegou_por_indice(s[sem_bu][["municipio", "zona", "secao"]], pd.read_parquet(idx), st)
        s.loc[sem_bu, "chegou2t"] = marca > 0
    return s


def taxas(df, e):
    """abstenção (% dos aptos), brancos+nulos (% do comparecimento), não-votos (% dos aptos)."""
    ap, co, br, nu = (df[f"{e}_{k}"].astype(float) for k in CAMPOS)
    return {"abst": 100 * (ap - co) / ap, "bn": 100 * (br + nu) / co, "nv": 100 * (ap - co + br + nu) / ap,
            "br": 100 * br / co, "nu": 100 * nu / co}


def municipios_2t():
    """2º turno de 2026 por município, do arquivo `u` (só as seções já apuradas)."""
    arq = RAW / "2026_2t" / "nacional" / "municipios.parquet"
    if not arq.exists():
        return None
    u = pd.read_parquet(arq)
    return pd.DataFrame({"municipio": u.municipio, "26b_ap": u.est, "26b_co": u.c, "26b_br": u.vb, "26b_nu": u.vn,
                         "26b_secoes": u.st, "26b_total": u.ts})


def main(so_2t=None, secoes_2t=True):
    """secoes_2t=False: na noite, só o resumo e os destaques (pequenos); os arquivos de seção do 2º turno
    (~10 MB no fim da noite, somadas as UFs) vão a cada 30 min, senão o histórico do git incharia."""
    sys.stdout.reconfigure(encoding="utf-8")
    so_2t = ("--so-2t" in sys.argv) if so_2t is None else so_2t
    WEB.mkdir(parents=True, exist_ok=True)
    s = secoes()
    nomes = nomes_municipios()
    loc = pd.read_parquet(RAW / "tse" / "locais_2026_BR.parquet", columns=["SG_UF", "NR_ZONA", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO"])
    loc = loc.drop_duplicates(["SG_UF", "NR_ZONA", "NR_LOCAL_VOTACAO"])
    cols = [f"{e}_{k}" for e in ELEICOES for k in CAMPOS]
    fixas = [c for c in cols if not c.startswith("26b")]
    tem26b = s["26b_ap"].notna()
    # --- o 2º turno de 2026 por UF, à parte (é o que muda na noite)
    for uf, g in (s[tem26b].groupby("uf") if secoes_2t else []):
        (WEB / f"{uf.lower()}_26b.json").write_text(json.dumps(
            {c: g[c].astype(int).tolist() for c in ["zona", "secao"] + [f"26b_{k}" for k in CAMPOS]}, separators=(",", ":")), encoding="utf-8")
    # --- um arquivo por UF, seção a seção (−1 = sem dado), só 2022 e o 1º turno de 2026: fixo
    for uf, g in ([] if so_2t else s.groupby("uf")):
        l = loc[loc.SG_UF == uf]
        dados = {"meta": {"uf": uf, "eleicoes": ELEICOES, "tol": TOL,
                          "locais": {f"{int(z)}-{int(n)}": nm.title() for z, n, nm in zip(l.NR_ZONA, l.NR_LOCAL_VOTACAO, l.NM_LOCAL_VOTACAO)},
                          "municipios": {int(m): nomes.get(int(m), "") for m in g.municipio.unique()}},
                 "sec": {c: g[c].fillna(-1).astype(int).tolist() for c in ["municipio", "zona", "secao", "local", "comparavel"] + fixas}}
        (WEB / f"{uf.lower()}.json").write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # --- resumo por município e por UF (o 2º turno de 2026 vem do arquivo u onde não há boletim)
    m = s.groupby(["uf", "municipio"])[cols].sum(min_count=1).reset_index()
    # as outras eleições só nas seções já apuradas no 2º turno de 2026 (sufixo _r): no meio da noite, comparar
    # o parcial do 2º turno com o 1º turno inteiro do município mede quais seções chegaram, não o eleitor
    r_ = s[s.chegou2t].groupby("municipio")[fixas].sum(min_count=1).add_suffix("_r")
    m = m.merge(r_, left_on="municipio", right_index=True, how="left")
    m2 = municipios_2t()
    if m2 is not None:
        # onde a UF não tem boletins do 2º turno, o município vem do arquivo u
        sem_bu = ~m.uf.isin(s.loc[tem26b, "uf"].unique())
        m = m.merge(m2[["municipio", "26b_secoes", "26b_total"] + [f"26b_{k}" for k in CAMPOS]], on="municipio", how="left", suffixes=("", "_u"))
        for k in CAMPOS:
            m[f"26b_{k}"] = np.where(sem_bu, m[f"26b_{k}_u"], m[f"26b_{k}"])
        m = m.drop(columns=[f"26b_{k}_u" for k in CAMPOS])
    resumo = {"meta": {"eleicoes": ELEICOES, "tol": TOL, "municipios": {int(k): v for k, v in nomes.items()},
                       "gerado": pd.Timestamp.now().strftime("%d/%m/%Y %H:%M"),
                       "secoes": int(len(s)), "comparaveis": int(s.comparavel.sum()),
                       "secoes_26b": int(tem26b.sum()), "ufs_26b_por_secao": sorted(s.loc[tem26b, "uf"].unique().tolist())},
              "mun": {c: (m[c].tolist() if c == "uf" else m[c].fillna(-1).astype(int).tolist())
                      for c in ["uf", "municipio"] + cols + [f"{c}_r" for c in fixas] + [c for c in ["26b_secoes", "26b_total"] if c in m]}}
    resumo["mun"]["regiao"] = [REGIAO.get(u, "Exterior") for u in m.uf]
    (WEB / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # --- destaques: as maiores mudanças do país, seção a seção, por par e medida (comparáveis, 100+ aptos)
    dest = {}
    for a_, b_ in PARES:
        ok = s[f"{a_}_ap"].notna() & s[f"{b_}_ap"].notna() & (s[f"{b_}_ap"] >= 100) & (s[f"{b_}_co"] > 0) & (s[f"{a_}_co"] > 0)
        ok &= s.uf != "ZZ"   # exterior: abstenção alta por natureza, tomaria a lista inteira
        if a_[:2] != b_[:2]:
            ok &= s.comparavel == 1
        if ok.sum() == 0:
            continue
        g = s[ok]
        ta, tb = taxas(g, a_), taxas(g, b_)
        for med in ("abst", "bn", "nv"):
            d = (tb[med] - ta[med])
            idx = pd.concat([d.nlargest(250), d.nsmallest(250)]).index
            dest[f"{a_}-{b_}-{med}"] = {c: s.loc[idx, c].fillna(-1).astype(int).tolist()
                                       for c in ["municipio", "zona", "secao", "local"] + cols} | {"uf": s.loc[idx, "uf"].tolist()}
    # entre turnos: a mudança 1º→2º de 2026 menos a de 2022, na mesma seção (comparável com 2022)
    ok = s[[f"{e}_ap" for e in ELEICOES]].notna().all(axis=1) & (s["26b_ap"] >= 100) & (s.comparavel == 1) & (s.uf != "ZZ")
    ok &= (s[[f"{e}_co" for e in ELEICOES]] > 0).all(axis=1)
    if ok.sum():
        g = s[ok]
        t_ = {e: taxas(g, e) for e in ELEICOES}
        for med in ("abst", "bn", "nv"):
            d = (t_["26b"][med] - t_["26a"][med]) - (t_["22b"][med] - t_["22a"][med])
            idx = pd.concat([d.nlargest(250), d.nsmallest(250)]).index
            dest[f"tt-{med}"] = {c: s.loc[idx, c].fillna(-1).astype(int).tolist()
                                 for c in ["municipio", "zona", "secao", "local"] + cols} | {"uf": s.loc[idx, "uf"].tolist()}
    (WEB / "destaques.json").write_text(json.dumps({"meta": {"eleicoes": ELEICOES}, "d": dest}, ensure_ascii=False,
                                                   separators=(",", ":")), encoding="utf-8")
    t = {e: taxas(s.assign(**{c: s[c] for c in cols}).loc[s[f"{e}_ap"].notna()].sum(numeric_only=True).to_frame().T, e) for e in ELEICOES}
    for e, tx in t.items():
        print(f"{ELEICOES[e]:18s} abstenção {float(tx['abst'].iloc[0]):5.2f}%  brancos+nulos {float(tx['bn'].iloc[0]):5.2f}%", flush=True)
    tam = sum(f.stat().st_size for f in WEB.glob("*.json")) / 1e6
    print(f"{len(s):,} seções ({int(s.comparavel.sum()):,} comparáveis com 2022; {int(tem26b.sum()):,} com 2º turno de 2026); "
          f"{len(list(WEB.glob('*.json')))} arquivos, {tam:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
