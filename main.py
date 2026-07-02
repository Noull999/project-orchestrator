#!/usr/bin/env python3
"""
Project Orchestrator.

Pipeline completo:
  Idea (brief) → Scoping Agent → Coding Agent → Reviewer + Writer → Docs finales

Uso:
  python main.py --brief "Quiero una app de..." --project /tmp/mi-proyecto --output /tmp/entrega
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCOPING_AGENT_PATH = os.environ.get("SCOPING_AGENT_PATH", "/root/project-scoping-agent")
CODING_AGENT_PATH = os.environ.get("CODING_AGENT_PATH", "/root/coding-agent")
SCOPING_AGENT = Path(SCOPING_AGENT_PATH)
CODING_AGENT = Path(CODING_AGENT_PATH)


def validate_agent_paths() -> None:
    """Verifica que las rutas configuradas para los agentes existan."""
    missing = []
    for name, path in (
        ("SCOPING_AGENT_PATH", SCOPING_AGENT),
        ("CODING_AGENT_PATH", CODING_AGENT),
    ):
        if not path.exists():
            missing.append((name, path))
    if missing:
        lines = "\n".join(f"  - {name}={path} no existe" for name, path in missing)
        raise FileNotFoundError(f"Rutas de agentes no encontradas:\n{lines}")


def run_command(cmd: list, cwd: Path = None, timeout: int = 600) -> subprocess.CompletedProcess:
    """Ejecuta un comando y retorna el resultado."""
    print(f"  [cmd] {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_scoping_agent(brief: str, output_dir: Path) -> dict:
    """Ejecuta el Scoping Agent y retorna info de los documentos generados."""
    print("\n[orchestrator] 1/4 Ejecutando Scoping Agent...")
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(SCOPING_AGENT / "main.py"),
        "--brief", brief,
        "--output", str(output_dir / "scoping"),
    ]
    result = run_command(cmd, cwd=SCOPING_AGENT, timeout=900)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"Scoping Agent falló: {result.returncode}")

    docs_dir = output_dir / "scoping"
    docs = {f.name: f for f in docs_dir.glob("*.md")}
    return {
        "docs_dir": docs_dir,
        "documents": docs,
    }


def extract_phase1_prompt(prompts_path: Path) -> str:
    """Extrae el prompt de la Fase 1 (MVP) desde 07-prompts.md."""
    print("\n[orchestrator] 2/4 Extrayendo prompt de Fase 1...")
    content = prompts_path.read_text(encoding="utf-8")

    # Busca variantes del heading de la Fase 1: "Fase 1", "Phase 1", "MVP", etc.
    match = re.search(
        r"^(?:##\s*(?:Prompt\s+(?:para\s+)?)?(?:Fase|Phase)\s*1|##\s*MVP)\b.*?\n"
        r"(.*?)(?=^##|\Z)",
        content,
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    if match:
        prompt = match.group(1).strip()
    else:
        # Fallback: toma todo desde la primera sección ## Prompt
        match = re.search(
            r"^##\s*Prompt.*?\n(.*)",
            content,
            re.DOTALL | re.IGNORECASE | re.MULTILINE,
        )
        if match:
            prompt = match.group(1).strip()
            print("  [WARN] No se detectó heading de Fase 1; se usó la primera sección ## Prompt")
        else:
            prompt = content.strip()
            print("  [WARN] No se detectó heading de Fase 1 ni sección ## Prompt; se usa el documento completo")

    # Limpia bloques de código markdown si los hay
    prompt = re.sub(r"```markdown\n?|```\n?", "", prompt).strip()

    print(f"  [orchestrator] Prompt extraído: {len(prompt)} chars")
    return prompt


def prepare_project(project_root: Path) -> None:
    """Asegura que exista un directorio de proyecto válido."""
    print(f"\n[orchestrator] Preparando proyecto en {project_root}...")
    project_root.mkdir(parents=True, exist_ok=True)

    # Si está vacío, inicializa un repo git básico
    if not (project_root / ".git").exists():
        run_command(["git", "init"], cwd=project_root)
        run_command(["git", "config", "user.email", "agent@example.com"], cwd=project_root)
        run_command(["git", "config", "user.name", "Project Orchestrator"], cwd=project_root)

    # Commit inicial si no hay commits
    result = run_command(["git", "log", "--oneline", "-1"], cwd=project_root)
    if result.returncode != 0 or not result.stdout.strip():
        readme = project_root / "README.md"
        readme.write_text("# Proyecto generado por Project Orchestrator\n", encoding="utf-8")
        run_command(["git", "add", "-A"], cwd=project_root)
        run_command(["git", "commit", "-m", "Initial commit"], cwd=project_root)


def scaffold_project(project_root: Path, stack_doc: str) -> None:
    """Crea un scaffold mínimo según el stack detectado para ayudar al Coding Agent."""
    print("\n[orchestrator] Creando scaffold inicial según stack...")
    lower = stack_doc.lower()

    is_fastapi = "fastapi" in lower and "python" in lower
    is_express = "express" in lower and "node" in lower

    if is_fastapi:
        _scaffold_fastapi(project_root)
    elif is_express:
        _scaffold_express(project_root)
    else:
        print("  [orchestrator] no hay scaffold predefinido para este stack, se deja al Coding Agent")


def _scaffold_fastapi(project_root: Path) -> None:
    """Crea scaffold mínimo para FastAPI."""
    files = {
        "pyproject.toml": """[project]
