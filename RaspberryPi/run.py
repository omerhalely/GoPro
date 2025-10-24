from app import create_app
import argparse


parser = argparse.ArgumentParser(description="GoPro Parser")

parser.add_argument(
    "--dev",
    type=lambda x: (str(x) == "true"),
    required=True,
    default="true",
    help="true - dev mode | false - production mode"
)
args = parser.parse_args()

dev_mode = args.dev

app = create_app(dev_mode)

if __name__ == "__main__":
    # debug=True for live reload in dev; turn off on Pi
    app.run(host="0.0.0.0", port=8000, debug=True)
