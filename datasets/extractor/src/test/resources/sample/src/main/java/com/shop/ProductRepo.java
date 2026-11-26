package com.shop;

public class ProductRepo implements Repo {
    @Override
    public Product find(int id) {
        return new Product();
    }
}
