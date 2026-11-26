package com.feat;

public class Orders {
    private final Repo repo;

    public Orders(Repo repo) {
        this.repo = repo;
    }

    public String place(int qty, String sku) {
        return repo.save(sku + qty);
    }
}
