#!/usr/bin/env python3
import json

with open('db/batch_04.json') as f:
    data = json.load(f)

print(f'Total de receitas extraídas: {len(data)}')
erros = [r for r in data if r.get('error')]
skips = [r for r in data if r.get('skip')]
gemini = [r for r in data if r.get('_model','').startswith('google')]
print(f'Erros: {len(erros)}')
print(f'Skipped: {len(skips)}')
print(f'Fallbacks para Gemini: {len(gemini)}')
print()
print('3 exemplos de receitas:')
for r in data[:3]:
    print(f'  - {r.get("nome","?")} (pág {r.get("page","?")})')