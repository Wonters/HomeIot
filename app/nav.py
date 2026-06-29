from pathlib import Path

_NAV_HTML = (Path(__file__).parent / "templates" / "app-nav.html").read_text()

_ACTIVE_CLASS = " active"

_SECTION_KEYS = (
    "ACTIVE_DASHBOARDS",
    "ACTIVE_DASHBOARD",
    "ACTIVE_VMC",
    "ACTIVE_CAPTEURS",
    "ACTIVE_CAPTEURS_ZIGBEE",
    "ACTIVE_CAPTEURS_LORA",
    "ACTIVE_INFRA",
)


def render_nav(active: str = "", page_title: str = "") -> str:
    values = {key: "" for key in _SECTION_KEYS}
    if active == "dashboard":
        values["ACTIVE_DASHBOARDS"] = _ACTIVE_CLASS
        values["ACTIVE_DASHBOARD"] = "active"
    elif active == "vmc":
        values["ACTIVE_VMC"] = _ACTIVE_CLASS
    elif active == "capteurs-zigbee":
        values["ACTIVE_CAPTEURS"] = _ACTIVE_CLASS
        values["ACTIVE_CAPTEURS_ZIGBEE"] = "active"
    elif active == "capteurs-lora":
        values["ACTIVE_CAPTEURS"] = _ACTIVE_CLASS
        values["ACTIVE_CAPTEURS_LORA"] = "active"
    elif active == "capteurs":
        values["ACTIVE_CAPTEURS"] = _ACTIVE_CLASS

    nav = _NAV_HTML.replace("{{PAGE_TITLE}}", page_title)
    for key, value in values.items():
        nav = nav.replace("{{" + key + "}}", value)
    return nav


def inject_app_nav(html: str, app_title: str, active: str = "") -> str:
    nav = render_nav(active=active, page_title=app_title)
    return html.replace("<body>", f"<body>\n{nav}\n", 1)
