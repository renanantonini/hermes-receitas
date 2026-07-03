#!/usr/bin/env python3
"""
Consolidate batch JSON files into the SQLite database.
Usage: python3 consolidate.py [batch_files...]
   or: python3 consolidate.py --all
"""

import glob
import json
import os
import sqlite3
import sys

DB_PATH = "/root/.hermes/projects/receitas/db/receitas.db"
BATCH_DIR = "/root/.hermes/projects/receitas/db"


def get_or_create_ingredient(conn, nome):
    """Get ingredient ID or create if doesn't exist."""
    cur = conn.execute("SELECT id FROM ingredients WHERE nome = ?", (nome,))
    row = cur.fetchone()
    if row:
        return row[0]
    conn.execute("INSERT INTO ingredients (nome) VALUES (?)", (nome,))
    return cur.lastrowid


def validate_recipe(recipe):
    """Sanity checks on extracted recipe data."""
    warnings = []
    
    nome = recipe.get("nome", "")
    if not nome or len(nome) < 3:
        warnings.append(f"nome inválido: '{nome}'")
    
    cal = recipe.get("calorias")
    if cal is not None:
        if not isinstance(cal, (int, float)) or cal < 10 or cal > 3000:
            warnings.append(f"calorias suspeitas: {cal}")
    
    # Sanity: if all macros present, check they're roughly coherent
    p = recipe.get("proteina_g")
    c = recipe.get("carboidrato_g")
    g = recipe.get("gordura_g")
    has_macros = all(x is not None for x in [p, c, g])
    
    if has_macros:
        if p < 0 or c < 0 or g < 0:
            warnings.append(f"macros negativos: prot={p} carb={c} gord={g}")
        # Rough sanity: if calories are provided, macros should be close
        if cal:
            calc_cal = p * 4 + c * 4 + g * 9
            ratio = abs(calc_cal - cal) / max(cal, 1)
            if ratio > 0.5:
                warnings.append(f"calorias ({cal}) divergem de macros ({calc_cal:.0f}): {ratio:.0%}")
    
    # Check ingredients
    ings = recipe.get("ingredientes", [])
    if not ings:
        warnings.append("sem ingredientes")
    
    # Check image path
    if not recipe.get("image_path"):
        warnings.append("sem image_path")
    
    return warnings


def insert_recipe(conn, recipe):
    """Insert a single recipe into the database."""
    if "error" in recipe or recipe.get("skip"):
        return False
    
    required = ["nome"]
    if not recipe.get("nome"):
        return False
    
    # Insert recipe
    conn.execute("""
        INSERT INTO recipes (
            nome, periodo, calorias, proteina_g, carboidrato_g, gordura_g,
            fibras_g, tempo_preparo_min, rendimento, dicas, doce_salgado,
            image_path, pdf_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        recipe.get("nome"),
        recipe.get("periodo"),
        recipe.get("calorias"),
        recipe.get("proteina_g"),
        recipe.get("carboidrato_g"),
        recipe.get("gordura_g"),
        recipe.get("fibras_g"),
        recipe.get("tempo_preparo_min"),
        recipe.get("rendimento"),
        recipe.get("dicas"),
        recipe.get("doce_salgado"),
        recipe.get("image_path"),
        recipe.get("pdf_source"),
    ))
    
    recipe_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # Insert ingredients (deduped)
    seen_ingredients = set()
    for ing in recipe.get("ingredientes", []):
        nome = ing.get("nome", "").strip()
        if not nome:
            continue
        nome_lower = nome.lower()
        if nome_lower in seen_ingredients:
            continue  # Skip duplicate ingredient in same recipe
        seen_ingredients.add(nome_lower)
        ing_id = get_or_create_ingredient(conn, nome_lower)
        conn.execute("""
            INSERT OR IGNORE INTO recipe_ingredients (recipe_id, ingredient_id, quantidade, unidade)
            VALUES (?, ?, ?, ?)
        """, (
            recipe_id,
            ing_id,
            ing.get("quantidade"),
            ing.get("unidade"),
        ))
    
    return True


def consolidate(batch_files):
    """Consolidate all batch files into the database."""
    conn = sqlite3.connect(DB_PATH)
    count_ok = 0
    count_err = 0
    count_skip = 0
    
    for bf in batch_files:
        with open(bf) as f:
            recipes = json.load(f)
        
        for recipe in recipes:
            if "error" in recipe:
                count_err += 1
                continue
            if recipe.get("skip"):
                count_skip += 1
                continue
            if insert_recipe(conn, recipe):
                count_ok += 1
                warnings = validate_recipe(recipe)
                if warnings:
                    nome = recipe.get("nome", "?")
                    for w in warnings:
                        print(f"  ⚠️  {nome}: {w}", file=sys.stderr)
            else:
                count_err += 1
    
    conn.commit()
    conn.close()
    
    return count_ok, count_err, count_skip


def main():
    if "--all" in sys.argv:
        batch_files = sorted(glob.glob(os.path.join(BATCH_DIR, "batch_*.json")))
        # Exclude test file
        batch_files = [f for f in batch_files if "test" not in f]
    else:
        batch_files = sys.argv[1:]
    
    if not batch_files:
        print("Usage: python3 consolidate.py --all")
        print("   or: python3 consolidate.py batch_01.json batch_02.json ...")
        sys.exit(1)
    
    print(f"Consolidando {len(batch_files)} arquivos batch...")
    ok, err, skip = consolidate(batch_files)
    print(f"\n✅ Inseridas: {ok}")
    print(f"⏭️  Puladas: {skip}")
    print(f"❌ Erros: {err}")
    print(f"📊 Total: {ok + err + skip}")
    
    # Verify
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
    ing_count = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
    link_count = conn.execute("SELECT COUNT(*) FROM recipe_ingredients").fetchone()[0]
    conn.close()
    print(f"\n📊 DB Final:")
    print(f"   {total} receitas")
    print(f"   {ing_count} ingredientes únicos")
    print(f"   {link_count} relações receita-ingrediente")


if __name__ == "__main__":
    main()
