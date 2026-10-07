"""Congela o painel de uma noite como página de consulta: web/<prefixo>.html + web/dados/<prefixo>_*.json.

O painel principal (index.html) segue mudando para a próxima eleição; a página
congelada fica com o código e os dados do dia em que foi gerada. Ela lê só os
arquivos com o próprio prefixo, não recarrega sozinha e diz no topo que é arquivo.

    python arquivar.py --prefixo 1t2026 --titulo "1º turno de 2026 — resultado final"
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

WEB = Path("web")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefixo", required=True)
    ap.add_argument("--titulo", required=True)
    ap.add_argument("--origem", default="2026", help="prefixo dos JSON de hoje")
    a = ap.parse_args()
    copiados = []
    for f in sorted((WEB / "dados").glob(f"{a.origem}_*.json")):
        destino = f.with_name(f.name.replace(f"{a.origem}_", f"{a.prefixo}_", 1))
        shutil.copyfile(f, destino)
        copiados.append(destino.name)
    h = (WEB / "index.html").read_text(encoding="utf-8")
    trocas = [
        # só o modo congelado (o painel ao vivo é o do 2º turno desde 06/10/2026)
        (r'const MODOS = \[\["2026t2","2º turno — ao vivo"\],\["ensaio2t","Ensaio com 2022"\]\];',
         f'const MODOS = [["{a.prefixo}","{a.titulo}"]];'),
        # sem atualização automática
        (r'setInterval\(\(\) => \{ if \(modo && modo.startsWith\("2026"\).*?\n', "// página de arquivo: sem atualização automática\n"),
        # abre no congelado
        (r'const r = await fetch\("dados/2026t2_brasil_presidente.json".*?\n\s*carregar\(r.ok \? "2026t2" : "ensaio2t"\);',
         f'carregar("{a.prefixo}");'),
        (r"<title>[^<]*</title>", f"<title>Eleições — {a.titulo}</title>"),
        (r'<h1>Eleições 2026 — 2º turno: apuração e projeção</h1>\s*<p class="sub" id="subtitulo">[^<]*',
         f'<h1>{a.titulo}</h1>\n    <p class="aviso-arquivo">Página de consulta: os dados como ficaram ao fim da apuração, com os '
         f'recortes de perfil acrescentados depois. O painel ao vivo está em <a href="index.html">index.html</a>.</p>\n'
         f'    <p class="sub" id="subtitulo">Brasil por município; São Paulo urna a urna. '),
    ]
    for padrao, novo in trocas:
        h, n = re.subn(padrao, novo, h, count=1, flags=re.S)
        if n != 1:
            sys.exit(f"não achei no index.html: {padrao[:60]}… — o arquivo mudou; ajustar arquivar.py")
    # no modo congelado o rótulo dos dados ("2026") e o painel ao vivo coincidem: modo "1t2026" vale como 2026
    h = h.replace('m.modo==="ensaio" ? "momento do ensaio: " : "atualizado às "',
                  'm.modo==="ensaio" ? "momento do ensaio: " : "dados finais, gerados às "')
    h = h.replace("</style>", "  .aviso-arquivo{background:var(--accent-soft);border:1px solid var(--line);border-radius:8px;"
                              "padding:6px 10px;font-size:13px;margin:6px 0}\n</style>", 1)
    (WEB / f"{a.prefixo}.html").write_text(h, encoding="utf-8")
    print(f"web/{a.prefixo}.html; dados: {', '.join(copiados)}")


if __name__ == "__main__":
    main()
