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


def test_build_coding_issue_includes_brief_stack_and_mvp(tmp_path):
    stack = tmp_path / "04-stack.md"
    stack.write_text("## Stack recomendado\nPython con FastAPI", encoding="utf-8")
    mvp = tmp_path / "06-mvp.md"
    mvp.write_text("## MVP\nCRUD de tareas", encoding="utf-8")
    scoping_info = {"documents": {"04-stack.md": stack, "06-mvp.md": mvp}}

    issue = main._build_coding_issue("Una API de tareas", scoping_info)

    assert "Brief: Una API de tareas" in issue
    assert "Python con FastAPI" in issue
    assert "CRUD de tareas" in issue
    assert "Implementa el MVP" in issue


def test_build_coding_issue_tolerates_missing_docs():
    issue = main._build_coding_issue("Solo brief", {"documents": {}})
    assert "Brief: Solo brief" in issue
    assert "Implementa el MVP" in issue


def test_validate_phase1_prompt_raises_on_empty():
    import pytest

    for empty in ("", "   ", "\n\t "):
        with pytest.raises(RuntimeError, match="phase1_prompt vacío"):
            main.validate_phase1_prompt(empty)


def test_validate_phase1_prompt_ok_when_present():
    # No debe lanzar
    main.validate_phase1_prompt("Crea el MVP con login")


def _fake_completed(returncode):
    import subprocess

    return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout="", stderr="")


def test_run_coding_agent_tolerates_soft_failure(tmp_path, monkeypatch):
    """exit != 0 pero con coding_result.json presente => entrega degradada, no crash."""
    result_file = tmp_path / "coding_result.json"
    result_file.write_text(json.dumps({"error": "Planner error: LLM vacío"}), encoding="utf-8")

    monkeypatch.setattr(main, "run_command", lambda *a, **k: _fake_completed(1))

    result = main.run_coding_agent("issue", tmp_path / "proj", tmp_path)
    assert result["error"] == "Planner error: LLM vacío"


def test_run_coding_agent_raises_on_hard_crash(tmp_path, monkeypatch):
    """exit != 0 y sin coding_result.json => crash duro, se aborta."""
    import pytest

    monkeypatch.setattr(main, "run_command", lambda *a, **k: _fake_completed(1))

    with pytest.raises(RuntimeError, match="sin producir resultado"):
        main.run_coding_agent("issue", tmp_path / "proj", tmp_path)


def test_run_coding_agent_success(tmp_path, monkeypatch):
    result_file = tmp_path / "coding_result.json"
    result_file.write_text(json.dumps({"test_result": {"summary": "PASS"}}), encoding="utf-8")

    monkeypatch.setattr(main, "run_command", lambda *a, **k: _fake_completed(0))

    result = main.run_coding_agent("issue", tmp_path / "proj", tmp_path)
    assert result["test_result"]["summary"] == "PASS"


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
