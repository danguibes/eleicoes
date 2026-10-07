# Aprendizados — do zero ao fim do 1º turno de 2026

Escrito em 05/10/2026, o dia seguinte ao 1º turno, para quem precisar recomeçar
este projeto do zero em outro lugar. Não é o README: o README diz o que o projeto
faz; esta página diz **o que custou chegar aqui**, o que deu errado, o que foi
medido e o que eu faria igual ou diferente.

O projeto: estimar, ao vivo na noite da eleição, como votaram os grupos
sociodemográficos do Brasil, urna a urna, comparando 2026 com 2022, e projetar o
resultado final a partir das urnas que já chegaram. Tudo em GitHub (Pages +
Actions), sem banco pago. Página: <https://danguibes.github.io/eleicoes/>.

---

## 1. As regras que valem antes de qualquer linha de código

1. **O voto é secreto. O menor dado que existe é a seção eleitoral.** Qualquer
   "como votaram os católicos" é inferência sobre agregados, com incerteza, e a
   página tem que dizer isso em cada quadro. Comparecimento por perfil (idade,
   sexo, escolaridade) é dado real do TSE e fica separado da inferência.
2. **Não inventar dado, coluna, nome de arquivo ou endereço.** Tudo que o TSE
   publica tem especificação. Antes de pedir um endereço, ele tem que ter sido
   listado por um arquivo do próprio TSE: 404 em excesso bloqueia o IP.
3. **Medir antes de afirmar, com régua.** Toda escolha de método passou por um
   ensaio contra uma eleição que já aconteceu (2018 → 2022), e o que não passou
   ficou registrado como descartado, com o número.
4. **Consultar antes de decisão metodológica grande.** Várias das melhores
   decisões vieram do Danilo, não do modelo. Por exemplo: "a inferência tem que ser
   urna a urna, comparada com a mais próxima de 2022", "não confio no Datafolha;
   use o comparecimento real como régua" e "Lula/PT sempre vermelho, o adversário
   sempre azul".
5. **`data/raw/` fora do git.** É grande e regenerável. O que **não** é
   regenerável (ver §3, o TSE tirou 2022 do ar) vai para `data/base/`, versionado.

---

## 2. De onde vêm os dados — e as armadilhas de cada fonte

### 2.1 Resultados ao vivo: `resultados.tse.jus.br`

- A configuração global é `oficial/comum/config/ele-c.json`. Ela diz o ciclo
  (`ele2026`) e os códigos. Em 2026 foram: pleito **3220** (1º turno), eleição
  **6257** (federal, Presidente) e **6259** (estadual: governador, senador e
  deputados). Confirmados em 30/09, quando o arquivo virou para 2026.
- Lista de municípios: `ele2026/6257/config/mun-e006257-cm.json`, com 5.757
  municípios contando o exterior. O código IBGE vem em `cdi`.
- Índice de seções por UF: `arquivo-urna/3220/config/<uf>/<uf>-p003220-cs.json`.
  Cada seção traz `da`/`ha` (data e hora) quando já chegou. **Seção agregada
  (`nsp`) não tem BU próprio:** os votos vêm no BU da principal.
- Auxiliar da seção:
  `arquivo-urna/3220/dados/<uf>/<mun>/<zona>/<secao>/p003220-<uf>-m<mun>-z<zona>-s<secao>-aux.json`.
  Lista os arquivos em `hashes[].arq[]` com `nm` e `tp`.
- **O BU mudou de nome em 2026**: `o03220sp<mun><zona><secao>-bu.dat` com
  `"tp":"bu"`. Em 2022 era `....bu`, e na contingência `.busa`. **Escolha pelo
  `tp`, nunca pelo nome.** Isso foi pego às 17h27 do domingo, nas primeiras 26
  seções: nenhum BU de SP era lido.
- O BU é ASN.1 BER, decodificado com `asn1tools` e a especificação do próprio
  ano (`spec/2022/bu.asn1`, `spec/2026/bu.asn1`). **A de 2026 não lê 2022.**
