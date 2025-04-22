import os
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import requests
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask App
app = Flask(__name__, static_folder="public", template_folder="template")
CORS(app)

# Constantes d'env
API_URL = os.getenv("API_URL", "http://localhost:1234")
APP_SECRET = os.getenv("APP_SECRET", "your-secret-key")
HTML_INDEX = "index.html"

# Retry session
def create_retry_session(retries=3, backoff_factor=0.3):
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(500, 502, 504)
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Vérification disponibilité LM Studio
def check_lm_studio_status():
    endpoints = [
        f"{API_URL}/v1/models",
        f"{API_URL}/models"
    ] if not API_URL.endswith('/') else [
        f"{API_URL}v1/models",
        f"{API_URL}models"
    ]
    session = create_retry_session(retries=1)
    for endpoint in endpoints:
        try:
            logger.info(f"Vérification: {endpoint}")
            response = session.get(endpoint, timeout=5)
            if response.status_code == 200:
                return True
        except Exception as e:
            logger.warning(f"Erreur sur {endpoint} : {e}")
    return False

# Prompt generator
def build_prompt(story_text, format_choice, language="fr"):
    if language == "fr":
        if format_choice == "gherkin":
            return f"""Voici une user story : "{story_text}"
En tant qu'assistant de test, génère des scénarios de test au format Gherkin en français.

Format:
Feature: [Titre de la fonctionnalité]

  Scenario: [Titre 1]
    Given ...
    When ...
    Then ...
"""
        else:
            return f"""Voici une user story : "{story_text}"
Génère des cas de test détaillés avec étapes et résultats attendus en français."""
    else:
        return f"""Here is a user story: "{story_text}"
Generate test cases in {format_choice} format in English."""

# Appel LM Studio
def generate_response(prompt, max_tokens=800):
    if not check_lm_studio_status():
        return "LM Studio inaccessible. Vérifiez la configuration."
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "mistral-7b-instruct-v0.3",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }

    endpoints = [
        f"{API_URL}/v1/chat/completions",
        f"{API_URL}/chat/completions"
    ] if not API_URL.endswith('/') else [
        f"{API_URL}v1/chat/completions",
        f"{API_URL}chat/completions"
    ]

    session = create_retry_session(retries=1)
    for api_endpoint in endpoints:
        try:
            logger.info(f"Appel: {api_endpoint}")
            response = session.post(api_endpoint, json=payload, headers=headers, timeout=90)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"Erreur sur {api_endpoint} : {e}")
    return "Erreur API : aucun endpoint ne fonctionne."

# Front page
@app.route("/")
def home():
    return render_template(HTML_INDEX)

# JIRA GET: pour le dialogue (HTML)
@app.route("/jira-test-generator", methods=["GET"])
def jira_test_generator_view():
    return render_template(HTML_INDEX)

# JIRA POST: génération des cas de test
@app.route("/jira-test-generator", methods=["POST"])
def jira_test_generator_api():
    data = request.json
    story = data.get("story", "")
    format_choice = data.get("format", "gherkin")
    language = data.get("language", "fr")

    if not story:
        return jsonify({"error": "Aucune user story fournie"}), 400

    prompt = build_prompt(story, format_choice, language)
    result = generate_response(prompt)
    return jsonify({"result": result})

# API directe pour appel JS
@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json()
    story = data.get("story", "").strip()
    format_choice = data.get("format", "gherkin")
    language = data.get("language", "fr")

    if not story:
        return jsonify({"error": "Aucune user story fournie"}), 400

    prompt = build_prompt(story, format_choice, language)
    generated = generate_response(prompt)
    return jsonify({"result": generated})

@app.route("/installed", methods=["POST"])
def on_installed():
    data = request.json
    logger.info(f"App installé avec data: {data}")
    return jsonify({"status": "installed"}), 200

@app.route("/uninstalled", methods=["POST"])
def on_uninstalled():
    logger.info("App désinstallée")
    return jsonify({"status": "uninstalled"}), 200


# LM Studio status
@app.route("/api/status", methods=["GET"])
def api_status():
    ok = check_lm_studio_status()
    return jsonify({"status": "LM Studio disponible" if ok else "Non disponible", "api_url": API_URL}), 200 if ok else 503

# Diagnostic complet
@app.route("/api/diagnostic", methods=["GET"])
def api_diagnostic():
    results = {"api_url": API_URL, "tested": []}
    endpoints = [
        "v1/models", "models",
        "v1/chat/completions", "chat/completions"
    ]
    session = create_retry_session()
    for path in endpoints:
        full_url = f"{API_URL.rstrip('/')}/{path}"
        try:
            r = session.get(full_url, timeout=5)
            results["tested"].append({
                "url": full_url,
                "status": r.status_code,
                "working": r.ok
            })
        except Exception as e:
            results["tested"].append({
                "url": full_url,
                "error": str(e),
                "working": False
            })
    return jsonify(results)

# Static files
@app.route("/public/<path:path>")
def serve_public(path):
    return send_from_directory("public", path)

@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)

# Run
if __name__ == "__main__":
    app.run(debug=True, port=5000)
