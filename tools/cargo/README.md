# CARGO

Context-sensitive label propagation over a System Dependency Graph built by Doop (points-to analysis of compiled bytecode):
Nitin, Asthana, Ray, Krishna, *CARGO: AI-Guided Dependency Analysis for Migrating Monolithic Applications to Microservices
Architecture*, ASE 2022 (arXiv:2207.11784). Upstream
[vikramnitin9/tackle-data-gravity-insights](https://github.com/vikramnitin9/tackle-data-gravity-insights) is the submodule
`tackle-data-gravity-insights/` (pinned to `902b315`, untouched).

## Run

```bash
cd tools/cargo
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore            # the paper's 30-run grid
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore --k 7 --seeds 42   # one run
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore/runs/k7_seed42
```

`tool.py` needs Docker (it manages a `sota-cargo-neo4j` container, `neo4j:5`; `--neo4j external` uses your own on `localhost:7687`)
and Python 3.12 (uv installs the pinned-by-range `dgi` dependencies from the script header).

1. **Doop facts** (stage 1, cached): `tools/cargo/doop-data/<dataset>/` holds the Datalog fact CSVs Doop produced from the
   dataset's bytecode. They are git-ignored (20-200 MB each, hours to regenerate). Without them the cell is N/A (error-form
   `output.json`).
2. A work copy of `dgi/` gets `patches/dgi-robustness.patch` applied (4 fixes found running 10 datasets: empty fact files,
   `java.lang.Class` literal heap objects, `string-buffer` pseudo-heap markers), then `dgi c2g` loads the facts into Neo4j (and
   `dgi tx2g` loads DiVA transactions from `transactions/<dataset>.json` when one exists, as for daytrader). A marker node means
   repeated invocations on the same dataset skip the reload.
3. CARGO standalone ("unique") runs the paper's RQ3 protocol: **K in {3,5,7,9,11,13} x seeds {42..46} = 30 runs**, averaged rather
   than swept-and-selected. Each run is `runs/k<K>_seed<S>/output.json` (class FQNs, `$` inner-class separator normalised to `.`);
   the root `output.json` is the first run. Score each run directory and average (`scripts/run_sweep.py` does this).

## Producing the Doop facts (not done by tool.py)

Doop (`quay.io/rkrsn/doop-main`) analyses the application **bytecode** with a 2-object-sensitive points-to analysis, via
`./doop -a dependency-analysis --cfg --Xfacts-subset APP --facts-only --open-programs jackee ...` followed by Souffle
(`dependency-analysis.dl`); see `tackle-data-gravity-insights/README.md`. Practical notes from running it on the 10 datasets:

- Doop's Gradle build fetches dependencies from a dead Artifactory (`centauri.di.uoa.gr`). The fix was rebuilding six deps from
  GitHub into a local Maven repo mounted as `/root/.m2` (clue-common 3.22.5 and 3.24.1, native-scanner 0.6.5, metadata-model 2.1.0,
  mini-sarif 0.1.2, HeapDL 1.1.11 plus hprof-parser 1.0, each with the defunct `net.researchgate.release`/`bintray` plugins stripped,
  and a stub jar for `apktool-cli` 2.4.2) and supplying a JRE 8 `rt.jar` via `DOOP_PLATFORMS_LIB`.
- Spring Boot apps need a plain jar of `target/classes` (the repackaged fat jar crashes `dgi`'s heap-object parser) and
  `--keep-spec` roots generated from `datasets/<dataset>/entrypoints.txt`, because `jackee` only knows Servlet/EJB entry points.
- The desktop app (javafx-pos) uses `--main com.rafsan.inventory.MainApp`. DayTrader took ~3 h; Roller a similar order.
- Doop's Soot cannot read Java 17 bytecode (reports 0 classes): the current Spring PetClinic (Boot 4 / Java 17) is N/A, and the
  cached facts here are for the older Java 8 build.

## Caveats

- The facts in the cache were produced from the jars of fyp-benchmarking's runs: CARGO's own bundled jars for acme-air, daytrader,
  jpetstore and plants (built from commits that cannot always be traced; the acme-air jar is a MongoDB variant that does not exist
  in `acmeair/acmeair`'s history), and jars built from the pinned checkouts for the rest. Classes in a partition that are not in
  `dataset.json` appear as `unmatched_ids`; classes Doop never reached appear as `unassigned` in every `*_score.json`
  `coverage` block. Read the coverage block before comparing CARGO's scores with other tools'.
- Doop's graph has call-return, data and heap dependencies but no EXTENDS/IMPLEMENTS edges, so CARGO never sees inheritance.
- The paper reports Coupling/Cohesion and its own ICP/BCP, which are different formulas from the ones in `metrics/`.