- Os outros arquivos da seção (`-log.jez`, `-vota.vsc`, `-rdv.dat`) não foram
  usados. A verificação de assinatura dos boletins ficou prometida e **não foi
  feita**.
- Resultado por município, o arquivo `u` (EA20):
  `<raiz>/6257/dados/<uf>/<uf><mun>-c0001-e006257-u.json`. Também existe para a
  UF e para o BR. Para governador (cargo 3) e senador (cargo 5), é a eleição
  6259.
- **Limites do TSE:** 100 requisições/s por IP. O bloqueio dura 10 minutos e
  recomeça a cada nova tentativa. **404 em excesso também bloqueia.** O cabeçalho
  `X-RateLimit-Limit: 2000` aparece até no 404, mas não diz qual é o limite de
  404.
- GET condicional com ETag devolve 304 e economiza tudo. O CDN usa
  `max-age=60`, **inclusive para 404**: o 404 fica em cache ("Hit from child")
  por um minuto.

### 2.2 O atraso que ninguém documenta: índice × auxiliar

O índice de seções **lista a seção antes de o auxiliar dela existir.** A distância
foi medida várias vezes na noite de 04/10:

- às 17h55, cerca de 5 minutos;
- às 18h28, 18 minutos (índice 18:10:52, `Last-Modified` 18:28:54);
- às 18h45, numa amostra de 40 seções chegadas entre 18h09 e 18h25, **22 ainda
  davam 404 na origem**, e as publicadas tinham saído entre 18h24 e 18h46. A
  distância era de 20 a 40 minutos;
- no dia seguinte, 05/10 às 12h40, um bloco de seções (todas com `ha` 22:59:05)
  **ainda dava 404, 13 horas depois.**

Depois de ~23h o TSE **reescreve a hora de todas as seções** quando elas viram
"Totalizada", e a hora deixa de servir para ordenar a fila.

Consequências para o coletor de boletins, todas aprendidas na noite:

- não pedir o auxiliar na hora em que a seção aparece no índice;
- **orçamento de 404** por minuto, abaixo da trava do cliente (20 por minuto,
  com a trava em 31);
- seção que dá 404 espera, e **a espera dobra** a cada nova falha (3, 6, 12…
  até 60 min);
- **quem já falhou vai para o fim da fila**, e entre as demais a ordem é
  **sorteada**. A ordem "mais antiga primeiro" parecia óbvia e travou o coletor
  duas vezes: um bloco de seções que nunca saía ocupava a frente da fila e
  gastava o orçamento inteiro de cada rodada;
- poucos pedidos em voo (8). Com 16 em voo, uma rajada de 404 passava da trava
  antes de a rodada conseguir parar.

**A lição maior:** o boletim urna a urna **não acompanha a noite**. Às 19h, SP
tinha 5% das seções nos boletins e 47% no arquivo por município. **Para ficar em
dia, a camada por município é a que serve. O boletim é detalhe que chega
depois.**

### 2.3 Dados abertos: `cdn.tse.jus.br`

- **Recusa script em qualquer IP**: 403 daqui e do GitHub Actions. Do navegador,
  baixa. A saída foi o Danilo baixar os zips para a pasta Downloads e o
  `baixar_tse.py --pasta` recortar **sem extrair** (o perfil do eleitorado de
  2026 tem 4,7 GB). Não tentar contornar: é detecção de robô, e contorná-la
  está fora do que se faz.
- Os arquivos que importam são:
  - `votacao_secao_<ano>_BR`, com os dois turnos;
  - `detalhe_votacao_secao_<ano>`, que traz aptos, comparecimento, brancos, nulos
    e **a hora de chegada de cada urna**, o que permite ensaiar a noite na ordem
    real;
  - `perfil_eleitor_secao`, `eleitorado_local_votacao` e `consulta_cand` (nomes).
- **O pandas estourou a memória com os 4,7 GB do perfil.** A solução foi
  `ParquetWriter` em streaming, com esquema todo em texto.

### 2.4 O TSE apaga o passado

