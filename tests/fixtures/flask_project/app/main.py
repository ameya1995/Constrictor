from flask import Flask

from app.views import bp

app = Flask(__name__)
app.register_blueprint(bp)


@app.route("/health")
def health():
    return {"status": "ok"}
