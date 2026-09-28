"""Inferência ecológica: como cada grupo votou, a partir das urnas e do perfil de quem está inscrito nelas.

Modelo (escolhido e medido em 28/09/2026 — PyEI e NUTS passaram de 20 minutos;
este ajusta em segundos):

  para cada unidade u (seção ou local), com composição g_u (fração do
  eleitorado em cada grupo r) e resultado n_u (votos por categoria c,
  incluindo **abstenção** — o perfil é de quem está inscrito, não de quem votou):

      n_u ~ DirichletMultinomial( conc · Σ_r g_ur · β[zona(u), r, :] )
      β[k, r, :] = softmax( θ[r, :] + τ · z[k, r, :] ),   z ~ N(0, 1)

  O voto de cada grupo varia entre zonas eleitorais e é encolhido para o do
  município (τ aprendido). A Dirichlet-multinomial absorve a variação entre
  unidades que a composição não explica. Ajuste por inferência variacional
  (SVI). O número publicado é o β do município: média das zonas ponderada pelo
  tamanho do grupo em cada uma.

Incerteza: reamostragem de zonas inteiras, refazendo o ajuste. O intervalo do
SVI sozinho sai estreito (83% de cobertura para 90% nominal, medido em dado
sintético) e não enxerga o erro do próprio modelo; a reamostragem enxerga parte.

**O que o modelo não resolve** é o viés de agregação: gente do mesmo grupo
votando diferente conforme o bairro, de um jeito que a zona não captura. É por
isso que existe a validação pelo comparecimento — o TSE publica o comparecimento
real por perfil, e o modelo tem que reproduzi-lo antes de ser usado no voto.

    python ei.py --validar      # comparecimento estimado × real, 2022, capital
"""
import argparse
import sys
import time
from pathlib import Path

import jax
import jax.numpy as jnp
import numpy as np
import numpyro
import numpyro.distributions as dist
import pandas as pd
from numpyro.infer import SVI, Predictive, Trace_ELBO
from numpyro.infer.autoguide import AutoLowRankMultivariateNormal

RAW = Path("data/raw")
OUT = Path("out")

# grupos, a partir das categorias do TSE (perfil por seção)
IDADE = [("16-24", 16, 24), ("25-34", 25, 34), ("35-44", 35, 44),
         ("45-59", 45, 59), ("60-69", 60, 69), ("70+", 70, 200)]
ESCOLARIDADE = {
    "ANALFABETO": "até fund. incompleto", "LÊ E ESCREVE": "até fund. incompleto",
    "ENSINO FUNDAMENTAL INCOMPLETO": "até fund. incompleto",
    "ENSINO FUNDAMENTAL COMPLETO": "fund. completo / médio incompleto",
    "ENSINO MÉDIO INCOMPLETO": "fund. completo / médio incompleto",
    "ENSINO MÉDIO COMPLETO": "médio completo / sup. incompleto",
    "SUPERIOR INCOMPLETO": "médio completo / sup. incompleto",
    "SUPERIOR COMPLETO": "superior completo",
}
SEXO = {"FEMININO": "mulheres", "MASCULINO": "homens"}


def faixa(ds):
    try:
        i = int(str(ds).strip().split()[0])
    except ValueError:
        return None
    return next((n for n, a, b in IDADE if a <= i <= b), None)


def grupo_de(p, variavel):
    if variavel == "idade":
        return p.DS_FAIXA_ETARIA.map(faixa)
    if variavel == "escolaridade":
        return p.DS_GRAU_ESCOLARIDADE.map(ESCOLARIDADE)
    if variavel == "sexo":
        return p.DS_GENERO.map(SEXO)
    raise ValueError(variavel)


def ordem_grupos(variavel):
    if variavel == "idade":
        return [n for n, _, _ in IDADE]
    if variavel == "escolaridade":
        return list(dict.fromkeys(ESCOLARIDADE.values()))
    return list(dict.fromkeys(SEXO.values()))


