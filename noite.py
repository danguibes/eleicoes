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


def supervisionar(cmds):
    """Sobe os filhos e os reinicia se caírem; depois de bloqueio do TSE ("PARADO" no log), espera 11 min."""
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
                          f"{' por BLOQUEIO do TSE — reinicia em 11 min' if bloqueio else '; reinicia em 20 s'}", flush=True)
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


def noite_2t(a):
    """2º turno, só Presidente: arquivo por município (nacional.py), índice de seções das 28 UFs
    (indices.py), boletins de SP urna a urna (coletor.py) e o publicador (domingo.py --turno 2).

    Ensaio (--falso): contra o tse_falso.py --turno 2, com o pleito local "falso_2t" (pasta própria),
    a base do 1º turno de 2022, painel em web/dados/falso2t_*.json e sem publicar. O tse_falso não
    tem boletins do 2º turno de 2022: sem coletor de SP no ensaio."""
    p = "falso_2t" if a.falso else "2026_2t"
    if not a.falso:
        hh, mm = map(int, a.inicio.split(":"))
        while (datetime.now().hour, datetime.now().minute) < (hh, mm):
            print(f"{datetime.now():%H:%M:%S}  aguardando {a.inicio}", flush=True)
            time.sleep(60)
    LOGS.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    # somam 75 req/s, abaixo do teto de 100 do TSE. O nacional manda (no ensaio, 4 min por varredura a 25 req/s)
    cmds = {
        "nacional2t": [py, "nacional.py", "--pleito", p, "--taxa", "45", "--intervalo", "30"],
        "indices2t": [py, "indices.py", "--pleito", p, "--taxa", "5", "--intervalo", "30"],
        "publicador2t": [py, "domingo.py", "--turno", "2", "--pleito", p, "--boot", "40"]
                        + (["--base", "2022", "--saida", "falso2t", "--sem-publicar"] if a.falso else []),
    }
    if not a.falso:
        cmds["sp2t"] = [py, "coletor.py", "--pleito", p, "--uf", "sp", "--taxa", "25", "--trabalhadores", "8", "--intervalo", "30"]
    supervisionar(cmds)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", default="2026")
    ap.add_argument("--inicio", default="16:45", help="não manda nenhum pedido antes desta hora (HH:MM)")
    ap.add_argument("--falso", action="store_true", help="ensaio contra o tse_falso.py local: sem horário, sem publicar")
    ap.add_argument("--turno", type=int, default=1)
    a = ap.parse_args()
    if a.turno == 2:
        return noite_2t(a)
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
        "nacional": [py, "nacional.py", "--pleito", a.pleito, "--taxa", "25", "--intervalo", "30"],
        # governador e senador de SP por município (entrou às 19h de 04/10/2026)
        "sp_mun": [py, "sp_municipios.py", "--pleito", a.pleito, "--taxa", "10", "--intervalo", "30"],
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
