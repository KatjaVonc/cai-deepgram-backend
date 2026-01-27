from flask import Flask
from flask_cors import CORS
import os
import asyncio
import json
import threading

app = Flask(__name__)
CORS(app)

DEEPGRAM_API_KEY = os.environ.get('DEEPGRAM_API_KEY', '')

@app.route('/')
def home():
    return {
        'status': 'ok',
        'name': 'CAI Deepgram Backend',
        'api_key_configured': bool(DEEPGRAM_API_KEY),
        'websocket': 'wss://cai-deepgram-backend.onrender.com'
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

async def handle_websocket(websocket):
    """Handle WebSocket connection for Deepgram streaming"""
    print("Client connected")
    
    try:
        import websockets as ws_lib
        
        config_msg = await websocket.recv()
        config = json.loads(config_msg)
        language = config.get('language', 'de')
        
        print(f"Language: {language}")
        
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
        
        async with ws_lib.connect(dg_url, extra_headers=headers) as dg_ws:
            print("Connected to Deepgram")
            
            await websocket.send(json.dumps({'status': 'ready'}))
            
            async def forward_audio():
                async for msg in websocket:
                    if isinstance(msg, bytes):
                        await dg_ws.send(msg)
                    elif isinstance(msg, str):
                        data = json.loads(msg)
                        if data.get('type') == 'close':
                            break
            
            async def forward_transcription():
                async for msg in dg_ws:
                    data = json.loads(msg)
                    if 'channel' in data:
                        text = data['channel']['alternatives'][0]['transcript']
                        is_final = data.get('is_final', False)
                        
                        if text:
                            await websocket.send(json.dumps({
                                'text': text,
                                'is_final': is_final
                            }))
                            print(f"{'[F]' if is_final else '[I]'} {text[:30]}...")
            
            await asyncio.gather(forward_audio(), forward_transcription())
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Client disconnected")

def run_websocket_server():
    """Run WebSocket server on separate thread"""
    async def start():
        import websockets
        port = int(os.environ.get('WS_PORT', 8765))
        async with websockets.serve(handle_websocket, "0.0.0.0", port):
            print(f"WebSocket server: port {port}")
            await asyncio.Future()
    
    asyncio.run(start())

if __name__ == '__main__':
    print("=" * 60)
    print("CAI DEEPGRAM BACKEND")
    print("=" * 60)
    
    if DEEPGRAM_API_KEY:
        print(f"API Key: {DEEPGRAM_API_KEY[:10]}...")
    else:
        print("WARNING: No API key!")
    
    print("=" * 60)
    
    ws_thread = threading.Thread(target=run_websocket_server, daemon=True)
    ws_thread.start()
    
    import time
    time.sleep(2)
    
    port = int(os.environ.get('PORT', 5000))
  print(f"Starting Flask on port {port}")
    app.run(host='0.0.0.0', port=port)

