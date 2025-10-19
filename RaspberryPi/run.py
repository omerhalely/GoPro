from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug=True for live reload in dev; turn off on Pi
    app.run(host="0.0.0.0", port=8000, debug=True)
