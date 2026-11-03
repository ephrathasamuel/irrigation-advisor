"""Flask app: serves the page and the JSON API."""

import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import advisor, weather
from .crops import CROPS, METHODS, SOILS
from .plan import InputError, build_plan, parse_inputs

PLAN_TTL_SECONDS = 60 * 60
MAX_STORED_PLANS = 500
# The page lives in public/ so Vercel can serve it from its CDN; Flask serves the same files locally.
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"


def create_app(fetch_forecast=weather.fetch_forecast, fetch_climate=weather.fetch_climate,
               explain=advisor.explain, ai_available=advisor.ai_available):
    app = Flask(__name__, static_folder=str(PUBLIC_DIR / "static"), static_url_path="/static")
    # Plans are kept briefly so the AI explains exactly the numbers the user saw.
    plans = OrderedDict()
    pool = ThreadPoolExecutor(max_workers=8)

    def remember(plan):
        now = time.time()
        while plans and (len(plans) >= MAX_STORED_PLANS or next(iter(plans.values()))[0] < now - PLAN_TTL_SECONDS):
            plans.popitem(last=False)
        plan_id = uuid.uuid4().hex
        plans[plan_id] = (now, plan)
        return plan_id

    @app.get("/")
    def index():
        return send_from_directory(PUBLIC_DIR, "index.html")

    @app.get("/api/options")
    def options():
        return jsonify(
            crops=[{"id": k, "name": v["name"], "perennial": v["stages"] is None} for k, v in CROPS.items()],
            soils=[{"id": k, "name": v["name"]} for k, v in SOILS.items()],
            methods=[{"id": k, "name": v["name"], "efficiency": v["efficiency"]} for k, v in METHODS.items()],
            languages=[{"id": k, "name": v} for k, v in advisor.LANGUAGES.items()],
            ai_available=ai_available(),
        )

    @app.post("/api/plan")
    def plan():
        try:
            inputs = parse_inputs(request.get_json(silent=True))
        except InputError as exc:
            return jsonify(error=str(exc)), 400

        forecast_job = pool.submit(fetch_forecast, inputs["lat"], inputs["lon"])
        climate_job = pool.submit(fetch_climate, inputs["lat"], inputs["lon"])
        try:
            forecast = forecast_job.result()
        except weather.WeatherError as exc:
            return jsonify(error=str(exc)), 502
        climate, climate_error = None, None
        try:
            climate = climate_job.result()
        except weather.WeatherError as exc:
            climate_error = f"{exc} The plan does not depend on it."

        try:
            result = build_plan(inputs, forecast, climate, climate_error)
        except InputError as exc:
            return jsonify(error=str(exc)), 400
        result["plan_id"] = remember(result)
        result["ai_available"] = ai_available()
        return jsonify(result)

    @app.post("/api/explain")
    def explain_plan():
        body = request.get_json(silent=True) or {}
        if not ai_available():
            return jsonify(error="AI explanations need an Anthropic API key. Add ANTHROPIC_API_KEY to the .env file and restart."), 503
        stored = plans.get(body.get("plan_id", ""))
        if not stored:
            return jsonify(error="This plan has expired. Calculate it again, then ask for the explanation."), 404
        try:
            return jsonify(explain(stored[1], body.get("language", "en")))
        except advisor.AdvisorError as exc:
            return jsonify(error=str(exc)), 502

    return app
