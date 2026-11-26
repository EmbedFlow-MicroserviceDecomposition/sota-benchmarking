package com.feat;

public class Outer {
    private final Repo repo;

    public Outer(Repo repo) {
        this.repo = repo;
    }

    public class Inner {
        public String ping(String s) {
            return repo.save(s);
        }
    }
}
