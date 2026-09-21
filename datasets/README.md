# Benchmark Datasets

This directory contains the monolithic target applications evaluated in the benchmark.

## Dataset Structure

Each dataset directory follows a standardized, modular structure:

| File / Component | Purpose |
| :--- | :--- |
| `dataset.py` | AST extraction script that parses source code into the canonical `dataset.json`. |
| `dataset.json` | Universal representation of methods, classes, and static dependency edges. |
| `usecases.json` | Mapping of application classes to business use case labels. |
| `exercise_usecases.py` | Workload runner that executes the business use cases against the running application. |
| `docker-compose.yml` / `yaml` | Containerized runtime environment (where applicable). |
| `<submodule>/` | Upstream application source repository (git submodule). |

---

## Submodule Setup & Customizations

Per project guidelines, submodules are kept at their clean upstream commit references. The runtime drivers and custom test runners required for dynamic analysis are documented below:

### 1. JavaFX POS (`javafx-pos`)
- **Type**: Desktop JavaFX application.
- **Customization**: Requires `UseCaseRunner.java` in `JavaFX-Point-of-Sales/src/main/java/com/rafsan/inventory/UseCaseRunner.java` to invoke use cases sequentially via CLI.
- **Build**:
  ```bash
  cd datasets/javafx-pos/JavaFX-Point-of-Sales
  mvn clean package -DskipTests
  ```

### 2. JForum (`jforum`)
- **Type**: Classic JavaEE Forum web application.
- **Customization**: Requires `UseCaseRunner.java` in `jakartaEE/src/main/java/net/jforum/UseCaseRunner.java` and a generated classpath file `cp.txt`.
- **Build & Classpath**:
  ```bash
  cd datasets/jforum/jakartaEE
  mvn compile
  mvn dependency:build-classpath -Dmdep.outputFile=cp.txt
  ```

### 3. Plants By WebSphere (`plants`)
- **Type**: WebSphere Liberty enterprise application.
- **Customization**: Configured with Open Liberty and DB2/derby drivers in `src/main/liberty/config/server.xml`.
- **Run**:
  ```bash
  docker compose -f datasets/plants/docker-compose.yml up -d
  ```

### 4. Containerized Web Applications
The following datasets run inside dedicated Docker Compose environments with database backends and pre-instrumented JVM configurations:
- **Acme Air**: `datasets/acme-air/docker-compose.yaml` (Liberty + MongoDB)
- **Apache Roller**: `datasets/apache-roller/docker-compose.yml` (Tomcat + PostgreSQL)
- **Bear Board**: `datasets/bear-board/docker-compose.yml` (Spring Boot + MySQL)
- **DayTrader**: `datasets/daytrader/docker-compose.yml` (Open Liberty + Derby)
- **JPetStore**: `datasets/jpetstore/docker-compose.yml` (Tomcat + HSQLDB)
- **Pharmacy**: `datasets/pharmacy/docker-compose.yml` (Spring Boot + PostgreSQL)
- **Spring Blog**: `datasets/spring-blog/docker-compose.yml` (Spring Boot + H2)
- **Spring PetClinic**: `datasets/spring-petclinic/docker-compose.yml` (Spring Boot + MySQL)

---

## Exercising Use Cases Independently

Every dataset provides a self-contained `exercise_usecases.py` script that can be executed independently of any specific analysis tool:

```bash
# Run all use cases sequentially
python3 datasets/acme-air/exercise_usecases.py

# Run a specific use case
python3 datasets/acme-air/exercise_usecases.py --usecase BrowseFlights

# List all available use cases for the dataset
python3 datasets/acme-air/exercise_usecases.py --list
```
