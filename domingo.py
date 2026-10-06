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


def publicar_2t(a):
    """2º turno: refaz o painel quando o arquivo dos municípios (nacional.py) ou o índice de
    seções (indices.py) mudam; publica no máximo a cada 2 min."""
    import painel_2t
    raiz = Path("data/raw") / a.pleito
    vigiados = [raiz / "nacional" / "municipios.parquet", raiz / "indices" / "chegadas.parquet"]
    visto = {p: 0 for p in vigiados}
    ultimo_push, pendente = 0.0, None
    print("publicador do 2º turno pronto", flush=True)
    while True:
        t = time.time()
        novo = [p for p in vigiados if p.exists() and p.stat().st_mtime > visto[p]]
        if novo and vigiados[0].exists():
            for p in novo:
                visto[p] = p.stat().st_mtime
            try:
                d = painel_2t.montar("2026t2", ano_base=a.base, n_boot=a.boot, pleito=a.pleito, saida=a.saida)
                ic = d["ic"].get("total", {}).get("total", {})
                pendente = f"Brasil {d['meta']['apuradas']:,}/{d['meta']['secoes']:,}" + (f" · Lula {ic['lula']}" if ic else "")
                print(f"{datetime.now():%H:%M}  {pendente}; rodada em {time.time() - t:.0f} s", flush=True)
            except Exception as e:
                print(f"   painel do 2º turno: {e!r}", flush=True)
        if pendente and not a.sem_publicar and time.time() - ultimo_push >= 120:
            publicar(f"2º turno {datetime.now():%H:%M}: {pendente}")
            ultimo_push, pendente = time.time(), None
        time.sleep(max(5, a.intervalo - (time.time() - t)))


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
    ap.add_argument("--turno", type=int, default=1)
    ap.add_argument("--base", choices=["2022", "2026"], default="2026", help="2º turno: 1º turno por seção de qual ano")
    ap.add_argument("--saida", help="2º turno: nome do arquivo do painel (o ensaio não sobrescreve o da noite)")
    a = ap.parse_args()
    if a.turno == 2:
        return publicar_2t(a)

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
    import painel_sp_mun
    # governador e senador de SP por município (sp_municipios.py): em dia, enquanto os
    # boletins de urna chegam com 20-40 min de atraso
    est = {cg: Path("data/raw") / a.pleito / f"sp_{cg}" / "municipios.parquet" for cg in ("governador", "senador")}
    visto = {sp: 0, nac: 0, **{p: 0 for p in est.values()}}
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
        for cg, p in est.items():
            if p.exists() and p.stat().st_mtime > visto[p]:
                visto[p] = p.stat().st_mtime
                try:
                    d = painel_sp_mun.montar(cg, n_boot=200)
                    feito.append(f"{cg} SP {d['meta']['apuradas']:,}/{d['meta']['secoes']:,}")
                except Exception as e:
                    print(f"   painel SP {cg} por município: {e!r}", flush=True)
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
