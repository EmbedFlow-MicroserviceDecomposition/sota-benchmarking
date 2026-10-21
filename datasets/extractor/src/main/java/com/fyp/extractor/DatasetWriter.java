package com.fyp.extractor;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/** Serialises a Graph into the sota-benchmarking dataset.json schema. */
public final class DatasetWriter {

    private DatasetWriter() {}

    public static void write(Graph graph, Path out, String dataset, String sourcePath,
                             String buildPath, String xmiPath) throws IOException {
        JsonObject root = new JsonObject();
        root.addProperty("dataset", dataset);
        root.addProperty("source_path", sourcePath);
        root.addProperty("build_path", buildPath);
        root.addProperty("xmi_path", xmiPath);

        JsonObject methods = new JsonObject();
        for (Graph.Method m : graph.methods().values()) {
            JsonObject o = new JsonObject();
            o.addProperty("id", m.id());
            o.addProperty("class", m.className());
            o.addProperty("package", m.pkg());
            o.addProperty("method_name", m.name());
            o.addProperty("return_type", m.returnType());
            o.add("parameters", strings(m.parameters()));
            o.add("calls", strings(m.calls()));
            o.addProperty("file_path", m.filePath());
            methods.add(m.id(), o);
        }
        root.add("methods", methods);

        JsonArray edges = new JsonArray();
        for (Graph.Edge e : graph.edges()) {
            JsonObject o = new JsonObject();
            o.addProperty("src", e.src());
            o.addProperty("dst", e.dst());
            o.addProperty("type", e.type());
            o.addProperty("weight", (double) graph.weight(e.src(), e.dst(), e.type()));
            edges.add(o);
        }
        root.add("edges", edges);

        Path parent = out.toAbsolutePath().getParent();
        if (parent != null) Files.createDirectories(parent);
        Files.writeString(out, new GsonBuilder().setPrettyPrinting().create().toJson(root));
    }

    private static JsonArray strings(Iterable<String> values) {
        JsonArray a = new JsonArray();
        values.forEach(a::add);
        return a;
    }
}
