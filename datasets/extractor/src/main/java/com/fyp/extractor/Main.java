package com.fyp.extractor;

import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/**
 * CLI: extractor --source DIR --out FILE --dataset NAME --build-path P --xmi-path P [--source-path P]
 * Exit 0 on success, 1 if any source file fails to parse, 2 on bad usage.
 */
public class Main {

    public static void main(String[] args) {
        System.exit(run(args));
    }

    static int run(String[] args) {
        Map<String, String> opts = new HashMap<>();
        for (int i = 0; i + 1 < args.length; i += 2) {
            opts.put(args[i], args[i + 1]);
        }
        for (String required : new String[]{"--source", "--out", "--dataset", "--build-path", "--xmi-path"}) {
            if (!opts.containsKey(required)) {
                System.err.println("Usage: extractor --source DIR --out FILE --dataset NAME "
                        + "--build-path P --xmi-path P [--source-path P]; missing " + required);
                return 2;
            }
        }
        Extractor extractor = new Extractor();
        try {
            Graph graph = extractor.extract(Path.of(opts.get("--source")));
            DatasetWriter.write(graph, Path.of(opts.get("--out")), opts.get("--dataset"),
                    opts.getOrDefault("--source-path", opts.get("--source")),
                    opts.get("--build-path"), opts.get("--xmi-path"));
            System.out.printf("classes=%d methods=%d edges=%d calls_resolved=%d/%d%n",
                    graph.nodes().size(), graph.methods().size(), graph.edges().size(),
                    extractor.totalCalls() - extractor.unresolvedCalls(), extractor.totalCalls());
            return 0;
        } catch (ParseFailureException e) {
            System.err.println("ERROR: " + e.getMessage());
            return 1;
        } catch (java.io.IOException e) {
            System.err.println("ERROR: " + e.getMessage());
            return 2;
        }
    }
}
