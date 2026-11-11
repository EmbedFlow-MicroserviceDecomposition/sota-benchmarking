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
the cell is N/A (error-form `output.json`): daytrader (1 atom: the tracer failed to instrument most classes) and plants (1 atom: the
app's own DB seeding bug leaves an empty catalogue). Runs are unseeded unless `--seed` is given; apache-roller takes ~1-2 h per run.

## Traces

The paper's requirement: execution traces must capture the target's functionality, so they come from **functional test cases run
against an executable instance built from the monolith** (black-box functional testing of the system, not unit tests). Every trace
in this benchmark is meant to be recorded that way against our pinned checkouts. The FoSCI authors' published traces are not used:
they were recorded on other builds of the apps.

| Dataset | Trace today |
| :--- | :--- |
| acme-air, bear-board, pharmacy, spring-petclinic, daytrader, plants | recorded with `tracer-agent/` in fyp-benchmarking by driving the app with ~20-30 scripted requests: **not yet a functional test suite**, to be re-recorded |
| autocare | the reduced form of such a scripted trace (reduction is idempotent) |
| jpetstore | **canonical**: `datasets/jpetstore/functional_tests.py` (the authors' 14-scenario list, 17 checks) run once against the pinned build (recipe below): 121 requests, 17 classes, 9 atoms |
| spring-blog | **canonical**: `datasets/spring-blog/functional_tests.py` (the 12 of the authors' 28 scenarios the pinned build implements, 27 checks) run once against the pinned build on a fresh database (recipe below): 350 requests, 38 classes, 24 atoms |
| jforum, apache-roller | **none yet**: the cell fails with "no execution trace" until one is recorded |
| javafx-pos (desktop) | none yet |
| genapp (COBOL) | none: N/A |

**Generating a trace** (`tracer-agent/`): an ASM `-javaagent` that logs every method enter/exit of a package prefix in FoSCI's raw
column format. Use `tracer-agent-jdk8.jar` for JDK 8 apps and `tracer-agent.jar` for JDK 11+:

```bash
java -javaagent:tracer-agent/tracer-agent.jar=<package.prefix>,<out.csv> -jar app.jar
# drive the app with real traffic, then: gzip -9 -n out.csv > datasets/<dataset>/fosci_trace.csv.gz
```

**Canonical recipe, worked example (JPetStore)**, no Docker needed:

1. Build the pinned source from a copy of `datasets/jpetstore/jpetstore-6`. The pin's enforcer wants JDK 21+ to build although it compiles
   for Java 17, and its licence plugin needs repository metadata a copy lacks:
   `JAVA_HOME=<jdk21> mvn -q clean package -DskipTests -Dlicense.skip=true`.
2. Unpack Tomcat 9.0.120 (the version the pin's own cargo profile uses), put `target/jpetstore.war` in `webapps/`, and start it on JDK 17
   with `CATALINA_OPTS="-javaagent:tools/fosci/tracer-agent/tracer-agent.jar=org.mybatis.jpetstore,<out>.csv"`.
3. Run `uv run datasets/jpetstore/functional_tests.py` once against it (it exits 1 if any check fails). It scrapes the live Stripes forms,
   so it works where the authors' recorded JMeter plan (`FoSCI/testplan/jpetstore-testplan.jmx`) cannot replay: that plan carries
   session-bound `_sourcePage`/`__fp` tokens. The pinned app rejects `editAccount` unless `username` and `password` are sent (both are
   `@Validate(required = true)` yet the edit form shows neither as an input), so the suite sends them; the authors' plan did not.
4. Stop Tomcat (the CSV is flushed per row), then `gzip -9 -n <out>.csv` into `datasets/<dataset>/fosci_trace.csv.gz`.

**Spring Blog**, no Docker either: build from a copy of the pinned source with JDK 8 (`JAVA_HOME=<jdk8> ./gradlew --no-daemon build -x test`;
Gradle 3.5.1), start a MySQL on 127.0.0.1:3306 with an empty `spring_blog_prod` database (Redis is configured but never contacted), and run
`java -javaagent:tools/fosci/tracer-agent/tracer-agent-jdk8.jar=com.raysmond.blog,<out>.csv -jar build/libs/SpringBlog-0.0.1-SNAPSHOT.jar --spring.profiles.active=prod`
(the prod profile's defaults already point at 127.0.0.1, user `root`, empty password). Then run `uv run datasets/spring-blog/functional_tests.py`
once on that fresh database. A MySQL 8.4+/9 server rejects Spring Boot 1.5's bundled Connector/J 5.1.45 (`caching_sha2_password`): use
MariaDB or MySQL 5.7/8.0, or put Connector/J 8.0.33 first on the classpath. Two defects of the pinned app are built into the suite: `/tags/<name>`
has no view template (HTTP 500 after the controller already ran), and a post cannot be deleted while another post shares one of its tags.
