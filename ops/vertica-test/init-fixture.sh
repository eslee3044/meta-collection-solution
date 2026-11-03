#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vertica-test.yml}"
: "${VERTICA_TEST_PASSWORD:?Set VERTICA_TEST_PASSWORD without printing it}"

compose=(docker compose -f "$COMPOSE_FILE")

"${compose[@]}" exec -T -e VERTICA_TEST_PASSWORD="$VERTICA_TEST_PASSWORD" vertica-test bash -lc '
set -euo pipefail
vsql=(/opt/vertica/bin/vsql -h localhost -U dbadmin -d docker)

if ! "${vsql[@]}" -Atqc "SELECT 1 FROM v_catalog.users WHERE user_name = '\''metavault_test'\''" | grep -q 1; then
  printf "CREATE USER metavault_test IDENTIFIED BY '\''%s'\'';\n" "$VERTICA_TEST_PASSWORD" | "${vsql[@]}"
fi

"${vsql[@]}" <<'SQL'
CREATE SCHEMA IF NOT EXISTS mv_test AUTHORIZATION metavault_test;
CREATE TABLE IF NOT EXISTS mv_test.mv_test_customers (
  customer_id INT NOT NULL,
  customer_name VARCHAR(100),
  created_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS mv_test.mv_test_orders (
  order_id INT NOT NULL,
  customer_id INT,
  order_amount NUMERIC(12,2),
  updated_at TIMESTAMP
);
CREATE OR REPLACE VIEW mv_test.mv_test_order_summary AS
  SELECT customer_id, COUNT(*) AS order_count, SUM(order_amount) AS total_amount
  FROM mv_test.mv_test_orders GROUP BY customer_id;
GRANT USAGE ON SCHEMA mv_test TO metavault_test;
GRANT SELECT ON ALL TABLES IN SCHEMA mv_test TO metavault_test;
SQL

"${vsql[@]}" -c "INSERT INTO mv_test.mv_test_customers SELECT 1, '\''customer-1'\'', CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM mv_test.mv_test_customers);"
"${vsql[@]}" -c "INSERT INTO mv_test.mv_test_orders SELECT 1001, 1, 125.50, CURRENT_TIMESTAMP WHERE NOT EXISTS (SELECT 1 FROM mv_test.mv_test_orders);"
"${vsql[@]}" -c "COMMIT;"

echo "Vertica fixture ready: database=docker schema=mv_test user=metavault_test port=5433"
'