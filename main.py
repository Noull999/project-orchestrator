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


def load_scoping_contract(docs_dir: Path) -> dict | None:
    """Carga el contrato estructurado scoping.json si el Scoping Agent lo generó.

    Trae phase1_prompt ya extraído y stack_hints (language/framework) sin
    necesidad de re-parsear el markdown con regex acá. Si no existe (versión
    vieja del Scoping Agent, o corrida manual sin este archivo), se retorna
    None y el llamador cae al fallback de parseo de markdown.
    """
    contract_path = docs_dir / "scoping.json"
    if not contract_path.exists():
        return None
    try:
        return json.loads(contract_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] No se pudo leer scoping.json ({e}), se usa fallback de markdown")
        return None


def load_existing_scoping(output_dir: Path) -> dict | None:
    """Reutiliza documentos de scoping previos si existen."""
    docs_dir = output_dir / "scoping"
    if not docs_dir.exists():
        return None
    docs = {f.name: f for f in docs_dir.glob("*.md")}
    if not docs:
        return None
    if "07-prompts.md" not in docs:
        print(f"\n[orchestrator] Scoping previo incompleto en {docs_dir} (falta 07-prompts.md), se regenera")
        return None
    print("\n[orchestrator] 1/4 Reutilizando documentos de scoping existentes...")
    print(f"  [orchestrator] {len(docs)} documentos encontrados en {docs_dir}")
    return {
        "docs_dir": docs_dir,
        "documents": docs,
        "contract": load_scoping_contract(docs_dir),
    }


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
        "contract": load_scoping_contract(docs_dir),
    }


def extract_phase1_prompt(prompts_path: Path) -> str:
    """Extrae el prompt de la Fase 1 (MVP) desde 07-prompts.md.

    Fallback de compatibilidad: se usa solo si el Scoping Agent no generó
    scoping.json (versión vieja, o el archivo se perdió/corrompió). Cuando
    existe scoping.json, main() usa directamente su campo phase1_prompt.
    """
    print("\n[orchestrator] 2/4 Extrayendo prompt de Fase 1 (fallback markdown)...")
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


def _slugify(name: str) -> str:
    """Convierte un nombre de proyecto en un slug válido para archivos."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-") or "project"


def scaffold_project_from_hints(project_root: Path, stack_hints: dict) -> None:
    """Crea el scaffold usando los hints estructurados de scoping.json (sin regex sobre markdown)."""
    print("\n[orchestrator] Creando scaffold inicial según stack (contrato scoping.json)...")
    language = stack_hints.get("language")
    framework = stack_hints.get("framework")
    project_name = _slugify(project_root.name)

    if language == "python" and framework == "fastapi":
        _scaffold_fastapi(project_root, project_name)
    elif language == "node" and framework == "express":
        _scaffold_express(project_root, project_name)
    else:
        print(f"  [orchestrator] no hay scaffold predefinido para {language}/{framework}, se deja al Coding Agent")


def scaffold_project(project_root: Path, stack_doc: str) -> None:
    """Crea un scaffold mínimo según el stack detectado para ayudar al Coding Agent.

    Fallback de compatibilidad: se usa solo si scoping.json no trae stack_hints
    (versión vieja del Scoping Agent). Cuando hay hints, se usa
    scaffold_project_from_hints en su lugar.
    """
    print("\n[orchestrator] Creando scaffold inicial según stack (fallback markdown)...")

    # Busca 'fastapi'/'express' solo dentro de la sección recomendada para evitar falsos positivos
    section_match = re.search(
        r"^##\s*Stack recomendado\s*\n(.*?)\n(?=^##|\Z)",
        stack_doc,
        re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    search_area = section_match.group(1) if section_match else stack_doc
    lower = search_area.lower()

    is_fastapi = "fastapi" in lower and "python" in lower
    is_express = "express" in lower and "node" in lower

    project_name = _slugify(project_root.name)

    if is_fastapi:
        _scaffold_fastapi(project_root, project_name)
    elif is_express:
        _scaffold_express(project_root, project_name)
    else:
        print("  [orchestrator] no hay scaffold predefinido para este stack, se deja al Coding Agent")


def _scaffold_fastapi(project_root: Path, project_name: str) -> None:
    """Crea scaffold mínimo para FastAPI."""
    files = {
        "pyproject.toml": f"""[project]
