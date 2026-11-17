"""Genera documento/documento.pdf y poster/poster.pdf.

El documento sale de documento.md con el formato de templates/template-documento.md
(A4, márgenes de 2,5 cm, Arial 12 e interlineado 1,5). El póster sale de
poster/poster.html, en A1. Los dos se imprimen con Chrome (o Edge) sin interfaz.

Uso, desde la raíz del repo:

    pip install markdown
    python documento/generar_pdf.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

RAIZ = Path(__file__).resolve().parent.parent

CSS = """
@page { size: A4; margin: 2.5cm; }
body { font-family: Arial, sans-serif; font-size: 12pt; line-height: 1.5; color: #000; }
h1 { font-size: 16pt; } h2 { font-size: 14pt; margin-top: 1.2em; } h3 { font-size: 12pt; }
table { border-collapse: collapse; width: 100%; font-size: 11pt; line-height: 1.3; margin: 0.5em 0; }
th, td { border: 1px solid #888; padding: 3px 6px; vertical-align: top; text-align: left; }
th { background: #eee; }
img { max-width: 100%; }
h2, h3 { break-after: avoid; }
pre, img, tr { break-inside: avoid; }
pre { font-size: 10pt; line-height: 1.3; background: #f4f4f4; padding: 6px; white-space: pre-wrap; }
code { font-size: 10.5pt; }
"""

NAVEGADORES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]


def navegador() -> str:
    for candidato in NAVEGADORES:
        ruta = shutil.which(candidato) or (candidato if os.path.isfile(candidato) else None)
        if ruta:
            return ruta
    sys.exit("No encontré Chrome ni Edge para imprimir el PDF.")


def imprimir(html: Path, pdf: Path, perfil: str) -> None:
    subprocess.run(
        [navegador(), "--headless=new", "--disable-gpu", f"--user-data-dir={perfil}",
         "--no-pdf-header-footer", "--virtual-time-budget=5000",
         f"--print-to-pdf={pdf}", html.as_uri()],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print(f"{pdf.relative_to(RAIZ)}: {paginas(pdf)} página(s)")


def paginas(pdf: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes()))


def documento_html(destino: Path) -> None:
    texto = (RAIZ / "documento" / "documento.md").read_text(encoding="utf-8")
    # Python-Markdown necesita una línea en blanco antes de una lista (GitHub no).
    texto = re.sub(r"(?m)^(\*\*[^\n]*:\*\*)\n- ", r"\1\n\n- ", texto)
    cuerpo = markdown.markdown(texto, extensions=["tables", "fenced_code", "sane_lists"])
    base = (RAIZ / "documento").as_uri() + "/"
    destino.write_text(
        f'<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><base href="{base}">'
        f"<style>{CSS}</style></head><body>{cuerpo}</body></html>",
        encoding="utf-8",
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        html = Path(tmp) / "documento.html"
        documento_html(html)
        imprimir(html, RAIZ / "documento" / "documento.pdf", str(Path(tmp) / "perfil"))
        imprimir(RAIZ / "poster" / "poster.html", RAIZ / "poster" / "poster.pdf", str(Path(tmp) / "perfil"))


if __name__ == "__main__":
    main()
