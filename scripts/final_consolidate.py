#!/usr/bin/env python3
"""Final consolidation: merge all batches + retry into SQLite, dedup by name."""
import json, glob, sqlite3, os

DB = "/root/.hermes/projects/receitas/db/receitas.db"
BATCH_DIR = "/root/.hermes/projects/receitas/db"

# Fresh DB
if os.path.exists(DB):
    os.remove(DB)
conn = sqlite3.connect(DB)
conn.executescript(open("/root/.hermes/projects/receitas/db/schema.sql").read())

# Load retry data by page
retry = {}
for rf in sorted(glob.glob(os.path.join(BATCH_DIR, "batch_retry_*.json"))):
    with open(rf) as f:
        for r in json.load(f):
            retry[r["page"]] = r

# Load all batches, use retry where available, dedup by name
seen = set()
count = 0

for bf in sorted(glob.glob(os.path.join(BATCH_DIR, "batch_0[1-8].json"))):
    with open(bf) as f:
        for r in json.load(f):
            page = r["page"]
            entry = retry.get(page, r)  # use retry if available
            if "error" in entry or "skip" in entry or not entry.get("nome"):
                continue
            nome = entry["nome"].strip()
            if nome in seen:
                continue
            seen.add(nome)
            
            # Insert recipe
            conn.execute("""
                INSERT INTO recipes (nome, periodo, calorias, proteina_g, carboidrato_g, gordura_g,
                    fibras_g, tempo_preparo_min, rendimento, dicas, doce_salgado, image_path, pdf_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (entry["nome"], entry.get("periodo"), entry.get("calorias"),
                entry.get("proteina_g"), entry.get("carboidrato_g"), entry.get("gordura_g"),
                entry.get("fibras_g"), entry.get("tempo_preparo_min"), entry.get("rendimento"),
                entry.get("dicas"), entry.get("doce_salgado"),
                entry.get("image_path"), entry.get("pdf_source")))
            rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            
            # Insert ingredients
            seen_ings = set()
            for ing in entry.get("ingredientes", []):
                nome_ing = ing.get("nome", "").strip().lower()
                if not nome_ing or nome_ing in seen_ings:
                    continue
                seen_ings.add(nome_ing)
                # Get or create ingredient
                cur = conn.execute("SELECT id FROM ingredients WHERE nome = ?", (nome_ing,))
                row = cur.fetchone()
                if row:
                    iid = row[0]
                else:
                    conn.execute("INSERT INTO ingredients (nome) VALUES (?)", (nome_ing,))
                    iid = cur.lastrowid
                conn.execute("INSERT OR IGNORE INTO recipe_ingredients VALUES (?,?,?,?)",
                    (rid, iid, ing.get("quantidade"), ing.get("unidade")))
            count += 1

conn.commit()

# Stats
total = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
ings = conn.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
links = conn.execute("SELECT COUNT(*) FROM recipe_ingredients").fetchone()[0]
periodos = conn.execute("SELECT periodo, COUNT(*) FROM recipes WHERE periodo IS NOT NULL GROUP BY periodo ORDER BY COUNT(*) DESC").fetchall()
doce = conn.execute("SELECT COUNT(*) FROM recipes WHERE doce_salgado='doce'").fetchone()[0]
salgado = conn.execute("SELECT COUNT(*) FROM recipes WHERE doce_salgado='salgado'").fetchone()[0]
sem_periodo = conn.execute("SELECT COUNT(*) FROM recipes WHERE periodo IS NULL").fetchone()[0]
conn.close()

print(f"✅ CONSOLIDAÇÃO FINAL")
print(f"{'='*40}")
print(f"📊 {total} receitas (meta: 365 | dif: {365 - total})")
print(f"📊 {ings} ingredientes únicos")
print(f"📊 {links} relações receita-ingrediente")
print(f"\n📋 Períodos:")
for p, c in periodos:
    print(f"   {p}: {c}")
print(f"   (sem período): {sem_periodo}")
print(f"\n🍬 Doces: {doce} | 🧂 Salgados: {salgado}")
print(f"\n💾 DB: {os.path.getsize(DB)/1024:.0f} KB")