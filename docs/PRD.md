# PRD — Sistema de Receitas Hermes

> **Product Requirements Document**
> Versão: 1.0
> Autor: Hermes (default profile)
> Data: 2026-07-02

---

## 1. Visão Geral

Sistema para gerenciar e consultar receitas culinárias diretamente pelo chat do Discord. Hermes mantém uma base própria de receitas (seed via PDFs, expansível), e quando Renan ou Kassia pedem ajuda com uma receita, Hermes pergunta sobre preferências (se não ditas), consulta a base, e sugere até 5 receitas com imagem do prato final.

## 2. Objetivos

- **Primary**: Permitir que Renan e Kassia encontrem receitas rapidamente pelo Discord, filtrando por calorias, macros, ingredientes disponíveis, período do dia e tipo (doce/salgado).
- **Secondary**: Manter uma base de receitas que cresce com o tempo, sem depender de serviços externos.

## 3. Stack Tecnológica

| Componente | Escolha | Motivo |
|------------|---------|--------|
| **Storage** | SQLite (`.db` file) | Zero config, portátil, FTS5, ideal para 300+ receitas com dados relacionais |
| **Processamento PDF** | Python + PyMuPDF (fitz) + pdf2image | Split por página, extração de texto e imagens |
| **Assets** | PNG/JPG em disco (~/.hermes/projects/receitas/assets/) | Imagens servidas como attachment no Discord via gateway |
| **Delivery** | Hermes Gateway (Discord nativo) | Anexo de arquivos direto, sem servidor extra |
| **Busca** | SQLite JSON + FTS5 + queries parametrizadas | Filtros combinados (calorias, macros, ingredientes) |
| **Orquestração** | Hermes Kanban + perfis multi-agent | Ciclo planner → executor → QA → sponsor |

## 4. Arquitetura do Sistema

```
~/.hermes/projects/receitas/
├── docs/
│   ├── PRD.md              ← este documento
│   ├── TDD.md              ← especificação técnica (próxima fase)
│   └── plans/              ← plans de implementação
├── db/
│   └── receitas.db         ← SQLite database
├── assets/                 ← Imagens convertidas por página
│   ├── receita_001.png
│   ├── receita_002.png
│   └── ...
├── pdf-pages/              ← PDFs individuais (opcional, intermediário)
│   ├── pagina_001.pdf
│   ├── pagina_002.pdf
│   └── ...
├── scripts/
│   ├── extract_pdf.py      ← Split + extração de dados + imagens
│   ├── init_db.py          ← Schema SQLite
│   └── seed_db.py          ← Popula DB a partir da extração
└── skill/
    └── hermes-receitas/    ← Skill do Hermes para consulta
        └── SKILL.md
```

### Fluxo de Dados

```
PDF original (394 pág)
    │
    ▼
[1. Split por página] → ~394 PDFs em pdf-pages/
    │
    ▼
[2. Extração] → PyMuPDF extrai texto estruturado + pdf2image converte página pra PNG
    │
    ▼
[3. Popula DB] → SQLite com todas as receitas + path da imagem
    │
    ▼
[4. Skill Hermes] → Skill hermes-receitas com lógica de consulta
    │
    ▼
[5. Discord] → Usuário pergunta → skill consulta DB → até 5 sugestões + imagens
```

## 5. Modelo de Dados

### Tabela: `recipes`

| Campo | Tipo | Descrição | Obrigatório |
|-------|------|-----------|-------------|
| `id` | INTEGER PK | Auto-increment | ✓ |
| `nome` | TEXT | Nome da receita | ✓ |
| `periodo` | TEXT | café da manhã, almoço, jantar, lanche | |
| `calorias` | INTEGER | Calorias totais | |
| `proteina_g` | REAL | Proteína em gramas | |
| `carboidrato_g` | REAL | Carboidratos em gramas | |
| `gordura_g` | REAL | Gorduras em gramas | |
| `fibras_g` | REAL | Fibras em gramas | |
| `tempo_preparo_min` | INTEGER | Tempo de preparo em minutos | |
| `rendimento` | TEXT | Porções/rendimento (ex: "4 porções") | |
| `dicas` | TEXT | Anotações/dicas do rodapé | |
| `doce_salgado` | TEXT | "doce", "salgado" ou NULL | |
| `image_path` | TEXT | Caminho relativo em assets/ | |
| `pdf_source` | TEXT | Página de origem (ex: "pagina_042.pdf") | |
| `created_at` | TEXT | ISO timestamp | ✓ |

