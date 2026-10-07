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

## O 2º turno (25/10/2026)

Só Presidente, Lula × Flávio. A página principal virou a do 2º turno; o 1º turno ficou congelado em
[`1t2026.html`](https://danguibes.github.io/eleicoes/1t2026.html), e as migrações de 2022 são o ponto de
partida do [simulador](https://danguibes.github.io/eleicoes/simulador.html).

```bash
python noite.py --turno 2              # a noite: código do pleito lido do ele-c.json do TSE
python tse_falso.py --turno 2 --acel 15 # ensaio: o 2º turno de 2022 servido nesta máquina…
python noite.py --turno 2 --falso      # …e a noite contra ele (pleito local falso_2t, não publica)
```

| processo | o que faz | ritmo |
|---|---|---|
| `nacional.py` | arquivo `u` de cada município, eleição 6258 | 45 req/s |
| `indices.py` | índice de seções das 28 UFs: **quais** urnas chegaram | 5 req/s |
| `coletor.py --uf sp` | boletins de SP, urna a urna | 25 req/s |
| `domingo.py --turno 2` | `painel_2t.py` (Brasil) e `painel_2t_sp.py` (SP por local) | a cada 30 s |

**Cada seção contra ela mesma no 1º turno** (`segundo.py`): a matriz de transição 1º → 2º turno
(`transicao.py`) é aprendida nas urnas que já chegaram e aplicada ao 1º turno das que faltam. Ensaio na
noite do 2º turno de 2022, erro médio da parte de Lula: contagem 2,71; o modelo do 1º turno 0,51–0,69;
**0,04–0,07** sabendo quais seções chegaram. Em SP por local, 0,03. Intervalo de 90% com fator 1,5 e piso
de ±0,2 ponto; uma eleição só de calibração.

Base: os boletins do 1º turno de 2026 do Brasil inteiro (`coletar_brasil.py` → `base_secoes.py`): 498.925 de
499.248 seções, 5.708 de 5.717 municípios batendo voto a voto com o TSE.

## A noite do 1º turno

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

**Ensaio local, sem tocar o TSE** (`tse_falso.py`): um servidor nesta máquina que serve
a noite de 2022 nos endereços e no formato de 2026, com relógio acelerado. Em 01/10/2026
ele pegou dois defeitos que teriam quebrado domingo — a camada nacional emparelhava as
categorias de 2022 com as candidaturas de 2026 (6 contra 8) e quebrava na primeira
rodada; e grupo sem voto apurado gravava `NaN` no JSON, e a página inteira deixava de
carregar. No fim, o Brasil apurado bateu com o oficial de 2022 (Lula 48,43%, 43,20%) e
os 101.073 boletins de SP passaram com zero erro em 202 mil requisições.

```bash
python tse_falso.py --acel 15        # num terminal
python noite.py --falso              # noutro: aponta para 127.0.0.1:8800 e não publica
# ver em http://localhost:8765/ ; depois: apagar data/raw/2026/sp e
# data/raw/2026/nacional/{municipios,ufs}.parquet e refazer os painéis de 2026
```

**Por que duas camadas.** Simulado com a hora real de chegada das 472.075 urnas
de 2022: no pico o TSE recebeu 5.022 urnas num minuto. Baixando dois arquivos por
urna a 70 req/s, a coleta nacional urna a urna atrasaria 25 min em média e 1 h no
pior momento. Os totais por município se varrem inteiros em ~6 min e ficam em dia.

## Perfis do município (para recortar, não para prever)

Além dos quintis do Censo, o Brasil por município tem sete perfis de outras fontes públicas
(`perfil_extra.py`), que **não entram no modelo**: servem para olhar o voto já dado.

| perfil | o que é | fonte |
|---|---|---|
| Bolsa Família | % da população em famílias beneficiárias, set/2026 | MDS, VIS DATA (API pública) |
| Adm. pública no PIB | % do valor adicionado na administração pública, 2021 | IBGE, PIB dos Municípios (tab. 5938) |
| Agropecuária no PIB | % do valor adicionado na agropecuária, 2021 | idem |
| PIB per capita | PIB 2023 ÷ população do Censo 2022 | idem |
| Esgoto em rede geral | % dos domicílios, 2022 | Censo 2022 (tab. 6805) |
| População rural | %, 2022 | Censo 2022 (tab. 10211) |
| Tamanho | habitantes, 2022 | Censo 2022 (tab. 4714) |

Funcionalismo público por município não existe no IBGE (o Cadastro Central de Empresas por natureza
jurídica só desce até UF): o peso da administração pública no PIB faz esse papel. IDH municipal oficial só
existe para 2010 (Atlas Brasil, sem download por script). Os filtros de região e UF aceitam qualquer
combinação ("Brasil sem o Sudeste"); o intervalo do conjunto sai da soma das reamostragens de cada UF.

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
ensaio: capital 1,25 (cobre 35 de 35), estado 3,5, Brasil por município 1,5
reamostrando **UFs inteiras** (89%; reamostrando municípios dentro da UF, 23%).
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
