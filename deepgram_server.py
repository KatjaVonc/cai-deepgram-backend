from flask import Flask
from flask_cors import CORS
import asyncio
import json
import threading
import os

app = Flask(__name__)

# Allow requests from your Netlify site
CORS(app, resources={
    r"/*": {
        "origins": ["*"],  # We'll restrict this later
        "allow_headers": ["Content-Type"],
        "methods": ["GET", "POST"]
    }
})

# Get API key from environment variable (Railway will provide this)
DEEPGRAM_API_KEY = os.environ.get('DEEPGRAM_API_KEY', '')

async def handle_client(websocket):
    """Handle WebSocket connection"""
    print("New client connected")
    
    try:
        import websockets as ws_lib
        
        # Get config from browser
        config_msg = await websocket.recv()
        config = json.loads(config_msg)
        language = config.get('language', 'de')
        
        print(f"Starting transcription: {language}")
        
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
        
        # Connect to Deepgram
        async with ws_lib.connect(dg_url, extra_headers=headers) as dg_ws:
            print("Connected to Deepgram")
            
            # Send ready
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
                            print(f"{'[F]' if is_final else '[I]'} {text[:50]}...")
            
            await asyncio.gather(forward_audio(), forward_transcription())
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        print("Client disconnected")

def run_ws_server():
    """Run WebSocket server"""
    async def start():
        import websockets
        port = int(os.environ.get('PORT', 8765))
        async with websockets.serve(handle_client, "0.0.0.0", port):
            print(f"WebSocket server on port {port}")
            await asyncio.Future()
    
    asyncio.run(start())

@app.route('/health')
def health():
    """Health check for Railway"""
    return {'status': 'ok', 'deepgram_configured': bool(DEEPGRAM_API_KEY)}

@app.route('/')
def home():
    """Root endpoint"""
    return {
        'name': 'CAI Tool - Deepgram Backend',
        'status': 'running',
        'websocket': f"wss://{os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost')}",
        'health': '/health'
    }

if __name__ == '__main__':
    print("=" * 60)
    print("CAI TOOL - DEEPGRAM BACKEND")
    print("=" * 60)
    
    if not DEEPGRAM_API_KEY:
        print("WARNING: No API key found!")
        print("Set DEEPGRAM_API_KEY environment variable")
    else:
        print(f"API Key: {DEEPGRAM_API_KEY[:10]}...")
    
    print("=" * 60)
    
    # Start WebSocket server in background
    ws_thread = threading.Thread(target=run_ws_server, daemon=True)
    ws_thread.start()
    
    import time
    time.sleep(2)
    
    # Start Flask (Railway expects this on PORT env var)
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Flask on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)