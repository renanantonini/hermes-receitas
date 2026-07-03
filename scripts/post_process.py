#!/usr/bin/env python3
"""
Post-processing: validate extracted recipes for quality issues.
Level 1: Rule-based checks (free, no API calls).
Level 2: Re-extract suspicious recipes (optional, costs tokens).

Usage:
  python3 post_process.py --level1          # Run validation only
  python3 post_process.py --level2 [--budget 4.00]  # Re-extract suspects
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
import base64

DB = "/root/.hermes/projects/receitas/db/receitas.db"
ASSETS = "/root/.hermes/projects/receitas/assets"


# ──────────────────────────────────────────────
# LEVEL 1 — Rule-based validation (free)
# ──────────────────────────────────────────────

STOPWORDS = {
    'de', 'da', 'do', 'das', 'dos', 'com', 'em', 'no', 'na', 'e', 'a', 'o', 'à',
    'para', 'ao', 'aos', 'pós', 'pré', 'um', 'uma', 'sem', 'mais',
}

DISH_TYPES = {
    'pão', 'bolo', 'torta', 'pudim', 'mousse', 'sopa', 'creme', 'caldo',
    'panqueca', 'omelete', 'crepioca', 'tapioca', 'cuscuz', 'salada',
    'risoto', 'lasanha', 'strogonoff', 'yakisoba', 'nhoque', 'escondidinho',
    'quibe', 'moqueca', 'feijoada', 'vatapá', 'bobó', 'farofa',
    'hambúrguer', 'sanduíche', 'wrap', 'burrito', 'taco', 'tigela',
    'muffin', 'cookie', 'brownie', 'cupcake', 'cheesecake',
    'brigadeiro', 'beijinho', 'cocada', 'paçoca', 'palha',
    'bolinho', 'coxinha', 'pastel', 'empada', 'esfirra', 'pizza',
    'mingau', 'vitamina', 'sorvete', 'picolé', 'gelatina', 'chá',
    'torrada', 'bruschetta', 'chips', 'dadinhos', 'palito', 'espetinho',
    'croquete', 'trufa', 'bombom', 'bolinha', 'potinho',
    'ceviche', 'tagine', 'pratão', 'jantinha', 'prato', 'tortinha',
    'frozen', 'manjar', 'cannoli', 'crumble', 'petit',
    'tiramisù', 'tiramisu', 'quindim', 'curau', 'canjica', 'pavê',
    'focaccia', 'macarrão', 'espaguete', 'polenta',
}

PREP_WORDS = {
    'assado', 'grelhado', 'cozido', 'frito', 'recheado', 'empanado',
    'leve', 'cremoso', 'saudável', 'fit', 'crocante', 'rápido', 'simples',
    'caseiro', 'natural', 'integral', 'reforçado', 'completo', 'morna',
    'tradicional', 'especial', 'noturno', 'noturna', 'matinal',
    'delicioso', 'fresco', 'quente', 'mexido', 'salgado',
    'doce', 'seco', 'aberto',
}

def extract_keywords(name):
    """Extract meaningful keywords from recipe name — excluding dish types and prep words."""
    name = name.lower()
    name = re.sub(r'\([^)]*\)', '', name)
    words = re.findall(r'[a-záàâãéèêíïóôõöúçü]+', name)
    keywords = [w for w in words 
                if w not in STOPWORDS 
                and w not in DISH_TYPES 
                and w not in PREP_WORDS
                and len(w) > 2]
    return keywords


def check_name_in_ingredients(nome, ingredients):
    """Check if keywords from recipe name appear in ingredient list."""
    keywords = extract_keywords(nome)
    if not keywords:
        return []
    
    missing = []
    ing_names = [i.lower() for i in ingredients]
    
    for kw in keywords:
        found = False
        for ing in ing_names:
            if kw in ing or ing in kw:
                # Check for meaningful substring match
                if len(kw) >= 4 or len(ing) >= 4:
                    found = True
                    break
        if not found:
            missing.append(kw)
    
    return missing


def check_calorie_consistency(calorias, proteina, carb, gordura):
    """Check if calories ≈ 4*protein + 4*carbs + 9*fat."""
    if None in (calorias, proteina, carb, gordura):
        return None
    
    calculated = (proteina or 0) * 4 + (carb or 0) * 4 + (gordura or 0) * 9
    if calculated == 0:
        return None
    
    divergence = abs(calorias - calculated) / max(calorias, calculated) * 100
    return divergence


def check_absurd_quantities(ingredients):
    """Check for suspicious quantities."""
    issues = []
    for ing in ingredients:
        nome = ing[0].lower()
        qtd = ing[1]
        un = (ing[2] or "").lower()
        
        if qtd is None:
            continue
        
        # Suco de limão > 50ml per serving
        if 'limão' in nome and qtd > 50 and 'ml' in un:
            issues.append(f"{nome}: {qtd}{un} parece excessivo")
        
        # Batata > 500g per serving
        if 'batata' in nome and qtd > 500:
            issues.append(f"{nome}: {qtd}g parece excessivo")
        
        # Leite > 1L per serving
        if 'leite' in nome and qtd > 1000 and 'ml' in un:
            issues.append(f"{nome}: {qtd}{un} parece excessivo")
    
    return issues


def detect_period_from_name(nome):
    """Detect if recipe name suggests a period that wasn't captured."""
    nome_lower = nome.lower()
    hints = {
        'café da manhã': ['café da manhã', 'café matinal', 'breakfast'],
        'almoço': ['almoço', 'almoçar'],
        'jantar': ['jantar', 'ceia', 'noturno'],
        'lanche': ['lanche', 'lanchinho', 'snack'],
        'sobremesa': ['sobremesa', 'doce', 'pudim', 'mousse', 'torta', 'bolo', 'brownie', 'cookie', 'muffin'],
        'pré-treino': ['pré-treino', 'pre treino', 'pré treino'],
        'pós-treino': ['pós-treino', 'pos treino', 'pós treino'],
    }
    
    suggestions = []
    for period, keywords in hints.items():
        for kw in keywords:
            if kw in nome_lower:
                suggestions.append(period)
                break
    
    return suggestions


