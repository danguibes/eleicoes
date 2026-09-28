"""Coletor da camada rápida: o resultado parcial de cada município do país (arquivo `u`, EA20).

A cada rodada, varre os ~5.700 municípios (e cidades do exterior) com GET
condicional — o que não mudou volta 304, sem corpo — com teto próprio de
requisições, para sobrar ritmo para os boletins urna a urna de SP.

A lista de municípios vem do arquivo de configuração do TSE (`mun-e<eleição>-cm.json`,
EA12) quando ele existe; senão, do cadastro de 2026 já baixado. Nunca se pede um
município que nenhuma das duas listas contenha: 404 em excesso bloqueia o IP.

Grava data/raw/<pleito>/nacional/municipios.parquet: por município, as seções
totalizadas e totais, eleitores das seções totalizadas e totais, comparecimento,
brancos, nulos e os votos de cada candidato.

    python nacional.py --pleito simulado --uma-vez
    python nacional.py --pleito 2026 --taxa 15
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from tse import PLEITOS, Bloqueado, Cliente

RAW = Path("data/raw")


def n(x):
    try:
        return int(str(x).replace(".", ""))
    except (TypeError, ValueError):
        return 0


def lista_municipios(p, cli, destino):
    """[(uf, mun5)] pela configuração do TSE; reserva: o cadastro de 2026."""
    url = f"{p.raiz()}/{p.eleicao}/config/mun-e{p.eleicao:06d}-cm.json"
    st, corpo, _ = cli.get(url)
    if st == 200:
        (destino / "mun-cm.json").write_bytes(corpo)
        cm = json.loads(corpo)
        out = [(a["cd"].lower(), m["cd"]) for a in cm.get("abr", []) for m in a.get("mu", [])]
        if out:
            print(f"lista do TSE: {len(out):,} municípios", flush=True)
            return out
    l = pd.read_parquet(RAW / "tse" / "locais_2026_BR.parquet", columns=["SG_UF", "CD_MUNICIPIO"]).drop_duplicates()
    out = [(u.lower(), f"{int(m):05d}") for u, m in zip(l.SG_UF, l.CD_MUNICIPIO)]
    print(f"configuração de municípios respondeu {st}; usando o cadastro de 2026: {len(out):,} municípios", flush=True)
    return out


def ler_u(corpo):
    d = json.loads(corpo)
    s, e, v = d.get("s", {}), d.get("e", {}), d.get("v", {})
    lin = {"st": n(s.get("st")), "ts": n(s.get("ts")), "est": n(e.get("est")), "te": n(e.get("te")),
           "c": n(e.get("c")), "vb": n(v.get("vb")), "vn": n(v.get("tvn")), "dg": d.get("dg"), "hg": d.get("hg")}
    for cg in d.get("carg", []):
        for ag in cg.get("agr", []):
            for pa in ag.get("par", []):
                for ca in pa.get("cand", []):
                    lin[f"n{n(ca.get('n'))}"] = n(ca.get("vap"))
    return lin


class Nacional:
    def __init__(self, pleito, taxa=15, cargo=1):
        self.p = PLEITOS[pleito]
        self.cli = Cliente(taxa=taxa)
        self.cargo = cargo
        self.dir = RAW / pleito / "nacional"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.etags, self.linhas, self.ufs = {}, {}, {}
        self.muns = lista_municipios(self.p, self.cli, self.dir)

    def url_uf(self, uf):
        suf = "v" if self.p.ciclo == "ele2022" else "u"
        return f"{self.p.raiz()}/{self.p.eleicao}/dados/{uf}/{uf}-c{self.cargo:04d}-e{self.p.eleicao:06d}-{suf}.json"

    def rodada(self):
        """Antes de varrer os municípios de uma UF, confirma que o arquivo da UF existe.
        Sem isso, rodar antes de o TSE publicar pediria ~5.700 endereços inexistentes
        por rodada — e 404 em excesso bloqueia o IP."""
        t0, mudou, erros = time.time(), 0, 0
        ufs = sorted({uf for uf, _ in self.muns})
        prontas = set()
        for uf in ufs:
            url = self.url_uf(uf)
            st, corpo, etag = self.cli.get(url, self.etags.get(url))
            if st in (200, 304):
                prontas.add(uf)
                if st == 200:
                    self.etags[url] = etag
                    self.ufs[uf] = ler_u(corpo)
        if not prontas:
            print(f"{datetime.now():%H:%M:%S}  nenhum arquivo de UF publicado ainda", flush=True)
            return 0
        falhas = {}
        for uf, mun in self.muns:
            if uf not in prontas or falhas.get(uf, 0) >= 3:
                continue
            url = self.p.url_municipio(uf, mun, self.cargo)
            st, corpo, etag = self.cli.get(url, self.etags.get(url))
            if st == 200:
                self.etags[url] = etag
                self.linhas[(uf, mun)] = {"uf": uf.upper(), "municipio": int(mun), **ler_u(corpo)}
                mudou += 1
            elif st != 304:
                erros += 1
                falhas[uf] = falhas.get(uf, 0) + 1   # 3 falhas numa UF: para a UF nesta rodada
        t = pd.DataFrame(self.linhas.values())
        if len(t):
            tmp = self.dir / "municipios.tmp.parquet"
            t.to_parquet(tmp, index=False)
            tmp.replace(self.dir / "municipios.parquet")
        if self.ufs:
            pd.DataFrame([{"uf": u.upper(), **v} for u, v in self.ufs.items()]).to_parquet(self.dir / "ufs.parquet", index=False)
        tot = t.ts.sum() if len(t) else 0
        print(f"{datetime.now():%H:%M:%S}  {len(self.muns):,} municípios em {time.time() - t0:.0f} s; "
              f"{mudou:,} mudaram, {erros} erros; seções totalizadas {t.st.sum() if len(t) else 0:,}/{tot:,}; "
              f"{self.cli.contagem}", flush=True)
        return mudou


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", choices=sorted(PLEITOS), required=True)
    ap.add_argument("--taxa", type=float, default=15)
    ap.add_argument("--intervalo", type=int, default=60)
    ap.add_argument("--uma-vez", action="store_true")
    a = ap.parse_args()
    nac = Nacional(a.pleito, a.taxa)
    try:
        while True:
            t = time.time()
            nac.rodada()
            if a.uma_vez:
                break
            time.sleep(max(5, a.intervalo - (time.time() - t)))
    except Bloqueado as e:
        sys.exit(f"PARADO: {e}. Espere 10 minutos antes de tentar de novo.")


if __name__ == "__main__":
    main()
