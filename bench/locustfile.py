import itertools
import os
import random

from locust import HttpUser, LoadTestShape, constant, events, task

REPEAT_RATE = float(os.environ.get("REPEAT_RATE", "0.0"))
BASE_USERS = 25
BURST_USERS = 200

HOT = [
    "this movie was absolutely fantastic",
    "best dinner i've had all year",
    "i love this song so much",
    "what a waste of two hours",
    "the service was terrible and rude",
    "an underwhelming sequel to a great original",
    "delightful from start to finish",
    "would not recommend to anyone",
    "surprisingly enjoyable performance",
    "boring, predictable, and far too long",
]

counter = itertools.count()
hits = 0
misses = 0


def tag():
    return os.getpid()


@events.test_stop.add_listener
def report_hit_rate(**kwargs):
    total = hits + misses
    if total:
        print(f"HITRATE pid={tag()} hits={hits} total={total} rate={hits / total:.1%}")


class SentimentUser(HttpUser):
    wait_time = constant(0)

    @task
    def predict(self):
        if random.random() < REPEAT_RATE:
            text = random.choice(HOT)
        else:
            text = f"{random.choice(HOT)} take {tag()}-{next(counter)}"
        r = self.client.post("/predict", json={"text": text})
        if r.status_code == 200:
            global hits, misses
            if r.json()["cached"]:
                hits += 1
            else:
                misses += 1


# locust uses any shape it finds and then ignores --users and --run-time
if os.environ.get("SHAPE") == "burst":

    class Burst(LoadTestShape):
        def tick(self):
            t = self.get_run_time()
            if t < 60:
                return BASE_USERS, 100
            if t < 90:
                return int(BASE_USERS + (BURST_USERS - BASE_USERS) * (t - 60) / 30), 100
            if t < 300:
                return BURST_USERS, 100
            return None
