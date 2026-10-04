"""Governador e senador de SP por município: o arquivo `u` (EA20) da eleição estadual.

Nasceu às 19h de domingo, 04/10/2026. Os dois cargos saíam só dos boletins de urna,
e o TSE estava publicando o auxiliar de cada seção 20 a 40 minutos depois de listá-la
no índice. Numa amostra de 40 seções chegadas entre 18h09 e 18h25, 22 ainda davam
404. Com o orçamento de 404, o coletor de boletins ia a ~3 seções/s. Enquanto isso, o
arquivo por município da capital já tinha 38% das seções de governador. Os boletins
continuam: dão o detalhe por local. Esta camada dá o estado em dia.

Os mesmos 645 municípios, dois cargos, GET condicional. Nenhum endereço fora da lista
do TSE, então nenhum 404 depois da publicação.

    python sp_municipios.py --taxa 10
"""
import argparse
import dataclasses
import sys
import time

import pandas as pd

from nacional import Nacional, ler_u
from tse import PLEITOS, Bloqueado

ELEICAO_ESTADUAL = 6259
CARGOS = {3: "governador", 5: "senador"}


class Estadual(Nacional):
    def __init__(self, pleito, taxa, cargo):
        PLEITOS[f"{pleito}_est"] = dataclasses.replace(PLEITOS[pleito], eleicao=ELEICAO_ESTADUAL)
        super().__init__(f"{pleito}_est", taxa, cargo)
        self.dir = self.dir.parent.parent / pleito / f"sp_{CARGOS[cargo]}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.muns = [(u, m) for u, m in self.muns if u == "sp"]

    def rodada(self):
        # só SP: dispensa a sondagem nacional e os arquivos das outras UFs
        t0, mudou, erros = time.time(), 0, 0
        for uf, mun in self.muns:
            url = self.p.url_municipio(uf, mun, self.cargo)
            st, corpo, etag = self.cli.get(url, self.etags.get(url))
            if st == 200:
                self.etags[url] = etag
                self.linhas[(uf, mun)] = {"uf": "SP", "municipio": int(mun), **ler_u(corpo)}
                mudou += 1
            elif st != 304:
                erros += 1
                if st == 404 and not self.linhas:
                    break   # ainda não publicado: um 404 por rodada, não 645
        t = pd.DataFrame(self.linhas.values())
        if len(t):
            tmp = self.dir / "municipios.tmp.parquet"
            t.to_parquet(tmp, index=False)
            tmp.replace(self.dir / "municipios.parquet")
        print(f"{time.strftime('%H:%M:%S')}  {CARGOS[self.cargo]}: {len(self.muns)} municípios em "
              f"{time.time() - t0:.0f} s; {mudou} mudaram, {erros} erros; seções "
              f"{t.st.sum() if len(t) else 0:,}/{t.ts.sum() if len(t) else 0:,}; {self.cli.contagem}", flush=True)
        return mudou


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", default="2026")
    ap.add_argument("--taxa", type=float, default=10)
    ap.add_argument("--intervalo", type=int, default=60)
    a = ap.parse_args()
    cs = [Estadual(a.pleito, a.taxa, c) for c in CARGOS]
    for c in cs[1:]:
        c.cli = cs[0].cli   # um só teto de requisições para os dois cargos
    try:
        while True:
            t = time.time()
            for c in cs:
                c.rodada()
            time.sleep(max(5, a.intervalo - (time.time() - t)))
    except Bloqueado as e:
        sys.exit(f"PARADO: {e}. Espere 10 minutos antes de tentar de novo.")


if __name__ == "__main__":
    main()