### Tabela: `ingredients`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | INTEGER PK | Auto-increment |
| `nome` | TEXT | Nome do ingrediente (ex: "farinha de trigo") |
| `unidade` | TEXT | Unidade de medida (g, ml, xícara, colher, unidade) |

### Tabela: `recipe_ingredients`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `recipe_id` | INTEGER FK → recipes.id | |
| `ingredient_id` | INTEGER FK → ingredients.id | |
| `quantidade` | REAL | Quantidade numérica |
| `unidade` | TEXT | Unidade específica na receita |

### Índices

- `idx_recipes_periodo` ON `recipes(periodo)`
- `idx_recipes_calorias` ON `recipes(calorias)`
- `idx_recipes_proteina` ON `recipes(proteina_g)`
- `idx_recipes_doce_salgado` ON `recipes(doce_salgado)`
- FTS5 virtual table: `recipes_fts` ON `recipes(nome, dicas)`

## 6. Requisitos Funcionais

### RF01 — Consulta por preferências
**Descrição**: Quando o usuário pede ajuda com receita, Hermes pergunta preferências (período, calorias, proteína, ingredientes, doce/salgado) se não foram informadas na mensagem original.
**Critério de aceite**: Se a mensagem já contiver filtros (ex: "receita com frango, até 400 cal"), Hermes NÃO pergunta de novo.

### RF02 — Busca combinada
**Descrição**: Hermes consulta o SQLite com os filtros informados e retorna até 5 receitas correspondentes.
**Critério de aceite**:
- Filtro por período (`WHERE periodo = 'almoço'`)
- Filtro por calorias (`WHERE calorias <= N`)
- Filtro por proteína (`WHERE proteina_g >= N`)
- Filtro por ingredientes (`JOIN recipe_ingredients + ingredients`)
- Filtro por doce/salgado
- Combinação de qualquer um dos acima

### RF03 — Sugestão com imagem
**Descrição**: Cada sugestão inclui o nome, dados nutricionais, ingredientes, e a imagem do prato final (anexada ao Discord).
**Critério de aceite**: Imagem aparece como attachment na mensagem do Discord.

### RF04 — Adicionar receita
**Descrição**: Renan pode adicionar novas receitas à base via comando ou enviando novos PDFs.
**Critério de aceite**: Comando `hermes receita add` com dados estruturados, ou envio de PDF adicional que passa pelo pipeline de extração.

### RF05 — Listar categorias/períodos
**Descrição**: Hermes pode listar todos os períodos disponíveis para ajudar na escolha.
**Critério de aceite**: Comando tipo "quais períodos têm disponíveis?" retorna lista única.

## 7. Requisitos Não-Funcionais

| ID | Requisito | Métrica |
|----|-----------|---------|
| RNF01 | A consulta ao DB e resposta não deve levar mais que 5s | Tempo de resposta |
| RNF02 | A extração inicial do PDF é feita uma vez, em lote | Processamento único |
| RNF03 | Imagens devem ocupar no máximo 2MB cada (compressão) | Tamanho do arquivo |
| RNF04 | O DB deve ser versionável e facilmente recriável | Scripts de seed |
| RNF05 | A skill hermes-receitas deve ser autocontida | Sem dependências externas |

## 8. Pipeline de Extração (PDF → DB)

### Fase 1: Split
- Ferramenta: `pdfseparate` (poppler-utils) ou PyMuPDF
- Input: PDF original (394 páginas)
- Output: 394 PDFs em `pdf-pages/pagina_{NNN}.pdf`

### Fase 2: Extração de texto
- Ferramenta: PyMuPDF (`fitz`)
- Extrair por página: nome, ingredientes, calorias, macros, tempo, rendimento, dicas
- Ignorar: menções a @santiagopaesphd, cabeçalhos/rodapés genéricos
- Output: JSON estruturado por página

