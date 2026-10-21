# JavaParser extractor

Shared extractor behind every dataset's `dataset.py`. It parses a Java source tree with JavaParser
(symbol-resolved, Java 17+ syntax) and writes `dataset.json`.

```bash
mvn -q package            # builds target/extractor.jar
java -jar target/extractor.jar --source <dir> --out dataset.json \
     --dataset <name> --build-path <p> --xmi-path <p> [--source-path <p>]
```

- `methods`: every method and constructor (`<init>`) of every class, interface, enum and record, id `pkg.Class.method`
  (nested types use dots, `pkg.Outer.Inner.method`); overloads share an id and the first signature wins.
  `calls` lists project callees, one entry per call site.
- `edges`: class-level `CALL` (method and constructor calls), `EXTENDS`, `IMPLEMENTS` and `FIELD` edges between project
  classes, `weight` = number of occurrences. Each call is attributed to its nearest enclosing named type.
- Source roots: every `*/src/main/java`; if there is none, the repo's top-level `src/` (Eclipse layout, e.g. acme-air); else the repo root. Maven test sources are therefore excluded.
- Any file that fails to parse aborts the run with exit code 1 and names the file; nothing is silently skipped.
- Calls the symbol solver cannot resolve are counted (`calls_resolved=a/b` on stdout) and dropped.
