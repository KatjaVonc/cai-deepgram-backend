from flask import Flask, request, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)

DEEPGRAM_API_KEY = os.environ.get('DEEPGRAM_API_KEY', '')

@app.route('/')
def home():
    return {
        'status': 'ok',
        'name': 'CAI Deepgram Backend',
        'api_key_configured': bool(DEEPGRAM_API_KEY)
    }

@app.route('/health')
def health():
    return {'status': 'healthy'}

@app.route('/test')
def test():
    return {
        'deepgram_key': DEEPGRAM_API_KEY[:10] + '...' if DEEPGRAM_API_KEY else 'NOT SET',
        'environment': 'production'
    }

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)


