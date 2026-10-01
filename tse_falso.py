"""Um TSE de mentira, nesta máquina: a noite de 2022 servida nos endereços e no formato de 2026.

Serve para ensaiar a noite inteira (coletores, publicador, painéis) sem tocar o
TSE: o simulado deles fechou antes de dar para testar (29/09/2026), e o
ambiente oficial só ganha dados no domingo. Nada aqui sai desta máquina.

Relógio: ao subir, o servidor fixa 2022-10-02 17:00 e anda ACEL vezes mais rápido.
Responde, com os códigos de 2026 (ciclo ele2026, pleito 3220, eleição 6257):

  .../arquivo-urna/3220/config/sp/sp-p003220-cs.json      índice de SP; `da`/`ha` só
                                                          nas seções já chegadas
  .../arquivo-urna/3220/dados/sp/<mun>/<zona>/<sec>/...-aux.json   auxiliar (formato
                                                          2026, `arq`); 404 se não chegou
  .../<sec>/<hash>/<nome>.bu                              o BU real de 2022, do disco
  .../6257/dados/<uf>/<uf><mun>-c0001-e006257-u.json      parcial do município
  .../6257/dados/<uf>/<uf>-c0001-e006257-u.json           parcial da UF

com ETag e 304, como o de verdade. Os boletins são de 2022 — quem os lê precisa
da especificação de 2022 (TSE_FALSO=1 troca isso no tse.py).

    python tse_falso.py --acel 15
"""
import argparse
import gzip
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path("data/raw")
INICIO = datetime(2022, 10, 2, 17, 0)
CANDS = [13, 22, 15, 12, 44, 30, 14, 16, 21, 27, 80]


class Noite:
    def __init__(self, acel):
        self.acel, self.t0 = acel, time.time()
        # --- SP urna a urna: índice e hora de chegada de cada seção
        self.cs = json.loads(sorted((RAW / "2022" / "sp" / "cs").glob("*.json"))[0].read_text(encoding="utf-8"))
        ch = pd.read_csv(RAW / "2022" / "sp" / "chegadas.csv", dtype=str)
        ch["t"] = pd.to_datetime(ch.recebido, format="%d/%m/%Y %H:%M:%S")
        self.chegada = {(m, z, s): t for m, z, s, t in zip(ch.municipio, ch.zona, ch.secao, ch.t)}
        # --- Brasil por município: votos de cada seção e hora de chegada (dados abertos)
        import brasil as br
        v, _ = br.votos_secao("2022", {c: f"c{c}" for c in CANDS})
        d = br.detalhe_2022()
        s = v.merge(d, on=["zona", "secao"], how="inner").sort_values("t")
        s["vb"] = s.get("bn", 0)
        cols = [f"c{c}" for c in CANDS]
        s["outros"] = s.get("outros", 0)
        self.mun = {}
        for (uf, mun), g in s.groupby(["uf", "municipio"]):
            t = g.t.to_numpy()
            acum = np.cumsum(np.c_[np.ones(len(g)), g.aptos, g.comparecimento, g[cols].fillna(0), g.bn.fillna(0)], axis=0)
            tot = acum[-1]
            self.mun[(uf.lower(), f"{int(mun):05d}")] = (t, acum, tot)
        print(f"pronto: {len(self.chegada):,} seções de SP, {len(self.mun):,} municípios", flush=True)

    def agora(self):
        return INICIO + timedelta(seconds=(time.time() - self.t0) * self.acel)

    # ---------------------------------------------------------------- respostas
    def cs_json(self):
        a = self.agora()
        out = {k: v for k, v in self.cs.items() if k != "abr"}
        out["dg"], out["hg"], out["idg"], out["cdp"], out["f"] = a.strftime("%d/%m/%Y"), a.strftime("%H:%M:%S"), str(int(a.timestamp())), "3220", "o"
        abr = []
        for ab in self.cs["abr"]:
            mus = []
            for mu in ab["mu"]:
                zs = []
                for z in mu["zon"]:
                    secs = []
                    for s in z["sec"]:
                        s2 = {k: v for k, v in s.items() if k not in ("da", "ha")}
                        t = self.chegada.get((mu["cd"], z["cd"], s["ns"]))
                        if t is not None and t <= a and "nsp" not in s:
                            s2["da"], s2["ha"] = t.strftime("%d/%m/%Y"), t.strftime("%H:%M:%S")
                        secs.append(s2)
                    zs.append({"cd": z["cd"], "sec": secs})
                mus.append({**{k: v for k, v in mu.items() if k != "zon"}, "zon": zs})
            abr.append({**{k: v for k, v in ab.items() if k != "mu"}, "mu": mus})
        out["abr"] = abr
        return out

    def aux_json(self, mun, zona, secao):
        t = self.chegada.get((mun, zona, secao))
        if t is None or t > self.agora():
            return None
        nome = f"o00406-{mun}{zona}{secao}.bu"
        h = hashlib.sha1(f"{mun}{zona}{secao}".encode()).hexdigest()
        return {"dg": t.strftime("%d/%m/%Y"), "hg": t.strftime("%H:%M:%S"), "f": "o", "st": "Totalizada",
                "hashes": [{"hash": h, "dr": t.strftime("%d/%m/%Y"), "hr": t.strftime("%H:%M:%S"),
                            "st": "Totalizado", "arq": [{"nm": nome, "tp": "bu"}]}]}

    def u_json(self, uf, mun=None):
        a = np.datetime64(self.agora())
        if mun and (uf, mun) not in self.mun:
            return None   # município que só existe em 2026: 404, como o de verdade
        itens = [self.mun[(uf, mun)]] if mun else [x for (u, _), x in self.mun.items() if u == uf]
        if not itens:
            return None
        ap = np.zeros(len(CANDS) + 4)
        tot = np.zeros(len(CANDS) + 4)
        for t, acum, tt in itens:
            k = np.searchsorted(t, a, side="right")
            if k:
                ap += acum[k - 1]
            tot += tt
        st, est, c = int(ap[0]), int(ap[1]), int(ap[2])
        cand = [{"n": str(n), "nm": f"CANDIDATO {n}", "nmu": f"CANDIDATO {n}", "vap": str(int(ap[3 + i]))}
                for i, n in enumerate(CANDS)]
        ag = self.agora()
        return {"ele": "6257", "dg": ag.strftime("%d/%m/%Y"), "hg": ag.strftime("%H:%M:%S"),
                "s": {"ts": str(int(tot[0])), "st": str(st)},
                "e": {"te": str(int(tot[1])), "est": str(est), "c": str(c)},
                "v": {"vb": str(int(ap[-1])), "tvn": "0"},
                "carg": [{"cd": "1", "agr": [{"par": [{"cand": cand}]}]}]}


