from fastapi import FastAPI

app = FastAPI(
    title="LEVEL_GROUP API",
    version="1.0.0"
)

@app.get("/")
def home():
    return {
        "message": "LEVEL_GROUP Backend is running"
    }