name = "task-api"
version = "0.1.0"
description = "API generada por Project Orchestrator"
requires-python = ">=3.11"
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "sqlalchemy>=2.0",
    "pydantic-settings",
    "alembic",
]

[project.optional-dependencies]
dev = ["pytest", "httpx", "pytest-cov"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""",
        "app/__init__.py": "",
        "app/main.py": """from fastapi import FastAPI

app = FastAPI(title="Task API")

@app.get("/health")
def health_check():
    return {"status": "ok"}
""",
        "tests/__init__.py": "",
        "tests/test_health.py": """from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
""",
    }
    for path, content in files.items():
        full = project_root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")

    run_command(["git", "add", "-A"], cwd=project_root)
    run_command(["git", "commit", "-m", "scaffold: estructura base FastAPI"], cwd=project_root)
    print("  [orchestrator] scaffold FastAPI creado")


def _scaffold_express(project_root: Path) -> None:
    """Crea scaffold mínimo para Express/Node.js."""
    files = {
        "package.json": """{
  "name": "task-api",
  "version": "0.1.0",
  "description": "API generada por Project Orchestrator",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js",
    "test": "jest"
  },
  "dependencies": {
    "express": "^4.18.0"
  },
  "devDependencies": {
    "jest": "^29.0.0",
    "supertest": "^6.3.0"
  }
}""",
        "src/index.js": """const express = require('express');