Em **28/09/2026** o ambiente oficial de 2022 saiu do ar e passou a responder "Nova
versão em breve". Os boletins de SP de 2022 tinham sido baixados horas antes. **O
que não é regenerável vai para o git no dia em que chega** (`data/base/`).

### 2.5 IBGE

- Censo 2022 por setor (SP) e por município (Brasil): renda, religião, cor,
  escolaridade e idade. A religião só sai por área de ponderação, não por setor.
- A ligação IBGE ↔ TSE passa pelo `cdi` do TSE e pelo nome. Ficaram 15 grafias
  diferentes, conferidas uma a uma. Boa Esperança do Norte (MT) foi criado
  depois do Censo e não tem perfil.
- 27 municípios não tinham coordenada nenhuma no TSE e caíram no centro do
  município (IBGE).

---

## 3. Arquitetura que funcionou

```
noite.py         sobe e reinicia os filhos; se um saiu com "PARADO" (bloqueio), espera 11 min
 ├ coletor.py    boletins de SP, urna a urna (ASN.1)
 ├ nacional.py   arquivo u de cada município do Brasil (Presidente), GET condicional, 8 em paralelo
 ├ sp_municipios.py  arquivo u de SP para governador e senador (entrou às 19h, ver §5)
 └ domingo.py    publicador: dado novo → projeção → JSON dos painéis → git push (no máx. a cada 2 min)
GitHub Actions   publica web/ no Pages; a página recarrega os dados a cada 2 min
```

- **Página sem build**: um `index.html` e JSON em colunas, com o navegador
  somando os recortes. Os filtros cruzados (clicar num quintil filtra a tela
  toda) saem disso de graça.
- **Pages enfileira deploys.** Um push a cada 30 s gerava fila. A cada 2 min
  funciona (cada deploy leva ~20 s).
- **Um "TSE de mentira" local** (`tse_falso.py`) serve a noite de 2022 nos
  endereços e no formato de 2026, com relógio acelerado. Em 01/10 ele pegou
  **dois defeitos que teriam quebrado o domingo**:
  - as categorias de 2022 eram emparelhadas por posição com as de 2026 (6 contra
    8), o que quebrava na primeira rodada e trocava nomes (Tebet virava "Cury");
  - um grupo sem voto apurado gravava `NaN` no JSON, e a página inteira deixava
    de carregar.
- **O simulado do TSE (29-30/09) foi perdido**: a máquina dormiu, o tempo-limite
  não matou os processos, e os 404 repetidos de antes da publicação dispararam a
  trava por um dia e meio. Daí vieram as correções:
  - uma única sondagem por rodada antes da publicação;
  - a lista de municípios guardada em disco;
  - `--inicio 16:45`.

---

## 4. Método: o que foi medido, o que passou, o que caiu

### 4.1 As urnas não chegam em ordem aleatória

Essa é a premissa de tudo, e foi o Danilo quem a levantou. A contagem parcial é
uma amostra **viesada**: no Brasil de 2022 ela mostrou Bolsonaro à frente até
~20h. Por isso a projeção compara **cada urna com ela mesma (ou com a mais
próxima) na eleição anterior**, e não com uma amostra aleatória.

### 4.2 Projeção

- **Por seção** (`projecao.py`):
  - parcela de cada candidato em razão log centrada (clr) e comparecimento em
    logit;
  - regressão contra a parcela do local de votação mais próximo na eleição
    anterior;
  - mais efeitos de perfil e de zona encolhidos (ridge), em mínimos quadrados
    ponderados por equações normais por zona;
  - bootstrap por bloco de zona.
- **Por município** (`municipal.py`), a camada rápida:
  - a mesma ideia sobre os totais parciais de cada município;
  - efeito de UF e bootstrap por **UF inteira**;
  - no Senado de 2026, **cada eleitor vota duas vezes** (`votos_por=2`).
- Abaixo de 1% das seções, nada é projetado: com 13 urnas o ensaio dava L−B
  +2,4 para um final de +9,6.

### 4.3 Intervalo

O intervalo é a meia-largura do bootstrap × um fator calibrado no ensaio:

