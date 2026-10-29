"""Decodifica o detalhamento do comparecimento dos .bu (biometria.py). Sem numpy nem pandas: roda em
subprocessos, e a política de controle de aplicativos desta máquina barra a DLL do numpy neles."""
from pathlib import Path


def _ler(arqs):
    import bu
    spec = bu._spec("2026")
    out = []
    for f in arqs:
        try:
            env = spec.decode("EntidadeEnvelopeGenerico", Path(f).read_bytes())
            b = spec.decode("EntidadeBoletimUrna", env["conteudo"])
        except Exception:
            continue
        mz = b["identificacaoSecao"]["municipioZona"]
        sa = b.get("dadosSecaoSA")
        sa = sa[1] if sa and sa[0] == "dadosSecao" else {}
        d = b.get("detalhamentoComparecimento") or {}
        out.append((mz["municipio"], mz["zona"], b["identificacaoSecao"]["secao"], b.get("dataHoraEmissao"), sa.get("dataHoraAbertura"),
                    sa.get("dataHoraEncerramento"), b.get("qtdEleitoresCompareceram"), d.get("qtdEleitoresHabilitadosPorBiometria"),
                    d.get("qtdEleitoresHabilitadosPorBiografia"), d.get("qtdEleitoresCompareceramSemBiometria")))
    return out
