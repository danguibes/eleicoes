"""Boletins de urna do Brasil inteiro DURANTE a noite: as 28 UFs revezando num processo só.

No 1º turno, o país urna a urna ficou para o dia seguinte (coletar_brasil.py, ~4 h). No 2º
turno, só com Presidente, a projeção vive bem com menos ritmo no arquivo por município, e
sobram ~35 req/s para os boletins: ~17 seções/s, as 27 UFs fora SP (~395 mil seções) em ~6-7 h —
de madrugada, não na manhã seguinte. Serve à página de não-votos (naovotos.py) por seção no país inteiro.

As peças são as do coletor.py, testadas no 1º turno: um Coletor por UF, mas todos com o MESMO
cliente (um teto de requisições e um orçamento de 404 para o processo inteiro), e cada rodada
pega no máximo `--limite` seções de cada UF, para nenhuma ficar para trás. Antes da publicação,
uma única sondagem por minuto ao índice da primeira UF: 28 índices em 404 a cada rodada dispararia a trava.

SP fica de fora: tem o próprio coletor.py, com espera de 4 min, porque o painel por local depende dele.

    python coletor_brasil_noite.py --pleito 2026_2t --taxa 35
"""
import argparse
import sys
import time

from coletor import Coletor, agora
from tse import Bloqueado, Cliente

UFS = ["mg", "rj", "ba", "rs", "pr", "pe", "ce", "pa", "sc", "go", "ma", "am", "es", "pb", "rn",
       "mt", "al", "pi", "df", "ms", "se", "ro", "to", "ac", "ap", "rr", "zz"]   # das maiores para as menores; SP tem o próprio


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", default="2026_2t")
    ap.add_argument("--ufs", nargs="*", default=UFS)
    ap.add_argument("--taxa", type=float, default=55)
    ap.add_argument("--trabalhadores", type=int, default=16)
    ap.add_argument("--espera", type=int, default=1800, help="segundos entre a hora do índice e o pedido do boletim")
    ap.add_argument("--limite", type=int, default=600, help="seções por UF por rodada")
    a = ap.parse_args()
    cli = Cliente(taxa=a.taxa)
    cs = []
    for uf in a.ufs:
        c = Coletor(a.pleito, uf, None, a.taxa, a.trabalhadores)
        c.cli = cli   # um teto e um orçamento de 404 para todas as UFs
        # o boletim sai 20-40 min depois da hora do índice (medido na noite do 1º turno); pedir antes é 404,
        # e o orçamento de 404 derrubou o ritmo para ~3 seções/s. Esta página não precisa ser instantânea.
        c.espera, c.em_voo = a.espera, a.trabalhadores
        cs.append(c)
    try:
        # antes da publicação: uma sondagem por minuto, no índice da primeira UF
        while True:
            try:
                cs[0].ler_indice()
                break
            except RuntimeError as e:
                print(f"{agora()}  {e}; de novo em 60 s", flush=True)
                time.sleep(60)
        while True:
            t0, feitas = time.time(), 0
            for c in cs:
                try:
                    feitas += c.rodada(a.limite)
                except RuntimeError as e:   # índice de uma UF ainda não publicado
                    print(f"{agora()}  {c.uf.upper()}: {e}", flush=True)
            print(f"{agora()}  volta pelas {len(cs)} UFs: {feitas:,} seções em {time.time() - t0:.0f} s; {cli.contagem}", flush=True)
            if feitas == 0:
                time.sleep(30)
    except Bloqueado as e:
        sys.exit(f"PARADO: {e}. Espere 10 minutos antes de tentar de novo.")


if __name__ == "__main__":
    main()