class Handler(BaseHTTPRequestHandler):
    noite = None

    def log_message(self, *a):
        pass

    def responder(self, corpo, tipo="application/json"):
        if corpo is None:
            self.send_response(404); self.end_headers(); return
        if not isinstance(corpo, bytes):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        etag = '"' + hashlib.md5(corpo).hexdigest() + '"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304); self.send_header("ETag", etag); self.end_headers(); return
        z = "gzip" in (self.headers.get("Accept-Encoding") or "")
        dados = gzip.compress(corpo) if z else corpo
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("ETag", etag)
        if z:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        n, p = self.noite, self.path.split("?")[0]
        if m := re.fullmatch(r"/oficial/ele2026/arquivo-urna/3220/config/sp/sp-p003220-cs\.json", p):
            return self.responder(n.cs_json())
        if m := re.fullmatch(r"/oficial/ele2026/arquivo-urna/3220/dados/sp/(\d{5})/(\d{4})/(\d{4})/p003220-sp-m\d{5}-z\d{4}-s\d{4}-aux\.json", p):
            return self.responder(n.aux_json(*m.groups()))
        if m := re.fullmatch(r"/oficial/ele2026/arquivo-urna/3220/dados/sp/(\d{5})/(\d{4})/(\d{4})/[0-9a-f]+/o00406-\d+\.bu", p):
            mun, zona, secao = m.groups()
            arq = RAW / "2022" / "sp" / "bu" / mun / zona / f"{secao}.bu"
            if self.noite.aux_json(mun, zona, secao) is None or not arq.exists():
                return self.responder(None)
            return self.responder(arq.read_bytes(), "application/octet-stream")
        if m := re.fullmatch(r"/oficial/ele2026/6257/dados/([a-z]{2})/([a-z]{2})(\d{5})-c0001-e006257-u\.json", p):
            return self.responder(n.u_json(m.group(1), m.group(3)))
        if m := re.fullmatch(r"/oficial/ele2026/6257/dados/([a-z]{2})/([a-z]{2})-c0001-e006257-u\.json", p):
            return self.responder(n.u_json(m.group(1)))
        return self.responder(None)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--acel", type=float, default=15)
    ap.add_argument("--porta", type=int, default=8800)
    a = ap.parse_args()
    Handler.noite = Noite(a.acel)
    srv = ThreadingHTTPServer(("127.0.0.1", a.porta), Handler)
    print(f"TSE de mentira em http://127.0.0.1:{a.porta} — relógio de 2022 a {a.acel:g}x", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
