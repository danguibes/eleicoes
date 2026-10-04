"""A noite da eleição: o publicador. Quem coleta são o coletor.py (SP, urna a urna) e o
nacional.py (Brasil, por município), em processos próprios — o noite.py sobe os três.

    python noite.py                        # a noite inteira: 2 coletores + publicador
    python domingo.py                      # só o publicador
    python domingo.py --sem-publicar       # tudo, menos o git push
    python domingo.py --ensaio             # 2022 reproduzido na ordem real de chegada (capital)

A cada 30 s, se o coletor de SP ou o nacional gravou dado novo: refaz a projeção,
os painéis (Brasil; SP nos três cargos) e publica (git push → Actions → Pages).
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
    subprocess.run(["git", "add", "web/metodo.html", "web/dados/", "out/"], check=True)
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
    ap.add_argument("--intervalo", type=int, default=30)
    ap.add_argument("--taxa", type=float, default=40)
    ap.add_argument("--sem-publicar", action="store_true")
    ap.add_argument("--estado", action="store_true", help="coleta a UF inteira e gera o painel (3 cargos)")
    ap.add_argument("--boot", type=int, default=50, help="reamostragens do painel por rodada")
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

    # publicador: não coleta nada (quem coleta é o coletor.py e o nacional.py, em
    # processos próprios — ver noite.py). Quando um dos dois grava dado novo, refaz
    # as projeções e os painéis e publica.
    import painel
    import painel_brasil
    sp = Path("data/raw") / a.pleito / "sp" / "secoes.jsonl"
    nac = Path("data/raw") / a.pleito / "nacional" / "municipios.parquet"
    cargos = ["presidente", "governador", "senador"]
    for c in cargos:
        painel.preparar("2026", c)
    visto = {sp: 0, nac: 0}
    ultimo_push, pendente = 0.0, None
    print("publicador pronto", flush=True)
    while True:
        t, feito = time.time(), []
        if nac.exists() and nac.stat().st_mtime > visto[nac]:
            visto[nac] = nac.stat().st_mtime
            try:
                d = painel_brasil.montar("2026", n_boot=a.boot)
                feito.append(f"Brasil {d['meta']['apuradas']:,}/{d['meta']['secoes']:,}")
            except Exception as e:
                print(f"   painel Brasil: {e!r}", flush=True)
        if sp.exists() and sp.stat().st_mtime > visto[sp]:
            visto[sp] = sp.stat().st_mtime
            tabelar.tabelar(a.pleito, "sp", cargos=cargos)
            for c in cargos:
                try:
                    d = painel.montar("2026", cargo=c, n_boot=a.boot)
                    if c == "presidente":
                        feito.append(f"SP {d['meta']['apuradas']:,}/{d['meta']['secoes']:,}")
                except Exception as e:  # um cargo com problema não derruba os outros
                    print(f"   painel SP {c}: {e!r}", flush=True)
        if feito:
            pendente = feito
        if pendente:
            hora = datetime.now().strftime("%H:%M")
            # um deploy a cada 2 min no máximo (cada um leva ~20 s no Actions): o Pages enfileira e pode recusar deploys
            # demais por hora; as rodadas do intervalo saem juntas no próximo push
            if not a.sem_publicar and time.time() - ultimo_push >= 120:
                publicar(f"Apuração {hora}: " + " · ".join(pendente))
                ultimo_push, pendente = time.time(), None
            if feito:
                print(f"{hora}  {' · '.join(feito)} seções; rodada em {time.time() - t:.0f} s", flush=True)
        time.sleep(max(5, a.intervalo - (time.time() - t)))


if __name__ == "__main__":
    main()
