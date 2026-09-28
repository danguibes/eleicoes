# Eleições — o voto por grupo, estimado a partir das seções

Projeto pessoal, irmão do [Brasileirão](https://github.com/danguibes/monte-carlo-brasileirao)
e da [NFL](https://github.com/danguibes/montecarlo_nfl), e herda deles o método:
medir antes de afirmar, uma régua contra a qual comparar, e registrar o que foi
descartado e por quê.

**O voto é secreto.** O menor resultado que existe é a seção eleitoral. Toda
quebra do tipo "voto por idade, escolaridade, renda, raça, religião" que aparece
aqui é **estimativa por inferência ecológica**, e vem com intervalo de incerteza.
O que é dado e não estimativa — o comparecimento por perfil, publicado pelo TSE —
fica separado.

Piloto: município de São Paulo, Presidente, 1º turno. Validação em 2022;
aplicação em 4/10/2026, na própria noite da apuração.

## A noite da eleição

O TSE publica o boletim de urna (BU) de cada seção à medida que ela chega, e um
índice por UF diz quais seções já chegaram e a que horas. O `coletor.py` segue
esse índice, baixa o auxiliar e o `.bu` de cada seção nova e decodifica o BU com
a especificação ASN.1 do próprio TSE (`spec/<ano>/bu.asn1`).

```bash
python coletor.py --pleito 2022 --uf sp --mun 71072 --uma-vez   # ensaio com 2022
python coletor.py --pleito simulado --uf sp --mun 71072          # simulado do TSE
python coletor.py --pleito 2026 --uf sp --mun 71072              # domingo
```

Regras que desenham o coletor, todas do TSE: no máximo 100 requisições por
segundo por IP, bloqueio de 10 minutos que recomeça a cada tentativa, e **404 em
excesso também bloqueia**. Por isso o coletor nunca pede um endereço que um
arquivo do TSE não tenha listado antes, usa GET condicional, e para no primeiro
403.

**As urnas não chegam em ordem aleatória.** Quem apura primeiro não é uma
amostra do município. O coletor guarda a hora de chegada de cada seção
(`chegadas.csv`), e em 2022 essa hora ainda está no auxiliar de cada seção — é o
que permite ensaiar a projeção de domingo na ordem em que as urnas chegaram de
verdade em 2022.

## Arquivos-base

O `cdn.tse.jus.br` recusa script a partir da máquina de casa (403; do navegador
baixa). O `baixar_tse.py` roda no GitHub Actions (workflow **baixar arquivos-base
do TSE**, botão *Run workflow*) e devolve só o recorte do município, em Parquet,
como artefato.
