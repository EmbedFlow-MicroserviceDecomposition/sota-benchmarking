# JavaFX Point of Sales Dataset

This directory contains the monolithic dataset and adapter for **JavaFX Point of Sales**, an open-source Java Desktop POS application.

The original monolithic application is tracked as a Git submodule in the `JavaFX-Point-of-Sales/` directory.

## Structure
- `JavaFX-Point-of-Sales/`: Git submodule containing the monolithic source code.
- `dataset.py`: Python script utilizing `javalang` to traverse the Java source code, extract all class/method signatures, and locate the required `javafx-pos_kdm.xmi`. It outputs this structured data to `dataset.json`.

## Eclipse MoDisco Generation (FAILED)

**Warning:** Similar to JForum, Eclipse MoDisco fails to successfully generate the KDM Code Model (`_kdm.xmi`) for this specific codebase. 

While the exact nature of the failure may vary (often related to unresolved JavaFX UI bindings or the ATL transformer `VMException`), it has been documented that MoDisco's internal model generation and KDM transformation processes break down on this repository.

Because MoDisco cannot process the source code into a valid KDM model, decomposition tools that strictly rely on MoDisco's KDM schema (like MAGNET) cannot natively evaluate this dataset. Any evaluation requires an alternative Call Graph generator to artificially synthesize the required `javafx-pos_kdm.xmi`.

## Setup & Runtime Execution

### 1. Database (Docker Compose)
Start the MariaDB database service pre-seeded with `inventory.sql`:
```bash
docker compose -f datasets/javafx-pos/docker-compose.yml up -d mysql
```

### 2. Compilation & Build
The application runs on Java 11. The build uses Maven with `maven-shade-plugin` to produce a runnable JAR (`target/inventory-1.0.jar`), including OpenJFX 11 and JAXB API (`javax.xml.bind:jaxb-api:2.3.1`, `org.glassfish.jaxb:jaxb-runtime:2.3.1`).
```bash
mvn package -f datasets/javafx-pos/JavaFX-Point-of-Sales/pom.xml -DskipTests
```

### 3. Use Case Transactions
Domain transactions are executed via `com.rafsan.inventory.UseCaseRunner` across the supported use cases: `Login`, `ManageCategory`, `ManageProduct`, `ManageSupplier`, `ManageEmployee`, `CreateSale`, `CreatePurchase`, and `GenerateInvoice`.

## Dataset Adapter

Generate the universal `dataset.json` mapping methods, static call graph edges, and ground-truth use cases:
```bash
uv run dataset.py
```
