"""Boletins de urna do Brasil inteiro, UF por UF, depois da apuração.

Na noite, baixar os ~470 mil boletins do país não cabia no tempo da apuração, e o
país ficou na camada por município (nacional.py). Depois que tudo está totalizado, o
tempo deixa de importar: este script passa por cada UF com o mesmo coletor de SP até
não sobrar seção pendente. Serve à página de checagens de 2026 (consistência,
Benford e urnas atípicas, seção a seção) e é a base do 2º turno: cada seção de 2026
comparada com ela mesma no 1º turno.

    python coletar_brasil.py --taxa 40 --trabalhadores 12
    python coletar_brasil.py --ufs ac rr      # só algumas
"""
import argparse
import json
import sys
import time
from pathlib import Path

from coletor import Coletor, agora
from tse import Bloqueado

RAW = Path("data/raw")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", default="2026")
    ap.add_argument("--ufs", nargs="*")
    ap.add_argument("--pular", nargs="*", default=["sp"], help="UFs coletadas por outro processo")
    ap.add_argument("--taxa", type=float, default=40)
    ap.add_argument("--trabalhadores", type=int, default=12)
    a = ap.parse_args()
    cm = json.loads((RAW / a.pleito / "nacional" / "mun-cm.json").read_text(encoding="utf-8"))
    ufs = a.ufs or sorted(x["cd"].lower() for x in cm["abr"])
    ufs = [u for u in ufs if u not in a.pular]
    try:
        for uf in ufs:
            c = Coletor(a.pleito, uf, None, a.taxa, a.trabalhadores)
            vazias = 0
            while True:
                feitas = c.rodada()
                # duas rodadas seguidas sem nada novo: o que sobrou é 404 persistente
                vazias = vazias + 1 if feitas == 0 else 0
                if vazias >= 2:
                    break
                time.sleep(5 if feitas else 60)
            print(f"{agora()}  {uf.upper()} pronta", flush=True)
    except Bloqueado as e:
        sys.exit(f"PARADO: {e}. Espere 10 minutos antes de tentar de novo.")


if __name__ == "__main__":
    main()
