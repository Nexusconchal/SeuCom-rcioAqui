"""Backup consistente do SQLite em uso."""
import argparse
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser(description="Backup do banco SeuComércioAqui")
parser.add_argument("source", type=Path)
parser.add_argument("destination", type=Path)
args = parser.parse_args()
source = args.source.resolve()
destination = args.destination.resolve()
if not source.is_file():
    parser.error("Banco de origem não encontrado.")
if source == destination:
    parser.error("Origem e destino precisam ser diferentes.")
if destination.exists():
    parser.error("O destino já existe; use um nome novo.")
destination.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as original:
    with sqlite3.connect(destination) as backup:
        original.backup(backup)
print(f"Backup salvo em {destination}")
