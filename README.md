# HDScan

File Archive Catalog & Disk Intelligence System — skenira diskove/foldere, kataloguje fajlove u SQLite bazu (sa hash-ovanjem za deduplikaciju), i omogućava pretragu, statistiku, Excel export i web UI za pregled kataloga.

## Instalacija

```
pip install -e .
```

## Komande (CLI: `hdscan`)

- `hdscan scan <path>` — skenira folder/disk u katalog (`--hash-mode full|sampled|none`, `--excel PATH`, `--no-excel`)
- `hdscan search [query]` — pretraga po imenu, ekstenziji, veličini, disku (`--ext`, `--min-size`, `--max-size`, `--disk`, `--dupes`, `--limit`)
- `hdscan stats` — statistika kataloga (broj fajlova, ukupna veličina, po disku)
- `hdscan backup` — forsira odmah backup baze
- `hdscan export <output.xlsx> [query]` — export kataloga (opciono filtriran) u Excel
- `hdscan browse` — pokreće lokalni web UI za pregled kataloga (`--port`, `--no-browser`)

## Skripte

- `scan.bat` — pokreće skeniranje
- `browse.bat` — pokreće web UI za pregled

## Testovi

```
pytest
```
