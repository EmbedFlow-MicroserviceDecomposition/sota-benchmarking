package tracer;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Runtime call logger for the FoSCI trace-collection javaagent. Writes rows
 * matching tools/fosci/traces/*.txt's raw column format (Jin et al. TSE 2019
 * section 2.3): traceID,order,structtype,method1,method2,m1_para,m2_para,
 * class1,class2,m1_return,m2_return. The param/return columns are never read
 * by our downstream pipeline (fosci_preprocess.py / genTestCaseFv.py only use
 * traceID + method1/2 + class1/2), so they're left blank here.
 *
 * One trace per top-level (root) call on a thread - matches the paper's
 * "ThreadID: a globally unique ID to identify a thread trace" for a
 * synchronous request-per-thread web app.
 */
public final class Tracer {
    private static PrintWriter out;
    private static final AtomicInteger traceIdGen = new AtomicInteger(0);
    private static final ThreadLocal<Deque<String[]>> STACK = ThreadLocal.withInitial(ArrayDeque::new);
    private static final ThreadLocal<Integer> TRACE_ID = new ThreadLocal<>();
    private static final ThreadLocal<Integer> ORDER = new ThreadLocal<>();

    private Tracer() {
    }

    public static synchronized void init(String path) throws IOException {
        out = new PrintWriter(new BufferedWriter(new FileWriter(path)));
        out.println("traceID,order,structtype,method1,method2,m1_para,m2_para,class1,class2,m1_return,m2_return");
        out.flush();
    }

    public static void enter(String className, String methodName) {
        Deque<String[]> stack = STACK.get();
        String qualified = className + "." + methodName;
        if (!stack.isEmpty()) {
            String[] caller = stack.peek();
            int ord = ORDER.get();
            ORDER.set(ord + 1);
            writeRow(TRACE_ID.get(), ord, caller[1], qualified, caller[0], className);
        } else {
            TRACE_ID.set(traceIdGen.getAndIncrement());
            ORDER.set(0);
        }
        stack.push(new String[]{className, qualified});
    }

    public static void exit() {
        Deque<String[]> stack = STACK.get();
        if (!stack.isEmpty()) {
            stack.pop();
        }
        if (stack.isEmpty()) {
            TRACE_ID.remove();
            ORDER.remove();
        }
    }

    private static synchronized void writeRow(int traceId, int order, String method1, String method2,
                                               String class1, String class2) {
        if (out == null) {
            return;
        }
        out.printf("%d,%d,null,%s,%s,,,%s,%s,,%n", traceId, order, method1, method2, class1, class2);
        out.flush();
    }
}
