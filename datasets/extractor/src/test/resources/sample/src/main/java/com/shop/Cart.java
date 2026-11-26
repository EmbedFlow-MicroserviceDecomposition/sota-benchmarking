package com.shop;

import java.util.ArrayList;
import java.util.List;

public class Cart {
    private List<Product> items = new ArrayList<>();

    public void addTwice(ProductRepo repo) {
        items.add(repo.find(1));
        items.add(repo.find(2));
    }
}
