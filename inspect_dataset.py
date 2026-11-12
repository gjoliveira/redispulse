
import csv
from pathlib import Path

files = list(Path("data/raw").glob("*.csv"))

if not files:
    print("No CSV files found in data/raw/")
else:
    for file in files:
        print(f"\nFile: {file.name}")

        with file.open(newline="") as f:
            reader = csv.DictReader(f)

            print("Columns:", reader.fieldnames)
            print("\nFirst 5 records:")

            for i, row in enumerate(reader):
                if i == 5:
                    break
                print(row)
