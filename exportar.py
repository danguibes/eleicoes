"""Gera web/index.html: página única, autocontida, com o que já foi medido.

O pipeline roda nesta máquina (o CDN do TSE recusa script em qualquer IP, e a
coleta da noite precisa rodar perto da apuração), então a página é gerada aqui e
o Actions só publica. Os números vêm dos arquivos em out/, versionados — nunca
de número copiado à mão para o template.

    python exportar.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

OUT = Path("out")
RAW = Path("data/raw")


def curva_chegada(pleito="2022", uf="sp", mun=71072, pontos=200):
    """Contagem acumulada de Presidente na ordem real de chegada das urnas.

    Gera out/chegada_<pleito>_<mun>.csv a partir da coleta, quando ela existe
    localmente; senão usa o CSV versionado.
    """
    arq = OUT / f"chegada_{pleito}_{mun}.csv"
    d = RAW / pleito / uf
    if (d / "votos.parquet").exists():
        v = pd.read_parquet(d / "votos.parquet")
        v = v[(v.cargo == "presidente") & (v.municipio == mun) & (v.tipo == "nominal")]
        ch = pd.read_csv(d / "chegadas.csv", dtype=str)
        ch["t"] = pd.to_datetime(ch.recebido, format="%d/%m/%Y %H:%M:%S")
        ch["zona"], ch["secao"] = ch.zona.astype(int), ch.secao.astype(int)
        p = v.pivot_table(index=["zona", "secao"], columns="codigo", values="votos",
                          aggfunc="sum").fillna(0)
        p.columns = [f"c{int(c)}" for c in p.columns]
        cands = list(p.columns)
        p["validos"] = p[cands].sum(axis=1)
        p = p.join(ch.set_index(["zona", "secao"]).t).sort_values("t")
        cum = p[cands + ["validos"]].cumsum()
        n = len(p)
        idx = sorted({max(0, int(round(q * n)) - 1) for q in
                      [i / pontos for i in range(1, pontos + 1)]})
        linhas = []
        for i in idx:
            r = cum.iloc[i]
            linhas.append({"hora": p.t.iloc[i].strftime("%H:%M:%S"),
                           "secoes": i + 1, "frac": (i + 1) / n,
                           **{c: r[c] / r.validos * 100 for c in cands}})
        pd.DataFrame(linhas).to_csv(arq, index=False, float_format="%.4f")
    return pd.read_csv(arq)


def main(ao_vivo=None):
    """ao_vivo: '2026' na noite; 'ensaio' grava web/ensaio.html (nunca publicado)."""
    sys.stdout.reconfigure(encoding="utf-8")
    cur = curva_chegada()
    cas = pd.read_csv(OUT / "casamento_2022_71072.csv")
    dados = {
        "gerado": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "chegada2022": {
            "hora": cur.hora.tolist(), "frac": cur.frac.round(4).tolist(),
            "lula": cur.c13.round(2).tolist(), "bolsonaro": cur.c22.round(2).tolist(),
            "secoes": int(cur.secoes.iloc[-1]),
        },
        "casamento": cas.fillna("").to_dict(orient="records"),
    }
    chave = ao_vivo or ("2026" if (OUT / "ao_vivo_2026.json").exists() else None)
    if chave:
        dados["aovivo"] = json.loads((OUT / f"ao_vivo_{chave}.json").read_text(encoding="utf-8"))
    ens = OUT / "ensaio_projecao_2018_2022.csv"
    if ens.exists():
        dados["ensaio"] = pd.read_csv(ens).round(3).to_dict(orient="records")
    for nome, arq in [("ens_sp", "ensaio_projecao_2018_2022_SP.csv"), ("ens_br", "ensaio_projecao_2018_2022_BR.csv"),
                      ("ens_mun", "ensaio_municipal_2018_2022_BR.csv"), ("atraso", "atraso_coleta_2022.csv"),
                      ("quintis", "quintis_2022.csv"), ("rendarel", "renda_x_religiao_2022.csv"),
                      ("regua", "busca_ei_comparecimento_2022.csv"), ("grupos", "voto_por_grupo_2022.csv")]:
        if (OUT / arq).exists():
            dados[nome] = pd.read_csv(OUT / arq).round(2).to_dict(orient="records")
    tpl = Path("web/template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DADOS__*/null", json.dumps(dados, ensure_ascii=False))
    if "/*__DADOS__*/null" in html:
        sys.exit("placeholder não substituído")
    # página de checagens: dado próprio, mesmo mecanismo de injeção
    ck = OUT / "checagens_2022.json"
    if ck.exists():
        t2 = Path("web/checagens_template.html").read_text(encoding="utf-8")
        h2 = t2.replace("/*__DADOS__*/null", ck.read_text(encoding="utf-8"))
        Path("web/checagens.html").write_text(h2, encoding="utf-8")
    destino = Path("web/ensaio.html" if ao_vivo == "ensaio" else "web/metodo.html")
    destino.write_text(html, encoding="utf-8")
    print(f"{destino}: {len(html) // 1024} KB", flush=True)


if __name__ == "__main__":
    main()
