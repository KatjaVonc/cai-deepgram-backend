from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import os
import json
import threading
import websockets
import asyncio

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
CORS(app, resources={r"/*": {"origins": "*"}})
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

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

@socketio.on('connect')
def handle_connect():
    print('Client connected:', flush=True)

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected', flush=True)

@socketio.on('start_stream')
def handle_start_stream(data):
    print(f'Starting stream with language: {data.get("language", "de")}', flush=True)
    
    language = data.get('language', 'de')
    
    # Start Deepgram connection in a thread
    thread = threading.Thread(target=deepgram_stream, args=(language,))
    thread.daemon = True
    thread.start()
    
    emit('ready', {'status': 'ready'})

def deepgram_stream(language):
    """Connect to Deepgram and handle streaming"""
    asyncio.run(stream_deepgram(language))

async def stream_deepgram(language):
    dg_url = (
        f"wss://api.deepgram.com/v1/listen"
        f"?model=nova-2"
        f"&language={language}"
        f"&smart_format=true"
        f"&interim_results=true"
        f"&utterance_end_ms=1000"
        f"&encoding=linear16"
        f"&sample_rate=16000"
    )
    
    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
    
    try:
        async with websockets.connect(dg_url, extra_headers=headers) as dg_ws:
            print("Connected to Deepgram", flush=True)
            
            # Listen for transcriptions from Deepgram
            async for message in dg_ws:
                data = json.loads(message)
                
                if 'channel' in data:
                    transcript = data['channel']['alternatives'][0]['transcript']
                    is_final = data.get('is_final', False)
                    
                    if transcript:
                        socketio.emit('transcription', {
                            'text': transcript,
                            'is_final': is_final
                        })
                        print(f"{'[F]' if is_final else '[I]'} {transcript[:30]}...", flush=True)
                        
    except Exception as e:
        print(f"Deepgram error: {e}", flush=True)
        socketio.emit('error', {'message': str(e)})

@socketio.on('audio_data')
def handle_audio(data):
    """Receive audio from browser - not used with Deepgram direct connection"""
    pass

if __name__ == '__main__':
    print("=" * 60)
    print("CAI DEEPGRAM BACKEND")
    print("=" * 60)
    
    if DEEPGRAM_API_KEY:
        print(f"API Key: {DEEPGRAM_API_KEY[:10]}...")
    else:
        print("WARNING: No API key!")
    
    print("=" * 60)
    
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)


---

## 📦 Update requirements.txt

flask==3.0.0
flask-cors==4.0.0
flask-socketio==5.3.6
python-socketio==5.11.1
websockets==12.0
eventlet==0.35.2

