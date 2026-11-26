package com.fyp.extractor;

import com.github.javaparser.JavaParser;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.ParseResult;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.TypeDeclaration;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.ObjectCreationExpr;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.resolution.declarations.ResolvedMethodLikeDeclaration;
import com.github.javaparser.symbolsolver.JavaSymbolSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.CombinedTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.JavaParserTypeSolver;
import com.github.javaparser.symbolsolver.resolution.typesolvers.ReflectionTypeSolver;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.function.Supplier;
import java.util.stream.Stream;

/**
 * Extracts class edges and method-level call data from a Java source tree.
 * Throws ParseFailureException if any file fails to parse.
 * Edge types: CALL (method + constructor calls, weighted by count),
 * EXTENDS, IMPLEMENTS, FIELD (declared field types incl. generic type args).
 * Only edges whose both endpoints are project classes are kept.
 */
public class Extractor {

    private int unresolvedCalls = 0;
    private int totalCalls = 0;

    public Graph extract(Path repo) {
        List<Path> sourceRoots = findSourceRoots(repo);

        CombinedTypeSolver solver = new CombinedTypeSolver(new ReflectionTypeSolver());
        for (Path root : sourceRoots) {
            solver.add(new JavaParserTypeSolver(root));
        }
        ParserConfiguration config = new ParserConfiguration()
                .setSymbolResolver(new JavaSymbolSolver(solver))
                .setLanguageLevel(ParserConfiguration.LanguageLevel.BLEEDING_EDGE);
        JavaParser parser = new JavaParser(config);

        List<CompilationUnit> units = new ArrayList<>();
        List<String> failures = new ArrayList<>();
        for (Path root : sourceRoots) {
            try (Stream<Path> files = Files.walk(root)) {
                for (Path p : files.filter(f -> f.toString().endsWith(".java")).toList()) {
                    try {
                        ParseResult<CompilationUnit> result = parser.parse(p);
                        if (result.isSuccessful() && result.getResult().isPresent()) {
                            units.add(result.getResult().get());
                        } else {
                            String problem = result.getProblems().isEmpty()
                                    ? "no compilation unit" : result.getProblems().get(0).getMessage();
                            failures.add(p + ": " + problem);
                        }
                    } catch (IOException e) {
                        failures.add(p + ": " + e.getMessage());
                    }
                }
            } catch (IOException e) {
                throw new RuntimeException(e);
            }
        }
        if (!failures.isEmpty()) {
            throw new ParseFailureException(failures);
        }

        Graph graph = new Graph();
        // pass 1: nodes
        for (CompilationUnit cu : units) {
            cu.findAll(TypeDeclaration.class).forEach(td ->
                    td.getFullyQualifiedName().ifPresent(fqn -> graph.addNode((String) fqn)));
        }
        // pass 2: methods, then class edges and call sites
        for (CompilationUnit cu : units) {
            String pkg = cu.getPackageDeclaration().map(p -> p.getNameAsString()).orElse("");
            String file = cu.getStorage().map(st -> repo.toAbsolutePath().normalize()
                    .relativize(st.getPath().toAbsolutePath().normalize()).toString()).orElse("");
            for (TypeDeclaration<?> td : cu.findAll(TypeDeclaration.class)) {
                String self = td.getFullyQualifiedName().map(Object::toString).orElse(null);
                if (self == null) continue;
                for (MethodDeclaration m : td.getMethods()) {
                    graph.addMethod(new Graph.Method(self + "." + m.getNameAsString(),
                            td.getNameAsString(), pkg, m.getNameAsString(),
                            simpleName(m.getType()),
                            m.getParameters().stream().map(pa -> simpleName(pa.getType())).toList(),
                            Graph.newCalls(), file));
                }
                for (ConstructorDeclaration c : td.getConstructors()) {
                    graph.addMethod(new Graph.Method(self + ".<init>", td.getNameAsString(), pkg,
                            "<init>", "void",
                            c.getParameters().stream().map(pa -> simpleName(pa.getType())).toList(),
                            Graph.newCalls(), file));
                }

                td.toClassOrInterfaceDeclaration().ifPresent(cid -> {
                    cid.getExtendedTypes().forEach(t ->
                            resolve(t).ifPresent(fqn -> graph.addEdge(self, fqn, "EXTENDS", 1)));
                    cid.getImplementedTypes().forEach(t ->
                            resolve(t).ifPresent(fqn -> graph.addEdge(self, fqn, "IMPLEMENTS", 1)));
                });

                // element type plus generic type arguments (List<Product> -> Product)
                for (FieldDeclaration fd : td.getFields()) {
                    fd.getElementType().findAll(ClassOrInterfaceType.class).forEach(t ->
                            resolve(t).ifPresent(fqn -> graph.addEdge(self, fqn, "FIELD", 1)));
                }
            }
            cu.findAll(MethodCallExpr.class).forEach(call ->
                    onCall(graph, call, call::resolve, false));
            cu.findAll(ObjectCreationExpr.class).forEach(call ->
                    onCall(graph, call, call::resolve, true));
        }
        return graph;
    }

