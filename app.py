import os
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
import requests
import json
import jwt
import uuid
from datetime import datetime, timedelta
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="public", template_folder="template")
CORS(app)

# Configurations
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("ACD")
API_URL = os.getenv("http://127.0.0.1:1234/v1/chat/completions")
#APP_SECRET = os.getenv("APP_SECRET", "your-secret-key")  # À définir dans les variables d'environnement

# Pour stocker les installations d'applications (en production, utilisez une base de données)
app_installations = {}

def build_prompt(story_text, format_choice):
    if format_choice == "gherkin":
        return f"""Voici une user story : "{story_text}"
En tant qu'assistant de test, génère un scénario de test au format Gherkin (Given/When/Then) en français."""
    else:
        return f"""Voici une user story : "{story_text}"
Génère un cas de test détaillé avec les étapes et résultats attendus."""

def generate_response(prompt, max_tokens=500):
    payload = {
        "model": "mistral-7b-instruct-v0.3",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7
    }

    try:
        logger.info(f"Envoi de requête à LM Studio: {API_URL}")
        response = requests.post(API_URL, json=payload, timeout=30)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        logger.error(f"Erreur API LM Studio: {response.status_code} - {response.text}")
        return f"Erreur API : {response.status_code} - {response.text}"
    except Exception as e:
        logger.error(f"Exception lors de l'appel à LM Studio: {str(e)}")
        return f"Erreur LM Studio : {str(e)}"

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/public/<path:path>")
def serve_public(path):
    return send_from_directory("public", path)

@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)

@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json()
    story = data.get("story", "").strip()
    format_choice = data.get("format", "gherkin")

    if not story:
        return jsonify({"error": "Aucune user story fournie"}), 400

    prompt = build_prompt(story, format_choice)
    generated = generate_response(prompt)
    return jsonify({"result": generated})

@app.route("/get-issue")
def get_issue():
    issue_key = request.args.get("key")
    if not issue_key:
        return jsonify({"error": "Clé d'issue manquante"}), 400

    client_key = request.args.get("clientKey")
    if not client_key or client_key not in app_installations:
        return jsonify({"error": "Authentification requise"}), 401

    installation = app_installations.get(client_key)
    base_url = installation.get("base_url")
    
    url = f"{base_url}/rest/api/3/issue/{issue_key}"
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json"}

    try:
        logger.info(f"Récupération de l'issue Jira: {issue_key}")
        res = requests.get(url, headers=headers, auth=auth, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        summary = data["fields"].get("summary", "")
        
        description = ""
        if data["fields"].get("description") and data["fields"]["description"].get("content"):
            for content_item in data["fields"]["description"]["content"]:
                if content_item.get("type") == "paragraph" and content_item.get("content"):
                    for text_item in content_item["content"]:
                        if text_item.get("type") == "text":
                            description += text_item.get("text", "") + "\n"
        
        return jsonify({
            "summary": summary,
            "description": description
        })
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de la récupération de l'issue: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/atlassian-connect.json")
def atlassian_connect():
    return send_from_directory(".", "atlassian-connect.json")

@app.route("/installed", methods=["POST"])
def installed():
    data = request.get_json()
    client_key = data.get("clientKey")
    
    if client_key:
        logger.info(f"Installation pour le client: {client_key}")
        app_installations[client_key] = {
            "client_key": client_key,
            "shared_secret": data.get("sharedSecret"),
            "base_url": data.get("baseUrl"),
            "installed_at": datetime.now().isoformat()
        }
        return "", 204
    else:
        logger.error("Installation sans client key")
        return jsonify({"error": "Client key required"}), 400

@app.route("/uninstalled", methods=["POST"])
def uninstalled():
    data = request.get_json()
    client_key = data.get("clientKey")
    
    if client_key and client_key in app_installations:
        logger.info(f"Désinstallation pour le client: {client_key}")
        del app_installations[client_key]
    
    return "", 204

@app.route("/jira-test-generator", methods=["GET"])
def jira_test_generator():
    issue_key = request.args.get("issueKey")
    context = {
        "issue_key": issue_key,
        "page_id": None
    }
    return render_template("index.html", **context)

@app.route("/confluence-test-generator", methods=["GET"])
def confluence_test_generator():
    page_id = request.args.get("pageId")
    context = {
        "issue_key": None,
        "page_id": page_id
    }
    return render_template("index.html", **context)

def create_jwt_token(client_key, shared_secret, method, uri):
    now = datetime.now()
    exp = now + timedelta(hours=1)
    
    claims = {
        "iss": "test-generator-app",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "qsh": compute_qsh(method, uri),
        "sub": client_key
    }
    
    return jwt.encode(claims, shared_secret, algorithm="HS256")

def compute_qsh(method, uri):
    canonical_uri = uri.split("?")[0]
    return f"{method}&{canonical_uri}&"

@app.route("/api/add-comment", methods=["POST"])
def add_comment():
    data = request.get_json()
    issue_key = data.get("issueKey")
    comment_text = data.get("comment")
    client_key = data.get("clientKey")
    
    if not all([issue_key, comment_text, client_key]):
        return jsonify({"error": "Paramètres manquants"}), 400
    
    if client_key not in app_installations:
        return jsonify({"error": "Installation non trouvée"}), 404
    
    installation = app_installations[client_key]
    base_url = installation["base_url"]
    
    comment_body = {
        "body": {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "Tests générés automatiquement"}]
                },
                {
                    "type": "codeBlock",
                    "attrs": {"language": "gherkin"},
                    "content": [{"type": "text", "text": comment_text}]
                }
            ]
        }
    }
    
    url = f"{base_url}/rest/api/3/issue/{issue_key}/comment"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    
    try:
        response = requests.post(url, json=comment_body, headers=headers, auth=auth, timeout=10)
        response.raise_for_status()
        return jsonify({"message": "Commentaire ajouté avec succès"}), 200
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de l'ajout du commentaire : {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
