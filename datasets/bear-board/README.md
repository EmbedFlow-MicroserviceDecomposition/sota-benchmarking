# Bear Board Dataset

This directory contains the monolithic dataset and adapter for **Bear Board**, an open-source Java application.

The original monolithic application is tracked as a Git submodule in the `bear-board/` directory.

## Structure
- `bear-board/`: Git submodule containing the monolithic source code.
- `dataset.py`: Python script utilizing `javalang` to traverse the Java source code, extract all class/method signatures, and locate the required `bear-board_kdm.xmi`. It outputs this structured data to `dataset.json`.

## Eclipse MoDisco Generation (FAILED)

**Warning:** Eclipse MoDisco fails to successfully generate the KDM Code Model (`_kdm.xmi`) for this specific codebase. 

As with other specific datasets in this repository (like JForum and JavaFX-POS), MoDisco's internal AST generation and ATL KDM transformation processes break down on this repository (usually resulting in an ATL `VMException` or `DanglingHREFException`).

Because MoDisco cannot process the source code into a valid KDM model, decomposition tools that strictly rely on MoDisco's KDM schema (like MAGNET) cannot natively evaluate this dataset. Any evaluation requires an alternative Call Graph generator to artificially synthesize the required `bear-board_kdm.xmi`.

## Usage

You can still run the adapter script to extract the method dataset via `javalang`:

```bash
uv run dataset.py
```

This will parse the raw Java files and output `dataset.json`, which can be used by tools that do not require KDM input.

### Mono2Micro Integration

The application is a standard Spring Boot application backed by MongoDB and Apache Kafka.

**1. Build the Application:**
Compile the Spring Boot fat JAR:
```bash
cd bear-board
mvn clean package -DskipTests
cd ..
```
The compiled JAR will be located at `bear-board/target/Maharjan_Rokin-0.0.1-SNAPSHOT.jar`.

**2. Start Services and Instrumented Application via Docker Compose:**
A `docker-compose.yml` is provided which automatically spins up MongoDB, Zookeeper, Kafka, AND the compiled Bear Board Spring Boot JAR with the Mono2Micro Minerva agent attached.

First, ensure the output logs directory exists:
```bash
mkdir -p ../../tools/mono2micro/outputs/bear-board/logs
```

Start the containers in the background:
```bash
docker-compose up -d
```

Then, capture the real-time application traces to the log file expected by Mono2Micro:
```bash
docker logs -f bear-board-bear-board-1 > ../../tools/mono2micro/outputs/bear-board/logs/console.log 2>&1
```

**3. Record Use Cases:**
In a separate terminal, launch the `usecase` orchestrator:
```bash
../../tools/mono2micro/Mono2Micro-CLI/mono2micro usecase -o ../../tools/mono2micro/outputs/bear-board/contexts/usecases.json
```

In a third terminal, run the interactive API tester script:
```bash
python api_tester.py
```
*(The script will pause before every HTTP request, allowing you to type the use case name into the Mono2Micro orchestrator and start recording before firing the actual API calls).*
