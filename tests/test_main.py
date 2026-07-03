#!/usr/bin/env python3
import importlib
import json
import sys
from pathlib import Path

import pytest

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


def test_scaffold_project_detects_fastapi_in_recommended_section(tmp_path):
    project_root = tmp_path / "api"
    project_root.mkdir()
    stack_doc = "## Stack recomendado\n### Backend\nPython con FastAPI\n"
    main.scaffold_project(project_root, stack_doc)
    assert (project_root / "pyproject.toml").exists()
    assert "fastapi" in (project_root / "pyproject.toml").read_text(encoding="utf-8").lower()


def test_scaffold_project_detects_express_in_recommended_section(tmp_path):
    project_root = tmp_path / "service"
    project_root.mkdir()
    stack_doc = "## Stack recomendado\n### Backend\nNode.js con Express\n"
    main.scaffold_project(project_root, stack_doc)
    assert (project_root / "package.json").exists()
    assert '"express"' in (project_root / "package.json").read_text(encoding="utf-8")


def test_extract_phase1_prompt_fallback_to_full_document(capsys, tmp_path):
    content = "Sin headings conocidos\n\nEste es el contenido completo."
    path = tmp_path / "prompts.md"
    path.write_text(content, encoding="utf-8")
    prompt = main.extract_phase1_prompt(path)
    assert prompt == content.strip()
    captured = capsys.readouterr()
    assert "No se detectó heading de Fase 1" in captured.out


def test_load_existing_scoping_reuses_md_files(tmp_path):
    docs_dir = tmp_path / "scoping"
    docs_dir.mkdir()
    (docs_dir / "07-prompts.md").write_text("## Prompt Fase 1\nHola", encoding="utf-8")
    (docs_dir / "04-stack.md").write_text("## Stack\nPython", encoding="utf-8")
    result = main.load_existing_scoping(tmp_path)
    assert result is not None
    assert result["docs_dir"] == docs_dir
    assert "07-prompts.md" in result["documents"]
    assert "04-stack.md" in result["documents"]


def test_load_existing_scoping_missing_07_prompts_regenerates(tmp_path):
    docs_dir = tmp_path / "scoping"
    docs_dir.mkdir()
    (docs_dir / "04-stack.md").write_text("## Stack\nPython", encoding="utf-8")
    assert main.load_existing_scoping(tmp_path) is None


def test_validate_agent_paths_missing_paths_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("SCOPING_AGENT_PATH", str(tmp_path / "no-existe-scoping"))
    monkeypatch.setenv("CODING_AGENT_PATH", str(tmp_path / "no-existe-coding"))
    importlib.reload(main)
    with pytest.raises(FileNotFoundError) as exc_info:
        main.validate_agent_paths()
    error_text = str(exc_info.value)
    assert "SCOPING_AGENT_PATH" in error_text
    assert "CODING_AGENT_PATH" in error_text
    assert "no existe" in error_text


def test_env_paths_override_defaults(monkeypatch, tmp_path):
    scoping_dir = tmp_path / "custom-scoping"
    coding_dir = tmp_path / "custom-coding"
    scoping_dir.mkdir()
    coding_dir.mkdir()
    monkeypatch.setenv("SCOPING_AGENT_PATH", str(scoping_dir))
    monkeypatch.setenv("CODING_AGENT_PATH", str(coding_dir))
    importlib.reload(main)
    assert main.SCOPING_AGENT == scoping_dir
    assert main.CODING_AGENT == coding_dir


def test_force_scoping_regenerates_even_when_existing(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    project_root = tmp_path / "project"
    output_dir.mkdir()
    project_root.mkdir()

    existing_docs_dir = output_dir / "scoping"
    existing_docs_dir.mkdir()
    (existing_docs_dir / "07-prompts.md").write_text("## Prompt Fase 1\nViejo", encoding="utf-8")

    run_scoping_calls = []

    def fake_run_scoping_agent(brief, output_dir):
        run_scoping_calls.append((brief, output_dir))
        docs_dir = output_dir / "scoping"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "07-prompts.md").write_text("## Prompt Fase 1\nNuevo", encoding="utf-8")
        return {
            "docs_dir": docs_dir,
            "documents": {"07-prompts.md": docs_dir / "07-prompts.md"},
            "contract": None,
        }

    monkeypatch.setattr(main, "validate_agent_paths", lambda: None)
    monkeypatch.setattr(main, "prepare_project", lambda project_root: None)
    monkeypatch.setattr(main, "run_scoping_agent", fake_run_scoping_agent)
    monkeypatch.setattr(main, "extract_phase1_prompt", lambda path: "prompt")
    monkeypatch.setattr(main, "scaffold_project", lambda project_root, stack_doc: None)
    monkeypatch.setattr(
        main,
        "run_coding_agent",
        lambda issue, project_root, output_dir: {
            "test_result": {},
            "review_result": {},
            "git_result": {},
        },
    )
    monkeypatch.setattr(
        main,
        "collect_outputs",
        lambda output_dir, scoping_info, coding_result, project_root: output_dir / "entrega",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--brief",
            "una app",
            "--project",
            str(project_root),
            "--output",
            str(output_dir),
            "--force-scoping",
        ],
    )
    main.main()
    assert len(run_scoping_calls) == 1
