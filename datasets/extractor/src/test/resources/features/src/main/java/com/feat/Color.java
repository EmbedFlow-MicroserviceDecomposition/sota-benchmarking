package com.feat;

public enum Color {
    RED, GREEN;

    public String label() {
        return name().toLowerCase();
    }
}
