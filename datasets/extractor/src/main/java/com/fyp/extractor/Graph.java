package com.fyp.extractor;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * Structural graph of a Java source tree: class nodes (FQNs), typed weighted
 * class edges, and the methods (including constructors as {@code <init>}) with
 * the project methods they call.
 */
public class Graph {

    public record Edge(String src, String dst, String type) {}

    /** One method or constructor; {@code calls} holds callee ids ("pkg.Class.method"), one per call site. */
    public record Method(String id, String className, String pkg, String name,
                         String returnType, List<String> parameters,
                         List<String> calls, String filePath) {}

    private final Set<String> nodes = new TreeSet<>();
    private final Map<Edge, Integer> weights = new LinkedHashMap<>();
    private final Map<String, Method> methods = new LinkedHashMap<>();

    public void addNode(String fqn) {
        nodes.add(fqn);
    }

    /** Adds weight to an edge; ignores self-edges and endpoints not in the node set. */
    public void addEdge(String src, String dst, String type, int weight) {
        if (src.equals(dst) || !nodes.contains(src) || !nodes.contains(dst)) {
            return;
        }
        weights.merge(new Edge(src, dst, type), weight, Integer::sum);
    }

    /** Registers a method; overloads share an id, so the first signature wins. */
    public void addMethod(Method method) {
        methods.putIfAbsent(method.id(), method);
    }

    /** Records a call site on a registered method; callee must be a project class. */
    public void addCall(String methodId, String calleeClass, String calleeId) {
        Method m = methods.get(methodId);
        if (m != null && nodes.contains(calleeClass)) {
            m.calls().add(calleeId);
        }
    }

    public Set<String> nodes() {
        return nodes;
    }

    public Set<Edge> edges() {
        return weights.keySet();
    }

    public Map<String, Method> methods() {
        return methods;
    }

    /** Weight of an edge, or 0 if absent. */
    public int weight(String src, String dst, String type) {
        return weights.getOrDefault(new Edge(src, dst, type), 0);
    }

    static List<String> newCalls() {
        return new ArrayList<>();
    }
}
