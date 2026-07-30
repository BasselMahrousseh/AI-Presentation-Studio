from fastapi import FastAPI

from routers import (
    admin,
    assets,
    decks,
    jobs,
    projects,
    templates,
)

app = FastAPI(
    title="Presentation Studio API",
    version="1.0.0"
)

app.include_router(projects.router)
app.include_router(decks.router)
app.include_router(jobs.router)
app.include_router(templates.router)
app.include_router(assets.router)
app.include_router(admin.router)


@app.get("/")
async def root():
    return {"status": "Presentation Studio API is running"}