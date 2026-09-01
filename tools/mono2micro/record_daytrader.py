import subprocess
import time
import urllib.request
import urllib.parse
import urllib.error

BASE_URL = "http://localhost:9082/daytrader"

def make_request(path, method="GET", data=None):
    url = f"{BASE_URL}{path}"
    headers = {'Accept': 'text/html,application/xhtml+xml,application/xml'}
    
    encoded_data = None
    if data:
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        
    req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.getcode(), response.read().decode('utf-8', errors='ignore')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='ignore')
    except Exception as e:
        return 0, str(e)

def run_usecase_api(name):
    print(f"--- Executing API calls for usecase: {name} ---")
    if name == "Login":
        status, _ = make_request("/app", method="POST", data={"action": "login", "uid": "uid:0", "passwd": "xxx"})
        print(f"POST /app (login) -> status {status}")
    elif name == "BuyStock":
        status, _ = make_request("/app", method="POST", data={"action": "buy", "symbol": "s:0", "quantity": "100"})
        print(f"POST /app (buy) -> status {status}")
    elif name == "SellStock":
        status, _ = make_request("/app", method="POST", data={"action": "sell", "holdingID": "1"})
        print(f"POST /app (sell) -> status {status}")
    elif name == "GetQuotes":
        status, _ = make_request("/app", method="POST", data={"action": "quotes", "symbols": "s:0,s:1,s:2,s:3,s:4"})
        print(f"POST /app (quotes) -> status {status}")
    elif name == "Portfolio":
        status, _ = make_request("/app?action=portfolio")
        print(f"GET /app?action=portfolio -> status {status}")
    elif name == "Account":
        status, _ = make_request("/app?action=account")
        print(f"GET /app?action=account -> status {status}")
    elif name == "TradeScenario":
        for i in range(5):
            status, _ = make_request("/scenario")
            print(f"[{i+1}/5] GET /scenario -> status {status}")
            time.sleep(0.5)
    elif name == "TradeConfig":
        status, _ = make_request("/config")
        print(f"GET /config -> status {status}")

def main():
    cmd = ["sh", "./mono2micro", "usecase", "-o", "../outputs/daytrader/contexts/usecases.json"]
    proc = subprocess.Popen(
        cmd,
        cwd="tools/mono2micro/Mono2Micro-CLI",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    usecases = [
        "Login",
        "GetQuotes",
        "BuyStock",
        "SellStock",
        "Portfolio",
        "Account",
        "TradeScenario",
        "TradeConfig"
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

        # Run API call
        run_usecase_api(uc)
        time.sleep(1)

        # Stop recording this usecase (send 9)
        proc.stdin.write("9\n")
        proc.stdin.flush()
        time.sleep(1)

    # Exit recording session (send 1)
    print("\nExiting usecase recording...")
    proc.stdin.write("1\n")
    proc.stdin.flush()

    out, _ = proc.communicate(timeout=25)
    print("Mono2Micro Output:\n", out)

if __name__ == "__main__":
    main()
