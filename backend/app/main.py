from fastapi import FastAPI

app = FastAPI(
    title="LEVEL_GROUP API",
    version="1.0.0"
)


@app.get("/")
def root():
    return {
        "status": "online",
        "project": "LEVEL_GROUP",
        "version": "1.0.0"
    }
