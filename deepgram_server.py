from flask import Flask
from flask_cors import CORS
from flask_sock import Sock
import os
import json
import threading
import queue

app = Flask(__name__)
CORS(app)
sock = Sock(app)

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

@sock.route('/ws')
def websocket_endpoint(ws):
    """WebSocket endpoint for Deepgram streaming"""
    print("Client connected", flush=True)
    
    try:
        # Get configuration
        config_msg = ws.receive()
        config = json.loads(config_msg)
        language = config.get('language', 'de')
        
        print(f"Language: {language}", flush=True)
        
        # Send ready signal
        ws.send(json.dumps({'status': 'ready'}))
        
        # Create queue for audio data
        audio_queue = queue.Queue()
        stop_flag = threading.Event()
        
        # Thread to receive audio from browser
        def receive_audio():
            while not stop_flag.is_set():
                try:
                    msg = ws.receive(timeout=0.1)
                    if msg:
                        if isinstance(msg, bytes):
                            audio_queue.put(msg)
                            print(".", end="", flush=True)  # Show activity
                        elif isinstance(msg, str):
                            data = json.loads(msg)
                            if data.get('type') == 'close':
                                stop_flag.set()
                                break
                except:
                    continue
        
        # Thread to forward to Deepgram and receive transcriptions
        def process_deepgram():
            import websockets
            import asyncio
            
            async def stream():
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
                
                print("Connecting to Deepgram...", flush=True)
                
                async with websockets.connect(dg_url, extra_headers=headers) as dg_ws:
                    print("Connected to Deepgram", flush=True)
                    
                    # Send audio task
                    async def send_audio():
                        while not stop_flag.is_set():
                            try:
                                # Get audio from queue (non-blocking)
                                audio_data = audio_queue.get(timeout=0.1)
                                await dg_ws.send(audio_data)
                            except queue.Empty:
                                await asyncio.sleep(0.01)
                            except Exception as e:
                                print(f"Send error: {e}", flush=True)
                                break
                    
                    # Receive transcription task
                    async def receive_transcription():
                        try:
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
                                        print(f"\n{'[F]' if is_final else '[I]'} {text[:50]}...", flush=True)
                        except Exception as e:
                            print(f"Receive error: {e}", flush=True)
                    
                    # Run both tasks
                    await asyncio.gather(
                        send_audio(),
                        receive_transcription(),
                        return_exceptions=True
                    )
            
            # Run async code
            asyncio.run(stream())
        
        # Start threads
        audio_thread = threading.Thread(target=receive_audio, daemon=True)
        deepgram_thread = threading.Thread(target=process_deepgram, daemon=True)
        
        audio_thread.start()
        deepgram_thread.start()
        
        # Wait for completion
        deepgram_thread.join()
        stop_flag.set()
        audio_thread.join()
        
    except Exception as e:
        print(f"Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        print("\nClient disconnected", flush=True)

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
    print(f"Starting server on port {port}")
    print("WebSocket endpoint: /ws")
    app.run(host='0.0.0.0', port=port)
