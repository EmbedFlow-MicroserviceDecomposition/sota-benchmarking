package com.feat;

public record Point(int x, int y) {
    public int sum() {
        return switch (x) {
            case 0 -> y;
            default -> x + y;
        };
    }
}
