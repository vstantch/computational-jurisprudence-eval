# Golden tables

Byte-exact copies of the tables as published, taken from the paper repository
(vstantch/computational-jurisprudence, `R3/r2-submitted/tables/`, identical to
`fi-review/tables/`). CI regenerates both from `results/MANIFEST.toml` and
fails on any byte difference:

    python3 python/mkcrossplatform.py apple-m4 x86-cloud /tmp/crossplatform.tex
    python3 python/mkvariability_table.py --out /tmp/variability.tex
    cmp /tmp/crossplatform.tex tests/golden/crossplatform.tex
    cmp /tmp/variability.tex tests/golden/variability.tex

Do not edit these files; they are the published result, not an output.
