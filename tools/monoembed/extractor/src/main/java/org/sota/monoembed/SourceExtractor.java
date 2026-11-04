package org.sota.monoembed;

import com.google.gson.Gson;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import spoon.Launcher;
import spoon.OutputType;
import spoon.processing.AbstractProcessor;
import spoon.reflect.declaration.CtType;
import spoon.reflect.declaration.CtTypeParameter;

/** Source-only Spoon rendering for MonoEmbed; no application build or external project is needed. */
public final class SourceExtractor {
    public static void main(String[] args) {
        if (args.length != 1) {
            throw new IllegalArgumentException("Expected one production Java source directory");
        }
        Path source = Path.of(args[0]).toAbsolutePath().normalize();
        List<Map<String, String>> types = new ArrayList<>();
        Launcher launcher = new Launcher();
        // Keep Spoon's default renderer and environment, as in the original pipeline.
        launcher.getEnvironment().setOutputType(OutputType.NO_OUTPUT);
        launcher.addInputResource(source.toString());
        launcher.addProcessor(new AbstractProcessor<CtType>() {
            @Override
            public void process(CtType type) {
                // Skip implicit types/type parameters; Python checks the complete named type universe.
                if (type instanceof CtTypeParameter || !type.getPosition().isValidPosition()) return;
                Map<String, String> record = new LinkedHashMap<>();
                record.put("fullName", type.getQualifiedName());
                record.put("content", type.toString());
                record.put("filePath", type.getPosition().getFile().getAbsolutePath());
                types.add(record);
            }
        });
        launcher.run();
        types.sort(Comparator.comparing(record -> record.get("fullName")));
        System.out.println(new Gson().toJson(types));
    }
}
