import os
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import requests
import json
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="public", template_folder="template")
CORS(app)

# Constantes
HTML_INDEX = "index.html"
CONTENT_TYPE_JSON = "application/json"

# Configuration des variables d'environnement
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")
API_URL = os.getenv("LM_STUDIO_API", "https://among-england-huge-dee.trycloudflare.com/v1/chat/completions")  # Modifiable par variable d'env
APP_SECRET = os.getenv("APP_SECRET", "your-secret-key")

# Session HTTP avec retry
def create_retry_session(retries=3, backoff_factor=0.3):
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(500, 502, 504),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Vérification de l’état de LM Studio
def check_lm_studio_status():
    try:
        # Extraire la partie base de l'URL
        base_url = "/".join(API_URL.split("/")[:-2]) if "/v1/" in API_URL else API_URL
        models_url = f"{base_url}/v1/models"
        logger.info(f"Vérification LM Studio à {models_url}")
        response = requests.get(models_url, timeout=10)
        logger.info(f"Réponse: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Erreur lors de la vérification LM Studio : {e}")
        return False

# Construction du prompt
def build_prompt(story_text, format_choice, language="fr"):
    if language == "fr":
        if format_choice == "gherkin":
            return f"""Voici une user story : "{story_text}"
En tant qu'assistant de test, génère des scénarios de test au format Gherkin (Given/When/Then) en français.

Format attendu:
Feature: [Titre de la fonctionnalité]

  Scenario: [Titre du scénario 1]
    Given [condition préalable]
    When [action utilisateur]
    Then [résultat attendu]

  Scenario: [Titre du scénario 2]
    ...
"""
        else:
            return f"""Voici une user story : "{story_text}"
Génère des cas de test détaillés en français avec les étapes et résultats attendus.

Format attendu:
# Cas de test 1 : [Titre du cas de test]
## Action
[Description détaillée]

## Résultat attendu
[Description détaillée]

# Cas de test 2 : ...
"""
    else:
        if format_choice == "gherkin":
            return f"""Here is a user story: "{story_text}"
Generate test scenarios in Gherkin format (Given/When/Then) in English.

Expected format:
Feature: [Feature title]

  Scenario: [Scenario 1 title]
    Given [precondition]
    When [user action]
    Then [expected result]

  Scenario: [Scenario 2 title]
    ...
"""
        else:
            return f"""Here is a user story: "{story_text}"
Generate detailed test cases in English with steps and expected results.

Expected format:
# Test Case 1: [Title]
## Action
[Action description]

## Expected Result
[Expected outcome]

# Test Case 2: ...
"""

# Envoi du prompt à LM Studio
def generate_response(prompt, max_tokens=800):
    if not check_lm_studio_status():
        logger.error("LM Studio n'est pas accessible")
        return "Erreur de connexion : LM Studio n'est pas accessible."

    headers = {"Content-Type": "application/json"}
    payload = {
        "model": "mistral-7b-instruct-v0.3",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }

    try:
        session = create_retry_session(retries=1)
        response = session.post(API_URL, json=payload, headers=headers, timeout=90)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        return "Timeout : le modèle met trop de temps à répondre."
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur requête LM Studio : {e}")
        return f"Erreur : {str(e)}"

@app.route("/")
def home():
    return render_template(HTML_INDEX)

@app.route("/public/<path:path>")
def serve_public(path):
    return send_from_directory("public", path)

@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)



@app.route("/api/debug", methods=["GET"])
def api_debug():
    base_url = "/".join(API_URL.split("/")[:-2]) if "/v1/" in API_URL else API_URL
    models_url = f"{base_url}/v1/models"
    return jsonify({
        "api_url": API_URL,
        "base_url": base_url,
        "models_url": models_url,
        "env_var": os.getenv("LM_STUDIO_API", "non défini")
    }), 200

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

# Endpoint test pour vérifier LM Studio
@app.route("/api/status", methods=["GET"])
def api_status():
    if check_lm_studio_status():
        return jsonify({"status": "LM Studio disponible"}), 200
    return jsonify({"status": "LM Studio non disponible"}), 503

if __name__ == "__main__":
    app.run(debug=True, port=5000)
