from locust import HttpUser, task, between
import json

class DifyUser(HttpUser):
    wait_time = between(1, 3)
    host = "http://127.0.0.1:8000"
    
    @task(3)
    def health_check(self):
        self.client.get("/health")
    
    @task(1)
    def task_architect(self):
        self.client.post("/task", json={
            "agent": "architect",
            "query": "Was ist die aktuelle System-Architektur?",
            "user": "locust-test"
        }, timeout=120)
    
    @task(1)
    def task_planner(self):
        self.client.post("/task", json={
            "agent": "planner",
            "query": "Welche Aufgaben stehen als nächstes an?",
            "user": "locust-test"
        }, timeout=120)