| escopo | fator | cobertura medida |
|---|---|---|
| capital, por seção | 1,25 | 35 de 35 |
| estado, por seção | 3,5 | — |
| Brasil, por município, reamostrando UFs | 1,5 | 89% |
| Brasil, por município, reamostrando municípios dentro da UF | — | **23%** |

O erro é regional; reamostrar a unidade pequena não o enxerga.

### 4.4 Ensaio 2018 → 2022, na ordem real de chegada

| escopo | contagem L−B com 25% | projeção com 25% | final | erro médio contagem → projeção |
|---|---|---|---|---|
| capital, por seção | +6,5 | +9,1 | +9,6 | 0,45 → 0,33 |
| estado de SP | −13,4 | −7,4 | −6,8 | 1,17 → 0,40 |
| Brasil, por seção | −4,4 | +4,1 | +5,2 | 1,79 → 0,35 |
| Brasil, por município | −4,4 | +3,4 | +5,2 | 1,79 → 0,26 |

**Sobrou um viés de ~0,9 ponto a menos para Lula até metade da noite**, igual nas
duas camadas: as urnas tardias foram mais Lula do que a eleição anterior e a UF
explicam.

### 4.5 E na noite de verdade (04/10/2026), Brasil por município

Final: **Flávio 47,03%, Lula 45,16%** (−1,87).

| hora | apurado | contagem L−F | projeção L−F | intervalo de Lula |
|---|---|---|---|---|
| 18:16 | 17% | −10,7 | −3,7 | 42,4–46,1 |
| 18:42 | 38% | −9,2 | −3,2 | 43,2–45,8 |
| 19:05 | 59% | −7,9 | −2,7 | 43,9–45,6 |
| 19:24 | 73% | −6,3 | −2,4 | 44,3–45,4 |
| 20:28 | 91% | −4,0 | −2,1 | 44,8–45,2 |
| 21:07 | 98,5% | −2,4 | −1,95 | 45,09–45,15 |

- **O intervalo continha o final desde 17% das urnas**, quando a contagem estava
  9 pontos longe.
- **O viés de 2022 se repetiu ao vivo**: a projeção ficou sempre abaixo de Lula,
  ~0,9 ponto no começo e menos à medida que a noite avançava. **A correção desse
  viés é a primeira coisa a fazer para o próximo turno.**
- No fim da noite, o intervalo ficou **estreito demais**: a 98,5%, dava
  45,09–45,15, e o final foi 45,16. O fator deveria crescer quando quase tudo já
  foi apurado (o resto é exatamente a parte atípica), ou ter um piso.

### 4.6 Inferência ecológica: falhou na régua, e isso mudou a página

- A ideia era estimar o voto **das pessoas** de cada grupo, como evangélicos e
  escolaridade, por inferência ecológica (PyEI e NUTS passaram de 20 min; SVI do
  NumPyro em ~20 s).
- **A régua foi o comparecimento por escolaridade**, que é dado real do TSE: o
  que a inferência estimasse para ele tinha que bater com o real. **Errou até 10
  pontos e inverteu a ordem da escolaridade em todas as variantes.**
- A idade, em 5 faixas, passou (erro máximo de 4,4 pontos).
- Decisão: escolaridade, renda, cor e religião aparecem como **perfil do lugar**,
  em quintis com o mesmo número de eleitores, como dado real agrupado, nunca como
  "voto do grupo". Cada quadro diz isso. É também o que evita o **paradoxo de
  Simpson** dos evangélicos, que apareceu nos dados de SP.
- **Casamento local de votação ↔ Censo**: raio de 1,5 km com peso exp(−d/600 m)
  casou melhor que Voronoi, mas só **razoavelmente**. A correlação na parcela de
  60+ entre TSE e Censo foi de 0,59.

### 4.7 Descartado por medição

| o que | por quê |
|---|---|
| perfil do eleitorado como variável fora de SP | ganho de 0,38 → 0,33 ponto: pouco |
| 2º turno da eleição anterior como covariável | piorou: 0,26 → 0,28 |
| quanto confiar no parcial do próprio município (por volume, fração ou zero) | não muda o viés |
| Datafolha como régua | o Danilo não confia; o comparecimento real substituiu com vantagem: é dado, não pesquisa |

