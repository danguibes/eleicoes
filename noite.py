"""Sobe a noite inteira: os dois coletores e o publicador, cada um no seu processo.

    python noite.py                    # 2026 (começa a pedir às 16:45; --inicio muda)
    python noite.py --pleito simulado  # ensaio contra o simulado do TSE (sem publicar)

  coletor.py  --uf sp      boletins urna a urna do estado de SP   (50 req/s)
  nacional.py              resultado parcial de cada município     (15 req/s)
  domingo.py               projeções, painéis e publicação

Os dois coletores somam 65 req/s, abaixo do teto de 100 do TSE. Cada processo
grava o próprio log em data/raw/logs/. Se um cair, é reiniciado; se caiu por
bloqueio do TSE (sai com "PARADO"), espera 11 minutos antes — o bloqueio é de 10 e
recomeça a cada nova tentativa.
"""
import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

LOGS = Path("data/raw/logs")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", default="2026")
    ap.add_argument("--inicio", default="16:45", help="não manda nenhum pedido antes desta hora (HH:MM)")
    ap.add_argument("--falso", action="store_true", help="ensaio contra o tse_falso.py local: sem horário, sem publicar")
    a = ap.parse_args()
    if a.falso:
        import os
        os.environ["TSE_FALSO"] = "1"   # herdado pelos filhos: tse.py aponta o 2026 para 127.0.0.1:8800
        a.inicio = "00:00"
    hh, mm = map(int, a.inicio.split(":"))
    while (datetime.now().hour, datetime.now().minute) < (hh, mm):
        # dormir sem pedir nada: antes da apuração, todo pedido é um 404
        print(f"{datetime.now():%H:%M:%S}  aguardando {a.inicio}", flush=True)
        time.sleep(60)
    LOGS.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    cmds = {
        "sp": [py, "coletor.py", "--pleito", a.pleito, "--uf", "sp", "--taxa", "50", "--trabalhadores", "16",
               "--intervalo", "30"],
        "nacional": [py, "nacional.py", "--pleito", a.pleito, "--taxa", "15", "--intervalo", "60"],
    }
    if a.pleito == "2026":
        cmds["publicador"] = [py, "domingo.py", "--pleito", a.pleito] + (["--sem-publicar"] if a.falso else [])
    procs, espera = {}, {}
    try:
        while True:
            for nome, cmd in cmds.items():
                p = procs.get(nome)
                if p is not None and p.poll() is None:
                    continue
                if p is not None:
                    log = (LOGS / f"{nome}.log").read_text(encoding="utf-8", errors="replace")[-2000:]
                    bloqueio = "PARADO" in log
                    espera[nome] = time.time() + (660 if bloqueio else 20)
                    print(f"{datetime.now():%H:%M:%S}  {nome} saiu (código {p.returncode})"
                          f"{' por BLOQUEIO do TSE — reinicia em 11 min' if bloqueio else '; reinicia em 20 s'}",
                          flush=True)
                    procs[nome] = None
                if time.time() >= espera.get(nome, 0):
                    f = open(LOGS / f"{nome}.log", "a", encoding="utf-8")
                    procs[nome] = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
                    print(f"{datetime.now():%H:%M:%S}  {nome} no ar (pid {procs[nome].pid})", flush=True)
            time.sleep(5)
    except KeyboardInterrupt:
        for p in procs.values():
            if p is not None and p.poll() is None:
                p.terminate()
        print("parado", flush=True)


if __name__ == "__main__":
    main()
