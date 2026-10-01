"""Vizinho mais próximo, com o SciPy quando ele carrega e numpy puro quando não.

Em 01/10/2026 o Controle de Aplicativos do Windows bloqueou uma DLL do SciPy
(`_linalg_pythran`) na primeira carga — e liberou nas cinco seguintes. É política de
segurança da máquina, não se mexe nela; o que se faz é a projeção da noite não
depender de uma DLL que pode ser recusada. O caminho em numpy é força bruta em
blocos: mais lento (segundos), e só roda uma vez por noite, na preparação.
"""
import numpy as np

try:
    from scipy.spatial import cKDTree
except ImportError:      # inclui DLL bloqueada pela política do Windows
    cKDTree = None


def mais_proximo(base, pontos, bloco=2000):
    """Para cada ponto, (distância, índice) do mais próximo em `base` (arrays N×2)."""
    base = np.asarray(base, float)
    pontos = np.asarray(pontos, float)
    if cKDTree is not None:
        return cKDTree(base).query(pontos)
    d_out = np.empty(len(pontos))
    i_out = np.empty(len(pontos), dtype=int)
    b2 = (base ** 2).sum(1)
    for ini in range(0, len(pontos), bloco):
        p = pontos[ini:ini + bloco]
        d2 = (p ** 2).sum(1)[:, None] + b2[None, :] - 2 * p @ base.T
        i = d2.argmin(1)
        i_out[ini:ini + bloco] = i
        d_out[ini:ini + bloco] = np.sqrt(np.maximum(d2[np.arange(len(p)), i], 0))
    return d_out, i_out
