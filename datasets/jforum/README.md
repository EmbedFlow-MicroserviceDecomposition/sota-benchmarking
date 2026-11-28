# JForum Dataset & Mono2Micro Benchmark Setup

This directory contains the dataset configuration, ground-truth business context use cases, Docker database setup, and evaluation pipeline for **JForum** (Jakarta EE / Java 11).

---

## 1. Run the App and Its Functional Suite

JForum 2.9 is a Jakarta EE 10 web application (Java 11, Tomcat 10.1). Build the WAR, then start Tomcat and an **empty**
MariaDB: the suite runs JForum's web installer itself, which creates the schema and the `Admin` user (password `admin`).

```bash
cd jakartaEE
docker run --rm -v "$PWD":/src -v sota-m2:/root/.m2 -w /src maven:3.9-eclipse-temurin-11 mvn -q -B package -DskipTests
cd .. && JAVA_AGENT= docker compose up -d     # no agent; http://localhost:8080/jforum
python3 exercise_usecases.py --wait           # 23 use cases, exits 1 if any fails
```

The suite follows the FoSCI authors' 37 JMeter scenarios (`tools/fosci/FoSCI/testscenario/jforum-ts.txt`) and adds the admin panel,
registration, attachments, karma, banners, polls, a moderated forum and every mail notification (no SMTP server listens, so the
sends fail inside the app). The app is protected by OWASP CSRFGuard, so the suite reads each form back from the page.
`uv run ../../tools/fosci/record_trace.py --dataset-path .` records `fosci_trace.csv.gz` from the same suite.

Known app behaviour the suite works around: deleting a post needs the moderation-log fields (`log_type`, `log_description`) that the
page's JavaScript adds; an admin "delete" of a user only locks the account.

## 2. Generate Universal Dataset Representation

Extract methods, AST-resolved call graph edges, and ground-truth business context mapping:

```bash
python3 datasets/jforum/dataset.py
```
This generates `datasets/jforum/dataset.json` containing all classes, methods, call graph edges, and domain use case mappings (`datasets/jforum/usecases.json`).

---

## 3. Generate the Classpath

```bash
mvn dependency:build-classpath -f datasets/jforum/jakartaEE/pom.xml -Dmdep.outputFile=cp.txt
```

## 4. Run Mono2Micro End-to-End Pipeline

### Step A: Source Code Analysis
Extract symbol tables and reference graphs:
```bash
sh ./tools/mono2micro/Mono2Micro-CLI/mono2micro analyze -s datasets/jforum/jakartaEE -o tools/mono2micro/outputs/jforum/tables
```

### Step B: Record Dynamic Traces
Mono2Micro records the functional suite use case by use case against the running app (agent attached through `JAVA_AGENT`):
```bash
python3 tools/mono2micro/record.py --dataset-path datasets/jforum
```

### Step C: Generate Microservice Partition Recommendations
Run the AI clustering recommender on dynamic traces:
```bash
sh ./tools/mono2micro/Mono2Micro-CLI/mono2micro recommend -d tools/mono2micro/outputs/jforum
```

### Step D: Standardize Output
Parse partition graph to the standard benchmark format:
```bash
python3 -c "from tools.mono2micro.tool import parse_mono2micro_output; parse_mono2micro_output('tools/mono2micro/outputs/jforum/mono2micro/mono2micro-output/oriole/final_graph.json', 'datasets/jforum/dataset.json', 'tools/mono2micro/outputs/jforum/output.json')"
```

---

## 5. Evaluate Benchmark Metrics

Compute all 7 benchmark metrics (`CHM`, `CHD`, `SM`, `ICP`, `IFN`, `NED`, `BCP`):

```bash
python3 metrics/compute_all.py --dataset-path datasets/jforum --output-path tools/mono2micro/outputs/jforum
```
