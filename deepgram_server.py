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
# NER ENDPOINT - ORIGINAL WORKING VERSION
# ===================================
@app.route('/ner', methods=['POST'])
def extract_ner():
    """Extract named entities using Claude API"""
    try:
        data = request.json
        text = data.get('text', '')
        target_language = data.get('target_language', 'en')
        
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
        
        # Get source language from frontend (if provided)
        source_language = data.get('source_language', 'de')
        source_lang_name = language_map.get(source_language, 'German')
        
        # Build prompt - multilingual base + German-specific hints
        base_prompt = f'Extract named entities from this {source_lang_name} text and provide translations to {target_lang_name}. Return ONLY a JSON array with NO additional text, in this exact format: [{{"text": "entity name", "type": "PERSON", "translation": "{target_lang_name} translation"}}]. Valid types are: PERSON, ORGANIZATION, LOCATION. For each entity, provide the appropriate translation or transliteration in {target_lang_name}.'
        
        # Add German-specific context when source is German
        if source_language == 'de':
            base_prompt += ' IMPORTANT: In German, ALL nouns are capitalized. Extract ONLY proper nouns (specific people, places, organizations like Österreich, Europa, USA, Angela Merkel, Europäische Union). Do NOT extract common nouns like Jahr, Zeit, Welt, Licht, Wahrheit, ich, wir, ein.'
        
        base_prompt += f' Text: "{text}"'
        
        # Call Claude API - HYBRID PROMPT
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'Content-Type': 'application/json',
                'x-api-key': CLAUDE_API_KEY,
                'anthropic-version': '2023-06-01'
            },
            json={
                'model': 'claude-3-haiku-20240307',
                'max_tokens': 1024,
                'messages': [{
                    'role': 'user',
                    'content': base_prompt
                }]
            },
            timeout=10
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
        
        # AGGRESSIVE FILTERING: Only keep entities that are likely proper nouns
        
        filtered_entities = []
        
        # Whitelist of known proper nouns (countries, organizations, etc)
        known_entities = {
            # Countries (German names)
            'österreich', 'deutschland', 'frankreich', 'italien', 'spanien', 'europa',
            'usa', 'china', 'russland', 'großbritannien', 'schweiz', 'polen',
            # Cities
            'wien', 'berlin', 'paris', 'london', 'rom', 'madrid', 'brüssel',
            # Organizations
            'europäische union', 'nato', 'un', 'eu', 'bundestag',
            # Regions
            'osten', 'westen', 'alpen', 'bayern', 'osten europas',
            # Lakes
            'bodensee', 'neusiedlersee', 'genfer see'
        }
        
        # Blacklist of common German words
        blacklist = {
            'jahr', 'jahre', 'jahren', 'zeit', 'zeiten', 'tag', 'tage', 'tagen',
            'welt', 'licht', 'wahrheit', 'krieg', 'frieden', 'leben', 'tod',
            'ich', 'du', 'er', 'sie', 'es', 'wir', 'ihr', 'ein', 'eine', 'der', 'die', 'das',
            'und', 'oder', 'aber', 'den', 'dem', 'des', 'heute', 'morgen', 'gestern'
        }
        
        # Common phrase patterns to reject
        reject_patterns = [
            'an einem tag', 'wie heute', 'wie gestern', 'wie morgen',
            'unserer', 'unser', 'meine', 'mein', 'dein', 'deine'
        ]
        
        for entity in entities:
            entity_text = entity.get('text', '').strip()
            entity_lower = entity_text.lower()
            
            # Rule 0: ALWAYS keep if in whitelist (even if it matches other rules)
            if entity_lower in known_entities:
                filtered_entities.append(entity)
                print(f"Kept (whitelist): {entity_text}", flush=True)
                continue
            
            # Rule 1: Skip if in blacklist
            if entity_lower in blacklist:
                print(f"Filtered (blacklist): {entity_text}", flush=True)
                continue
            
            # Rule 2: Skip if contains reject patterns
            should_reject = False
            for pattern in reject_patterns:
                if pattern in entity_lower:
                    print(f"Filtered (phrase pattern): {entity_text}", flush=True)
                    should_reject = True
                    break
            if should_reject:
                continue
            
            # Rule 3: Keep if multi-word AND both words are capitalized (likely proper noun)
            if ' ' in entity_text:
                words = entity_text.split()
                if len(words) >= 2:
                    # Check if words look like proper nouns (capitalized, not articles)
                    proper_looking = [w for w in words if w[0].isupper() and w.lower() not in {'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'und', 'oder'}]
                    if len(proper_looking) >= 2:
                        filtered_entities.append(entity)
                        print(f"Kept (multi-word proper): {entity_text}", flush=True)
                        continue
            
            # Rule 4: Keep if ends in -see or -berg (lakes/mountains)
            if entity_lower.endswith('see') or entity_lower.endswith('berg'):
                filtered_entities.append(entity)
                print(f"Kept (geographical): {entity_text}", flush=True)
                continue
            
            # Rule 5: Skip single words under 4 chars
            if ' ' not in entity_text and len(entity_text) < 4:
                print(f"Filtered (too short): {entity_text}", flush=True)
                continue
            
            # Rule 6: If single word, only keep if it looks very proper-noun-like
            if ' ' not in entity_text:
                # Must be capitalized and longish
                if entity_text[0].isupper() and len(entity_text) >= 5:
                    filtered_entities.append(entity)
                    print(f"Kept (single proper): {entity_text}", flush=True)
                    continue
            
            # Default: skip uncertain ones
            print(f"Filtered (uncertain): {entity_text}", flush=True)
        
        print(f"Final: {len(filtered_entities)} entities after filtering (from {len(entities)})", flush=True)
        print(f"Kept entities: {[e['text'] for e in filtered_entities]}", flush=True)
        return jsonify({'entities': filtered_entities})
        
    except Exception as e:
        print(f"NER error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ===================================
# WEBSOCKET CODE
# ===================================
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
        audio_queue = queue.Queue(maxsize=100)
        stop_flag = threading.Event()
        
        # Thread to receive audio from browser
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
        
        # Start threads
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
    print("CAI DEEPGRAM BACKEND")
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
    print("WebSocket endpoint: /ws")
    print("NER endpoint: /ner")
    app.run(host='0.0.0.0', port=port)
