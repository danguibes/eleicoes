# Base de 2022 — cópia versionada

Em **28/09/2026, fim da tarde**, o TSE tirou do ar o ambiente oficial de
resultados de 2022 (`resultados.tse.jus.br/oficial/ele2022/...` passou a dar 404,
e a raiz virou "Resultados | Nova versão em breve", já com a marca de 2026).
Horas antes, o `coletor.py` tinha baixado os 101.073 boletins do estado de SP,
conferidos voto a voto contra o total oficial nos três cargos.

Por esse caminho eles não voltam. Então a parte que o painel usa fica aqui:

- `votos_2022_SP_pres_gov_sen.parquet` — o `votos.parquet` do `tabelar.py`
  (Presidente, governador e senador; uma linha por seção × cargo × votável).
- `chegadas_2022_SP.parquet` — hora em que cada seção chegou ao TSE na noite de
  2022; é o que permite ensaiar a projeção na ordem real.

Os BUs brutos (1,8 GB) e os decodificados com todos os cargos (476 MB) ficaram
só em `data/raw/`, nesta máquina. A alternativa pública é o `bweb_1t_SP_*.zip`
do Portal de Dados Abertos, que só baixa pelo navegador.
