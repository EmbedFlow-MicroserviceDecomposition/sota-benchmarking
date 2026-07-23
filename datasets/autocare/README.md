# AutoCare Nepal Dataset

This directory contains the monolithic dataset and adapter for **AutoCare Nepal**, an open-source Java application.

The original monolithic application is tracked as a Git submodule in the `autocare-nepal/` directory.

## Structure
- `autocare-nepal/`: Git submodule containing the monolithic source code.
- `dataset.py`: Python script utilizing `javalang` to traverse the Java source code, extract all class/method signatures, and locate the required `autocare_kdm.xmi`. It outputs this structured data to `dataset.json`.

## Eclipse MoDisco Generation (FAILED)

**Warning:** Eclipse MoDisco fails to successfully generate the KDM Code Model (`_kdm.xmi`) for this specific codebase. 

As with other specific datasets in this repository, MoDisco's internal AST generation and ATL KDM transformation processes break down on this repository.

Because MoDisco cannot process the source code into a valid KDM model, decomposition tools that strictly rely on MoDisco's KDM schema (like MAGNET) cannot natively evaluate this dataset. Any evaluation requires an alternative Call Graph generator to artificially synthesize the required `autocare_kdm.xmi`.

## Usage

You can still run the adapter script to extract the method dataset via `javalang`:

```bash
uv run dataset.py
```

This will parse the raw Java files and output `dataset.json`, which can be used by tools that do not require KDM input.

### Mono2Micro Integration

The application is a standard Spring Boot application that builds into a fat JAR. However, a few manual modifications are required to compile it successfully. Do not commit these changes to the submodule.

**1. Fix the Gradle Wrapper:**
The original repository is missing the `gradle-wrapper.jar`. You can either use a globally installed Gradle (Java 8 + Gradle 5.4.1 recommended) or download the missing wrapper jar directly:
```bash
wget -O autocare-nepal/gradle/wrapper/gradle-wrapper.jar https://raw.githubusercontent.com/gradle/gradle/v5.4.1/gradle/wrapper/gradle-wrapper.jar
```

**2. Fix Compilation Errors:**
There is a bug in `src/main/java/com/policynepal/autocare/vehicle/service/VehicleService.java` where a testing library (`org.assertj.core.util.Files`) was accidentally imported into the main source code, causing compilation to fail. 
You must patch `VehicleService.java`:
1. Remove `import org.assertj.core.util.Files;`
2. Change `Files.delete(imageFile);` to `imageFile.delete();`

**3. Build the Application:**
Once patched, compile the Spring Boot fat JAR:
```bash
cd autocare-nepal
./gradlew build
```
The compiled JAR will be located at `build/libs/autocare-0.0.1-SNAPSHOT.jar`.

**4. Start MongoDB and the Instrumented Application:**
A `docker-compose.yml` is provided which automatically spins up the required MongoDB instance AND the compiled Autocare Spring Boot JAR with the Mono2Micro Minerva agent already attached.

First, ensure the output logs directory exists:
```bash
mkdir -p ../../tools/mono2micro/outputs/autocare/logs
```

Start the containers in the background:
```bash
docker-compose up -d
```

Then, capture the real-time application traces to the log file expected by Mono2Micro:
```bash
docker logs -f autocare_autocare_1 > ../../tools/mono2micro/outputs/autocare/logs/console.log 2>&1
```

**5. Record Use Cases:**
Because the Autocare API is locked down via Spring Security OAuth2, manual testing is cumbersome. An interactive Python script (`api_tester.py`) is provided to automate the authentication flow and sequence of API calls.

In a separate terminal, launch the `usecase` orchestrator:
```bash
../../tools/mono2micro/Mono2Micro-CLI/mono2micro usecase -o ../../tools/mono2micro/outputs/autocare/contexts/usecases.json
```

In a third terminal, run the interactive API tester:
```bash
python api_tester.py
```
*(The script will pause before every HTTP request, allowing you to manually type the use case name into the Mono2Micro orchestrator and start recording before it fires the actual traffic).*
