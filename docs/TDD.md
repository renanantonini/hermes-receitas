# TDD — Sistema de Receitas Hermes

> **Versão do documento**: v1.2
> **Mudanças**: Fluxo de imagem alterado — imagens são enviadas apenas sob demanda

---

## 1. Visão Técnica

Sistema de receitas integrado ao Hermes Agent, acessível via Discord. O sistema mantém uma base SQLite com receitas extraídas via visão computacional (Claude Sonnet 4), e uma skill do Hermes que consulta a base, filtra por critérios e retorna resultados com imagens anexadas.

## 2. Stack Tecnológica Detalhada

| Camada | Tecnologia | Justificativa |
|--------|-----------|---------------|
| **Database** | SQLite 3 + FTS5 | Portátil, zero-config, busca textual fulltext |
| **Extração dados** | Claude Sonnet 4 via OpenRouter | Visão de alta qualidade para PDF escaneado |
| **Pré-processamento** | PyMuPDF (fitz) | Extração de imagens de páginas PDF |
| **Assets** | JPEG em filesystem (~/.hermes/projects/receitas/assets/) | Anexo direto no Discord via gateway |
| **Interface** | Hermes Skill (hermes-receitas) | Consultas via chat Discord |
| **Orquestração** | Hermes Kanban + multi-agent | Ciclo planner → TDD → executor → QA |

## 3. Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────┐
│                    DISCORD                            │
│  Renan/Kassia: "hermes, receita com frango até 400cal"│
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              HERMES SKILL (hermes-receitas)           │
│  1. Interpreta o pedido (extrai filtros)              │
│  2. Se faltar info → pergunta preferências            │
│  3. Monta query SQL                                   │
│  4. Executa contra SQLite                             │
│  5. Formata resposta + anexa imagens                  │
│  6. Envia pro Discord                                 │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              SQLITE DATABASE                          │
│  recipes / ingredients / recipe_ingredients / FTS5   │
│  ~/.hermes/projects/receitas/db/receitas.db          │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              ASSETS (imagens JPEG)                    │
│  ~/.hermes/projects/receitas/assets/receita_XXXX.jpeg│
└─────────────────────────────────────────────────────┘
```

## 4. Modelo de Dados (SQLite)

### 4.1 Tabelas

```sql
-- Já implementado em db/schema.sql

recipes:
  id              INTEGER PRIMARY KEY
  nome            TEXT NOT NULL          -- Nome da receita
  periodo         TEXT                   -- café da manhã, almoço, jantar, lanche
  calorias        INTEGER                -- Calorias totais
  proteina_g      REAL                   -- Proteína em gramas
  carboidrato_g   REAL                   -- Carboidratos em gramas
  gordura_g       REAL                   -- Gorduras em gramas
  fibras_g        REAL                   -- Fibras em gramas
  tempo_preparo_min INTEGER              -- Minutos de preparo
  rendimento      TEXT                   -- Ex: "1 porção", "6 porções"
  dicas           TEXT                   -- Notas/dicas do rodapé
  doce_salgado    TEXT                   -- "doce", "salgado" ou NULL
  image_path      TEXT                   -- Caminho relativo em assets/
  pdf_source      TEXT                   -- Página de origem
  created_at      TEXT DEFAULT datetime('now')

ingredients:
  id              INTEGER PRIMARY KEY
  nome            TEXT NOT NULL UNIQUE    -- Nome normalizado (lowercase)

recipe_ingredients:
  recipe_id       INTEGER FK → recipes.id
  ingredient_id   INTEGER FK → ingredients.id
  quantidade      REAL                    -- Quantidade numérica
  unidade         TEXT                    -- Unidade (g, ml, xícara, unidade, etc)
  PRIMARY KEY (recipe_id, ingredient_id)
```

### 4.2 Índices e FTS

```sql
-- Índices de performance
CREATE INDEX idx_recipes_periodo ON recipes(periodo);
CREATE INDEX idx_recipes_calorias ON recipes(calorias);
CREATE INDEX idx_recipes_proteina ON recipes(proteina_g);
CREATE INDEX idx_recipes_doce_salgado ON recipes(doce_salgado);
CREATE INDEX idx_ingredients_nome ON ingredients(nome);

-- Full-Text Search
CREATE VIRTUAL TABLE recipes_fts USING fts5(nome, dicas, content='recipes', content_rowid='id');
```

### 4.3 Exemplos de Query

```sql
-- Busca por período + calorias + proteína
SELECT r.* FROM recipes r
WHERE r.periodo = 'almoço'
  AND r.calorias <= 400
  AND r.proteina_g >= 30
ORDER BY r.proteina_g DESC
LIMIT 5;

