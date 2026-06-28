from pathlib import Path

_NAV_HTML = (Path(__file__).parent / "templates" / "app-nav.html").read_text()


def inject_app_nav(html: str, app_title: str) -> str:
    nav = _NAV_HTML.replace("{{APP_TITLE}}", app_title)
    return html.replace("<body>", f"<body>\n{nav}\n", 1)
