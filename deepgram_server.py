from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sock import Sock
import os
import json
import threading
import queue
import requests

app = Flask(__name__)
CORS(app)
sock = Sock(app)

DEEPGRAM_API_KEY = os.environ.get('DEEPGRAM_API_KEY', '')
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')

@app.route('/')
def home():
    return {
        'status': 'ok',
        'name': 'CAI Deepgram Backend',
        'api_key_configured': bool(DEEPGRAM_API_KEY),
        'claude_api_key_configured': bool(CLAUDE_API_KEY)
    }

@app.route('/health')
def health():
    return {'status': 'healthy'}

# ===================================
# NER ENDPOINT - SONNET 3.5 (SMARTER)
# ===================================
@app.route('/ner', methods=['POST'])
def extract_ner():
    """Extract named entities using Claude API with Sonnet"""
    try:
        data = request.json
        text = data.get('text', '')
        target_language = data.get('target_language', 'en')
        source_language = data.get('source_language', 'de')
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        if not CLAUDE_API_KEY:
            return jsonify({'error': 'Claude API key not configured'}), 500
        
        # Language name mapping
        language_map = {
            'de': 'German',
            'en': 'English',
            'it': 'Italian',
            'ro': 'Romanian',
            'sl': 'Slovenian',
            'fr': 'French',
            'es': 'Spanish'
        }
        target_lang_name = language_map.get(target_language, 'English')
        source_lang_name = language_map.get(source_language, 'German')
        
        # Call Claude API - SONNET 3.5 (smarter model)
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'Content-Type': 'application/json',
                'x-api-key': CLAUDE_API_KEY,
                'anthropic-version': '2023-06-01'
            },
            json={
                'model': 'claude-3-5-sonnet-20241022',
                'max_tokens': 2048,
                'messages': [{
                    'role': 'user',
                    'content': f'''You are a named entity recognition expert. Extract ONLY proper nouns from this {source_lang_name} text.

PROPER NOUNS are names of SPECIFIC entities:
- Countries, cities, regions: Österreich, Wien, Europa, USA
- Organizations, institutions: Europäische Union, NATO, Bundestag
- People: Angela Merkel, Van der Bellen
- Geographical features with names: Bodensee, Alpen

COMMON NOUNS are generic words (do NOT extract):
- Generic concepts: Jahr, Zeit, Welt, Krieg, Frieden, Wahrheit, Licht
- Regular nouns: Allianzen, Drohnen, Herkunft, Staatsgrenze
- Pronouns/articles: ich, wir, der, die, das, ein

Critical: Distinguish meaning, not just capitalization. "Europa" (the continent) is a proper noun. "Welt" (world in general) is common.

Return ONLY a JSON array with translations to {target_lang_name}: [{{"text": "entity", "type": "PERSON|ORGANIZATION|LOCATION", "translation": "{target_lang_name}"}}]

Text: "{text}"'''
                }]
            },
            timeout=15
        )
        
        if response.status_code != 200:
            print(f"Claude API error: {response.status_code}", flush=True)
            print(f"Response: {response.text}", flush=True)
            return jsonify({'error': f'Claude API error: {response.status_code}'}), response.status_code
        
        # Parse Claude response
        claude_data = response.json()
        content = claude_data['content'][0]['text'].strip()
        
        # Extract JSON from response
        import re
        json_match = re.search(r'\[[\s\S]*\]', content)
        if not json_match:
            print(f"No JSON found in response: {content}", flush=True)
            return jsonify({'entities': []})
        
        entities = json.loads(json_match.group(0))
        
        print(f"Sonnet extracted {len(entities)} entities: {[e['text'] for e in entities]}", flush=True)
        return jsonify({'entities': entities})
        
    except Exception as e:
        print(f"NER error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ===================================
# WEBSOCKET CODE (unchanged)
# ===================================
@sock.route('/ws')
def websocket_endpoint(ws):
    """WebSocket endpoint for Deepgram streaming"""
    print("Client connected", flush=True)
    
    try:
        config_msg = ws.receive()
        config = json.loads(config_msg)
        language = config.get('language', 'de')
        
        print(f"Language: {language}", flush=True)
        ws.send(json.dumps({'status': 'ready'}))
        
        audio_queue = queue.Queue(maxsize=100)
        stop_flag = threading.Event()
        
        def receive_audio():
            while not stop_flag.is_set():
                try:
                    msg = ws.receive(timeout=0.1)
                    if msg:
                        if isinstance(msg, bytes):
                            try:
                                audio_queue.put(msg, timeout=0.1)
                            except queue.Full:
                                pass
                        elif isinstance(msg, str):
                            data = json.loads(msg)
                            if data.get('type') == 'close':
                                stop_flag.set()
                                break
                except:
                    continue
        
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
                    f"&vad_events=true"
                    f"&detect_entities=true"
                )
                
                headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
                
                print("Connecting to Deepgram...", flush=True)
                
                try:
                    async with websockets.connect(dg_url, extra_headers=headers, ping_interval=5, ping_timeout=10) as dg_ws:
                        print("Connected to Deepgram", flush=True)
                        
                        async def send_audio():
                            try:
                                while not stop_flag.is_set():
                                    try:
                                        audio_data = audio_queue.get(timeout=0.1)
                                        await dg_ws.send(audio_data)
                                    except queue.Empty:
                                        await asyncio.sleep(0.01)
                            except Exception as e:
                                print(f"Send error: {e}", flush=True)
                        
                        async def receive_transcription():
                            try:
                                async for msg in dg_ws:
                                    try:
                                        data = json.loads(msg)
                                        
                                        if 'channel' in data:
                                            alternatives = data['channel'].get('alternatives', [])
                                            if alternatives and len(alternatives) > 0:
                                                transcript = alternatives[0].get('transcript', '')
                                                is_final = data.get('is_final', False)
                                                
                                                if transcript:
                                                    ws.send(json.dumps({
                                                        'text': transcript,
                                                        'is_final': is_final
                                                    }))
                                                    status = '[F]' if is_final else '[I]'
                                                    print(f"{status} {transcript[:50]}...", flush=True)
                                        
                                    except Exception as e:
                                        print(f"Message parse error: {e}", flush=True)
                                        continue
                                        
                            except websockets.exceptions.ConnectionClosed as e:
                                print(f"Deepgram closed: {e}", flush=True)
                            except Exception as e:
                                print(f"Receive error: {e}", flush=True)
                                import traceback
                                traceback.print_exc()
                        
                        await asyncio.gather(
                            send_audio(),
                            receive_transcription(),
                            return_exceptions=True
                        )
                        
                except Exception as e:
                    print(f"Connection error: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
            
            asyncio.run(stream())
        
        audio_thread = threading.Thread(target=receive_audio, daemon=True)
        deepgram_thread = threading.Thread(target=process_deepgram, daemon=True)
        
        audio_thread.start()
        deepgram_thread.start()
        
        deepgram_thread.join()
        stop_flag.set()
        audio_thread.join(timeout=2)
        
    except Exception as e:
        print(f"Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        print("Client disconnected", flush=True)

if __name__ == '__main__':
    print("=" * 60)
    print("CAI DEEPGRAM BACKEND - SONNET 3.5")
    print("=" * 60)
    
    if DEEPGRAM_API_KEY:
        print(f"Deepgram API Key: {DEEPGRAM_API_KEY[:10]}...")
    else:
        print("WARNING: No Deepgram API key!")
    
    if CLAUDE_API_KEY:
        print(f"Claude API Key: {CLAUDE_API_KEY[:10]}...")
    else:
        print("WARNING: No Claude API key!")
    
    print("=" * 60)
    
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on port {port}")
    print("Using Claude Sonnet 3.5 for better German NER")
    app.run(host='0.0.0.0', port=port)