def validate_recipe(recipe_id, nome, periodo, calorias, proteina, carb, gordura, ingredients):
    """Run all level-1 checks on a single recipe."""
    issues = []
    
    # Check 1: Calorie-macro consistency (most reliable indicator of errors)
    cal_div = check_calorie_consistency(calorias, proteina, carb, gordura)
    if cal_div is not None and cal_div > 40:
        issues.append({
            "type": "calorie_mismatch",
            "severity": "high",
            "detail": f"Calorias ({calorias}) divergem de macros ({cal_div:.0f}%)",
            "divergence": cal_div
        })
    
    # Check 2: Absurd quantities
    qty_issues = check_absurd_quantities(ingredients)
    if qty_issues:
        issues.append({
            "type": "absurd_quantity",
            "severity": "medium",
            "detail": "; ".join(qty_issues)
        })
    
    # Check 3: Period from name
    if not periodo:
        suggestions = detect_period_from_name(nome)
        if suggestions and "sobremesa" in suggestions:
            issues.append({
                "type": "missing_period",
                "severity": "low",
                "detail": f"Nome sugere sobremesa",
                "suggested": suggestions
            })
    
    # Check 4: Low ingredient count
    if len(ingredients) < 3:
        issues.append({
            "type": "few_ingredients",
            "severity": "medium",
            "detail": f"Apenas {len(ingredients)} ingredientes"
        })
    
    return issues


