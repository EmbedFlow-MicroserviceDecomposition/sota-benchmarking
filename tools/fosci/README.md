# FoSCI

Execution-trace based service candidate identification: Jin et al., *Service Candidate Identification from Monolithic Systems
Based on Execution Traces*, TSE 2019 ([wj86/FoSCI](https://github.com/wj86/FoSCI), submodule `FoSCI/`, pinned to `d293133`). The submodule is kept for the authors'
documentation, test scenarios and JMeter test plans; the execution traces in it are **not used** (see Traces). The optimiser is the authors' **fosci-wrap** (v2 release), vendored unmodified in
`fosci-wrap/` (stdlib-only Python; the release is not a git repository).

## Run

```bash
cd tools/fosci
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore [--n-services 10] [--seed 0]
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
```

## Pipeline

1. **Trace**: `datasets/<dataset>/fosci_trace.csv.gz`, the only input. Without it the cell fails with "no execution trace" (not
   N/A), and `benchmark.py run` tries it again once the file exists.
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
the cell is N/A (error-form `output.json`). Daytrader (1 atom: the tracer failed to instrument most classes, and the app's default
Direct-JDBC mode skips its EJB layer) and plants were N/A until their functional suites: they now have 74 and 20 atoms. Runs are unseeded unless `--seed` is given; apache-roller takes ~1-2 h per run.

## Traces

The paper's requirement: execution traces must capture the target's functionality, so they come from **functional test cases run
against an executable instance built from the monolith** (black-box functional testing of the system, not unit tests). Every trace
in this benchmark is meant to be recorded that way against our pinned checkouts. The FoSCI authors' published traces are not used:
they were recorded on other builds of the apps.

| Dataset | Trace today |
| :--- | :--- |
| pharmacy | recorded with `tracer-agent/` in fyp-benchmarking by driving the app with ~20-30 scripted requests: **not yet a functional test suite**, to be re-recorded |
| autocare | functional suite (15 use cases: sign-up, every OAuth2 grant incl. the failing client-credentials one, users, vehicles with every search filter, S3 image upload/delete, comments; `--jdk8`): 61 traces, classes 41/48 (85%; every non-interface class), methods 86% |
| jpetstore | functional suite (`datasets/jpetstore/exercise_usecases.py`, 18 use cases covering the authors' 14 scenarios): 337 traces, classes 17/24 (71%; every non-interface class), methods 64% |
| spring-blog | functional suite (22 use cases, every controller endpoint; `--jdk8`): 2008 traces, classes 37/47 (79%; 92% of non-interfaces: the rest are `Constants` and dead code), methods 74% |
| plants | functional suite (22 use cases: JSF storefront, checkout, registration, admin; `--jdk8`): 4158 traces, classes 30/37 (81%; the rest are never-thrown exceptions, a JPA key class, back-order classes the app never seeds and an unwired validator), methods 61% |
| daytrader | functional suite (26 use cases: both UIs, every config mode, database build, primitives, WebSockets; `--jdk8`; amd64 image, emulated on Apple Silicon): 504 traces, classes 85/115 (74%; the rest are classes the server calls directly that call no other app class, so a call-based trace cannot see them, and the `/ejb3` primitives that fail to load), methods 62% |
| acme-air | functional suite (14 use cases: every REST endpoint, loader, profile, flight search, booking, cancellation; `--jdk8`): 95 traces, classes 40/84 (48%). **Below 70% by construction:** 37 classes cannot appear in a trace of the running app: the `wxs` data service (15; its proprietary objectgrid dependency is not published and the server runs `morphia`), `acmeair-reporter` (12; a command-line JMeter log parser, not in the WAR) and 10 interfaces. Of the 47 reachable classes 40 (85%) are covered; methods 31% |
| bear-board | functional suite (18 use cases: users, events, awards, whitelist, tweet board, STOMP news push over WebSocket): 38 traces, classes 25/34 (74%; 89% of non-interfaces: the rest are `Tweet`, which only the live Twitter API fills, and the `Role`/`Roles` enums, only read as constants), methods 87% |
| spring-petclinic | functional suite (10 use cases: owner search/create/edit with validation, pets of every type incl. duplicate and missing fields, visits, vets as HTML/JSON/XML, the crash page; `--jdk8`): 527 traces, classes 20/24 (83%; every non-interface class), methods 59% |
| jforum, apache-roller | **none yet**: the cell fails with "no execution trace" until one is recorded |
| javafx-pos (desktop) | none yet |
| genapp (COBOL) | none: N/A |

**Recording a trace** (`record_trace.py`): runs the dataset's functional test suite (`datasets/<dataset>/exercise_usecases.py`,
the same suite Mono2Micro records; harness in `datasets/workload.py`) against a fresh `docker compose` instance of the app with
`tracer-agent/` attached, then writes `fosci_trace.csv.gz` and `fosci_trace_coverage.json` into the dataset. It refuses to write the
trace unless every use case passes. Per-use-case trace row spans go to `outputs/<dataset>/trace/usecase_spans.json`.

```bash
uv run record_trace.py --dataset-path ../../datasets/jpetstore [--package org.mybatis.jpetstore]
uv run record_trace.py --dataset-path ../../datasets/spring-blog --jdk8   # JDK 8 apps need the JDK 8 agent
uv run record_trace.py --dataset-path ../../datasets/plants --jdk8
uv run record_trace.py --dataset-path ../../datasets/daytrader --jdk8
uv run record_trace.py --dataset-path ../../datasets/acme-air --jdk8
uv run record_trace.py --dataset-path ../../datasets/bear-board
uv run record_trace.py --dataset-path ../../datasets/spring-petclinic --jdk8
uv run record_trace.py --dataset-path ../../datasets/autocare --jdk8
uv run trace_coverage.py --dataset-path ../../datasets/jpetstore   # coverage of an existing trace; exits 1 below 70%
```

The dataset's compose file must start the app with `${JAVA_AGENT}` (the compose default keeps Mono2Micro's agent) and mount
`tools/fosci/tracer-agent` at `/fosci` and `${TRACE_DIR}` at `/trace`. The tracer (`tracer-agent.jar` for JDK 11+,
`tracer-agent-jdk8.jar` for JDK 8) is an ASM `-javaagent` that logs every call between two classes of the package prefix in
FoSCI's raw column format. **Coverage target: 70% of `dataset.json` classes.** A class counts as covered when it calls or is called by
another app class in the trace, which is all FoSCI sees. Interfaces such as MyBatis mappers run through generated proxies and
can never appear, so the report also gives coverage of non-interface classes. Methods the tracer cannot see (getters and setters
called by JSP/EL or reflection, and handlers that only forward to a view) keep method coverage below class coverage.

The tracer computes stack-map frames with a `ClassWriter` that reads class hierarchies from the defining class loader's class files.
ASM's default loads them through the agent's loader, which cannot see an app server's classes: before this fix such classes
(Plants' EJBs, for example) were silently left uninstrumented. `failed to instrument` lines in the app's log name any class still
skipped. Rebuild both jars after changing `src/` (the jars already contain ASM; only `tracer/*.class` is replaced):

```bash
cd tools/fosci && mkdir -p outputs/tracer-build && docker run --rm -v "$PWD/tracer-agent":/agent \
  -v "$PWD/outputs/tracer-build":/build -w /build eclipse-temurin:11-jdk sh -c 'for v in 11 8; do
    jar=/agent/tracer-agent.jar; [ $v = 8 ] && jar=/agent/tracer-agent-jdk8.jar
    mkdir -p c$v && javac --release $v -cp $jar -d c$v /agent/src/tracer/*.java && (cd c$v && jar uf $jar tracer/*.class); done'
```
