"""Robô da noite da eleição: acompanha as seções que chegam e baixa o BU de cada uma.

O caminho, de uma requisição barata para muitas caras:

  1. o índice de seções da UF (`cs`, EA16) — um GET, condicional, por rodada.
     Cada seção cujo auxiliar já foi gerado vem com data e hora (`da`/`ha`).
  2. para cada seção nova ou alterada, o auxiliar dela (`aux`, EA18), que diz o
     hash da transmissão válida e os nomes dos arquivos;
  3. o `.bu` daquele hash, decodificado na hora (2,4 ms por boletim).

Nunca se pede um endereço que um arquivo do TSE não tenha listado antes — 404 em
excesso bloqueia o IP.

Tudo que vem do TSE fica em data/raw/<pleito>/ (fora do git). O que o resto do
projeto lê é `secoes.jsonl` (uma linha por seção decodificada) e
`chegadas.csv` (quando cada seção apareceu no índice, e quando nós a vimos) — o
segundo é o que permite ensaiar a projeção na ordem em que as urnas chegaram de
verdade, e não numa ordem aleatória.

    python coletor.py --pleito 2022 --uf sp --mun 71072 --uma-vez
    python coletor.py --pleito simulado --uf sp --mun 71072 --intervalo 60
    python coletor.py --pleito 2026 --uf sp --mun 71072
"""
import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import bu
from tse import PLEITOS, Bloqueado, Cliente, obter

VALIDOS = {"Recebido", "Totalizado"}
ESPERA_CDN = 240   # s entre a hora do índice e o pedido do auxiliar (medido: ~5 min de defasagem)  # descarta Rejeitado, Excluído, Sem arquivo


def agora():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


