import subprocess
import time
import os

def run_usecase_app(name, tables_dir, log_file, root_dir, cp_string):
    print(f"--- Executing Java application for usecase: {name} ---")
    cmd = [
        "java",
        f"-javaagent:tools/mono2micro/Mono2Micro-CLI/instrumenter/minerva-agent-1.0.jar={tables_dir}",
        "-cp", cp_string,
        "net.jforum.UseCaseRunner",
        name
    ]
    with open(log_file, "a", encoding="utf-8") as f:
        res = subprocess.run(cmd, cwd=root_dir, stdout=f, stderr=subprocess.STDOUT)
    print(f"Java execution for {name} -> exit code {res.returncode}")

def main():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    output_dir = os.path.join(root_dir, "tools/mono2micro/outputs/jforum")
    tables_dir = os.path.join(output_dir, "tables")
    logs_dir = os.path.join(output_dir, "logs")
    contexts_dir = os.path.join(output_dir, "contexts")
    log_file = os.path.join(logs_dir, "console.log")

    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(contexts_dir, exist_ok=True)

    # Read cp.txt
    cp_file = os.path.join(root_dir, "datasets/jforum/jakartaEE/cp.txt")
    with open(cp_file, "r") as f:
        maven_cp = f.read().strip()
    
    classes_dir = os.path.join(root_dir, "datasets/jforum/jakartaEE/target/classes")
    cp_string = f"{classes_dir}:{maven_cp}"

    # Clean previous log file if exists
    if os.path.exists(log_file):
        os.remove(log_file)

    cmd = ["sh", "./mono2micro", "usecase", "-o", os.path.join(contexts_dir, "usecases.json")]
    proc = subprocess.Popen(
        cmd,
        cwd=os.path.join(root_dir, "tools/mono2micro/Mono2Micro-CLI"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    usecases = [
        "UserAuthentication",
        "ForumManagement",
        "TopicManagement",
        "PostManagement",
        "PrivateMessaging",
        "Search",
        "AdminManagement",
        "Installation"
    ]

    time.sleep(2)

    for uc in usecases:
        print(f"\n==========================================")
        print(f"Recording Usecase: {uc}")
        print(f"==========================================")
        # Send label name
        proc.stdin.write(f"{uc}\n")
        proc.stdin.flush()
        time.sleep(1)

        # Run application execution
        run_usecase_app(uc, tables_dir, log_file, root_dir, cp_string)
        time.sleep(1)

        # Stop recording this usecase (send 9)
        proc.stdin.write("9\n")
        proc.stdin.flush()
        time.sleep(1)

    # Exit recording session (send 1)
    print("\nExiting usecase recording...")
    proc.stdin.write("1\n")
    proc.stdin.flush()
    proc.wait()
    print("Usecase recording finished successfully.")

if __name__ == "__main__":
    main()
