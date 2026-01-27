from flask import Flask, request
from flask_cors import CORS
from flask_sock import Sock
import os
import json
import asyncio

app = Flask(__name__)
CORS(app)
sock = Sock(app)

DEEPGRAM_API_KEY = os.environ.get('DEEPGRAM_API_KEY', '')

@app.route('/')
def home():
    return {
        'status': 'ok',
        'name': 'CAI Deepgram Backend',
        'api_key_configured': bool(DEEPGRAM_API_KEY),
        'websocket': 'wss://cai-deepgram-backend.onrender.com/ws'
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

@sock.route('/ws')
def websocket_endpoint(ws):
    """WebSocket endpoint for Deepgram streaming"""
    print("Client connected")
    
    try:
        # Get configuration
        config_msg = ws.receive()
        config = json.loads(config_msg)
        language = config.get('language', 'de')
        
        print(f"Language: {language}")
        
        # Import websockets for Deepgram connection
        import websockets
        
        # Build Deepgram URL
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
        
        # Use asyncio to handle Deepgram WebSocket
        async def stream_deepgram():
            async with websockets.connect(dg_url, extra_headers=headers) as dg_ws:
                print("Connected to Deepgram")
                
                # Send ready signal
                ws.send(json.dumps({'status': 'ready'}))
                
                # Forward audio to Deepgram
                async def forward_audio():
                    while True:
                        try:
                            msg = ws.receive(timeout=0.1)
                            if msg:
                                if isinstance(msg, str):
                                    data = json.loads(msg)
                                    if data.get('type') == 'close':
                                        break
                                else:
                                    await dg_ws.send(msg)
                        except:
                            await asyncio.sleep(0.01)
                
                # Forward transcription from Deepgram
                async def forward_transcription():
                    async for msg in dg_ws:
                        data = json.loads(msg)
                        if 'channel' in data:
                            text = data['channel']['alternatives'][0]['transcript']
                            is_final = data.get('is_final', False)
                            
                            if text:
                                ws.send(json.dumps({
                                    'text': text,
                                    'is_final': is_final
                                }))
                                print(f"{'[F]' if is_final else '[I]'} {text[:30]}...")
                
                await asyncio.gather(
                    forward_audio(),
                    forward_transcription()
                )
        
        # Run async function
        asyncio.run(stream_deepgram())
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Client disconnected")

if __name__ == '__main__':
    print("=" * 60)
    print("CAI DEEPGRAM BACKEND (Single Port)")
    print("=" * 60)
    
    if DEEPGRAM_API_KEY:
        print(f"API Key: {DEEPGRAM_API_KEY[:10]}...")
    else:
        print("WARNING: No API key!")
    
    print("=" * 60)
    
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on port {port}")
    print("WebSocket endpoint: /ws")
    app.run(host='0.0.0.0', port=port)

