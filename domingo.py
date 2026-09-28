"""A noite da eleição num comando: coletar, projetar, gerar a página, publicar — em ciclo.

    python domingo.py                      # 2026, capital, publica a cada rodada
    python domingo.py --sem-publicar       # tudo, menos o git push
    python domingo.py --ensaio             # 2022 reproduzido na ordem real de chegada,
                                           # base 2018, relógio acelerado, sem publicar

Cada rodada:
  1. coletor: índice de seções do TSE + BU de cada urna nova (para no 1º 403)
  2. tabelar: BUs -> votos.parquet (só Presidente, para ser rápido)
  3. projeção: urnas apuradas + previsão das que faltam, com intervalo
  4. out/ao_vivo_<pleito>.json ganha uma linha; exportar.py refaz a página
  5. git commit + push de web/ e out/ — o Actions publica em ~1 minuto

Se o TSE bloquear (403), o ciclo para e diz quanto esperar: insistir só
prolonga o bloqueio.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

OUT = Path("out")


def publicar(msg):
    subprocess.run(["git", "add", "web/index.html", "out/"], check=True)
    r = subprocess.run(["git", "commit", "-q", "-m", msg])
    if r.returncode == 0:
        subprocess.run(["git", "push", "-q"], check=False)


def registrar(pleito, res, hora):
    arq = OUT / f"ao_vivo_{pleito}.json"
    h = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"rodadas": []}
    res = {"hora": hora, **res}
    if res["secoes"] and (not h["rodadas"] or h["rodadas"][-1]["secoes"] != res["secoes"]):
        h["rodadas"].append(res)
    h["pleito"] = pleito
    h["atualizado"] = hora
    h["ultima"] = res
    arq.write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", default="2026")
    ap.add_argument("--mun", default="71072")
    ap.add_argument("--intervalo", type=int, default=60)
    ap.add_argument("--taxa", type=float, default=40)
    ap.add_argument("--sem-publicar", action="store_true")
    ap.add_argument("--ensaio", action="store_true")
    ap.add_argument("--acelerar", type=float, default=60, help="ensaio: minutos de 2022 por minuto real")
    a = ap.parse_args()

    import exportar
    import projecao
    import tabelar

    if a.ensaio:
        noite = projecao.Noite(pleito="2022", ano_cadastro="2022", base="2018", mun=int(a.mun))
        ch = pd.read_csv("data/raw/2022/sp/chegadas.csv", dtype=str)
        ch["t"] = pd.to_datetime(ch.recebido, format="%d/%m/%Y %H:%M:%S")
        ch = ch.sort_values("t")
        relogio = ch.t.iloc[0].floor("min")
        (OUT / "ao_vivo_ensaio.json").unlink(missing_ok=True)
        while relogio <= ch.t.iloc[-1] + timedelta(minutes=1):
            chegou = ch[ch.t <= relogio]
            apenas = set(zip(chegou.zona.astype(int), chegou.secao.astype(int)))
            t = time.time()
            res = noite.rodada(apenas=apenas)
            registrar("ensaio", res, relogio.strftime("%H:%M"))
            exportar.main(ao_vivo="ensaio")
            lb = {c["cat"]: c for c in res.get("candidatos", [])}
            if lb:
                print(f"{relogio:%H:%M}  {res['secoes']:>6} seções  contagem L−B "
                      f"{lb['lula']['contagem'] - lb['bolsonaro']['contagem']:+5.2f}  projeção "
                      f"{lb['lula']['projecao'] - lb['bolsonaro']['projecao']:+5.2f}  "
                      f"({time.time() - t:.0f} s)", flush=True)
            relogio += timedelta(minutes=a.acelerar * a.intervalo / 60)
        return

    from coletor import Coletor
    from tse import Bloqueado

    col = Coletor(a.pleito, "sp", [a.mun], a.taxa, 10)
    noite = projecao.Noite(pleito=a.pleito, ano_cadastro="2026", base="2022", mun=int(a.mun))
    print("pronto; entrando no ciclo", flush=True)
    while True:
        t = time.time()
        try:
            novas = col.rodada()
        except Bloqueado as e:
            sys.exit(f"PARADO pelo TSE: {e}. Espere 10 minutos inteiros antes de rodar de novo.")
        except RuntimeError as e:  # índice ainda não publicado (404 antes das 17h)
            print(f"{datetime.now():%H:%M:%S}  {e}; tentando de novo", flush=True)
            time.sleep(a.intervalo)
            continue
        if novas:
            tabelar.tabelar(a.pleito, "sp", cargos=["presidente"])
            res = noite.rodada()
            hora = datetime.now().strftime("%H:%M")
            registrar(a.pleito, res, hora)
            exportar.main(ao_vivo=a.pleito)
            if not a.sem_publicar:
                publicar(f"Apuração {hora}: {res['secoes']} de {res['total']} seções")
            print(f"{hora}  {res['secoes']}/{res['total']} seções, rodada em {time.time() - t:.0f} s",
                  flush=True)
        time.sleep(max(5, a.intervalo - (time.time() - t)))


if __name__ == "__main__":
    main()