def run_level1():
    """Run level 1 validation on all recipes."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    
    total = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    suspicious = []
    
    for r in conn.execute("SELECT * FROM recipes ORDER BY id"):
        ings = conn.execute("""
            SELECT i.nome, ri.quantidade, ri.unidade
            FROM recipe_ingredients ri
            JOIN ingredients i ON ri.ingredient_id = i.id
            WHERE ri.recipe_id = ?
        """, (r["id"],)).fetchall()
        
        issues = validate_recipe(
            r["id"], r["nome"], r["periodo"],
            r["calorias"], r["proteina_g"], r["carboidrato_g"], r["gordura_g"],
            [(i["nome"], i["quantidade"], i["unidade"]) for i in ings]
        )
        
        if issues:
            suspicious.append({
                "id": r["id"],
                "nome": r["nome"],
                "page": r["pdf_source"],
                "image": r["image_path"],
                "issues": issues
            })
    
    conn.close()
    
    # Report
    high = sum(1 for s in suspicious if any(i["severity"] == "high" for i in s["issues"]))
    medium = sum(1 for s in suspicious if any(i["severity"] == "medium" for i in s["issues"]))
    low = sum(1 for s in suspicious if any(i["severity"] == "low" for i in s["issues"]))
    
    print(f"\n{'='*60}")
    print(f"📊 RELATÓRIO DE VALIDAÇÃO — NÍVEL 1")
    print(f"{'='*60}")
    print(f"Total de receitas: {total}")
    print(f"Receitas com suspeitas: {len(suspicious)} ({len(suspicious)/total*100:.1f}%)")
    print(f"  🔴 Alta gravidade (ingredientes faltando): {high}")
    print(f"  🟡 Média gravidade: {medium}")
    print(f"  🟢 Baixa gravidade: {low}")
    
    if high > 0:
        print(f"\n{'='*60}")
        print(f"🔴 RECEITAS COM ALTA GRAVIDADE (ingredientes do nome faltando)")
        print(f"{'='*60}")
        for s in suspicious:
            high_issues = [i for i in s["issues"] if i["severity"] == "high"]
            if high_issues:
                for iss in high_issues:
                    print(f"  📄 {s['page']} — {s['nome']}")
                    print(f"     ⚠️  {iss['detail']}")
                    print(f"     📸 {s['image']}")
    
    return suspicious


# ──────────────────────────────────────────────
# LEVEL 2 — Re-extract suspicious recipes
# ──────────────────────────────────────────────

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


def re_extract_recipe(page_num, nome_original, missing_keywords, budget_tracker):
    """Re-extract a single suspicious recipe with an improved prompt."""
    image_path = f"/root/.hermes/projects/receitas/assets/receita_{page_num:04d}.jpeg"
    if not os.path.exists(image_path):
        return {"page": page_num, "error": "Image not found"}
    
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    img_url = f"data:image/jpeg;base64,{img_b64}"
    
    # Improved prompt that tells the model what to look for
    prompt = (
        f"A receita se chama '{nome_original}'.\n"
        f"IMPORTANTE: Esta receita DEVE conter estes ingredientes: {', '.join(missing_keywords)}.\n"
        f"Analise a imagem e extraia a lista COMPLETA de ingredientes (UM POR UM, com quantidades exatas).\n"
        f"Não invente nada. Não omita nada. Verifique cada item duas vezes.\n\n"
        f"Extraia também: nome, periodo (café da manhã/almoço/jantar/lanche/sobremesa/ceia/pré-treino/pós-treino/null), "
        f"calorias, proteina_g, carboidrato_g, gordura_g, fibras_g, tempo_preparo_min, rendimento, dicas, doce_salgado.\n\n"
        f"Responda APENAS com o JSON, sem markdown."
    )
    
    payload = {
        "model": "anthropic/claude-sonnet-4",
        "messages": [
            {"role": "system", "content": "Você é um extrator de receitas preciso e rigoroso."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": img_url}}
            ]}
        ],
        "max_tokens": 1000,
        "temperature": 0.0,
    }
    
    headers = {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://hermes-agent.app",
    }
    
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=data, headers=headers, method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            raw = result["choices"][0]["message"]["content"]
            
            # Track cost
            if "usage" in result:
                budget_tracker["tokens"] += result["usage"].get("total_tokens", 0)
            
            # Parse JSON
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
            
            recipe = json.loads(cleaned)
            if recipe is None:
                return {"page": page_num, "error": "Model returned null"}
            
            recipe["page"] = page_num
            recipe["image_path"] = f"receita_{page_num:04d}.jpeg"
            recipe["pdf_source"] = f"pagina_{page_num:04d}.pdf"
            return recipe
    
    except Exception as e:
        return {"page": page_num, "error": str(e)}


def run_level2(suspicious, budget_limit=4.00):
    """Re-extract high-severity suspicious recipes."""
    api_key = get_api_key()
    if not api_key:
        print("❌ OPENROUTER_API_KEY não encontrada")
        return
    
    # Filter only high severity
    to_retry = [s for s in suspicious if any(i["severity"] == "high" for i in s["issues"])]
    
    cost_per_page = 0.008  # estimate
    estimated = len(to_retry) * cost_per_page
    
    print(f"\n{'='*60}")
    print(f"📊 NÍVEL 2 — RE-EXTRAÇÃO SELETIVA")
    print(f"{'='*60}")
    print(f"Receitas para re-extrair: {len(to_retry)}")
    print(f"Custo estimado: ${estimated:.2f}")
    print(f"Budget restante: ${budget_limit:.2f}")
    
    if estimated > budget_limit:
        print(f"❌ Custo estimado excede budget. Reduza ou aumente budget.")
        return
    
    budget_tracker = {"tokens": 0}
    results = []
    
    for i, s in enumerate(to_retry, 1):
        # Extract the missing keywords
        missing_kws = []
        for iss in s["issues"]:
            if iss["type"] == "missing_ingredient":
                missing_kws.extend(iss.get("keywords", []))
        
        # Get page number from pdf_source
        page_match = re.search(r'(\d+)', s["page"])
        page_num = int(page_match.group(1)) if page_match else 0
        
        print(f"\n[{i}/{len(to_retry)}] Re-extraindo: {s['nome']} (pág {page_num})...", end=" ", flush=True)
        
        result = re_extract_recipe(page_num, s["nome"], missing_kws, budget_tracker)
        results.append(result)
        
        if "error" in result:
            print(f"❌ {result['error'][:60]}")
        else:
            print(f"✅ {result.get('nome', '?')}")
        
        time.sleep(0.5)
    
    # Calculate cost
    total_cost = budget_tracker["tokens"] * 3 / 1_000_000  # Claude Sonnet $3/M input
    print(f"\n📊 Custo: ~${total_cost:.2f}")
    
    return results


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--level1", action="store_true", help="Run level-1 validation")
    parser.add_argument("--level2", action="store_true", help="Run level-2 re-extraction")
    parser.add_argument("--budget", type=float, default=4.00, help="Max budget for level 2 ($)")
    args = parser.parse_args()
    
    if args.level1:
        suspicious = run_level1()
        
        if args.level2 and suspicious:
            results = run_level2(suspicious, args.budget)
            if results:
                # Save results
                output = "db/re_extracted.json"
                with open(output, "w") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
                print(f"\n✅ Resultados salvos em {output}")
    
    elif args.level2:
        # Load existing validation and re-extract
        print("⚠️  Use --level1 --level2 para executar ambos.")
    
    else:
        print("Uso: python3 post_process.py --level1 [--level2] [--budget 4.00]")


if __name__ == "__main__":
    main()