"""Caminhos compartilhados pelos testes (sem pytest: use unittest)."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "dados"
TXT = DADOS / "txt"
DB = DADOS / "desafio1_bracis.db"
GOLDENSET = DADOS / "goldenset.csv"
INDICE = DADOS / "indice.json"
TEM_DADOS = DB.exists() and TXT.is_dir() and GOLDENSET.exists()
