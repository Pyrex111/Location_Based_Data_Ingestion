"""Location-based file uploads: the ECE569A Smart Drive course prototype."""

import math
import os

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

load_dotenv()
app = Flask(__name__)
app.config.update(
    S3_BUCKET=os.getenv("S3_BUCKET", "").strip(),
    AWS_REGION=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-2")),
    OPENCAGE_API_KEY=os.getenv("OPENCAGE_API_KEY", "").strip(),
)


def get_city_name(latitude, longitude):
    """Reverse geocode valid coordinates, returning None for manual fallback."""
    if not app.config["OPENCAGE_API_KEY"]:
        return None
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    try:
        response = requests.get(
            "https://api.opencagedata.com/geocode/v1/json",
            params={
                "q": f"{latitude},{longitude}",
                "key": app.config["OPENCAGE_API_KEY"],
                "limit": 1,
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    results = data.get("results", [])
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None
    components = results[0].get("components", {})
    if not isinstance(components, dict):
        return None
    city = components.get("city") or components.get("town") or components.get("village")
    return city.strip() if isinstance(city, str) and city.strip() else None


def get_s3_client():
    """Use Boto3's credential chain; no credentials are stored in this project."""
    return boto3.client("s3", region_name=app.config["AWS_REGION"])


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/upload")
def upload_files():
    files = request.files.getlist("files[]")
    if not files or any(not file.filename for file in files):
        return jsonify(message="Please select at least one file."), 400
    filenames = [secure_filename(file.filename) for file in files]
    if any(not filename for filename in filenames):
        return jsonify(message="One or more filenames are invalid."), 400

    manual_city = request.form.get("manual_city", "").strip()
    city = manual_city or get_city_name(
        request.form.get("latitude"), request.form.get("longitude")
    )
    if not city:
        return jsonify(
            message="Could not determine city. Please provide manually.",
            manual_city_required=True,
        ), 400
    city_prefix = secure_filename(city)
    if not city_prefix or len(city_prefix) > 128:
        return jsonify(message="Please enter a valid city name."), 400
    if not app.config["S3_BUCKET"]:
        return jsonify(message="Configure S3_BUCKET before uploading files."), 503

    uploaded = []
    try:
        s3 = get_s3_client()
        for file, filename in zip(files, filenames):
            key = f"{city_prefix}/{filename}"
            s3.upload_fileobj(file, app.config["S3_BUCKET"], key)
            uploaded.append(key)
    except NoCredentialsError:
        return jsonify(message="Error: Unable to access S3 credentials.", uploaded=uploaded), 500
    except (BotoCoreError, ClientError):
        return jsonify(message="Error: Unable to upload files to S3.", uploaded=uploaded), 502

    return jsonify(
        message=f"Files successfully uploaded to S3 in folder '{city_prefix}'.",
        uploaded=uploaded,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
