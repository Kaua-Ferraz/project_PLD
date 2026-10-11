import pandas as pd
from pathlib import Path

raiz = Path(__file__).resolve().parent.parent
caminho_csv = raiz / "data" / "raw" / "ons" / "carga-energia" / "current" / "Carga_Energia-2026.csv"
df = pd.read_csv(
    caminho_csv,
    sep=";"
)

print("Dimensões:", df.shape)
print("\nColunas:", df.columns.tolist())
print("\nTipos:\n", df.dtypes)
print("\nPrimeiras linhas:\n", df.head(10).to_string(index=False))
print("\nValores ausentes:\n", df.isna().sum())