---

## 5. A noite de 04/10/2026, em ordem — cada falha e a correção

| hora | o que aconteceu | correção |
|---|---|---|
| 17h27 | nenhum BU de SP era lido: o nome mudou para `-bu.dat` | escolher pelo `tp`; seção sem BU legível volta para a fila |
| 17h40 | a varredura nacional levava 8–9 min, presa na latência (~90 ms por pedido) | 8 pedidos em paralelo, teto de 25 req/s |
| 17h43 | a trava de 404 desligou o coletor de SP por 11 min | esperar 4 min depois da hora do índice; parar a rodada no 1º 404 |
| 17h45–18h03 | **projeção nacional zerada**: 7 municípios novos em 2026 sem 2022 davam `NaN` no comparecimento-base, que contaminava a padronização do modelo inteiro | mediana no lugar; guarda para `NaN` nas covariáveis |
| ~18h | mapa preto: cor de grupo sem dado | guarda de cor para valor não finito |
| 18h14–18h37 | coletor de SP desligado pela **nossa própria** trava a cada minuto, parado em 2.341 seções | ordem, 8 em voo, espera por seção, orçamento de 404 |
| 18h45 | governador e senador de SP parados em ~5% (só existiam via boletins) | **camada por município de SP** para os dois cargos, ao lado dos boletins, com a chave "Fonte" na página |
| ~19h | o Danilo pediu atualização mais rápida | push a cada 2 min; a página recarrega a cada 2 min |
| 05/10 12h40 | coletor de SP parado em 44.932 seções: o bloco que nunca sai travava a frente da fila | sorteio na fila e espera crescente |

E as falhas de antes da noite, que custaram tempo:

- **A trava de 404 disparou por um dia e meio no simulado** (29–30/09), porque
  antes da publicação todo pedido é 404. Agora há uma única sondagem por rodada.
- **O GET condicional pulava seções pendentes**: com 304 no índice, o coletor
  concluía "nada mudou". Agora ele relê o índice guardado.
- **Colisão de `id` na página de método** (`regua` duas vezes) e o clique do
  quintil roubando o clique das linhas de região: os dois foram corrigidos.
- **A cor por posição pintou Bolsonaro de vermelho em SP**, onde ele ficou em
  primeiro. A regra é **cor por identidade**: PT vermelho, o principal
  adversário azul.
- **O mesmo número de urna muda de dono entre eleições** (222 no Senado de SP: um
  candidato em 2022, outro em 2026). As chaves da eleição anterior levam o
  sufixo `_ant`.

---

## 6. Ambiente desta máquina (Windows)

- **O Controle de Aplicativos do Windows** bloqueou uma DLL do SciPy uma vez e
  bloqueia o JAX sempre. Não se mexe em política de segurança.
  - `vizinho.py` tem um caminho em numpy puro para o vizinho mais próximo.
  - O NumPyro/JAX não é necessário na noite.
- **Parar processo pelo PID** (`Get-CimInstance Win32_Process` → `Stop-Process
  -Id`), nunca `taskkill` com filtro amplo: um filtro amplo já derrubou o que
  não devia.
- Matar o `noite.py` **não** mata os filhos. Reiniciar a noite sem parar os
  filhos duplica os coletores.
- Quando o `noite.py` reinicia um filho, ele procura "PARADO" nos últimos 2.000
  caracteres do log do filho. Depois de um reinício manual, é preciso empurrar o
  "PARADO" para fora desse trecho, senão o filho espera 11 min à toa.
- `jq` não existe neste shell (o `--jq` do `gh` funciona).
- Máquina em modo de não dormir na noite da eleição: o simulado foi perdido por
  isso.

---

## 7. Para recomeçar do zero — a ordem que eu seguiria

1. **No primeiro dia:** baixar o que o TSE pode apagar e versionar o que não é
   regenerável.