class Coletor:
    def __init__(self, pleito, uf, municipios, taxa, trabalhadores):
        self.depois = {}   # seção -> quando pedir de novo, depois de um 404
        self.falhas = {}   # seção -> quantos 404 já deu
        self.p = obter(pleito)
        self.uf = uf
        self.municipios = set(municipios) if municipios else None
        self.cli = Cliente(taxa=taxa)
        self.trab = trabalhadores
        self.dir = Path("data/raw") / pleito / uf
        self.dir.mkdir(parents=True, exist_ok=True)
        self.arq_estado = self.dir / "estado.json"
        self.estado = (json.loads(self.arq_estado.read_text())
                       if self.arq_estado.exists() else
                       {"cs_etag": None, "secoes": {}})

    # -- índice ---------------------------------------------------------------
    def ler_indice(self):
        """Devolve {(mun, zona, secao): 'dd/mm/aaaa hh:mm:ss'} das seções com auxiliar.

        Com 304 relê a última versão guardada em vez de devolver "nada mudou": o
        índice parado não quer dizer que as seções dele já foram todas baixadas
        (uma rodada interrompida no meio deixa pendentes — foi assim que o
        primeiro ensaio parou em 30 de 26.288)."""
        st, corpo, etag = self.cli.get(self.p.url_cs(self.uf), self.estado["cs_etag"])
        if st == 304 and self.estado.get("cs_arquivo"):
            corpo = Path(self.estado["cs_arquivo"]).read_bytes()
        elif st != 200:
            raise RuntimeError(f"índice de seções respondeu {st}")
        cs = json.loads(corpo)
        if st == 200:
            # guarda cada versão do índice: é a série temporal da apuração
            (self.dir / "cs").mkdir(exist_ok=True)
            arq = self.dir / "cs" / f"{cs.get('idg', agora().replace(':', ''))}.json"
            arq.write_bytes(corpo)
            self.estado["cs_etag"] = etag
            self.estado["cs_arquivo"] = str(arq)
        prontas, total = {}, 0
        for abr in cs["abr"]:
            for mu in abr["mu"]:
                if self.municipios and mu["cd"] not in self.municipios:
                    continue
                for z in mu["zon"]:
                    for s in z["sec"]:
                        if "nsp" in s:
                            continue  # agregada: os votos vêm no BU da principal
                        total += 1
                        if s.get("da"):
                            prontas[(mu["cd"], z["cd"], s["ns"])] = f"{s['da']} {s['ha']}"
                        elif self.p.encerrado:
                            prontas[(mu["cd"], z["cd"], s["ns"])] = "encerrado"
        return prontas, total, cs.get("dg"), cs.get("hg")

    # -- uma seção ------------------------------------------------------------
    def buscar_secao(self, mun, zona, secao):
        if self.adiar.is_set():
            return {"erro": "adiado"}   # 404 demais nesta rodada: o resto fica para a próxima
        # orçamento de 404: a trava do cliente dispara em 31 por minuto; com 8 em voo, parar
        # de pedir ao chegar em 20 deixa no máximo 27. Os 404 vêm espalhados pela fila (o CDN
        # não publica na ordem do índice), então parar no 3º fazia rodadas de 20 seções.
        with self.cli.trava:
            agora_m = time.monotonic()
            while self.cli.n404 and agora_m - self.cli.n404[0] > 60:
                self.cli.n404.popleft()
            if len(self.cli.n404) >= 20:
                self.adiar.set()
                return {"erro": "adiado"}
        st, corpo, _ = self.cli.get(self.p.url_aux(self.uf, mun, zona, secao))
        if st == 404:
            # uma seção atrasada no CDN não pode parar a fila inteira: ela espera 3 min
            # e espera cada vez mais: em 05/10 havia seções com auxiliar ainda 404 treze horas
            # depois; na frente da fila, elas gastavam o orçamento de toda rodada, e as 58 mil
            # já publicadas atrás delas nunca eram pedidas
            k = (mun, zona, secao)
            self.falhas[k] = self.falhas.get(k, 0) + 1
            self.depois[k] = time.time() + min(3600, 180 * 2 ** (self.falhas[k] - 1))
        if st != 200:
            return {"erro": f"aux {st}"}
        aux = json.loads(corpo)
        hashes = [h for h in aux.get("hashes", []) if h.get("st") in VALIDOS]
        if not hashes:
            return {"situacao": aux.get("st"), "sem_bu": True}
        h = hashes[-1]
        # 2022 lista nomes em `nmarq`; 2026 em `arq: [{nm, tp}]`
        nomes = h.get("nmarq") or [a["nm"] for a in h.get("arq", [])]
        # .busa: BU do Sistema de Apuração, a contingência quando a urna falha.
        # Mesmo formato ASN.1. Em 2022 foram 2 das 101.073 seções de SP — e sem
        # isto elas sumiam caladas (a soma do estado ficava 400 votos curta).
        # 2026 mudou o nome: "o03220sp...-bu.dat" com "tp":"bu" (em 2022 era "....bu"). Escolhe
        # pelo TIPO quando ele vem; o nome só como reserva. Sem isto, nenhuma urna de SP
        # era lida — pego às 17h27 do domingo, nas primeiras 26 seções.
        tipos = {a["nm"]: a.get("tp") for a in h.get("arq", [])}
        nome_bu = (next((n for n, t in tipos.items() if t == "bu"), None)
                   or next((n for n, t in tipos.items() if t == "busa"), None)
                   or next((n for n in nomes if n.endswith(".bu")), None)
                   or next((n for n in nomes if n.endswith(".busa")), None))
        if not nome_bu:
            return {"situacao": aux.get("st"), "sem_bu": True, "hash": h["hash"]}
        st, conteudo, _ = self.cli.get(
            self.p.url_arquivo(self.uf, mun, zona, secao, h["hash"], nome_bu))
        if st != 200:
            return {"erro": f"bu {st}"}
        d = self.dir / "bu" / mun / zona
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{secao}.bu").write_bytes(conteudo)
        lido = bu.ler(conteudo, self.p.spec)
        lido.update({"hash": h["hash"], "recebido": f"{h.get('dr')} {h.get('hr')}",
                     "situacao": aux.get("st")})
        return lido

    # -- rodada ---------------------------------------------------------------
    def rodada(self, limite=None):
        prontas, total, dg, hg = self.ler_indice()
        vistas = self.estado["secoes"]
        novas = [k for k, quando in prontas.items()
                 if vistas.get("/".join(k), {}).get("indice") != quando
                 or not vistas.get("/".join(k), {}).get("bu", True)]   # sem BU legível: tenta de novo
        # O índice lista a seção como chegada ANTES de o auxiliar dela estar no CDN: pedir
        # na hora dava 404 em rajada, e às 17h43 de domingo a trava de 404 desligou o coletor
        # por 11 min. Medido em seguida: a seção entrou no índice às 17:49:53 e o auxiliar
        # ainda era 404 às 17:55 (200 às 17:56). Espera ESPERA_CDN depois da hora do índice.
        def madura(k):
            q = prontas[k]
            if q == "encerrado":
                return True
            try:
                return (datetime.now() - datetime.strptime(q, "%d/%m/%Y %H:%M:%S")).total_seconds() >= ESPERA_CDN
            except ValueError:
                return True
        verdes = len(novas)
        novas = [k for k in novas if madura(k) and self.depois.get(k, 0) <= time.time()]
        verdes -= len(novas)
        # da mais antiga para a mais nova: o CDN publica o auxiliar até ~18 min depois da hora
        # do índice (medido às 18h28: índice 18:10:52, Last-Modified 18:28:54). Quando a mais
        # antiga ainda dá 404, as mais novas também dariam — e a rodada para ali.
        def quando(k):
            try:
                return datetime.strptime(prontas[k], "%d/%m/%Y %H:%M:%S")
            except ValueError:
                return datetime.min
        # quem já deu 404 vai para o fim da fila; entre as demais, sorteio. Depois de ~23h o TSE
        # reescreveu a hora de todas as seções (viraram "Totalizada"), e a mais antiga deixou de
        # ser a mais provável de estar publicada: em 05/10 o bloco de 22:59:05 era todo 404 e
        # ocupava a frente da fila, enquanto 20 de 20 sorteadas no resto davam 200
        import random
        sorte = {k: random.random() for k in novas}
        novas.sort(key=lambda k: (self.falhas.get(k, 0), sorte[k]))
        if limite:
            novas = novas[:limite]
        print(f"{agora()}  índice gerado {dg} {hg}: {len(prontas)}/{total} seções "
              f"com auxiliar, {len(novas)} novas ou alteradas, {verdes} esperando o CDN", flush=True)
        if not novas:
            self.salvar()
            return 0
        import threading
        self.adiar = threading.Event()
        f_sec = open(self.dir / "secoes.jsonl", "a", encoding="utf-8")
        f_che = open(self.dir / "chegadas.csv", "a", newline="", encoding="utf-8")
        w = csv.writer(f_che)
        if f_che.tell() == 0:
            w.writerow(["municipio", "zona", "secao", "indice", "recebido", "visto", "situacao"])
        feitas = erros = 0
        t0 = time.time()
        try:
            # poucos em voo: no primeiro 404 a rodada para, e só os que já estavam no ar
            # podem somar 404 (com 16 eram 16 por rodada e a trava disparava em 1 min; com 8, no pior caso 16 por minuto)
            with ThreadPoolExecutor(min(self.trab, 8)) as ex:
                fut = {ex.submit(self.buscar_secao, *k): k for k in novas}
                for f in as_completed(fut):
                    k = fut[f]
                    res = f.result()  # Bloqueado sobe daqui e para tudo
                    chave = "/".join(k)
                    if "erro" in res:
                        erros += 1
                        continue
                    vistas[chave] = {"indice": prontas[k], "hash": res.get("hash"),
                                     "bu": "eleicoes" in res}
                    if "eleicoes" not in res:
                        print(f"   AVISO {chave}: sem boletim legível ({res.get('situacao')})", flush=True)
                    w.writerow([*k, prontas[k], res.get("recebido"), agora(), res.get("situacao")])
                    if "eleicoes" in res:
                        f_sec.write(json.dumps(res, ensure_ascii=False, default=str) + "\n")
                    feitas += 1
                    if feitas % 500 == 0:
                        dt = time.time() - t0
                        print(f"   {feitas}/{len(novas)}  {feitas / dt:.1f} seções/s  "
                              f"{self.cli.contagem}", flush=True)
                        f_sec.flush(); f_che.flush(); self.salvar()
        finally:
            f_sec.close(); f_che.close(); self.salvar()
        print(f"{agora()}  {feitas} seções gravadas, {erros} com erro, "
              f"{time.time() - t0:.0f} s, {self.cli.contagem}", flush=True)
        return feitas

    def salvar(self):
        tmp = self.arq_estado.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.estado))
        tmp.replace(self.arq_estado)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pleito", required=True, help=f"{sorted(PLEITOS)} ou 2026_2t (código lido do TSE)")
    ap.add_argument("--uf", default="sp")
    ap.add_argument("--mun", nargs="*", help="códigos TSE de 5 dígitos; vazio = UF inteira")
    ap.add_argument("--taxa", type=float, default=20, help="requisições por segundo (TSE: máx. 100)")
    ap.add_argument("--trabalhadores", type=int, default=8)
    ap.add_argument("--intervalo", type=int, default=60, help="segundos entre rodadas")
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--limite", type=int, help="no máximo N seções por rodada (ensaio)")
    a = ap.parse_args()
    c = Coletor(a.pleito, a.uf, a.mun, a.taxa, a.trabalhadores)
    try:
        while True:
            try:
                c.rodada(a.limite)
            except RuntimeError as e:
                # índice ainda não publicado (404 antes da apuração): espera, devagar —
                # um 404 por minuto fica longe do limite que bloqueia
                print(f"{agora()}  {e}; tentando de novo em {max(a.intervalo, 60)} s", flush=True)
                if a.uma_vez:
                    break
                time.sleep(max(a.intervalo, 60))
                continue
            if a.uma_vez:
                break
            time.sleep(a.intervalo)
    except Bloqueado as e:
        sys.exit(f"PARADO: {e}. Espere 10 minutos antes de tentar de novo.")


if __name__ == "__main__":
    main()
