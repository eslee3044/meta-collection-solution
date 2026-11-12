from app.main import apply_source
from app.models import DataSource
from app.schemas import DataSourceIn
from app.security import decrypt_json


def test_mysql_ssl_credentials_are_saved_separately_from_connection_options():
    source = DataSource()
    payload = DataSourceIn(
        name="Aiven MySQL",
        db_type="mysql",
        host="mysql.example.com",
        port=3306,
        database="sample",
        username="reader",
        password="db-password",
        ssl_enabled=True,
        ssl_ca_cert="-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----",
    )

    apply_source(source, payload)

    assert source.options["ssl_enabled"] is True
    assert "connect_args" not in source.options
    secret = decrypt_json(source.secret_encrypted)
    assert secret["password"] == "db-password"
    assert secret["ssl_ca_cert"].startswith("-----BEGIN CERTIFICATE-----")
