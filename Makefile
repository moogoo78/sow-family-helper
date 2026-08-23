DC := docker compose
DC_TRAEFIK := docker compose -f docker-compose.yml -f compose.traefik.yml

.PHONY: help up down restart build logs ps shell \
        up-traefik down-traefik restart-traefik logs-traefik ps-traefik \
        set-password health clean

help:
	@echo "Local (host port 127.0.0.1:8010):"
	@echo "  make up             build + start"
	@echo "  make down           stop"
	@echo "  make restart        down + up"
	@echo "  make build          build image only"
	@echo "  make logs           follow logs"
	@echo "  make ps             show status"
	@echo "  make shell          shell into app container"
	@echo "  make set-password   run scripts/set_password.py in container"
	@echo "  make health         curl /healthz"
	@echo "  make clean          down + remove volumes"
	@echo ""
	@echo "Behind Traefik (compose.traefik.yml overlay):"
	@echo "  make up-traefik / down-traefik / restart-traefik / logs-traefik / ps-traefik"

up:
	$(DC) up -d --build

down:
	$(DC) down

restart: down up

build:
	$(DC) build

logs:
	$(DC) logs -f

ps:
	$(DC) ps

shell:
	$(DC) exec app sh

set-password:
	$(DC) exec app python3 scripts/set_password.py

health:
	curl -s localhost:8010/healthz && echo

clean:
	$(DC) down -v

up-traefik:
	$(DC_TRAEFIK) up -d --build

down-traefik:
	$(DC_TRAEFIK) down

restart-traefik: down-traefik up-traefik

logs-traefik:
	$(DC_TRAEFIK) logs -f

ps-traefik:
	$(DC_TRAEFIK) ps
