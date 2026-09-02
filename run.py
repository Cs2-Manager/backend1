from app import create_app, models  # noqa: F401
from app.extensions import db

app = create_app()


def init_db():
    db.create_all()
    print("Database tables initialized.")


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=5000, debug=app.config["DEBUG"])
