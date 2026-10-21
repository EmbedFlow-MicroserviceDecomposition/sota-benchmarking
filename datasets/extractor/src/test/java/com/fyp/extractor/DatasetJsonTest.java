package com.fyp.extractor;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Fixture src/test/resources/features (package com.feat): interface Repo and
 * Greeter, enum Color, record Point (switch expression), Outer with inner class
 * Outer.Inner, and Orders. Orders.place and Outer.Inner.ping each call
 * Repo.save once.
 */
class DatasetJsonTest {

    static Graph graph;

    @BeforeAll
    static void extractFeatures() {
        graph = new Extractor().extract(Path.of("src/test/resources/features"));
    }

    @Test
    void methodsCoverInterfaceEnumRecordAndNestedTypes() {
        var ids = graph.methods().keySet();
        assertTrue(ids.contains("com.feat.Repo.save"), ids.toString());
        assertTrue(ids.contains("com.feat.Greeter.greet"), ids.toString());
        assertTrue(ids.contains("com.feat.Color.label"), ids.toString());
        assertTrue(ids.contains("com.feat.Point.sum"), ids.toString());
        assertTrue(ids.contains("com.feat.Outer.Inner.ping"), ids.toString());
    }

    @Test
    void constructorsAreRecordedAsInit() {
        assertTrue(graph.methods().containsKey("com.feat.Orders.<init>"));
    }

    @Test
    void methodRecordCarriesSignatureAndResolvedCalls() {
        Graph.Method m = graph.methods().get("com.feat.Orders.place");
        assertEquals("Orders", m.className());
        assertEquals("com.feat", m.pkg());
        assertEquals("place", m.name());
        assertEquals("String", m.returnType());
        assertEquals(java.util.List.of("int", "String"), m.parameters());
        assertEquals(java.util.List.of("com.feat.Repo.save"), m.calls());
    }

    @Test
    void callsAreAttributedToTheNearestEnclosingType() {
        assertEquals(1, graph.weight("com.feat.Outer.Inner", "com.feat.Repo", "CALL"));
        assertEquals(0, graph.weight("com.feat.Outer", "com.feat.Repo", "CALL"));
    }

    @Test
    void parseFailureNamesTheFile() {
        var ex = assertThrows(ParseFailureException.class,
                () -> new Extractor().extract(Path.of("src/test/resources/broken")));
        assertTrue(ex.getMessage().contains("Broken.java"), ex.getMessage());
    }

    @Test
    void writesDatasetJsonWithTheSotaSchema() throws Exception {
        Path out = Files.createTempFile("dataset", ".json");
        DatasetWriter.write(graph, out, "Feat", "src", "feat/target/feat.war", "feat_kdm.xmi");
        JsonObject root = new Gson().fromJson(Files.readString(out), JsonObject.class);
        assertEquals("Feat", root.get("dataset").getAsString());
        assertEquals("src", root.get("source_path").getAsString());
        assertEquals("feat/target/feat.war", root.get("build_path").getAsString());
        assertEquals("feat_kdm.xmi", root.get("xmi_path").getAsString());
        JsonObject m = root.getAsJsonObject("methods").getAsJsonObject("com.feat.Orders.place");
        for (String key : new String[]{"id", "class", "package", "method_name",
                "return_type", "parameters", "calls", "file_path"}) {
            assertTrue(m.has(key), key);
        }
        JsonObject edge = root.getAsJsonArray("edges").get(0).getAsJsonObject();
        for (String key : new String[]{"src", "dst", "type", "weight"}) {
            assertTrue(edge.has(key), key);
        }
    }

    @Test
    void cliExitsOneOnParseFailureAndZeroOtherwise() throws Exception {
        Path out = Files.createTempFile("dataset", ".json");
        String[] common = {"--out", out.toString(), "--dataset", "T", "--build-path", "b", "--xmi-path", "x"};
        assertEquals(1, Main.run(concat(new String[]{"--source", "src/test/resources/broken"}, common)));
        assertEquals(0, Main.run(concat(new String[]{"--source", "src/test/resources/features"}, common)));
    }

    private static String[] concat(String[] a, String[] b) {
        String[] r = java.util.Arrays.copyOf(a, a.length + b.length);
        System.arraycopy(b, 0, r, a.length, b.length);
        return r;
    }
}
