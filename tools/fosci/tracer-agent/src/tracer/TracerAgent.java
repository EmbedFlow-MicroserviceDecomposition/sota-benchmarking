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
                    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS | ClassWriter.COMPUTE_FRAMES);
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