    /** Records one call site: a CALL edge for the nearest enclosing type, and the callee on the enclosing method. */
    private void onCall(Graph graph, Node call,
                        Supplier<? extends ResolvedMethodLikeDeclaration> resolver, boolean ctor) {
        Optional<TypeDeclaration<?>> owner = enclosingType(call);
        if (owner.isEmpty()) return;
        totalCalls++;
        String self = owner.get().getFullyQualifiedName().map(Object::toString).orElseThrow();
        try {
            ResolvedMethodLikeDeclaration target = resolver.get();
            String callee = target.declaringType().getQualifiedName();
            graph.addEdge(self, callee, "CALL", 1);
            enclosingMemberId(call).ifPresent(id ->
                    graph.addCall(id, callee, callee + "." + (ctor ? "<init>" : target.getName())));
        } catch (RuntimeException e) {
            unresolvedCalls++;
        }
    }

    /** Nearest enclosing type that has a fully qualified name (skips local/anonymous types). */
    private static Optional<TypeDeclaration<?>> enclosingType(Node node) {
        Node cur = node;
        while (true) {
            Optional<TypeDeclaration> t = cur.findAncestor(TypeDeclaration.class);
            if (t.isEmpty()) return Optional.empty();
            if (t.get().getFullyQualifiedName().isPresent()) {
                return Optional.of((TypeDeclaration<?>) t.get());
            }
            cur = t.get();
        }
    }

    /** Id of the method or constructor (declared directly in a type) containing the node. */
    private static Optional<String> enclosingMemberId(Node node) {
        Node cur = node;
        while (cur.getParentNode().isPresent()) {
            cur = cur.getParentNode().get();
            boolean callable = cur instanceof MethodDeclaration || cur instanceof ConstructorDeclaration;
            if (callable && cur.getParentNode().filter(p -> p instanceof TypeDeclaration).isPresent()) {
                TypeDeclaration<?> td = (TypeDeclaration<?>) cur.getParentNode().get();
                String name = cur instanceof MethodDeclaration m ? m.getNameAsString() : "<init>";
                return td.getFullyQualifiedName().map(fqn -> fqn + "." + name);
            }
        }
        return Optional.empty();
    }

    /** Type name without generic arguments ("List" for List<String>). */
    private static String simpleName(com.github.javaparser.ast.type.Type type) {
        return type instanceof ClassOrInterfaceType c ? c.getNameAsString() : type.asString();
    }

    private Optional<String> resolve(ClassOrInterfaceType type) {
        try {
            return Optional.of(type.resolve().asReferenceType().getQualifiedName());
        } catch (RuntimeException e) {
            return Optional.empty();
        }
    }

    public int unresolvedCalls() {
        return unresolvedCalls;
    }

    public int totalCalls() {
        return totalCalls;
    }

    /** Source roots: every directory matching *&#47;src/main/java; else the repo's top-level src/ (Eclipse layout); else the repo root. */
    static List<Path> findSourceRoots(Path repo) {
        try (Stream<Path> dirs = Files.walk(repo)) {
            List<Path> roots = dirs
                    .filter(Files::isDirectory)
                    .filter(p -> p.endsWith(Path.of("src", "main", "java")))
                    .toList();
            if (!roots.isEmpty()) return roots;
            Path src = repo.resolve("src");
            return Files.isDirectory(src) ? List.of(src) : List.of(repo);
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }
}
