"""Checagens de consistência dos dados de 2022 — o que o dado aguenta e o que ele não diz.

Três blocos, todos sobre o 1º turno de Presidente de 2022 no Brasil inteiro:

  1. consistência: em cada seção, os votos somam o comparecimento? o
     comparecimento cabe nos aptos? (e, nos boletins de SP, cargo a cargo);
  2. Benford, como lição e não como teste: o primeiro dígito dos votos por seção
     e por município, contra o esperado pela lei. Por seção a lei não vale nem com
     dado limpo; por município vale — porque o TAMANHO dos municípios a segue;
  3. urnas atípicas: quanto cada seção se afasta do esperado pelo local de
     votação de 2018 mais próximo e pela UF, e de que tipo são as mais afastadas.

Desvio estatístico não é evidência de irregularidade. O que a página mostra é
onde o dado surpreende o modelo, com as causas comuns ao lado.

    python checagens.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import brasil as br
import projecao as pj

RAW = Path("data/raw")
OUT = Path("out")
BENFORD = [np.log10(1 + 1 / d) for d in range(1, 10)]


def primeiro_digito(x):
    x = np.asarray(x)
    x = x[x > 0]
    return (x // 10 ** np.floor(np.log10(x))).astype(int)


def dist_digito(x):
    d = primeiro_digito(x)
    c = np.bincount(d, minlength=10)[1:10]
    obs = c / c.sum()
    mad = float(np.mean(np.abs(obs - BENFORD)))   # desvio absoluto médio (Nigrini)
    return {"obs": [round(float(v), 4) for v in obs], "n": int(c.sum()), "mad": round(mad, 4),
            "faixa": [int(np.percentile(x[x > 0], 5)), int(np.percentile(x[x > 0], 95))] if len(x) else [0, 0]}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cats = {13: "lula", 22: "bolsonaro", 15: "tebet", 12: "ciro"}
    v, cs = br.votos_secao("2022", cats)
    det = br.detalhe_2022()
    s = v.merge(det, on=["zona", "secao"], how="inner")
    s["votos"] = s[cs].sum(axis=1)
    out = {}

    # 1. consistência
    difere = (s.votos != s.comparecimento)
    acima = s.comparecimento > s.aptos
    out["consistencia"] = {
        "secoes": int(len(s)), "soma_difere": int(difere.sum()), "comparecimento_acima_aptos": int(acima.sum()),
        "sem_comparecimento": int((s.comparecimento == 0).sum()),
        "exemplos_difere": s.loc[difere, ["uf", "municipio", "zona", "secao", "votos", "comparecimento"]]
                            .head(10).to_dict(orient="records")}
    vb = pd.read_parquet(RAW / "2022" / "sp" / "votos.parquet")
    por = vb.groupby(["zona", "secao", "cargo"]).agg(v=("votos", "sum"), c=("comparecimento", "first"), a=("aptos", "first"))
    senado = por.xs("senador", level="cargo")
    outros = por.drop(index="senador", level="cargo")
    out["consistencia_sp_bu"] = {
        "secoes": int(vb.drop_duplicates(["zona", "secao"]).shape[0]),
        "cargos": sorted(vb.cargo.unique().tolist()),
        "soma_difere": int((outros.v != outros.c).sum()),
        "comparecimento_acima_aptos": int((por.c > por.a).sum()),
        # no Senado de 2022 cada eleitor votou em UM (uma vaga); em 2026 serão dois
        "senado_soma_difere": int((senado.v != senado.c).sum())}
    print("consistência:", out["consistencia"]["soma_difere"], "seções com soma ≠ comparecimento;",
          out["consistencia"]["comparecimento_acima_aptos"], "com comparecimento > aptos", flush=True)

    # 2. Benford
    m = s.groupby("municipio")[["lula", "bolsonaro"]].sum()
    out["benford"] = {"esperado": [round(b, 4) for b in BENFORD],
                      "secao_lula": dist_digito(s.lula.to_numpy()), "secao_bolsonaro": dist_digito(s.bolsonaro.to_numpy()),
                      "municipio_lula": dist_digito(m.lula.to_numpy()), "municipio_bolsonaro": dist_digito(m.bolsonaro.to_numpy()),
                      "municipio_aptos": dist_digito(s.groupby("municipio").aptos.sum().to_numpy())}
    for k in ("secao_lula", "municipio_lula", "municipio_aptos"):
        print(f"Benford {k}: MAD {out['benford'][k]['mad']}", flush=True)

    # 3. urnas atípicas: esperado pelo local de 2018 mais próximo + efeito de UF
    c22 = br.coords("2022")
    u = br.completar_xy(s.merge(c22.drop(columns=["SG_UF", "municipio"]), on=["zona", "local"], how="left"), c22)
    base, cb = br.base_local("2018", {17: "bolsonaro18", 13: "haddad18", 12: "ciro18", 45: "alckmin18", 30: "amoedo18"})
    base = base.merge(br.coords("2018").drop(columns=["SG_UF", "municipio"]), on=["zona", "local"], how="left")
    X, _ = br.montar_X(u, base, cb)
    ok = (u.lula + u.bolsonaro) > 0
    y = pj.logit(((u.lula + 0.5) / (u.lula + u.bolsonaro + 1)).to_numpy(float))
    ufc = pd.factorize(u.uf)[0]
    Xn = X.to_numpy(float)
    Xn = (Xn - Xn.mean(0)) / (Xn.std(0) + 1e-9)
    coef = pj.ajustar(Xn[ok], y[ok, None], u.votos.to_numpy(float)[ok] + 1, ufc[ok], np.unique(ufc), lam=50)
    esp = pj.prever(coef, Xn, ufc, np.unique(ufc))[:, 0]
    res = y - esp
    # escala robusta: mediana dos desvios absolutos
    z = res / (1.4826 * np.median(np.abs(res[ok] - np.median(res[ok]))))
    u["z"] = z
    u["lula_2t_esperado"] = 100 / (1 + np.exp(-esp))
    u["lula_x_bolso"] = 100 * u.lula / (u.lula + u.bolsonaro).replace(0, np.nan)
    loc = pd.read_parquet(RAW / "tse" / "locais_2022_BR.parquet",
                          columns=["NR_TURNO", "SG_UF", "NR_ZONA", "NR_SECAO", "DS_TIPO_LOCAL", "NM_LOCAL_VOTACAO", "NM_MUNICIPIO"])
    loc = loc[loc.NR_TURNO == "1"]
    loc = loc.assign(zona=br.zg(loc.SG_UF, loc.NR_ZONA), secao=loc.NR_SECAO.astype(int)).drop_duplicates(["zona", "secao"])
    u = u.merge(loc[["zona", "secao", "DS_TIPO_LOCAL", "NM_LOCAL_VOTACAO", "NM_MUNICIPIO"]], on=["zona", "secao"], how="left")
    u["exterior"] = u.uf == "ZZ"
    u["pequena"] = u.aptos < 100
    at = u[ok & (np.abs(u.z) > 4)]
    def causa(r):
        if r.exterior: return "exterior"
        nome = str(r.NM_LOCAL_VOTACAO or "").upper()
        # o cadastro chama de "convencional" a escola da aldeia; o nome do local diz o que é
        if any(k in nome for k in ("INDIGENA", "INDÍGENA", "ALDEIA", "QUILOMBO", "QUILOMBOLA")):
            return "escola indígena / aldeia / quilombo"
        if r.DS_TIPO_LOCAL and r.DS_TIPO_LOCAL != "Convencional": return str(r.DS_TIPO_LOCAL).lower()
        if r.pequena: return "seção pequena (<100 aptos)"
        return "convencional"
    at = at.assign(causa=at.apply(causa, axis=1))
    base_cat = u[ok].apply(causa, axis=1).value_counts()
    tab = at.causa.value_counts().rename("atipicas").to_frame().join(base_cat.rename("todas"))
    tab["taxa_por_mil"] = 1000 * tab.atipicas / tab.todas
    out["atipicas"] = {
        "limiar_z": 4, "secoes": int(ok.sum()), "n": int(len(at)),
        "por_causa": tab.reset_index().rename(columns={"index": "causa"}).round(2).to_dict(orient="records"),
        "maiores": at.reindex(at.z.abs().sort_values(ascending=False).index).head(40)[
            ["uf", "NM_MUNICIPIO", "zona", "secao", "NM_LOCAL_VOTACAO", "causa", "aptos", "comparecimento", "lula", "bolsonaro",
             "lula_x_bolso", "lula_2t_esperado", "z"]].assign(zona=lambda d: d.zona % 10000).round(2).to_dict(orient="records"),
        "hist_z": np.histogram(np.clip(z[ok], -10, 10), bins=40, range=(-10, 10))[0].tolist()}
    print(f"atípicas (|z|>4): {len(at):,} de {int(ok.sum()):,}", flush=True)
    print(tab.round(2).to_string(), flush=True)
    OUT.mkdir(exist_ok=True)
    (OUT / "checagens_2022.json").write_text(json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
