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
import spoon.reflect.declaration.CtPackage;
import spoon.reflect.declaration.CtMethod;
import spoon.reflect.code.CtInvocation;
import spoon.reflect.reference.CtTypeReference;
import spoon.reflect.visitor.filter.TypeFilter;
import java.util.stream.Collectors;

/** Source-only Spoon rendering for MonoEmbed; no application build or external project is needed. */
public final class SourceExtractor {
    public static void main(String[] args) {
        if (args.length == 0) {
            throw new IllegalArgumentException("Expected at least one production Java source directory");
        }
        List<Map<String, Object>> types = new ArrayList<>();
        Launcher launcher = new Launcher();
        // Keep Spoon's default renderer and environment, as in the original pipeline.
        launcher.getEnvironment().setOutputType(OutputType.NO_OUTPUT);
        for (String arg : args) {
            launcher.addInputResource(Path.of(arg).toAbsolutePath().normalize().toString());
        }
        launcher.addProcessor(new AbstractProcessor<CtType>() {
            @Override
            public void process(CtType type) {
                // Skip implicit types/type parameters; Python checks the complete named type universe.
                if (type instanceof CtTypeParameter || !type.getPosition().isValidPosition()) return;
                // Match named source declarations: anonymous and method-local types
                // have no independent nodes in the common benchmark class universe.
                if (!(type.getParent() instanceof CtPackage) && !(type.getParent() instanceof CtType)) return;
                Map<String, Object> record = new LinkedHashMap<>();
                record.put("fullName", type.getQualifiedName());
                record.put("content", type.toString());
                record.put("filePath", type.getPosition().getFile().getAbsolutePath());
                // Supply method metadata for source syntax beyond javalang's Java 8 grammar.
                // Rendering occurs first, preserving the original embedding input text.
                String owner = type.getQualifiedName().replace('$', '.');
                String pkg = type.getPackage().getQualifiedName();
                List<Map<String, Object>> methods = new ArrayList<>();
                for (CtMethod<?> method : ((CtType<?>) type).getMethods()) {
                    if (!method.getPosition().isValidPosition()) continue;
                    Map<String, Object> entry = new LinkedHashMap<>();
                    entry.put("id", owner + "." + method.getSimpleName());
                    entry.put("class", pkg.isEmpty() ? owner : owner.substring(pkg.length() + 1));
                    entry.put("package", pkg);
                    entry.put("method_name", method.getSimpleName());
                    entry.put("return_type", method.getType().getSimpleName());
                    entry.put("parameters", method.getParameters().stream()
                            .map(parameter -> parameter.getType().getSimpleName()).collect(Collectors.toList()));
                    List<String> calls = new ArrayList<>();
                    for (CtInvocation<?> invocation : method.getElements(new TypeFilter<>(CtInvocation.class))) {
                        CtType<?> enclosing = invocation.getParent(CtType.class);
                        if (enclosing != type) continue;
                        CtTypeReference<?> target = invocation.getExecutable().getDeclaringType();
                        String callee = target == null ? owner : target.getQualifiedName().replace('$', '.');
                        calls.add(callee + "." + invocation.getExecutable().getSimpleName());
                    }
                    entry.put("calls", calls);
                    entry.put("file_path", type.getPosition().getFile().getAbsolutePath());
                    methods.add(entry);
                }
                record.put("methods", methods);
                types.add(record);
            }
        });
        launcher.run();
        types.sort(Comparator.comparing(record -> record.get("fullName").toString()));
        System.out.println(new Gson().toJson(types));
    }
}
