AGENT_DIR := project/agents/1. calendar assistant
BACKEND_DIR := project/backend
PYTHON ?= python3
BACKEND_PYTHON := .venv/bin/python

.PHONY: help setup-backend setup-agent backend agent frontend preparation-mcp demo demo-full mock-mcp workflow workflow-status workflow-auth calendar-webhook calendar-watch calendar-sync meetings test test-backend test-agent test-demo check gmail-auth calendar-auth

help:
	@echo "make chatgpt-demo   Probar LangGraph con tu suscripción de ChatGPT (OAuth)"
	@echo "make setup-backend  Instalar backend y Chromium para PDF"
	@echo "make setup-agent    Instalar dependencias del agente con uv.lock"
	@echo "make backend        Iniciar la API local (puerto 8000)"
	@echo "make agent          Iniciar la llamada local"
	@echo "make agent2         MCP de Meeting Assistant (PostgreSQL y GitHub)"
	@echo "make agent2-login   Iniciar sesión con ChatGPT para el agente 2"
	@echo "make workflow       Iniciar el único worker local de LangGraph"
	@echo "make frontend       Abrir servidor de la oficina virtual (puerto 8765)"
	@echo "make preparation-mcp  Iniciar el MCP local de preparación (STDIO)"
	@echo "make demo           Agendar y preparar dos proyectos con mocks; esperar a Stuart"
	@echo "make demo-full      Añadir revisión ficticia de Stuart y aceptación del handoff"
	@echo "make mock-mcp       Abrir el MCP de la última demo (worker: make workflow)"
	@echo "make test           Integraciones esenciales offline"
	@echo "make test-e2e       Recorrido completo offline (bajo demanda)"
	@echo "make test-postgres  Persistencia con PostgreSQL aislado (bajo demanda)"
	@echo "make insumos-mock   Generar ficha, resumen y presentación HTML/PDF"
	@echo "make prepare-capture Preparar la extensión privada para Chrome"
	@echo "make check          Comprobar formato e imports de Python"
	@echo "make gmail-auth     Autorizar el envío de Gmail del backend"
	@echo "make calendar-auth  Autorizar Google Calendar del agente"
	@echo "make calendar-watch Registrar o renovar el webhook HTTPS de Calendar"
	@echo "make calendar-webhook Receptor exclusivo de Calendar en localhost:8001"
	@echo "make calendar-sync  Recuperar cambios de Calendar bajo demanda"
	@echo "make meetings       Ver reuniones persistidas en el workflow"

setup-backend:
	$(PYTHON) -m venv "$(BACKEND_DIR)/.venv"
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m pip install -r requirements-dev.txt
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m playwright install chromium

setup-agent:
	cd "$(AGENT_DIR)" && uv sync --locked

backend:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8000

calendar-webhook:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m uvicorn app.calendar_webhook:app --host 127.0.0.1 --port 8001

agent:
	@test "$${LIVEKIT_INFERENCE_ENABLED:-0}" = "1" || { echo "Inferencia LiveKit bloqueada. Una prueba real requiere LIVEKIT_INFERENCE_ENABLED=1 make agent y consume créditos."; exit 1; }
	cd "$(AGENT_DIR)" && lk agent console

preparation-mcp:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.mcp_server

demo:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.demo

demo-full:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.demo --collaborate

mock-mcp:
	@cd "$(BACKEND_DIR)" && WORKFLOW_MODE=mock $(BACKEND_PYTHON) -m app.mcp_server

.PHONY: chatgpt-demo
chatgpt-demo:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.chatgpt_demo

test-demo: test-e2e

.PHONY: test-e2e test-postgres
test-e2e:
	@cd "$(BACKEND_DIR)" && RUN_MOCK_E2E=1 $(BACKEND_PYTHON) -m pytest -q tests/demos/test_mock_end_to_end.py

test-postgres:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m pytest -q -o addopts= -m postgres tests/project_opening/test_postgres.py

workflow:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.worker

workflow-status:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.workflow status

calendar-watch:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.workflow calendar-watch

calendar-sync:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.workflow calendar-sync

meetings:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.workflow meetings

workflow-auth:
	@cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.authorize_workflow

frontend:
	$(PYTHON) -m http.server 8765 --bind 127.0.0.1 --directory project/frontend

test: test-backend test-agent

test-backend:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m pytest -q $(TESTS)

test-agent:
	cd "$(AGENT_DIR)" && .venv/bin/python -m pytest -q $(TESTS)

check:
	"$(BACKEND_DIR)/.venv/bin/ruff" check project/transcript-capture/prepare.py
	"$(BACKEND_DIR)/.venv/bin/ruff" format --check project/transcript-capture/prepare.py
	cd "$(BACKEND_DIR)" && .venv/bin/ruff format --check app tests
	cd "$(BACKEND_DIR)" && .venv/bin/ruff check app tests
	cd "$(AGENT_DIR)" && uv run --locked ruff format --check src tests demos
	cd "$(AGENT_DIR)" && uv run --locked ruff check src tests demos

gmail-auth:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.authorize_gmail

calendar-auth:
	cd "$(AGENT_DIR)" && uv run --locked python -m src.integrations.google_oauth

.PHONY: prepare-capture
prepare-capture:
	project/backend/$(BACKEND_PYTHON) project/transcript-capture/prepare.py

.PHONY: insumos-mock
insumos-mock:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.insumos --mock

.PHONY: agent2 agent2-login agent2-logout agent2-register agent2-run agent2-queue agent2-preview
agent2:
	PYTHONPATH="$(CURDIR)/$(BACKEND_DIR)" "$(BACKEND_DIR)/$(BACKEND_PYTHON)" "project/agents/2. meeting assistant/src/agent.py" mcp

agent2-login:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.meeting_assistant login

agent2-logout:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.meeting_assistant logout

agent2-register:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.meeting_assistant register --request fixtures/nike-lindora-stuart/opening.json

agent2-run:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.meeting_assistant next

agent2-queue:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.meeting_assistant queue

agent2-preview:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.meeting_assistant preview

.PHONY: agent2-live
CASE ?=
MODEL ?= auto
MOCK_BOARD ?= 0
agent2-live:
	cd "$(BACKEND_DIR)" && $(BACKEND_PYTHON) -m app.cli.agent2_live $(if $(CASE),--case "$(CASE)",) --model "$(MODEL)" --allow-inference $(if $(filter 1,$(MOCK_BOARD)),--mock-board,) $(if $(EXECUTION_ID),--execution-id "$(EXECUTION_ID)",)
