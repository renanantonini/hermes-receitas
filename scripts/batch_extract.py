#!/usr/bin/env python3
"""
Batch recipe extractor — calls OpenRouter vision models to extract
structured recipe data from images. Primary: Claude Sonnet 4.
Fallback: Gemini 2.5 Flash. Retries up to 2x on JSON parse errors.

Usage: python3 batch_extract.py --start 23 --end 69 --output db/batch_01.json
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

ASSETS_DIR = "/root/.hermes/projects/receitas/assets"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS = [
    "anthropic/claude-sonnet-4",        # Primary — alta qualidade
    "google/gemini-2.5-flash",          # Fallback — barato (~$0.15)
]

SYSTEM_PROMPT = """Você é um extrator de receitas. Analise a imagem da receita e extraia os dados APENAS no formato JSON abaixo.

Extraia OS SEGUINTES campos:
- nome: string (nome da receita)
- periodo: string ou null ("café da manhã", "almoço", "jantar", "lanche")
- calorias: int ou null
- proteina_g: float ou null
- carboidrato_g: float ou null
- gordura_g: float ou null
- fibras_g: float ou null
- tempo_preparo_min: int ou null
- rendimento: string ou null (ex: "1 porção")
- dicas: string ou null (notas do rodapé)
- doce_salgado: string ou null ("doce", "salgado")
- ingredientes: array de objetos com {nome: string, quantidade: string|number, unidade: string}

REGRAS:
- NÃO extraia o modo de preparo.
- Ignore "PhD Santiago Paes" e "@santiagopaesphd".
- Responda APENAS o JSON. NADA de markdown, explicações ou texto extra.
- Se a imagem NÃO for uma receita (capa, índice, etc), retorne: null"""


def get_api_key():
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = "/root/.hermes/.env"
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith("OPENROUTER_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return None


def image_to_data_url(path):
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/jpeg;base64,{data}"


def extract_json_from_response(text):
    """Try multiple strategies to extract valid JSON from model response."""
    text = text.strip()
    
    # Strategy 1: exact JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: remove markdown code fences
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.MULTILINE)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Strategy 3: find JSON object in the text
    match = re.search(r'(\{.*\})', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Strategy 4: try to fix common JSON issues
    # Remove trailing commas
    fixed = re.sub(r',\s*}', '}', cleaned)
    fixed = re.sub(r',\s*]', ']', fixed)
    # Replace single quotes with double quotes (for field names)
    fixed = re.sub(r"'([^']+)':", r'"\1":', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    return None


def call_model(model, page_num, image_url, max_retries=2):
    """Call OpenRouter with a model and return the parsed recipe."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extraia os dados da receita na página {page_num}."},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ],
        "max_tokens": 1000,
        "temperature": 0.1,
    }
    
    headers = {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://hermes-agent.app",
    }
    
    for attempt in range(max_retries + 1):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
            
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
                raw = result["choices"][0]["message"]["content"]
                
                recipe = extract_json_from_response(raw)
                
                if recipe is not None:
                    recipe["_model"] = model
                    if "usage" in result:
                        recipe["_usage"] = {
                            "input": result["usage"].get("prompt_tokens", 0),
                            "output": result["usage"].get("completion_tokens", 0),
                        }
                    return recipe, None
                
                # Model returned null explicitly — not a recipe page
                raw_stripped = raw.strip()
                if raw_stripped == "null" or raw_stripped == "":
                    return None, "__SKIP__"
                
                # JSON parse failed — retry
                err_msg = f"JSON parse error (attempt {attempt+1}): raw starts with '{raw[:100]}'"
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                return None, err_msg
                
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            err_msg = f"HTTP {e.code}: {body[:200]}"
            if attempt < max_retries:
                time.sleep(2)
                continue
            return None, err_msg
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)[:200]}"
            if attempt < max_retries:
                time.sleep(2)
                continue
            return None, err_msg
    
    return None, "Max retries exceeded"


def extract_page(page_num):
    """Extract recipe data with primary + fallback models."""
    filename = f"receita_{page_num:04d}.jpeg"
    filepath = os.path.join(ASSETS_DIR, filename)
    
    if not os.path.exists(filepath):
        return {"page": page_num, "error": f"Arquivo não encontrado: {filename}"}
    
    image_url = image_to_data_url(filepath)
    
    # Try models in order with retries
    for model_idx, model in enumerate(MODELS):
        recipe, error = call_model(model, page_num, image_url)
        
        if error == "__SKIP__":
            return {"page": page_num, "skip": True, "reason": "Página sem receita"}
        
        if recipe is not None:
            recipe["page"] = page_num
            recipe["image_path"] = f"receita_{page_num:04d}.jpeg"
            recipe["pdf_source"] = f"pagina_{page_num:04d}.pdf"
            return recipe
        
        # Log fallback
        if model_idx == 0 and len(MODELS) > 1:
            print(f"  [fallback] Pág {page_num}: {error[:80]} → tentando Gemini...", file=sys.stderr)
    
    return {"page": page_num, "error": f"Todas as tentativas falharam. Último erro: {error}"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()
    
    api_key = get_api_key()
    if not api_key:
        print(json.dumps({"error": "OPENROUTER_API_KEY não encontrada"}))
        sys.exit(1)
    
    results = []
    total_pages = args.end - args.start + 1
    
    for i, page in enumerate(range(args.start, args.end + 1)):
        result = extract_page(page)
        results.append(result)
        
        if "skip" in result:
            status = "SKIP"
        elif "error" in result:
            status = f"ERR: {result['error'][:60]}"
        else:
            model_used = result.get("_model", "?")
            model_tag = "C" if "claude" in model_used else "G"
            status = f"OK[{model_tag}] {result.get('nome', '?')[:35]}"
        
        print(f"[{i+1}/{total_pages}] Pág {page}: {status}", file=sys.stderr)
        
        if i < total_pages - 1:
            time.sleep(args.delay)
    
    output_path = args.output
    with open(output_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    ok = sum(1 for r in results if "error" not in r and "skip" not in r)
    skip = sum(1 for r in results if "skip" in r)
    err = sum(1 for r in results if "error" in r)
    
    fallback_count = sum(1 for r in results if "error" not in r and "skip" not in r and r.get("_model", "").startswith("google"))
    
    print(json.dumps({
        "status": "ok",
        "total": len(results),
        "ok": ok,
        "skip": skip,
        "errors": err,
        "fallback_used": fallback_count,
        "output": output_path
    }))


if __name__ == "__main__":
    main()