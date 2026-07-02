# Project Orchestrator

Orquestador que conecta los agentes de José en un solo pipeline:

```
Idea (brief)
    ↓
Scoping Agent → docs pre-código + prompt Fase 1
    ↓
Coding Agent → código + tests + PR
    ↓
Reviewer Agent → revisión de calidad
    ↓
Writer Agent → docs post-código
    ↓
Entrega final organizada en 01-pre-codigo/ y 02-post-codigo/
```

## Requisitos

- Python 3.10+
- Agents instalados en `/root/project-scoping-agent` y `/root/coding-agent`
- Variables de entorno configuradas en cada agente (`.env`)

## Uso

```bash
python main.py \
  --brief "Quiero una app SaaS para peluquerías en Chile..." \
  --project /tmp/mi-proyecto \
  --output /tmp/mi-entrega
```

## Salida

```
/tmp/mi-entrega/
├── entrega/
│   ├── 00-index.md
│   ├── 01-pre-codigo/
│   │   ├── 01-executive-summary.md
│   │   ├── ...
│   │   └── 10-estimation.md
│   └── 02-post-codigo/
│       ├── 00-coding-report.md
│       └── ...
├── scoping/
├── phase1_prompt.txt
└── coding_result.json
```

## Próximos pasos

- [ ] Crear repo GitHub automáticamente desde el orchestrator
- [ ] Pipeline batch: ejecutar múltiples fases secuencialmente
- [ ] Aprobación humana entre fases
- [ ] Dashboard web para lanzar orquestaciones
