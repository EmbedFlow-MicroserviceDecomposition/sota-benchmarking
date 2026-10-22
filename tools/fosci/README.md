# FoSCI

Execution-trace based service candidate identification: Jin et al., *Service Candidate Identification from Monolithic Systems
Based on Execution Traces*, TSE 2019 ([wj86/FoSCI](https://github.com/wj86/FoSCI), submodule `FoSCI/`, pinned to `d293133`, holds the
authors' traces as git-lfs files). The optimiser is the authors' **fosci-wrap** (v2 release), vendored unmodified in
`fosci-wrap/` (stdlib-only Python; the release is not a git repository).

## Run

```bash
cd tools/fosci
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore [--n-services 10] [--seed 0]
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
```

## Pipeline

1. **Trace**: `datasets/<dataset>/fosci_trace.csv.gz` if present, else the authors' trace (`jpetstore`, `spring-blog`, `jforum`,
   `apache-roller`). The authors' files are git-lfs: `cd tools/fosci/FoSCI && git lfs pull --include=traces/<file>` (jforum 129 MB,
   roller 489 MB; the submodule is checked out with pointer files).
2. `fosci_preprocess.py`: trace reduction (Algorithm 1) -> `workflow_reduced.csv`; `calldep.csv` (directed class call counts) and
   `concerndep.csv` (Jaccard of camelCase name terms), which the release does not ship a script for.
3. fosci-wrap's own `genTestCaseFv.py` -> `groupclassbytrace.py` -> `function_logic_identify.py` (diff=3): Functional Atoms.
4. `run_nsga.py`: NSGA-II + the paper's knee-point selection (fosci-wrap's `__main__` dumps the whole Pareto front).

Output: `output.json` (class FQNs of the traced classes), `atoms.csv`, `run_info.json` (trace/atom counts, N, seed), `fosci.log`.
Classes never executed by the traffic are not in the partition; `coverage` in the score files reports how many dataset classes
were assigned.

## Service count N

Per-subject N from the paper (midpoint of Section 4.6's ranges): spring-blog 8, jforum 9, apache-roller 16; autocare 8 (N=10 stalled
against its 12 atoms); otherwise the stock 10. N is capped at `atoms - 2`, because N close to the atom count never converges
(a bear-board run hung for 4+ CPU hours at N=10 on 5 atoms): bear-board 3, acme-air 5, spring-petclinic 7. Fewer than 4 atoms means
the cell is N/A (error-form `output.json`): daytrader (1 atom: the tracer failed to instrument most classes) and plants (1 atom: the
app's own DB seeding bug leaves an empty catalogue). Runs are unseeded unless `--seed` is given; apache-roller takes ~1-2 h per run.

## Traces

| Dataset | Trace |
| :--- | :--- |
| jpetstore, spring-blog, jforum, apache-roller | the FoSCI authors' |
| acme-air, bear-board, pharmacy, spring-petclinic, daytrader, plants | self-generated with `tracer-agent/` (see below), `fosci_trace.csv.gz` |
| autocare | the reduced trace saved by fyp-benchmarking (reduction is idempotent) |
| genapp (COBOL), javafx-pos (desktop) | none: N/A |

The authors' traces were recorded on their own app versions; classes that do not exist in our pinned checkout are simply
`unmatched_ids` in the score files (jforum: the authors' app vs `jforum/jakartaEE`).

**Generating a trace** (`tracer-agent/`): an ASM `-javaagent` that logs every method enter/exit of a package prefix in FoSCI's raw
column format. Use `tracer-agent-jdk8.jar` for JDK 8 apps and `tracer-agent.jar` for JDK 11+:

```bash
java -javaagent:tracer-agent/tracer-agent.jar=<package.prefix>,<out.csv> -jar app.jar
# drive the app with real traffic, then: gzip -9 -n out.csv > datasets/<dataset>/fosci_trace.csv.gz
```
