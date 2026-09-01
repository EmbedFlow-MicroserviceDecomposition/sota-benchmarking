import urllib.request
import urllib.error
import json
import time

BASE_URL = "http://localhost:9082/daytrader"

def make_request(path, method="GET", data=None, headers=None):
    url = f"{BASE_URL}{path}"
    req_headers = {'Accept': 'text/html,application/xhtml+xml,application/xml'}
    if headers:
        req_headers.update(headers)
    
    encoded_data = data.encode('utf-8') if isinstance(data, str) else data
    req = urllib.request.Request(url, data=encoded_data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.getcode(), response.read().decode('utf-8', errors='ignore')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', errors='ignore')
    except Exception as e:
        return 0, str(e)

def test_trade_scenario():
    print("Executing TradeScenarioServlet benchmark sequence...")
    status, body = make_request("/TradeScenarioServlet")
    print(f"TradeScenarioServlet -> status {status}")

def test_ping():
    print("Executing PingServlet...")
    status, body = make_request("/ping")
    print(f"PingServlet -> status {status}")

def test_config():
    print("Executing TradeConfigServlet...")
    status, body = make_request("/config")
    print(f"TradeConfigServlet -> status {status}")

def main():
    print("=======================================================")
    print("      DayTrader API Tester for Mono2Micro Tracing")
    print("=======================================================")
    
    test_ping()
    test_config()
    test_trade_scenario()
    
    print("\nDayTrader API testing sequence completed.")

if __name__ == "__main__":
    main()
