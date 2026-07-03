#!/usr/bin/env python3
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import main


def test_load_scoping_contract_reads_json(tmp_path):
    docs_dir = tmp_path
    (docs_dir / "scoping.json").write_text(
        json.dumps({"phase1_prompt": "Crea el MVP", "stack_hints": {"language": "python"}}),
        encoding="utf-8",
    )
    contract = main.load_scoping_contract(docs_dir)
    assert contract["phase1_prompt"] == "Crea el MVP"


def test_load_scoping_contract_missing_file_returns_none(tmp_path):
    assert main.load_scoping_contract(tmp_path) is None


def test_load_scoping_contract_corrupt_json_returns_none(tmp_path):
    (tmp_path / "scoping.json").write_text("{not valid json", encoding="utf-8")
    assert main.load_scoping_contract(tmp_path) is None


def test_extract_phase1_prompt_variants(tmp_path):
    variants = {
        "fase1.md": "## Prompt para Fase 1 (MVP)\nContenido A\n## Prompts para fases posteriores\nOtro",
        "fase1b.md": "## Fase 1: MVP\nContenido B\n## Fase 2\nOtro",
        "phase1.md": "## Phase 1\nContenido C\n## Consideraciones\nOtro",
        "mvp.md": "## MVP\nContenido D\n## Otra\nOtro",
    }
    for name, content in variants.items():
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        prompt = main.extract_phase1_prompt(path)
        assert "Contenido" in prompt


def test_scaffold_project_from_hints_fastapi(tmp_path):
    project_root = tmp_path / "my-api"
    project_root.mkdir()
    main.scaffold_project_from_hints(project_root, {"language": "python", "framework": "fastapi"})
    assert (project_root / "app" / "main.py").exists()
    assert 'name = "my-api"' in (project_root / "pyproject.toml").read_text(encoding="utf-8")


def test_scaffold_project_from_hints_express(tmp_path):
    project_root = tmp_path / "my-service"
    project_root.mkdir()
    main.scaffold_project_from_hints(project_root, {"language": "node", "framework": "express"})
    assert (project_root / "src" / "index.js").exists()
    assert '"name": "my-service"' in (project_root / "package.json").read_text(encoding="utf-8")


def test_scaffold_project_from_hints_unknown_does_nothing(tmp_path):
    project_root = tmp_path / "unknown"
    project_root.mkdir()
    main.scaffold_project_from_hints(project_root, {"language": "rust", "framework": None})
    assert not (project_root / "pyproject.toml").exists()
    assert not (project_root / "package.json").exists()


def test_slugify_project_name():
    assert main._slugify("Mi Proyecto Genial!") == "mi-proyecto-genial"
    assert main._slugify("") == "project"


def test_scaffold_project_detects_fastapi_only_in_recommended_section(tmp_path):
    project_root = tmp_path / "app"
    project_root.mkdir()
    stack_doc = (
        "## Stack recomendado\n### Backend\nPython con Django\n"
        "## Alternativas descartadas\nSe consideró FastAPI con Express."
    )
    main.scaffold_project(project_root, stack_doc)
    # No debe scaffoldear FastAPI ni Express: la mención está fuera de la sección recomendada
    assert not (project_root / "pyproject.toml").exists()
    assert not (project_root / "package.json").exists()