2. **Mapear os endereços pela configuração do TSE** (`ele-c.json` → config da
   eleição → índice → auxiliar), nunca pelo padrão de 4 anos atrás. Conferir
   cada arquivo com um pedido antes de escrever o coletor.
3. **Duas camadas desde o início:**
   - **por município** (arquivo `u`), que acompanha a noite;
   - **urna a urna** (BU), que dá o detalhe e chega com 20–40 min de atraso, ou
     horas.
   Todos os cargos que importam na camada rápida.
4. **Ensaio contra uma eleição passada, na ordem real de chegada**, antes de
   qualquer página bonita. É dele que saem o fator do intervalo e o viés.
5. **Um TSE de mentira local**, rodando a noite inteira: pega o que os testes de
   unidade não pegam.
6. **Corrigir o viés de chegada tardia**, medido duas vezes (ensaio e noite real):
   ~0,9 ponto contra o candidato das urnas tardias na primeira metade da noite.
7. **Página só com dado agregado real; inferência de grupo só se passar na régua
   do comparecimento.**
8. **Depois da noite:** baixar os boletins do país inteiro (≈6 h a 35 req/s) para
   as checagens e para a base do turno seguinte.

---

## 8. Depois do 1º turno (05/10/2026) — o que preparou o 2º

- **Os boletins do país inteiro baixam em uma tarde** depois da apuração
  (`coletar_brasil.py`, ~17 seções/s a 35 req/s). Mas o coletor de SP travou
  de novo: um bloco de seções com auxiliar 404 treze horas depois ocupava a
  frente da fila. A correção foi sorteio na fila, 404 para o fim e espera
  crescente. Sobraram 569 das 103.656 seções de SP (0,5%) sem boletim publicado.
- **Transição 1º → 2º turno de 2022, seção a seção** (`transicao.py`). As
  mesmas 472 mil urnas e os mesmos 156,5 milhões de aptos nos dois turnos. A
  regressão ecológica com linhas no simplex:
  - **prevê bem**: 0,68 ponto de erro por município fora do ajuste, contra 1,68
    de repetir o 1º turno;
  - **identifica mal cada célula**: entre municípios, dava Tebet → 24% Lula e
    branco → 44% Bolsonaro; **dentro de cada município** (só as seções dele,
    puxadas para a UF), dá Tebet → 38%/46% e branco → 12%/35%. Os dois métodos
    discordam em até 14 pontos (Ciro → Lula: 50 contra 36). A estimativa dentro
    do município é estável em κ (0,02–0,5).
- **Ensaio da noite do 2º turno de 2022** (`ensaio_2t.py`), por município, na
  ordem real de chegada. Erro médio no percentual de Lula:

  | variante | erro médio |
  |---|---|
  | contagem | 2,71 |
  | base de 2018 | 0,69 |
  | base do 1º turno | 0,51 |
  | transição | 0,27 |
  | **transição sabendo quais seções chegaram** | **0,04** |

  As três primeiras tinham o mesmo viés de ~0,5 contra Lula no meio da noite. Ele
  não vem da base: vem de **quais seções de cada município** já estão no parcial.
- **O índice de seções diz quais são** (`conferir_indice.py`). Somando os
  boletins das `st` primeiras seções do índice de cada município, o parcial
  publicado sai voto a voto em 83–90% dos municípios de SP. O resto (0,2–0,6%
  dos votos) são as seções sem boletim. O índice anda à frente do arquivo `u`,
  nunca atrás (salvo dois momentos).
- **Código do 2º turno:** a eleição de Presidente é a **6258** (`cdt2` da 6257,
  no `ele-c.json`). O pleito do 2º turno ainda não estava publicado em 05/10.
  `tse.pleito_2t()` o lê quando aparecer, sem supor 3221.
- **Simulador** (`simulador.py`, `web/simulador.html`):
  - o ponto de partida são as matrizes de 2022 de cada município;
  - os candidatos novos entram por analogia escolhida pelo Danilo: Cury ←
    Tebet, Renan ← Ciro, Caiado ← Soraya, Zema ← D'Avila;
  - partida: **Lula 47,45% × Flávio 52,55%**; os dois métodos concordam no total
    (47,42%);
  - `requestAnimationFrame` não dispara com a aba oculta: o recálculo agenda
    com `setTimeout`.
