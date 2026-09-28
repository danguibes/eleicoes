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

O `cdn.tse.jus.br` recusa script em qualquer IP — medido daqui e do GitHub
Actions, 403 nos dois; do navegador baixa. Então os zips são baixados no
navegador para a pasta Downloads, e o `baixar_tse.py --pasta` recorta o estado de
SP de dentro deles, em Parquet, sem extrair (o perfil de 2026 tem 4,7 GB). A
lista de arquivos e os links estão no próprio script.

```bash
python baixar_tse.py --pasta "C:/Users/Danilo Bessa/Downloads"
python baixar_ibge.py      # o FTP do IBGE aceita script
```

O workflow **baixar arquivos-base do TSE** ficou como registro da tentativa.

## O que foi medido (28/09/2026)

**O coletor confere voto a voto.** Capital, 2022, 1º turno: 26.288 seções,
52.577 requisições, zero erro, 35 minutos a 25 req/s. A soma dos BUs bate com o
total oficial do município em seções, aptos, comparecimento, brancos, nulos e nos
votos de cada um dos 11 candidatos.

**As urnas não chegam em ordem aleatória.** Na ordem real de 2022, com 25% das
seções a soma simples dava Lula − Bolsonaro = +6,5; o final foi +9,6.

**A projeção corrige isso** (`projecao.py --ensaio`): alvo 2022, base 2018, cada
urna comparada com o local de votação de 2018 mais próximo, na ordem real de
chegada de 2022.

| urnas | contagem L−B | projeção L−B | final |
|---|---|---|---|
| 10% | +7,7 | +11,1 | +9,6 |
| 25% | +6,5 | +9,1 | +9,6 |
| 50% | +7,1 | +9,3 | +9,6 |
| 75% | +8,7 | +9,6 | +9,6 |

O intervalo de 90% é a meia-largura do bootstrap por zona × 1,25, centrada na
projeção: cobre o real em 35 de 35 conferências. Os percentis crus cobriam 71%
(assimétricos), e com o resíduo de urna somado na escala log, 46% (Jensen).
**Calibrado neste mesmo ensaio**, numa eleição só.

**Casamento local de votação ↔ Censo** (`casamento.py`): raio de 1,5 km com peso
exp(−d/600 m) casa melhor que Voronoi, e casa **razoavelmente, não bem** —
correlação de 0,59 na parcela de 60+ entre TSE e Censo.

**A inferência ecológica de base falhou no comparecimento** (`ei.py`), que é a
régua porque o TSE publica o comparecimento real por perfil. Errou até 10 pontos
e **inverteu a ordem da escolaridade** (superior completo estimado abaixo do
ensino médio). Causa: viés de agregação — grupos que moram juntos trocam
comportamento no modelo (60–69 × 70+: correlação 0,76 entre seções; superior ×
até fundamental incompleto: −0,75). Não era convergência (10 mil passos dão o
mesmo) nem se resolveu com contexto como covariável. O voto por grupo só vai para
a página com uma variante que passe nesta régua (`ei_busca.py`).

**Descartado:** PyEI (R×C com voto por unidade) e NUTS no modelo enxuto — os dois
passaram de 20 minutos num problema do tamanho da capital. O SVI ajusta em ~20 s.
