-- Schema do Banco de Receitas
-- SQLite

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    periodo TEXT,
    calorias INTEGER,
    proteina_g REAL,
    carboidrato_g REAL,
    gordura_g REAL,
    fibras_g REAL,
    tempo_preparo_min INTEGER,
    rendimento TEXT,
    dicas TEXT,
    doce_salgado TEXT,
    image_path TEXT,
    pdf_source TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    recipe_id INTEGER NOT NULL,
    ingredient_id INTEGER NOT NULL,
    quantidade REAL,
    unidade TEXT,
    PRIMARY KEY (recipe_id, ingredient_id),
    FOREIGN KEY (recipe_id) REFERENCES recipes(id),
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
);

-- Índices para busca rápida
CREATE INDEX IF NOT EXISTS idx_recipes_periodo ON recipes(periodo);
CREATE INDEX IF NOT EXISTS idx_recipes_calorias ON recipes(calorias);
CREATE INDEX IF NOT EXISTS idx_recipes_proteina ON recipes(proteina_g);
CREATE INDEX IF NOT EXISTS idx_recipes_doce_salgado ON recipes(doce_salgado);
CREATE INDEX IF NOT EXISTS idx_ingredients_nome ON ingredients(nome);

-- FTS5 para busca textual
CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
    nome,
    dicas,
    content='recipes',
    content_rowid='id'
);

-- Triggers para manter FTS sincronizado
CREATE TRIGGER IF NOT EXISTS recipes_ai AFTER INSERT ON recipes BEGIN
    INSERT INTO recipes_fts(rowid, nome, dicas) VALUES (new.id, new.nome, new.dicas);
END;

CREATE TRIGGER IF NOT EXISTS recipes_ad AFTER DELETE ON recipes BEGIN
    INSERT INTO recipes_fts(recipes_fts, rowid, nome, dicas) VALUES('delete', old.id, old.nome, old.dicas);
END;

CREATE TRIGGER IF NOT EXISTS recipes_au AFTER UPDATE ON recipes BEGIN
    INSERT INTO recipes_fts(recipes_fts, rowid, nome, dicas) VALUES('delete', old.id, old.nome, old.dicas);
    INSERT INTO recipes_fts(rowid, nome, dicas) VALUES (new.id, new.nome, new.dicas);
END;
