import argparse
import subprocess
import time

JSONPATH = '{.spec.replicas}{" "}{.status.readyReplicas}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.out, "w", buffering=1) as f:
        f.write("timestamp,desired,ready\n")
        while True:
            out = subprocess.run(
                ["kubectl", "get", "deploy", "serve", "-o", f"jsonpath={JSONPATH}"],
                capture_output=True,
                text=True,
            ).stdout.split()
            if out:
                # readyReplicas is absent, not zero, while no pod is ready
                ready = out[1] if len(out) > 1 else "0"
                f.write(f"{time.time():.3f},{out[0]},{ready}\n")
            time.sleep(2)


if __name__ == "__main__":
    main()
