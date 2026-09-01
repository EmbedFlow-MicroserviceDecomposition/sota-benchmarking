# JForum Dataset & Mono2Micro Benchmark Setup

This directory contains the dataset configuration, ground-truth business context use cases, Docker database setup, and evaluation pipeline for **JForum** (Jakarta EE / Java 11).

---

## 1. Database Setup with Docker Compose

JForum uses a MariaDB/MySQL backend database. We provide a `docker-compose.yml` that boots MariaDB 10.5 and initializes all required schema tables and seed data:

```bash
docker compose -f datasets/jforum/docker-compose.yml up -d mysql
```

Verify that tables are created:
```bash
docker exec jforum-mysql-1 mysql -u root -e "SHOW TABLES IN jforum;"
```

---

## 2. Generate Universal Dataset Representation

Extract methods, AST-resolved call graph edges, and ground-truth business context mapping:

```bash
python3 datasets/jforum/dataset.py
```
This generates `datasets/jforum/dataset.json` containing all classes, methods, call graph edges, and domain use case mappings (`datasets/jforum/usecases.json`).

---

## 3. Build Application and Generate Classpath

Compile JForum (configured for Java 11):

```bash
mvn compile -f datasets/jforum/jakartaEE/pom.xml
mvn dependency:build-classpath -f datasets/jforum/jakartaEE/pom.xml -Dmdep.outputFile=cp.txt
```

---

## 4. Run Mono2Micro End-to-End Pipeline

### Step A: Source Code Analysis
Extract symbol tables and reference graphs:
```bash
sh ./tools/mono2micro/Mono2Micro-CLI/mono2micro analyze -s datasets/jforum/jakartaEE -o tools/mono2micro/outputs/jforum/tables
```

### Step B: Record Dynamic Traces Across Domain Use Cases
Execute the instrumented `net.jforum.UseCaseRunner` with the Minerva agent across all 8 business use cases (`UserAuthentication`, `ForumManagement`, `TopicManagement`, `PostManagement`, `PrivateMessaging`, `Search`, `AdminManagement`, `Installation`):
```bash
python3 tools/mono2micro/record_jforum.py
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
