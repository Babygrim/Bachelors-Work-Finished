from pathlib import Path

import webview

from core.application import WebApp


if __name__ == "__main__":
    app = WebApp()
    window = webview.create_window(
        "Picture Editor",
        url=(Path(__file__).parent / "ui" / "web" / "index.html").as_uri(),
        js_api=app,
        width=1440,
        height=900,
        min_size=(980, 640),
    )
    app._bind_window(window)
    webview.start()