# Eleições 2026 — apuração e projeção, urna a urna

Projeto pessoal, irmão do [Brasileirão](https://github.com/danguibes/monte-carlo-brasileirao)
e da [NFL](https://github.com/danguibes/montecarlo_nfl), e herda deles o método:
medir antes de afirmar, uma régua contra a qual comparar, e registrar o que foi
descartado e por quê.

Página: <https://danguibes.github.io/eleicoes/> (painel) e
[`metodo.html`](https://danguibes.github.io/eleicoes/metodo.html) (como funciona,
o que foi medido e o que não passou na régua).

**O voto é secreto.** O menor resultado que existe é a seção eleitoral. O que a
página mostra por grupo ou por perfil é o voto **das urnas dos lugares** com
aquele perfil, ou, onde passou na régua, estimativa por inferência ecológica com
intervalo. O que é dado — resultado das urnas, comparecimento por perfil do TSE —
aparece marcado como dado.

## O que o painel faz

- **Brasil por município** (camada rápida) e **São Paulo por local de votação**
  (três cargos). Filtros de região, UF, município, zona e sete quintis de perfil
  (renda, católicos, evangélicos, sem religião, pretos e pardos, superior
  completo, 60+), com clique cruzado: uma fonte filtrada para todos os quadros.
- Para cada recorte: **eleição anterior** (1º ou 2º turno de 2022, pelo botão),
  **2026 apurado** e **2026 projetado**, com intervalo de 90% e votos absolutos.
- **Chances** (2º turno, quem termina em 1º, vagas do Senado) e curvas, das
  reamostragens do modelo alargadas pelo fator calibrado.
- **Mapa** por município (malha do IBGE, sem mapa de fundo).
- **Modo ensaio**: a noite de 2022 reproduzida urna a urna, parada em 25% das
  urnas, com 2018 como eleição anterior.

## A noite da eleição

```bash
python noite.py                    # 2026: os dois coletores e o publicador
python noite.py --pleito simulado  # ensaio contra o simulado do TSE (não publica)
```

Três processos, reiniciados se caírem:

| processo | o que faz | ritmo |
|---|---|---|
| `coletor.py --uf sp` | boletins de urna (BU) de SP, urna a urna, decodificados com a ASN.1 do TSE | 50 req/s |
| `nacional.py` | resultado parcial de cada município do país (arquivo `u`, EA20) | 15 req/s |
| `domingo.py` | quando há dado novo: projeções, painéis (`painel.py`, `painel_brasil.py`), git push | a cada 30 s |

Regras do TSE que desenham os coletores: no máximo 100 requisições por segundo
por IP, bloqueio de 10 minutos que recomeça a cada tentativa, e **404 em excesso
também bloqueia**. Por isso: nunca se pede endereço que um arquivo do TSE não
tenha listado; o `nacional.py` confirma que o arquivo da UF existe antes de varrer
os municípios dela (antes da publicação seriam ~5.700 404 por rodada); GET
condicional; e bloqueio reinicia o processo só depois de 11 minutos.

**Por que duas camadas.** Simulado com a hora real de chegada das 472.075 urnas
de 2022: no pico o TSE recebeu 5.022 urnas num minuto. Baixando dois arquivos por
urna a 70 req/s, a coleta nacional urna a urna atrasaria 25 min em média e 1 h no
pior momento. Os totais por município se varrem inteiros em ~6 min e ficam em dia.

## Arquivos-base

O `cdn.tse.jus.br` recusa script em qualquer IP (403 daqui e do GitHub Actions;
do navegador baixa). Os zips vão do navegador para Downloads e o
`baixar_tse.py --pasta` recorta sem extrair (o perfil de 2026 tem 4,7 GB):

```bash
python baixar_tse.py --pasta "C:/Users/Danilo Bessa/Downloads"            # SP
python baixar_tse.py --pasta "C:/Users/Danilo Bessa/Downloads" --uf BR     # Brasil
python baixar_ibge.py          # Censo 2022 por setor (SP)
python municipios_ibge.py      # Censo 2022 por município (Brasil) e a ligação IBGE↔TSE
python mapa.py                 # malha do IBGE em SVG
```

**O ambiente oficial de 2022 saiu do ar em 28/09/2026** (virou "Resultados | Nova
versão em breve"). A coleta de SP tinha terminado horas antes; a parte que o
painel usa está versionada em [`data/base/`](data/base/LEIA-ME.md). O Brasil de
2022 vem do Portal de Dados Abertos (`votacao_secao_2022_BR`, com os dois turnos,
e `detalhe_votacao_secao_2022`, que traz a hora de chegada de cada urna).

## O que foi medido

**Os coletores conferem voto a voto.** Estado de SP, 2022: 101.073 seções,
~150 mil requisições, zero erro; Presidente, governador e senador batem com o
total oficial em comparecimento e em cada candidato. Duas seções foram apuradas
pelo sistema de contingência e têm `.busa` em vez de `.bu` — sem ler os dois, o
estado ficava 400 votos curto, calado.

**As urnas não chegam em ordem aleatória**, e a projeção corrige. Ensaios na
ordem real de chegada de 2022, base 2018:

| escopo | contagem L−B com 25% | projeção L−B com 25% | final | erro médio contagem → projeção |
|---|---|---|---|---|
| capital, por seção | +6,5 | +9,1 | +9,6 | 0,45 → 0,33 pt |
| estado de SP, por seção | −13,4 | −7,4 | −6,8 | 1,17 → 0,40 pt |
| Brasil, por seção | −4,4 | +4,1 | +5,2 | 1,79 → 0,35 pt |
| Brasil, por município | −4,4 | +3,4 | +5,2 | 1,79 → 0,26 pt |

No Brasil, a contagem mostrou Bolsonaro à frente até ~20h; a projeção apontava
Lula à frente desde 10% das urnas (18h31).

**O intervalo de 90%** é a meia-largura do bootstrap × um fator calibrado no
ensaio: capital 1,25 (cobre 35 de 35), estado 3,5, Brasil por município 1,25
reamostrando **UFs inteiras** (91%; reamostrando municípios dentro da UF, 23%).
**Sobra um viés** de ~0,9 ponto a menos para Lula até metade da noite, igual nas
duas camadas: as urnas tardias de 2022 foram mais Lula do que a eleição anterior
e a UF explicam. Calibrado numa eleição só.

**Descartado por medição:**
- o perfil do eleitorado como variável fora de SP (não baixado): sem ele, o erro
  da capital vai de 0,33 para 0,38 pt — pouco;
- o 2º turno da eleição anterior como variável: piorou (0,26 → 0,28 pt);
- quanto confiar no parcial do próprio município (por volume, por fração, zero):
  não muda o viés;
- PyEI e NUTS: passaram de 20 minutos; o SVI ajusta em ~20 s.

**Casamento local de votação ↔ Censo** (`casamento.py`): raio de 1,5 km com peso
exp(−d/600 m) casa melhor que Voronoi, e casa **razoavelmente, não bem** —
correlação de 0,59 na parcela de 60+ entre TSE e Censo.

**A inferência ecológica falhou na régua do comparecimento** (`ei.py`,
`ei_busca.py`): errou até 10 pontos e **inverteu a ordem da escolaridade** em
todas as variantes. Por isso escolaridade, renda, cor e religião aparecem como
**perfil do lugar** (quintis, dado real agrupado), e não como voto do grupo. A
idade em 5 faixas passou (erro máximo 4,4 pt) e o voto por idade e sexo de 2022
está na página de método, com o comparecimento real no lugar do estimado.

**Censo por município** (`municipios_ibge.py`): 5.570 de 5.571 municípios do TSE
ligados ao IBGE; 15 grafias diferentes conferidas uma a uma; Boa Esperança do
Norte (MT) foi criado depois do Censo e fica sem perfil.
