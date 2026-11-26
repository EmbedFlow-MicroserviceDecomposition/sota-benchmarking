package com.fyp.extractor;

import org.junit.jupiter.api.Test;

import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** Eclipse-style layout (src/com/ecl, no src/main/java) must still resolve cross-class calls. */
class SourceRootTest {

    @Test
    void srcDirIsUsedAsSourceRootWhenThereIsNoMavenLayout() {
        Graph g = new Extractor().extract(Path.of("src/test/resources/eclipse"));
        assertEquals(2, g.weight("com.ecl.A", "com.ecl.B", "CALL"));
    }
}
