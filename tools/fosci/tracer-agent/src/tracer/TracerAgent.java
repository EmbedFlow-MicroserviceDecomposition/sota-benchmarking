package tracer;

import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.commons.AdviceAdapter;

import java.io.IOException;
import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;

/**
 * javaagent entry point. Args: "targetPackagePrefix,outputCsvPath" where
 * targetPackagePrefix uses '/' separators (e.g. com/rokin/baylorboard).
 * Instruments every non-abstract method of every class under that package to
 * call Tracer.enter()/Tracer.exit() around the method body.
 */
public final class TracerAgent {
    private TracerAgent() {
    }

    public static void premain(String args, Instrumentation inst) throws IOException {
        String[] parts = args.split(",", 2);
        String prefix = parts[0].replace('.', '/');
        String outputPath = parts[1];

        Tracer.init(outputPath);

        inst.addTransformer(new ClassFileTransformer() {
            @Override
            public byte[] transform(ClassLoader loader, String className, Class<?> classBeingRedefined,
                                     ProtectionDomain protectionDomain, byte[] classfileBuffer) {
                if (className == null || !className.startsWith(prefix) || className.contains("$$")) {
                    // "$$" excludes CGLIB/Spring-AOP-generated proxy classes (EnhancerBySpringCGLIB,
                    // FastClassBySpringCGLIB) - synthetic bootstrap noise, not real application logic.
                    return null;
                }
                try {
                    ClassReader reader = new ClassReader(classfileBuffer);
                    ClassWriter writer = new LoaderAwareClassWriter(reader, loader);
                    ClassVisitor visitor = new TracingClassVisitor(writer, className.replace('/', '.'));
                    reader.accept(visitor, ClassReader.EXPAND_FRAMES);
                    return writer.toByteArray();
                } catch (Throwable t) {
                    System.err.println("[TracerAgent] failed to instrument " + className + ": " + t);
                    return null;
                }
            }
        });
    }

    /**
     * COMPUTE_FRAMES needs the common superclass of two types. ASM's default loads both classes through the agent's
     * own class loader, which cannot see an app server's application classes ("Type ... not present"), so such
     * classes were silently left uninstrumented. This reads the hierarchy from the class files of the loader that is
     * defining the class, without loading anything; an unresolvable type still skips the class (never a wrong frame).
     */
    static final class LoaderAwareClassWriter extends ClassWriter {
        private final ClassLoader loader;

        LoaderAwareClassWriter(ClassReader reader, ClassLoader loader) {
            super(reader, ClassWriter.COMPUTE_MAXS | ClassWriter.COMPUTE_FRAMES);
            this.loader = loader;
        }

        @Override
        protected String getCommonSuperClass(String type1, String type2) {
            ClassReader r1 = read(type1);
            ClassReader r2 = read(type2);
            if ((r1.getAccess() & Opcodes.ACC_INTERFACE) != 0 || (r2.getAccess() & Opcodes.ACC_INTERFACE) != 0) {
                return "java/lang/Object";
            }
            java.util.Set<String> ancestors = new java.util.HashSet<>();
            for (String t = type1; t != null; t = read(t).getSuperName()) {
                ancestors.add(t);
            }
            for (String t = type2; t != null; t = read(t).getSuperName()) {
                if (ancestors.contains(t)) {
                    return t;
                }
            }
            return "java/lang/Object";
        }

        private ClassReader read(String type) {
            String resource = type + ".class";
            ClassLoader[] loaders = {loader, ClassLoader.getSystemClassLoader()};
            for (ClassLoader l : loaders) {
                java.io.InputStream in = l == null ? ClassLoader.getSystemResourceAsStream(resource)
                                                   : l.getResourceAsStream(resource);
                if (in != null) {
                    try (java.io.InputStream stream = in) {
                        return new ClassReader(stream);
                    } catch (IOException e) {
                        throw new TypeNotPresentException(type, e);
                    }
                }
            }
            throw new TypeNotPresentException(type, null);
        }
    }

    static final class TracingClassVisitor extends ClassVisitor {
        private final String className;

        TracingClassVisitor(ClassVisitor cv, String className) {
            super(Opcodes.ASM9, cv);
            this.className = className;
        }

        @Override
        public MethodVisitor visitMethod(int access, String name, String descriptor, String signature,
                                          String[] exceptions) {
            MethodVisitor mv = super.visitMethod(access, name, descriptor, signature, exceptions);
            if (mv == null || (access & Opcodes.ACC_ABSTRACT) != 0 || (access & Opcodes.ACC_NATIVE) != 0
                    || "<clinit>".equals(name)) {
                return mv;
            }
            return new TracingMethodVisitor(mv, access, name, descriptor, className);
        }
    }

    static final class TracingMethodVisitor extends AdviceAdapter {
        private final String className;
        private final String methodName;

        TracingMethodVisitor(MethodVisitor mv, int access, String name, String descriptor, String className) {
            super(Opcodes.ASM9, mv, access, name, descriptor);
            this.className = className;
            this.methodName = name;
        }

        @Override
        protected void onMethodEnter() {
            visitLdcInsn(className);
            visitLdcInsn(methodName);
            visitMethodInsn(Opcodes.INVOKESTATIC, "tracer/Tracer", "enter",
                    "(Ljava/lang/String;Ljava/lang/String;)V", false);
        }

        @Override
        protected void onMethodExit(int opcode) {
            visitMethodInsn(Opcodes.INVOKESTATIC, "tracer/Tracer", "exit", "()V", false);
        }
    }
}