def composicao_secoes(ano, variavel, mun="71072"):
    """Seção × grupo: número de eleitores (perfil do TSE, somando agregadas na principal)."""
    from projecao import principal_de
    col_n = "QT_ELEITORES_PERFIL" if ano == "2022" else "QT_ELEITORES"
    p = pd.read_parquet(RAW / "tse" / f"perfil_{ano}_SP.parquet",
                        columns=["CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "DS_GENERO",
                                 "DS_FAIXA_ETARIA", "DS_GRAU_ESCOLARIDADE", col_n])
    p = p[p.CD_MUNICIPIO == mun]
    p = p.assign(zona=p.NR_ZONA.astype(int), secao=p.NR_SECAO.astype(int),
                 n=pd.to_numeric(p[col_n]), grupo=grupo_de(p, variavel))
    pr = principal_de(ano)[["zona", "secao", "principal"]]
    p = p.merge(pr, on=["zona", "secao"], how="left")
    p["secao"] = p.principal.fillna(p.secao).astype(int)
    g = (p.dropna(subset=["grupo"])
         .pivot_table(index=["zona", "secao"], columns="grupo", values="n", aggfunc="sum")
         .reindex(columns=ordem_grupos(variavel)).fillna(0))
    return g


# ---------------------------------------------------------------- modelo
def _modelo(g, reg, K, x=None, n=None, tot=None):
    U, R = g.shape
    C = n.shape[1] if n is not None else 2
    th = numpyro.sample("theta", dist.Normal(0, 2).expand([R, C]).to_event(2))
    tau = numpyro.sample("tau", dist.HalfNormal(0.5))
    z = numpyro.sample("z", dist.Normal(0, 1).expand([K, R, C]).to_event(3))
    eta = th[None] + tau * z                                   # K,R,C
    if x is not None:
        # contexto da unidade mexe no voto de cada grupo: sem isso, a diferença
        # entre bairros vira troca entre grupos que moram juntos (viés de agregação)
        gam = numpyro.sample("gamma", dist.Normal(0, 1).expand([x.shape[1], R, C]).to_event(3))
        bu = jax.nn.softmax(eta[reg] + jnp.einsum("up,prc->urc", x, gam), -1)   # U,R,C
        pu = jnp.einsum("ur,urc->uc", g, bu)
        numpyro.deterministic("bu", bu)
    else:
        pu = jnp.einsum("ur,urc->uc", g, jax.nn.softmax(eta, -1)[reg])
    b = jax.nn.softmax(eta, -1)
    conc = numpyro.sample("conc", dist.LogNormal(5, 2))
    with numpyro.plate("u", U):
        numpyro.sample("v", dist.DirichletMultinomial(conc * pu + 1e-6, total_count=tot), obs=n)
    numpyro.deterministic("b", b)


def ajustar(G, N, zona, X=None, passos=3000, amostras=200, semente=0):
    """G: unidades × grupos (contagens), N: unidades × categorias (contagens).
    Devolve amostras do β do município (amostras × grupos × categorias),
    ponderando as zonas pelo tamanho de cada grupo nelas."""
    G = np.asarray(G, float)
    N = np.asarray(N, float)
    zonas, reg = np.unique(zona, return_inverse=True)
    K = len(zonas)
    g = G / G.sum(1, keepdims=True)
    args = (jnp.array(g), jnp.array(reg), K)
    kw = dict(n=jnp.array(N), tot=jnp.array(N.sum(1)))
    if X is not None:
        X = np.asarray(X, float)
        kw["x"] = jnp.array((X - X.mean(0)) / (X.std(0) + 1e-9))
    guia = AutoLowRankMultivariateNormal(_modelo)
    svi = SVI(_modelo, guia, numpyro.optim.Adam(0.02), Trace_ELBO())
    r = svi.run(jax.random.PRNGKey(semente), passos, *args, progress_bar=False, **kw)
    post = Predictive(guia, params=r.params, num_samples=amostras)(
        jax.random.PRNGKey(semente + 1), *args, **kw)
    if X is not None:
        # com contexto o voto é por unidade: pondera cada unidade pelo tamanho do grupo nela
        bu = np.asarray(Predictive(_modelo, posterior_samples=post, return_sites=["bu"])(
            jax.random.PRNGKey(semente + 2), *args, **kw)["bu"])       # S,U,R,C
        return (G[None, :, :, None] * bu).sum(1) / G.sum(0)[None, :, None]
    b = np.asarray(Predictive(_modelo, posterior_samples=post, return_sites=["b"])(
        jax.random.PRNGKey(semente + 2), *args, **kw)["b"])            # S,K,R,C
    w = np.zeros((K, G.shape[1]))
    np.add.at(w, reg, G)                                               # eleitores do grupo por zona
    return (w[None, :, :, None] * b).sum(1) / w.sum(0)[None, :, None]  # S,R,C


