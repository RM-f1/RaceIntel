from fastapi.testclient import TestClient

from raceintel.api.main import app

client = TestClient(app)