- **Boletins do Brasil inteiro, 1º turno de 2026:** 498.925 de 499.248 seções,
  baixadas em ~4 h com dois processos (UFs disjuntas, 35 req/s cada). 5.708 de
  5.717 municípios batem voto a voto com o arquivo `u`; faltam 0,06% dos votos,
  de seções sem boletim publicado. Base em `data/raw/2026/secoes_1t_brasil.parquet`
  (`base_secoes.py`).
- **Checagens de 2026:** zero seções com soma diferente do comparecimento, zero
  com comparecimento acima dos aptos; o Senado de SP soma o dobro do
  comparecimento (duas vagas). A assinatura digital **não foi feita**, e a página
  diz isso.
- **Projeção do 2º turno** (`segundo.py`), na reprodução do 2º turno de 2022:
  erro médio de 0,067 ponto; o intervalo de 90% com fator 1,5 cobriu o real nos
  7 momentos. É calibração numa eleição só.
- **Noite do 2º turno montada e ensaiada de ponta a ponta** (06/10/2026).
  `noite.py --turno 2` sobe três processos, mais o coletor de boletins de SP na
  noite real:
  - `nacional.py`: arquivo `u` da eleição 6258;
  - `indices.py`: índice de seções das 28 UFs;
  - `domingo.py --turno 2`, que usa `painel_2t.py` e, por ele, `segundo.py`.

  Ensaio contra `tse_falso.py --turno 2`, que serve o 2º turno de 2022 em todas as
  UFs com um pleito local `falso_2t` e pasta própria:

  | varredura | seções | intervalo de Lula |
  |---|---|---|
  | 1ª | 9% | 50,65–51,20 |
  | 2ª | 57% | 50,71–51,11 |
  | 3ª | 95% | 50,70–51,10 (central 50,898) |

  O real foi 50,90. Nenhum 404, rodada do painel em 7–10 s. A varredura dos 5.710
  municípios leva ~4 min a 25 req/s.
- **A reamostragem a partir da matriz central** (400 iterações em vez de 1.500)
  manteve a calibração (fator 1,5: 7 de 7). O intervalo, porém, chega a ±0,05
  ponto no meio da noite, e por isso ganhou um **piso de ±0,2**.
- **O código do pleito do 2º turno ainda não está publicado.** `tse.obter("2026_2t")`
  o lê do `ele-c.json` quando a noite sobe; se não houver, o processo para com
  mensagem clara, e o `noite.py` tenta de novo em 20 s.

## 9. Perfis de outras fontes (07/10/2026)

- **API do IBGE** (`servicodados.ibge.gov.br/api/v3/agregados`): o catálogo inteiro sai numa chamada, e os
  metadados de cada tabela dizem até que nível territorial ela desce. O que mordeu:
  - **"-" é zero**, não vazio: 33 municípios sem população rural e 26 sem esgoto eram zeros lidos
    como faltantes;
  - **o PIB por setor, por município, só vai até 2021** na API (2022 e 2023 vêm "..."), embora o PIB
    total de 2023 já esteja lá;
  - **o Cadastro Central de Empresas por natureza jurídica só desce até UF**: não há funcionalismo
    público por município; o peso da administração pública no PIB é o substituto, com o nome dizendo
    o que é.
- **Bolsa Família**: a API pública do MDS (`aplicacoes.mds.gov.br/sagi/servicos/misocial`, Solr) dá
  pessoas beneficiárias e população do Censo 2022 por município e mês, por script.
- **IDH municipal**: o oficial é de 2010, e o endereço antigo do Atlas Brasil não responde; ficou de fora.
- **Filtro de UF como conjunto**: "Brasil sem o Sudeste" é desmarcar o Sudeste. O intervalo de qualquer
  conjunto sai das reamostragens por UF somadas no navegador (`amostras_uf`), a mesma conta das faixas
  de quintis.
