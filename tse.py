"""Endereços da divulgação de resultados do TSE e um cliente HTTP que não se deixa bloquear.

Os endereços seguem o `ele-c.json` e as especificações EA16 (configuração de
seções) e EA18 (auxiliar de seção). Nada aqui é adivinhado: 2022 e o simulado de
2026 foram conferidos respondendo 200; o oficial de 2026 segue o mesmo padrão com
os códigos publicados na página técnica do TSE, e só vai ser confirmado quando o
`oficial/comum/config/ele-c.json` virar para `ele2026`.

A regra do TSE é o que desenha o cliente: no máximo 100 requisições por segundo
por IP, bloqueio de 10 minutos que recomeça a cada nova tentativa, e **404 em
excesso também bloqueia**. Por isso o coletor nunca tenta um endereço que não
tenha sido listado antes por um arquivo do próprio TSE, e para ao primeiro 403.
"""
import threading
import time
from collections import deque
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class Pleito:
    nome: str
    base: str
    amb: str
    ciclo: str
    pleito: int       # código do pleito (turno) — nomeia o arquivo-urna
    eleicao: int      # código da eleição federal, que contém Presidente
    spec: str         # ano da especificação ASN.1 do BU; 2022 não lê com a de 2026
    # Pleito encerrado: o índice foi regerado depois e não traz mais a hora de
    # chegada (medido em 2022: 26.356 seções, nenhuma com `da`). Aí toda seção
    # conta como pronta, e a hora sai do auxiliar (`dr`/`hr`).
    encerrado: bool = False

    def raiz(self):
        return f"{self.base}/{self.amb}/{self.ciclo}"

    def url_cs(self, uf):
        return (f"{self.raiz()}/arquivo-urna/{self.pleito}/config/{uf}/"
                f"{uf}-p{self.pleito:06d}-cs.json")

    def dir_secao(self, uf, mun, zona, secao):
        return (f"{self.raiz()}/arquivo-urna/{self.pleito}/dados/{uf}/"
                f"{mun}/{zona}/{secao}")

    def url_aux(self, uf, mun, zona, secao):
        return (f"{self.dir_secao(uf, mun, zona, secao)}/"
                f"p{self.pleito:06d}-{uf}-m{mun}-z{zona}-s{secao}-aux.json")

    def url_arquivo(self, uf, mun, zona, secao, hash_, nome):
        return f"{self.dir_secao(uf, mun, zona, secao)}/{hash_}/{nome}"

    def url_municipio(self, uf, mun, cargo=1):
        # 2022 publica o "v"; 2026 publica o "u" (resultado unificado, EA20)
        suf = "v" if self.ciclo == "ele2022" else "u"
        return (f"{self.raiz()}/{self.eleicao}/dados/{uf}/"
                f"{uf}{mun}-c{cargo:04d}-e{self.eleicao:06d}-{suf}.json")


PLEITOS = {
    "2022": Pleito("2022", "https://resultados.tse.jus.br", "oficial",
                   "ele2022", 406, 544, "2022", encerrado=True),
    "simulado": Pleito("simulado", "https://resultados-sim.tse.jus.br",
                       "simulado", "simulado2026", 17801, 21270, "2026"),
    "2026": Pleito("2026", "https://resultados.tse.jus.br", "oficial",
                   "ele2026", 3220, 6257, "2026"),
}


# Ensaio local (tse_falso.py): o "2026" aponta para esta máquina e lê os BUs de 2022
# com a especificação de 2022. Nunca vale em produção — só com TSE_FALSO=1.
import os as _os
if _os.environ.get("TSE_FALSO"):
    PLEITOS["2026"] = Pleito("2026", "http://127.0.0.1:8800", "oficial", "ele2026", 3220, 6257, "2022")


class Bloqueado(Exception):
    """O TSE recusou (403/429). Continuar tentando só prolonga o bloqueio."""


class Cliente:
    """GET com teto de taxa, GET condicional e freio de 404.

    O teto é global entre threads: um balde simples, `taxa` requisições por
    segundo. O freio de 404 existe porque o TSE conta 404 como abuso — se mais de
    `max_404` acontecerem em 60 s, algo está errado no endereço e continuar só
    queima o IP.
    """

    def __init__(self, taxa=20, max_404=30):
        self.s = requests.Session()
        self.s.headers["Accept-Encoding"] = "gzip"
        self.intervalo = 1.0 / taxa
        self.prox = time.monotonic()
        self.trava = threading.Lock()
        self.max_404 = max_404
        self.n404 = deque()
        self.contagem = {"req": 0, "200": 0, "304": 0, "404": 0}

    def _esperar_vez(self):
        with self.trava:
            agora = time.monotonic()
            vez = max(agora, self.prox)
            self.prox = vez + self.intervalo
        if vez > agora:
            time.sleep(vez - agora)

    def get(self, url, etag=None, tentativas=3):
        """Devolve (status, bytes|None, etag). 304 volta com bytes None."""
        cab = {"If-None-Match": etag} if etag else {}
        status = 0
        for i in range(tentativas):
            self._esperar_vez()
            try:
                r = self.s.get(url, headers=cab, timeout=30)
            except requests.RequestException:
                time.sleep(2 * (i + 1))
                continue
            status = r.status_code
            with self.trava:
                self.contagem["req"] += 1
                k = str(r.status_code)
                if k in self.contagem:
                    self.contagem[k] += 1
            if r.status_code in (403, 429):
                raise Bloqueado(f"{r.status_code} em {url}")
            if r.status_code == 404:
                self._registrar_404(url)
                return 404, None, None
            if r.status_code == 304:
                return 304, None, etag
            if r.status_code == 200:
                return 200, r.content, r.headers.get("ETag")
            time.sleep(2 * (i + 1))  # 5xx: espera e tenta de novo
        return status, None, None

    def _registrar_404(self, url):
        agora = time.monotonic()
        with self.trava:
            self.n404.append(agora)
            while self.n404 and agora - self.n404[0] > 60:
                self.n404.popleft()
            if len(self.n404) > self.max_404:
                raise Bloqueado(f"{len(self.n404)} respostas 404 em 60 s "
                                f"(última: {url}) — parando antes do TSE parar a gente")