const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server on port ${PORT}`));

module.exports = app;
""",
        "tests/health.test.js": """const request = require('supertest');
const app = require('../src/index');

describe('GET /health', () => {
  it('should return ok', async () => {
    const res = await request(app).get('/health');
    expect(res.statusCode).toBe(200);
    expect(res.body).toEqual({ status: 'ok' });
  });
});
""",
    }
    for path, content in files.items():
        full = project_root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")

    run_command(["git", "add", "-A"], cwd=project_root)
    run_command(["git", "commit", "-m", "scaffold: estructura base Express"], cwd=project_root)
    print("  [orchestrator] scaffold Express creado")


def run_coding_agent(issue: str, project_root: Path, output_dir: Path) -> dict:
    """Ejecuta el Coding Agent sobre el proyecto."""
    print("\n[orchestrator] 3/4 Ejecutando Coding Agent...")

    result_file = output_dir / "coding_result.json"

    cmd = [
        sys.executable,
        str(CODING_AGENT / "graph.py"),
        str(project_root),
        "--issue", issue,
        "--output", str(result_file),
        "--skip-pr",
    ]
    result = run_command(cmd, cwd=CODING_AGENT, timeout=1800)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"Coding Agent falló: {result.returncode}")

    coding_result = json.loads(result_file.read_text(encoding="utf-8"))

    return coding_result


def collect_outputs(
    output_dir: Path,
    scoping_info: dict,
    coding_result: dict,
    project_root: Path,
) -> Path:
    """Junta todos los documentos en la carpeta final de entrega."""
    print("\n[orchestrator] 4/4 Recolectando documentos finales...")

    final_dir = output_dir / "entrega"
    final_dir.mkdir(parents=True, exist_ok=True)

    pre_dir = final_dir / "01-pre-codigo"
    pre_dir.mkdir(exist_ok=True)
    for name, path in scoping_info["documents"].items():
        shutil.copy(path, pre_dir / name)

    post_dir = final_dir / "02-post-codigo"
    post_dir.mkdir(exist_ok=True)

    # Documentos generados por el Coding Agent (delivery docs)
    delivery_docs_dir = project_root / ".delivery-docs"
    if delivery_docs_dir.exists():
        for f in delivery_docs_dir.glob("*.md"):
            shutil.copy(f, post_dir / f.name)

    # Reporte del coding agent (nuevo nombre: coding_result.md)
    coding_report = output_dir / "coding_result.md"
    if coding_report.exists():
        shutil.copy(coding_report, post_dir / "00-coding-report.md")

    # Resultado JSON del coding agent
    coding_json = output_dir / "coding_result.json"
    if coding_json.exists():
        shutil.copy(coding_json, post_dir / "01-coding-result.json")

    # Index final
    index = build_index(final_dir, scoping_info, coding_result)
    (final_dir / "00-index.md").write_text(index, encoding="utf-8")

    return final_dir


def build_index(final_dir: Path, scoping_info: dict, coding_result: dict) -> str:
    """Genera un índice de todos los documentos entregados."""
    pre_files = sorted((final_dir / "01-pre-codigo").glob("*.md"))
    post_files = sorted((final_dir / "02-post-codigo").glob("*.md"))

    lines = [
        "# Índice de Entrega del Proyecto",
        "",
        f"**Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 1. Documentos pre-código (Scoping Agent)",
        "",
    ]
    for f in pre_files:
        lines.append(f"- [{f.name}](01-pre-codigo/{f.name})")

    lines.extend(["", "## 2. Documentos post-código (Coding Agent)", ""])
    for f in post_files:
        lines.append(f"- [{f.name}](02-post-codigo/{f.name})")

    test = coding_result.get("test_result", {})
    review = coding_result.get("review_result", {})
    git = coding_result.get("git_result", {})

    lines.extend(["", "## 3. Resumen de ejecución", ""])
    lines.append(f"- **Tests:** {test.get('summary', 'N/A')}")
    lines.append(f"- **Revisión:** {review.get('verdict', 'N/A')}")
    lines.append(f"- **PR:** {git.get('pr_url', 'No creado (skip_pr)')}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Project Orchestrator")
    parser.add_argument("--brief", "-b", required=True, help="Descripción de la idea/proyecto")
    parser.add_argument("--project", "-p", required=True, help="Carpeta del proyecto a crear/usar")
    parser.add_argument("--output", "-o", default="/tmp/orchestrator-output", help="Carpeta de salida")
    args = parser.parse_args()

    output_dir = Path(args.output)
    project_root = Path(args.project).expanduser().resolve()

    validate_agent_paths()
    prepare_project(project_root)

    # 1. Scoping
    scoping_info = run_scoping_agent(args.brief, output_dir)

    # 2. Extraer prompt de Fase 1
    prompts_path = scoping_info["docs_dir"] / "07-prompts.md"
    phase1_prompt = extract_phase1_prompt(prompts_path)

    # Guardar el prompt que se le pasará al Coding Agent
    (output_dir / "phase1_prompt.txt").write_text(phase1_prompt, encoding="utf-8")

    # 2.5 Crear scaffold según stack recomendado
    stack_doc = scoping_info["documents"].get("04-stack.md")
    if stack_doc:
        scaffold_project(project_root, stack_doc.read_text(encoding="utf-8"))

    # 3. Coding Agent
    coding_result = run_coding_agent(phase1_prompt, project_root, output_dir)

    # 4. Recolectar entrega
    final_dir = collect_outputs(output_dir, scoping_info, coding_result, project_root)

    print(f"\n✓ Entrega completa en: {final_dir}")
    print(f"  - Pre-código: {final_dir / '01-pre-codigo'}")
    print(f"  - Post-código: {final_dir / '02-post-codigo'}")
    print(f"  - Índice: {final_dir / '00-index.md'}")

    test = coding_result.get("test_result", {})
    print(f"\nResumen: tests={test.get('summary', 'N/A')}")


if __name__ == "__main__":
    main()
