from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from capteurs.store import ensure_indexes
from capteurs.mqtt_client import start_mqtt, stop_mqtt
from capteurs.xsense_cloud import start_xsense_cloud, stop_xsense_cloud
from capteurs.capteurs import router as capteurs_router
from dashboard.dashboard import router as dashboard_router
from home_summary import router as home_router
from supervisor import start_supervisor, stop_supervisor
from nav import render_nav
from vmc.vmc import router as vmc_router

_HOME_TEMPLATE = (Path(__file__).parent / "templates" / "home.html").read_text()
HOME_HTML = _HOME_TEMPLATE.replace("{{NAV}}", render_nav())

app = FastAPI()
app.include_router(vmc_router, prefix="/vmc", tags=["vmc"])
app.include_router(capteurs_router, prefix="/capteurs", tags=["capteurs"])
app.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
app.include_router(home_router, prefix="/home", tags=["home"])


@app.on_event("startup")
async def startup():
    ensure_indexes()
    start_mqtt()
    start_xsense_cloud()
    start_supervisor()


@app.on_event("shutdown")
async def shutdown():
    stop_supervisor()
    stop_xsense_cloud()
    stop_mqtt()


@app.get("/", response_class=HTMLResponse)
def home():
    return HOME_HTML