### Fase 3: Conversão para imagem
- Ferramenta: `pdf2image` (poppler)
- Cada página → PNG em `assets/receita_{NNN}.png`
- Resolução mínima: 300 DPI
- Compressão otimizada (max 2MB)

### Fase 4: População do DB
- Inserir dados extraídos no SQLite
- Vincular `image_path` ao asset gerado
- Validar integridade (sem duplicatas, nomes consistentes)

## 9. Skill Hermes — hermes-receitas

A skill `hermes-receitas` será a interface entre o usuário e o sistema. Ela:

1. **Intercepta** mensagens no Discord sobre receitas
2. **Pergunta** preferências se não informadas (RF01)
3. **Monta query SQL** com base nos filtros
4. **Executa** contra o SQLite
5. **Formata** resposta com dados + imagens (RF03)
6. **Oferece** opção de ver outra, refinar busca, ou adicionar receita

### Exemplo de interação:

```
Kassia: Hermes, me ajuda com uma receita de almoço?

Hermes: Claro! Alguma preferência? 
- Limite de calorias?
- Proteína mínima?
- Ingredientes que tem em casa?
- Doce ou salgado?

Kassia: Até 400 calorias, bastante proteína, tenho frango

Hermes: Encontrei 3 receitas:
────────────────────────────────
🍗 1. Frango Grelhado com Legumes
   🔥 320 cal | 38g prot | 12g carb | 15g gordura
   ⏱ 25 min | 2 porções
   Ingredientes: peito de frango, brócolis, cenoura...
   [IMAGEM ANEXADA]

🥗 2. Salada de Frango com Quinoa
   🔥 350 cal | 35g prot | 28g carb | 10g gordura
   ⏱ 15 min | 1 porção
   Ingredientes: frango desfiado, quinoa, tomate...
   [IMAGEM ANEXADA]

[... até 5]

Quer ver alguma com mais detalhes? Ou refinar a busca?
```

## 10. Ciclo de Desenvolvimento (Multi-Agent)

```
┌──────────────────────────────────────────────────────┐
│                     FASE 1: PRD                       │
│  Hermes (default) escreve este documento             │
│  Planner revisa → APROVADO / REJEITADO / RESSALVAS  │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│                     FASE 2: TDD                       │
│  Hermes (default) escreve especificação técnica      │
│  + testes (TDD.md)                                   │
│  Planner revisa                                      │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│                     FASE 3: BUILD                     │
│  Executor implementa (task por task no Kanban)       │
│  QA valida cada entrega                              │
│  Hermes (default) sponsor review                     │
│  Renan → aceite final                                │
└──────────────────────────────────────────────────────┘
```

### Perfis:

| Perfil | Função | Modelo Sugerido |
|--------|--------|-----------------|
| **default** | Sponsor — escreve PRD/TDD, coordena, valida final | deepseek/deepseek-v4-flash |
| **planner** | Revisor — lê e critica documentos | modelo forte (claude sonnet) |
| **executor** | Implementador — código + testes | modelo rápido |
| **qa** | Validador — checa spec vs implementação | modelo forte |

## 11. Critérios de Sucesso

- [ ] Pipeline de extração processa 394 páginas sem erros
- [ ] DB populado com todas as receitas + imagens
- [ ] Skill hermes-receitas responde no Discord em <5s
- [ ] Renan e Kassia conseguem buscar receitas por calorias, proteína, ingredientes
- [ ] Imagens das receitas aparecem como attachments
- [ ] Nova receita pode ser adicionada via comando
- [ ] Ciclo multi-agent completo (PRD → build → aceite)

## 12. Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|:------------:|:-------:|-----------|
| PDF com estrutura inconsistente | Média | Alto | Fallback: página vira imagem + OCR |
| Extração de dados falha em algumas páginas | Média | Médio | Log por página, retentativa manual |
| Imagens muito grandes (>2MB) | Baixa | Médio | Compressão automática no pipeline |
| Skill muito verbosa no Discord | Baixa | Baixo | Limitar a 5 resultados, colapsar detalhes |

---

**Próximos passos:**
1. Revisão do PRD pelo perfil **planner**
2. Ajustes conforme feedback
3. Escrita do **TDD** (especificação técnica + testes)
4. Implementação via Kanban (executor + QA)
5. Aceite final de Renan