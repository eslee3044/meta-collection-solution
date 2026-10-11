from app.statement_cancel import cancel_statement


class Driver:
    def __init__(self):
        self.called = False

    def cancel(self):
        self.called = True


def test_cancel_statement_uses_driver_cancel_method():
    driver = Driver()
    result = cancel_statement(driver)
    assert result.cancelled is True
    assert result.supported is True
    assert driver.called is True


def test_cancel_statement_reports_unsupported_driver_without_error():
    result = cancel_statement(object())
    assert result.cancelled is False
    assert result.supported is False