def com_reamostragem(G, N, zona, n_boot=20, **kw):
    """Ajuste principal + reamostragem de zonas. Devolve (ponto R×C, amostras B×R×C)."""
    G, N, zona = np.asarray(G, float), np.asarray(N, float), np.asarray(zona)
    ponto = ajustar(G, N, zona, **kw).mean(0)
    rng = np.random.default_rng(0)
    zs_all = np.unique(zona)
    boot = []
    for i in range(n_boot):
        zs = rng.choice(zs_all, len(zs_all), replace=True)
        idx = np.concatenate([np.where(zona == z)[0] for z in zs])
        # zona repetida vira zona distinta, senão o modelo a vê como uma só
        rot = np.concatenate([np.full((zona == z).sum(), j) for j, z in enumerate(zs)])
        boot.append(ajustar(G[idx], N[idx], rot, semente=i + 1, amostras=50, **kw).mean(0))
    return ponto, np.array(boot)


# ---------------------------------------------------------------- validação
def validar(variaveis=("idade", "escolaridade", "sexo"), n_boot=20):
    """Comparecimento por grupo: estimado pelas seções × real publicado pelo TSE."""
    v = pd.read_parquet(RAW / "2022" / "sp" / "votos.parquet")
    v = v[(v.cargo == "presidente") & (v.municipio == 71072)]
    s = v.drop_duplicates(["zona", "secao"]).set_index(["zona", "secao"])
    real = pd.read_parquet(RAW / "tse" / "comparecimento_2022_SP.parquet")
    real = real[(real.CD_MUNICIPIO == "71072") & (real.NR_TURNO == "1")]
    for c in ("QT_APTOS", "QT_COMPARECIMENTO"):
        real[c] = real[c].astype(int)
    linhas = []
    for var in variaveis:
        comp = composicao_secoes("2022", var)
        j = comp.join(s[["aptos", "comparecimento"]], how="inner")
        G = j[comp.columns].to_numpy()
        N = np.c_[j.comparecimento, j.aptos - j.comparecimento]
        t = time.time()
        ponto, boot = com_reamostragem(G, N, j.index.get_level_values("zona").to_numpy(),
                                       n_boot=n_boot)
        real["grupo"] = grupo_de(real, var)
        rg = real.groupby("grupo")[["QT_APTOS", "QT_COMPARECIMENTO"]].sum()
        for i, gname in enumerate(comp.columns):
            lo, hi = np.percentile(boot[:, i, 0], [5, 95])
            r = rg.loc[gname]
            linhas.append({"variavel": var, "grupo": gname,
                           "real": 100 * r.QT_COMPARECIMENTO / r.QT_APTOS,
                           "estimado": 100 * ponto[i, 0], "lo90": 100 * lo, "hi90": 100 * hi,
                           "eleitores": int(r.QT_APTOS)})
        print(f"{var}: {len(j):,} seções, {time.time() - t:.0f} s", flush=True)
        for l in linhas[-len(comp.columns):]:
            print(f"   {l['grupo']:34s} real {l['real']:5.1f}  estimado {l['estimado']:5.1f} "
                  f"[{l['lo90']:5.1f}, {l['hi90']:5.1f}]", flush=True)
    r = pd.DataFrame(linhas)
    r["erro"] = r.estimado - r.real
    r["cobre"] = (r.real >= r.lo90) & (r.real <= r.hi90)
    OUT.mkdir(exist_ok=True)
    r.to_csv(OUT / "validacao_comparecimento_2022.csv", index=False, float_format="%.3f")
    print(f"\nerro absoluto médio {r.erro.abs().mean():.2f} pt; máximo {r.erro.abs().max():.2f}; "
          f"IC90 cobre o real em {r.cobre.mean():.0%}")
    return r


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    numpyro.set_host_device_count(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--validar", action="store_true")
    ap.add_argument("--boot", type=int, default=20)
    a = ap.parse_args()
    if a.validar:
        validar(n_boot=a.boot)