-- Busca por ingredientes disponíveis
SELECT r.* FROM recipes r
JOIN recipe_ingredients ri ON r.id = ri.recipe_id
JOIN ingredients i ON ri.ingredient_id = i.id
WHERE i.nome IN ('frango', 'whey', 'canela', 'farinha de trigo')
GROUP BY r.id
HAVING COUNT(DISTINCT i.nome) >= 3  -- precisa ter pelo menos 3 dos ingredientes
ORDER BY COUNT(DISTINCT i.nome) DESC
LIMIT 5;

-- Busca textual (FTS5)
SELECT r.* FROM recipes r
JOIN recipes_fts fts ON r.id = fts.rowid
WHERE recipes_fts MATCH 'low carb OR fit OR proteico'
LIMIT 5;
```

## 5. Pipeline de Extração

### 5.1 Fluxo

```
PDF original (149MB, 394 pág)
    │
    ▼
[1. Extração de imagens] ─ PyMuPDF extrai 1 JPEG por página
    │                       → assets/receita_XXXX.jpeg (1818×2573px)
    ▼
[2. Processamento via IA] ─ Claude Sonnet 4 (OpenRouter)
    │                        → 1 chamada por página (~$0.008/página)
    │                        → Retorna JSON estruturado
    ▼
[3. Consolidação] ─ Script insere dados no SQLite
    │                → recipes, ingredients, recipe_ingredients
    ▼
[4. Pronto para consulta]
```

### 5.2 Controle de Qualidade

- Páginas 1-22: capa/intro/índice (pular, sem receita)
- Páginas 23-394: receitas (372 páginas)
- Cada extração retorna "skip" se não for uma receita
- Retentativa automática em caso de falha de API (timeout)
- Log de erros por página para auditoria

### 5.3 Custo Estimado

| Item | Quantidade | Custo Unit | Total |
|------|-----------|------------|-------|
| Visual tokens (Claude Sonnet 4) | 372 × 1.568 | $3/1M input | ~$1,86 |
| Prompt texto | 372 × 200 | $3/1M input | ~$0,22 |
| Output tokens | 372 × 250 | $15/1M output | ~$1,40 |
| **Total estimado** | | | **~$3,48** |
| **Teto de segurança** | | | **$8,00** |

## 6. Skill Hermes — Especificação

### 6.1 Nome e Localização

- Skill: `hermes-receitas`
- Local: `~/.hermes/skills/software-development/hermes-receitas/SKILL.md`

### 6.2 Comportamento

A skill é ativada quando Renan ou Kassia menciona "receita" no Discord (detectado pelo gateway). Ela:

1. **Analisa a mensagem** para extrair filtros implícitos:
   - Período do dia (café, almoço, jantar, lanche)
   - Calorias (ex: "até 400 cal", "<500 kcal")
   - Proteína (ex: "alta proteína", "pelo menos 30g de proteína")
   - Carboidrato (ex: "baixo carb", "menos de 20g de carb")
   - Gordura (ex: "pouca gordura", "até 10g de gordura")
   - Ingredientes disponíveis (ex: "tenho frango, whey e banana")
   - Doce/salgado (ex: "quero algo doce")

2. **Pergunta preferências faltantes** (se a mensagem original não especificar):
   - "Qual período? Café, almoço, jantar ou lanche?"
   - "Tem limite de calorias?"
   - "Precisa de bastante proteína?"
   - "Tem algum ingrediente em casa?"
   - "Doce ou salgado?"

3. **Monta query SQL** combinando todos os filtros:
   - Usa `WHERE` para período, calorias, proteína, doce/salgado
   - Usa `JOIN` + `GROUP BY` + `HAVING` para ingredientes
   - Usa FTS5 para busca textual em nome/dicas

4. **Executa a query** contra o SQLite

5. **Formata a resposta**:
   - Até 5 receitas ordenadas por relevância (melhor match primeiro)
   - Cada receita mostra: nome, calorias, macros, tempo, rendimento
   - Lista ingredientes (opcional, colapsado)
   - **Sem imagem na listagem** (imagem enviada apenas sob demanda)
   - Pergunta se quer ver detalhes de alguma (incluindo imagem)
   - Se o usuário escolher, envia a imagem da receita selecionada

### 6.3 Formato de Resposta (Discord)

```
🍗 Encontrei 3 receitas que encaixam:

━━━━━━━━━━━━━━━━━━━━━━━━━
1. **Frango Grelhado com Legumes**
🔥 320 cal | 38g prot | 12g carb | 15g gor
⏱ 25 min | 2 porções | 🌶️ salgado
Ingredientes: peito de frango, brócolis, cenoura...

━━━━━━━━━━━━━━━━━━━━━━━━━
2. **Salada de Frango com Quinoa**
🔥 350 cal | 35g prot | 28g carb | 10g gor
⏱ 15 min | 1 porção | 🌶️ salgado
Ingredientes: frango desfiado, quinoa, tomate...

━━━━━━━━━━━━━━━━━━━━━━━━━
3. **Wrap de Frango Fit**
🔥 280 cal | 32g prot | 22g carb | 8g gor
⏱ 10 min | 1 porção | 🌶️ salgado
Ingredientes: tortilha integral, frango, alface...

