.PHONY: test test-local test-live test-db-up test-db-down

test:
	python -m pytest tests/ -v --timeout=60

test-local: test-db-up
	TEST_DATABASE_URL="postgresql://compass:compass@localhost:5432/compass_test" python -m pytest tests/ -v --timeout=60 -m "not live"

test-live:
	python -m pytest tests/ -v --timeout=90 -m "live"

test-db-up:
	docker compose -f docker-compose.test.yml up -d
	@echo "Waiting for test database to be healthy..."
	@docker compose -f docker-compose.test.yml exec -T test-postgres sh -c 'until pg_isready -U compass -d compass_test; do sleep 1; done'
	@echo "Test database is ready."

test-db-down:
	docker compose -f docker-compose.test.yml down
