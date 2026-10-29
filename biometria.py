"""Como cada eleitor foi habilitado, seção a seção, nos dois turnos de 2026 — do próprio boletim de urna.

O boletim de 2026 traz `detalhamentoComparecimento`: habilitados por biometria (a digital conferiu),
por "biografia" (a digital não conferiu e o mesário liberou pelos dados do eleitor) e sem biometria
(eleitor sem digital cadastrada). Os três somam o comparecimento. É o dado que o TSE publicou como
dado aberto em 28/10/2026; aqui sai dos .bu já baixados (data/raw/<pleito>/<uf>/bu/...).

Também guarda os horários do boletim (abertura, encerramento, emissão), para conferir o relógio da urna
contra a hora de chegada no TSE (`recebido`, relógio do servidor).

    python biometria.py            # → data/raw/2026_2t/biometria.parquet (os dois turnos)
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from biometria_ler import _ler

RAW = Path("data/raw")


def extrair(pleito):
    import pandas as pd
    arqs = [str(f) for f in RAW.glob(f"{pleito}/*/bu/**/*.bu")]
    uf_de = {}
    for f in arqs:
        uf_de[f] = Path(f).relative_to(RAW / pleito).parts[0].upper()
    lotes = [arqs[i:i + 2000] for i in range(0, len(arqs), 2000)]
    linhas = []
    with ProcessPoolExecutor(10) as ex:
        for i, r in enumerate(ex.map(_ler, lotes), 1):
            linhas += r
            if i % 25 == 0:
                print(f"  {pleito}: {len(linhas):,}/{len(arqs):,}", flush=True)
    d = pd.DataFrame(linhas, columns=["municipio", "zona", "secao", "emissao", "abertura", "encerramento", "comparec", "por_bio", "por_biog", "sem_bio"])
    # a UF pelo caminho do arquivo (municipio+zona+secao não é único entre UFs só por acaso)
    chave = {(int(Path(f).parts[-3]), int(Path(f).parts[-2]), int(Path(f).stem)): uf_de[f] for f in arqs}
    d["uf"] = [chave.get((m, z, s)) for m, z, s in zip(d.municipio, d.zona, d.secao)]
    d["turno"] = "1t" if pleito == "2026" else "2t"
    # hora de chegada no TSE (relógio do servidor, Brasília), do secoes.jsonl
    rec = {}
    for f in RAW.glob(f"{pleito}/*/secoes.jsonl"):
        uf = f.parent.name.upper()
        for ln in open(f, encoding="utf-8"):
            try:
                s = json.loads(ln)
            except json.JSONDecodeError:
                continue
            rec[(uf, s["zona"], s["secao"])] = s.get("recebido")
    d["recebido"] = [rec.get((u, z, s)) for u, z, s in zip(d.uf, d.zona, d.secao)]
    return d


def main():
    import pandas as pd
    sys.stdout.reconfigure(encoding="utf-8")
    d = pd.concat([extrair("2026"), extrair("2026_2t")], ignore_index=True)
    d.to_parquet(RAW / "2026_2t" / "biometria.parquet")
    for t, g in d.groupby("turno"):
        c = g.comparec.sum()
        print(f"{t}: {len(g):,} boletins; comparecimento {c:,}; por biometria {100 * g.por_bio.sum() / c:.2f}% · por biografia "
              f"{100 * g.por_biog.sum() / c:.2f}% · sem biometria {100 * g.sem_bio.sum() / c:.2f}%; soma confere em "
              f"{100 * ((g.por_bio + g.por_biog + g.sem_bio) == g.comparec).mean():.2f}% das seções", flush=True)


if __name__ == "__main__":
    main()
