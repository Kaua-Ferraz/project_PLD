import pandas as pd
from pathlib import Path

raiz = Path(__file__).resolve().parent.parent

folder = (
    raiz / "data" / "raw" / "ons"
    / "balanco-energia-subsistema" / "current"
)

files = sorted(folder.glob("*.csv"))

if not files:
    raise FileNotFoundError("Nenhum CSV encontrado.")

df = pd.read_csv(
    files[0],
    sep=";"
)

print("Arquivo:", files[0].name)

print("\nDimensões:", df.shape)

print("\nColunas:")
print(df.columns.tolist())

print("\nTipos:")
print(df.dtypes)

print("\nPrimeiras linhas:")
print(df.head(10).to_string(index=False))

print("\nValores ausentes:")
print(df.isna().sum())