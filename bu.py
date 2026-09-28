"""Lê o boletim de urna (.bu) com a especificação ASN.1 publicada pelo TSE.

As especificações ficam em spec/<ano>/bu.asn1, copiadas do pacote "Formato dos
arquivos de BU, RDV e assinatura digital" do TSE. **Cada ano lê com a sua**: o
bu.asn1 de 2026 ganhou enumerações novas e não decodifica um BU de 2022.

    python bu.py spec_ano arquivo.bu     # imprime a seção decodificada
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

import asn1tools

AQUI = Path(__file__).parent


@lru_cache(maxsize=None)
def _spec(ano):
    return asn1tools.compile_files(str(AQUI / "spec" / ano / "bu.asn1"), codec="ber")


def ler(conteudo, ano):
    """Devolve um dicionário compacto e serializável da seção.

    Mantém todos os cargos — presidente, governador, senador, deputados — porque
    o custo de guardar é nada perto do de baixar de novo.
    Votos: lista de [cargo, tipo, codigo, n]; codigo é None em branco/nulo.
    """
    spec = _spec(ano)
    env = spec.decode("EntidadeEnvelopeGenerico", conteudo)
    bu = spec.decode("EntidadeBoletimUrna", env["conteudo"])
    ident = bu["identificacaoSecao"]
    mz = ident["municipioZona"]
    sa = bu.get("dadosSecaoSA")
    abertura = encerramento = None
    if sa and sa[0] == "dadosSecao":
        abertura = sa[1].get("dataHoraAbertura")
        encerramento = sa[1].get("dataHoraEncerramento")
    eleicoes = []
    for rve in bu["resultadosVotacaoPorEleicao"]:
        cargos = []
        for rv in rve["resultadosVotacao"]:
            for tc in rv["totaisVotosCargo"]:
                cargo = tc["codigoCargo"][1]
                votos = []
                for v in tc["votosVotaveis"]:
                    iv = v.get("identificacaoVotavel") or {}
                    votos.append([v["tipoVoto"], iv.get("codigo"), v["quantidadeVotos"]])
                cargos.append({"cargo": cargo,
                               "comparecimento": rv.get("qtdComparecimento"),
                               "votos": votos})
        eleicoes.append({"id": rve["idEleicao"],
                         "aptos": rve.get("qtdEleitoresAptos"),
                         "cargos": cargos})
    return {"municipio": mz["municipio"], "zona": mz["zona"],
            "local": ident.get("local"), "secao": ident["secao"],
            "emissao": bu.get("dataHoraEmissao"),
            "abertura": abertura, "encerramento": encerramento,
            "biometria": bu.get("qtdEleitoresCompBiometrico"),
            "eleicoes": eleicoes}


if __name__ == "__main__":
    print(json.dumps(ler(Path(sys.argv[2]).read_bytes(), sys.argv[1]),
                     ensure_ascii=False, indent=1, default=str))
