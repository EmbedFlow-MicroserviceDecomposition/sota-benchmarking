package com.fyp.extractor;

import java.util.List;

/** Thrown when one or more source files cannot be parsed; never silently skipped. */
public class ParseFailureException extends RuntimeException {

    public ParseFailureException(List<String> failures) {
        super("cannot parse " + failures.size() + " file(s):\n  " + String.join("\n  ", failures));
    }
}
