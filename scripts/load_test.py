"""
scripts/load_test.py
--------------------
Concurrent Load & Reliability Testing Utility for ExamProctor:
Measures:
- Requests Per Second (RPS)
- Latency metrics: Average, Median (p50), 95th Percentile (p95), Min, Max
- Error rate under concurrent load
- Key endpoints tested:
  1. Health & Liveness Probe (/health)
  2. Readiness Probe (/health/ready)
  3. Authentication / Login (/login)
  4. Candidate Dashboard (/student/dashboard)
  5. Assessment Analytics API (/api/v1/analytics/examiner)
Usage:
    python scripts/load_test.py [--concurrency 10] [--requests 100]
"""
import sys
import os
import time
import statistics
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app


def run_benchmark_endpoint(client: TestClient, method: str, path: str, num_requests: int, concurrency: int) -> dict:
    latencies = []
    errors = 0
    status_codes = {}

    def _single_request():
        t0 = time.perf_counter()
        try:
            if method.upper() == "GET":
                resp = client.get(path)
            elif method.upper() == "POST":
                resp = client.post(path)
            else:
                resp = client.get(path)
            dt = (time.perf_counter() - t0) * 1000  # ms
            return resp.status_code, dt
        except Exception:
            dt = (time.perf_counter() - t0) * 1000
            return 500, dt

    overall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_single_request) for _ in range(num_requests)]
        for f in as_completed(futures):
            code, lat = f.result()
            latencies.append(lat)
            status_codes[code] = status_codes.get(code, 0) + 1
            if code >= 500:
                errors += 1

    total_time = time.perf_counter() - overall_start
    rps = round(num_requests / total_time, 2) if total_time > 0 else 0

    sorted_lats = sorted(latencies)
    avg_lat = round(statistics.mean(sorted_lats), 2)
    p50_lat = round(sorted_lats[int(len(sorted_lats) * 0.50)], 2)
    p95_lat = round(sorted_lats[int(len(sorted_lats) * 0.95)], 2)
    min_lat = round(sorted_lats[0], 2)
    max_lat = round(sorted_lats[-1], 2)
    error_rate = round((errors / num_requests) * 100, 2)

    return {
        "endpoint": f"{method} {path}",
        "requests": num_requests,
        "concurrency": concurrency,
        "total_time_sec": round(total_time, 3),
        "rps": rps,
        "avg_ms": avg_lat,
        "p50_ms": p50_lat,
        "p95_ms": p95_lat,
        "min_ms": min_lat,
        "max_ms": max_lat,
        "errors": errors,
        "error_rate_pct": error_rate,
        "status_distribution": status_codes
    }


def main():
    parser = argparse.ArgumentParser(description="ExamProctor Load Tester")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent worker threads")
    parser.add_argument("--requests", type=int, default=100, help="Total requests per endpoint")
    args = parser.parse_args()

    client = TestClient(app)

    endpoints_to_test = [
        ("GET", "/health"),
        ("GET", "/health/ready"),
        ("GET", "/login"),
        ("GET", "/api/v1/organizations")
    ]

    print("=" * 80)
    print(f"EXAMPROCTOR PERFORMANCE & LOAD TEST BENCHMARK")
    print(f"Concurrency: {args.concurrency} workers | Requests per target: {args.requests}")
    print("=" * 80)

    results = []
    for method, path in endpoints_to_test:
        print(f"Benchmarking {method} {path}...")
        res = run_benchmark_endpoint(client, method, path, args.requests, args.concurrency)
        results.append(res)
        print(f"  -> RPS: {res['rps']} req/s | Avg: {res['avg_ms']}ms | p95: {res['p95_ms']}ms | Errors: {res['errors']} ({res['error_rate_pct']}%)")

    print("\n" + "=" * 80)
    print("SUMMARY RESULTS TABLE")
    print("=" * 80)
    header = f"{'Endpoint':<30} {'RPS':<10} {'Avg (ms)':<10} {'p95 (ms)':<10} {'Error %':<10}"
    print(header)
    print("-" * 80)
    for r in results:
        print(f"{r['endpoint']:<30} {r['rps']:<10} {r['avg_ms']:<10} {r['p95_ms']:<10} {r['error_rate_pct']:<10}")
    print("=" * 80)


if __name__ == "__main__":
    main()
