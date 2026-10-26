"""2º turno de 2026: o log de TODAS as urnas com boletim que fecharam depois das 17:15 (Brasília).

A prorrogação até as 19h (STF, 25/10) chegou tarde e só valeu onde a seção ainda estava aberta:
os votos tardios se concentram em poucas urnas, e uma amostra aleatória quase não as pega. Aqui se
conta, voto a voto, quantos foram computados depois das 17h nessas urnas. As que fecharam até 17:15
ficam com a amostra aleatória (hora_do_voto.py), que mede a fila normal das 17h.

    python hora_do_voto_tardias.py
"""
import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tse
from hora_do_voto_analise import fuso, segundos

RAW = Path("data/raw")
SAIDA = RAW / "2026_2t" / "hora_do_voto" / "tardias.jsonl"
CORTE = segundos("17:15:00")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = tse.obter("2026_2t")
    cli = tse.Cliente(taxa=15, max_404=30)
    feitas = set()
    if SAIDA.exists():
        feitas = {(r["uf"], r["zona"], r["secao"]) for r in map(json.loads, open(SAIDA, encoding="utf-8"))}
    alvo = []
    for f in sorted(RAW.glob("2026_2t/*/secoes.jsonl")):
        uf = f.parent.name
        if uf == "zz":
            continue
        vis = {}
        for ln in open(f, encoding="utf-8"):
            s = json.loads(ln)
            vis[(s["zona"], s["secao"])] = s
        for s in vis.values():
            if not (s.get("abertura") and s.get("encerramento")):
                continue
            e = s["encerramento"]
            t = segundos(f"{e[9:11]}:{e[11:13]}:{e[13:15]}") + fuso(s["abertura"]) * 3600
            if t >= CORTE and (uf.upper(), s["zona"], s["secao"]) not in feitas:
                alvo.append((uf, s, t))
    print(f"{len(alvo):,} urnas a baixar", flush=True)

    def um(x):
        uf, s, t = x
        mun, z, sec = f"{s['municipio']:05d}", f"{s['zona']:04d}", f"{s['secao']:04d}"
        st, b, _ = cli.get(p.url_arquivo(uf, mun, z, sec, s["hash"], f"o{p.pleito:05d}{uf}{mun}{z}{sec}-log.jez"))
        r = {"uf": uf.upper(), "municipio": s["municipio"], "zona": s["zona"], "secao": s["secao"], "encerramento": t}
        if st != 200:
            return {**r, "erro": st}
        off = fuso(s["abertura"]) * 3600
        L = zipfile.ZipFile(io.BytesIO(b)).read("logd.dat").decode("latin-1").splitlines()
        seg = [segundos(l[11:19]) + off for l in L if l.startswith("25/10/2026") and "O voto do eleitor foi computado" in l]
        return {**r, "votos": len(seg), "depois_17": sum(x >= 17 * 3600 for x in seg), "depois_1705": sum(x >= 17 * 3600 + 300 for x in seg),
                "depois_18": sum(x >= 18 * 3600 for x in seg), "ultimo": max(seg) if seg else None}

    with open(SAIDA, "a", encoding="utf-8") as f, ThreadPoolExecutor(8) as ex:
        for i, r in enumerate(ex.map(um, alvo), 1):
            f.write(json.dumps(r) + "\n")
            if i % 250 == 0:
                print(f"  {i:,}/{len(alvo):,} {cli.contagem}", flush=True)
    print("pronto", cli.contagem, flush=True)


if __name__ == "__main__":
    main()
