"""O índice de seções diz QUAIS seções o arquivo por município já soma? Conferido voto a voto no 1º turno de 2026.

A projeção do 2º turno (ensaio_2t.py, variante D) precisa saber quais seções de cada
município já estão no parcial publicado: compara o 2º turno delas com o 1º turno delas
mesmas. O arquivo `u` dá só a soma e a contagem (`st`); o índice de seções da UF dá
quais seções chegaram, com a hora. Na noite de 04/10 o índice andou à frente do `u` em
até 30% dos municípios de SP, então a regra é: as `st` primeiras seções do índice, pela
hora de chegada.

Aqui se mede se a regra reproduz o parcial: para cada versão do painel do Brasil
publicada na noite (git) e a versão do índice de SP imediatamente anterior, soma-se o
boletim de urna das `st` primeiras seções de cada município e compara-se com o parcial
publicado de Lula e Flávio.

    python conferir_indice.py
"""
import glob
import json
import subprocess
import sys

import pandas as pd


def indice_por_municipio(arq):
    j = json.load(open(arq, encoding="utf-8"))
    linhas = []
    for ab in j["abr"]:
        for mu in ab["mu"]:
            for z in mu["zon"]:
                for s in z["sec"]:
                    if s.get("da") and "nsp" not in s:
                        linhas.append((int(mu["cd"]), int(z["cd"]), int(s["ns"]),
                                       pd.to_datetime(f"{s['da']} {s['ha']}", format="%d/%m/%Y %H:%M:%S")))
    return j["hg"], pd.DataFrame(linhas, columns=["municipio", "zona", "secao", "t"])


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    v = pd.read_parquet("data/raw/2026/sp/votos.parquet")
    v = v[v.cargo == "presidente"]
    bu = v.pivot_table(index=["municipio", "zona", "secao"], columns="codigo", values="votos", aggfunc="sum", fill_value=0)
    bu = bu[[13, 22]].rename(columns={13: "lula", 22: "flavio"}).reset_index()
    indices = sorted((indice_por_municipio(f) for f in glob.glob("data/raw/2026/sp/cs/*.json")), key=lambda x: x[0])
    hs = subprocess.run(["git", "log", "--format=%h", "--after=2026-10-04 17:30", "--before=2026-10-04 21:30", "--",
                         "web/dados/2026_brasil_presidente.json"], capture_output=True, text=True).stdout.split()
    for h in hs[::4]:
        d = json.loads(subprocess.run(["git", "show", f"{h}:web/dados/2026_brasil_presidente.json"],
                                      capture_output=True, text=True, encoding="utf-8").stdout)
        mu = pd.DataFrame(d["mun"])
        mu = mu[mu.uf == "SP"][["municipio", "apuradas", "ap_lula", "ap_flavio"]]
        hora = d["meta"]["hora"]
        antes = [x for x in indices if x[0][:5] <= hora]
        if not antes:
            continue
        hg, ix = antes[-1]
        ix = ix.merge(bu, on=["municipio", "zona", "secao"], how="left").sort_values(["municipio", "t"])
        ix["ordem"] = ix.groupby("municipio").cumcount()
        k = mu.set_index("municipio").apuradas
        ix = ix[ix.ordem < ix.municipio.map(k).fillna(0)]
        soma = ix.groupby("municipio")[["lula", "flavio"]].sum()
        c = mu.set_index("municipio").join(soma, how="left").fillna(0)
        c = c[c.apuradas > 0]
        exato = ((c.lula == c.ap_lula) & (c.flavio == c.ap_flavio))
        erro = (c.lula - c.ap_lula).abs().sum() + (c.flavio - c.ap_flavio).abs().sum()
        tot = c.ap_lula.sum() + c.ap_flavio.sum()
        print(f"painel {hora} · índice {hg}: {exato.sum()}/{len(c)} municípios exatos; "
              f"votos fora do lugar {erro:,.0f} de {tot:,.0f} ({100 * erro / max(tot, 1):.2f}%)", flush=True)


if __name__ == "__main__":
    main()