━━━━━━━━━━━━━━━━━━━━━━━━━
Quer ver detalhes de alguma? Me diga o número (1, 2 ou 3) que eu monto a ficha completa com a imagem.
```

### 6.4 Comandos

| Comando | Descrição |
|---------|-----------|
| `hermes, me ajuda com uma receita` | Inicia fluxo de recomendação |
| `hermes, quero uma receita de [período]` | Filtra por período |
| `hermes, receita com [ingredientes]` | Busca por ingredientes |
| `hermes, receita doce/salgada` | Filtra por tipo |
| `hermes, quais períodos têm?` | Lista períodos disponíveis |
| `hermes, adicionar receita` | Adiciona nova receita (modo assistido) |
| `hermes, quantas receitas tem?` | Estatísticas da base |
| `hermes, detalhes da receita [N]` | Ver detalhes + imagem da receita N |

### 6.5 Tratamento de Erros

- **Sem resultados**: "Não encontrei nenhuma receita com esses critérios. Quer tentar outros filtros?"
- **Erro de DB**: "Opa, algo deu errado na consulta. Deixa eu tentar de novo."
- **Imagem não encontrada**: Mostra receita sem imagem, avisa que a imagem não está disponível

## 7. Testes

### 7.1 Testes de Unidade (SQLite)

```python
def test_busca_por_periodo():
    """Deve retornar receitas de café da manhã."""
    results = db.query("SELECT * FROM recipes WHERE periodo = 'café da manhã' LIMIT 3")
    assert len(results) >= 1
    assert all(r['periodo'] == 'café da manhã' for r in results)

def test_busca_por_calorias():
    """Deve retornar receitas com até 400 calorias."""
    results = db.query("SELECT * FROM recipes WHERE calorias <= 400 LIMIT 5")
    assert len(results) >= 1
    assert all(r['calorias'] <= 400 for r in results)

def test_busca_por_ingredientes():
    """Deve retornar receitas que contêm frango."""
    results = db.query_por_ingredientes(['frango'])
    assert len(results) >= 1

def test_busca_combinada():
    """Deve combinar período + calorias + proteína."""
    results = db.query_combinada(
        periodo='almoço', max_calorias=400, min_proteina=30
    )
    assert len(results) >= 1

def test_busca_sem_resultados():
    """Deve retornar lista vazia para critérios impossíveis."""
    results = db.query("SELECT * FROM recipes WHERE calorias < 0")
    assert len(results) == 0
```

### 7.2 Testes de Integração

```python
def test_skill_fluxo_completo():
    """Simula um pedido no Discord e verifica a resposta."""
    mensagem = "hermes, me ajuda com uma receita de almoço com frango"
    resposta = skill.processar(mensagem)
    assert len(resposta.receitas) <= 5
    assert all(r.tem_imagem() for r in resposta.receitas)

def test_skill_pergunta_preferencias():
    """Se não houver filtros, deve perguntar."""
    mensagem = "hermes, me ajuda com uma receita"
    resposta = skill.processar(mensagem)
    assert resposta.precisa_perguntar()
    assert 'período' in resposta.perguntas
```

## 8. Estrutura de Arquivos

```
~/.hermes/projects/receitas/
├── docs/
│   ├── PRD.md
│   └── TDD.md                        ← este documento
├── db/
│   ├── schema.sql                    ← Schema SQLite
│   ├── receitas.db                   ← Database (quando populado)
│   ├── batch_01.json ... batch_08.json
├── assets/
│   ├── receita_0001.jpeg ... receita_0394.jpeg
├── scripts/
│   ├── batch_extract.py              ← Extração via Claude Sonnet
│   ├── consolidate.py                ← Batch JSON → SQLite
│   └── search_test.py                ← Testes de query
└── skill/
    └── software-development/
        └── hermes-receitas/
            └── SKILL.md              ← Skill do Hermes
```

## 9. Critérios de Aceite

- [ ] SQLite populado com 365 receitas (páginas 23-394, menos páginas não-receita)
- [ ] Imagens de todas as receitas disponíveis em assets/
- [ ] Skill hermes-receitas responde no Discord
- [ ] Busca por período funciona
- [ ] Busca por calorias funciona
- [ ] Busca por proteína funciona
- [ ] Busca por ingredientes funciona
- [ ] Busca combinada funciona
- [ ] Pergunta preferências quando não especificadas
- [ ] Máximo 5 resultados por consulta
- [ ] Imagens anexadas nas respostas
- [ ] Custo total de extração < $8,00
- [ ] Tempo de resposta no Discord < 10s

---

**Próximos passos:**
1. Revisão do TDD + PRD pelo perfil **planner**
2. Ajustes conforme feedback
3. Execução da extração em batch
4. Criação da skill hermes-receitas
5. Testes e validação QA
6. Aceite final de Renan