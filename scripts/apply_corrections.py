#!/usr/bin/env python3
"""Apply verified corrections to the recipe database."""
import sqlite3

DB = "/root/.hermes/projects/receitas/db/receitas.db"
conn = sqlite3.connect(DB)

corrections = [
    # (pdf_source, updates_dict, new_ingredients_list)
    
    # Pág 366 — Arroz Doce
    ("pagina_0366.pdf", {
        "periodo": "pré-treino",
        "calorias": 310, "proteina_g": 4.0, "carboidrato_g": 63.0, "gordura_g": 5.0
    }, [
        ("arroz branco cozido", 100, "g"),
        ("leite de coco light", 100, "ml"),
        ("mel", 20, "g"),
        ("canela em pó", 3, "g"),
        ("passas", 20, "g"),
    ]),
    
    # Pág 61 — Cuscuz Recheado
    ("pagina_0061.pdf", {
        "periodo": "café da manhã", "doce_salgado": "salgado",
        "calorias": 574, "proteina_g": 31.0, "carboidrato_g": 83.0, "gordura_g": 13.0,
        "tempo_preparo_min": 20, "rendimento": "1 porção",
    }, [
        ("flocos de milho para cuscuz", 100, "g"),
        ("sardinha em conserva escorrida", 80, "g"),
        ("requeijão light", 40, "g"),
        ("tomate", 50, "g"),
        ("suco de limão", 5, "ml"),
        ("sal", "a gosto", ""),
        ("coentro", "a gosto", ""),
    ]),
    
    # Pág 388 — Arroz com Pescada
    ("pagina_0388.pdf", {
        "periodo": "pós-treino", "doce_salgado": "salgado",
        "calorias": 448, "proteina_g": 35.0, "carboidrato_g": 48.0, "gordura_g": 13.0,
        "tempo_preparo_min": 20, "rendimento": "1 porção",
    }, [
        ("filé de pescada grelhado", 150, "g"),
        ("azeite", 10, "ml"),
        ("sal", "a gosto", ""),
        ("alho", 5, "g"),
        ("suco de limão", 15, "ml"),
        ("ervas finas", "a gosto", ""),
        ("brócolis cozido", 80, "g"),
        ("arroz branco cozido", 150, "g"),
    ]),
    
    # Pág 291 — Muffin de Mirtilo
    ("pagina_0291.pdf", {
        "periodo": "sobremesa", "doce_salgado": "doce",
        "calorias": 116, "proteina_g": 8.0, "carboidrato_g": 11.0, "gordura_g": 5.0,
        "tempo_preparo_min": 30, "rendimento": "6 porções",
        "dicas": "Os mirtilos são ricos em antocianinas, compostos antioxidantes associados ao suporte da recuperação e da saúde cerebral."
    }, [
        ("farinha de aveia", 80, "g"),
        ("mirtilo fresco", 80, "g"),
        ("iogurte grego desnatado", 80, "g"),
        ("fermento em pó", 5, "g"),
        ("whey protein baunilha", 25, "g"),
        ("ovo inteiro", 60, "g"),
        ("adoçante stevia", 15, "g"),
        ("óleo de coco", 15, "ml"),
    ]),
    
    # Pág 312 — Sorvete de Morango (corrigido manualmente: 86g prot é impossível com 30g whey)
    ("pagina_0312.pdf", {
        "periodo": "sobremesa", "doce_salgado": "doce",
        "calorias": 241, "proteina_g": 24.0, "carboidrato_g": 20.0, "gordura_g": 2.0,
        "tempo_preparo_min": 5, "rendimento": "1 porção",
        "dicas": None,
    }, [
        ("morango congelado", 200, "g"),
        ("whey protein baunilha", 30, "g"),
        ("iogurte grego desnatado", 100, "g"),
        ("adoçante stevia", 10, "g"),
        ("suco de limão", 10, "ml"),
    ]),
]

for pdf_src, updates, ingredients in corrections:
    # Find recipe
    cur = conn.execute("SELECT id, nome FROM recipes WHERE pdf_source = ?", (pdf_src,))
    row = cur.fetchone()
    if not row:
        print(f"❌ {pdf_src} não encontrado")
        continue
    
    rid = row[0]
    nome = row[1]
    
    # Build SET clause
    set_parts = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [rid]
    conn.execute(f"UPDATE recipes SET {set_parts} WHERE id = ?", values)
    
    # Replace ingredients
    conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (rid,))
    for ing_name, qtd, un in ingredients:
        n = ing_name.lower()
        cur2 = conn.execute("SELECT id FROM ingredients WHERE nome = ?", (n,))
        row2 = cur2.fetchone()
        if row2:
            iid = row2[0]
        else:
            conn.execute("INSERT INTO ingredients (nome) VALUES (?)", (n,))
            iid = cur2.lastrowid
        conn.execute("INSERT INTO recipe_ingredients VALUES (?,?,?,?)", (rid, iid, qtd, un))
    
    print(f"✅ {nome}")

conn.commit()

# Verify
print("\n🔍 Verificação:")
for pdf_src, updates, _ in corrections:
    r = conn.execute("SELECT nome, calorias, proteina_g FROM recipes WHERE pdf_source = ?", (pdf_src,)).fetchone()
    calc = (r[2] or 0)*4
    print(f"  {r[0]}: {r[1]}cal, {r[2]}g prot (calculado: {calc}cal)")

total = conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
ings = conn.execute("SELECT COUNT(DISTINCT nome) FROM ingredients").fetchone()[0]
links = conn.execute("SELECT COUNT(*) FROM recipe_ingredients").fetchone()[0]
print(f"\n📊 Total: {total} receitas, {ings} ingredientes, {links} relações")
conn.close()