name = "{project_name}"
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
        "app/main.py": f"""from fastapi import FastAPI

app = FastAPI(title="{project_name}")

@app.get("/health")
def health_check():
    return {{"status": "ok"}}
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


def _scaffold_express(project_root: Path, project_name: str) -> None:
    """Crea scaffold mínimo para Express/Node.js."""
    files = {
        "package.json": f"""{{
  "name": "{project_name}",
  "version": "0.1.0",
  "description": "API generada por Project Orchestrator",
  "main": "src/index.js",
  "scripts": {{
    "start": "node src/index.js",
    "test": "jest"
  }},
  "dependencies": {{
    "express": "^4.18.0"
  }},
  "devDependencies": {{
    "jest": "^29.0.0",
    "supertest": "^6.3.0"
  }}
}}""",
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


def validate_phase1_prompt(phase1_prompt: str) -> None:
    """Aborta si el prompt de Fase 1 está vacío.

    El Scoping Agent puede degradar prompt_engineer a vacío si el LLM falla; en
    ese caso invocar al Coding Agent con una instrucción vacía solo generaría
    código basura, así que se corta acá con un mensaje accionable.
    """
    if not phase1_prompt.strip():
        raise RuntimeError(
            "El Scoping Agent no produjo un prompt de Fase 1 utilizable "
            "(phase1_prompt vacío). Se aborta antes de invocar al Coding Agent. "
            "Revisá 07-prompts.md y el log del Scoping Agent."
        )


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
        # El Coding Agent sale con código != 0 cuando un nodo reportó error.
        # Si alcanzó a escribir coding_result.json es un fallo "blando" (entrega
        # degradada, con el error ya documentado en el resultado): se continúa
        # para armar la entrega igual. Si ni siquiera generó el archivo, es un
        # crash duro y se aborta.
        if not result_file.exists():
            print(result.stderr)
            raise RuntimeError(
                f"Coding Agent falló sin producir resultado ({result.returncode})"
            )
        print(
            f"  [WARN] Coding Agent terminó con código {result.returncode}; "
            "se continúa con la entrega degradada (ver coding_result.json)"
        )

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
    parser.add_argument(
        "--force-scoping",
        action="store_true",
        help="Regenerar los documentos de scoping aunque ya existan",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    project_root = Path(args.project).expanduser().resolve()

    validate_agent_paths()
    prepare_project(project_root)

    # 1. Scoping (reutiliza si ya existe, salvo que se pida forzar)
    scoping_info = None if args.force_scoping else load_existing_scoping(output_dir)
    if scoping_info is None:
        scoping_info = run_scoping_agent(args.brief, output_dir)

    # 2. Obtener prompt de Fase 1: preferir el contrato estructurado scoping.json;
    #    si no existe, caer al parseo por regex del markdown (ver extract_phase1_prompt).
    contract = scoping_info.get("contract")
    if contract and contract.get("phase1_prompt"):
        print("\n[orchestrator] 2/4 Usando phase1_prompt del contrato scoping.json")
        phase1_prompt = contract["phase1_prompt"]
    else:
        prompts_path = scoping_info["docs_dir"] / "07-prompts.md"
        phase1_prompt = extract_phase1_prompt(prompts_path)

    # Fallback robusto: si el Scoping Agent deja phase1_prompt vacío (por ejemplo,
    # porque el LLM del prompt_engineer no respondió), armamos un prompt útil
    # a partir del MVP y el stack, que son los documentos más relevantes.
    if not phase1_prompt.strip():
        print("\n[orchestrator] 2/4 phase1_prompt vacío; construyendo fallback desde MVP y stack...")
        mvp_doc = scoping_info["documents"].get("06-mvp.md")
        stack_doc = scoping_info["documents"].get("04-stack.md")
        parts = [f"Brief: {args.brief}"]
        if stack_doc:
            parts.append(f"\nStack recomendado:\n{stack_doc.read_text(encoding='utf-8')}")
        if mvp_doc:
            parts.append(f"\nMVP y alcance:\n{mvp_doc.read_text(encoding='utf-8')}")
        parts.append(
            "\nImplementa el MVP completo descrito arriba. Genera el código, tests y "
            "documentación necesarios para que el proyecto sea ejecutable y verificable."
        )
        phase1_prompt = "\n".join(parts)
        print(f"  [orchestrator] Prompt fallback construido: {len(phase1_prompt)} chars")

    # Guardar el prompt que se le pasará al Coding Agent
    (output_dir / "phase1_prompt.txt").write_text(phase1_prompt, encoding="utf-8")

    # Abortar si el prompt vino vacío, antes de invocar al Coding Agent.
    validate_phase1_prompt(phase1_prompt)

    # 2.5 Crear scaffold según stack recomendado: preferir hints del contrato
    stack_hints = (contract or {}).get("stack_hints")
    if stack_hints and stack_hints.get("language"):
        scaffold_project_from_hints(project_root, stack_hints)
    else:
        stack_doc = scoping_info["documents"].get("04-stack.md")
        if stack_doc:
            scaffold_project(project_root, stack_doc.read_text(encoding="utf-8"))

    # 3. Coding Agent
    coding_result = run_coding_agent(phase1_prompt, project_root, output_dir)
    if coding_result.get("error"):
        print(f"\n[orchestrator] ⚠ El Coding Agent reportó un error: {coding_result['error']}")
        print("[orchestrator] Se arma igual la entrega con lo disponible (revisá 02-post-codigo).")

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
