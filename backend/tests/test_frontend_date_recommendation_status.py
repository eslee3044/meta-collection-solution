from pathlib import Path


APP_SOURCE = Path(__file__).parents[2] / "frontend" / "src" / "App.tsx"


def test_column_selection_always_explains_missing_date_recommendations():
    source = APP_SOURCE.read_text(encoding="utf-8")

    assert 'className="date-recommendation-status"' in source
    assert "PARTITION KEY 추천 없음" in source
    assert "생성일자 계열 컬럼이 없어 자동 추천하지 않았습니다." in source
    assert "UPDATE BASE 추천 없음" in source
    assert "변경일자 또는 생성일자 계열 컬럼이 없어 자동 추천하지 않았습니다." in source
    assert "등록 후 직접 지정할 수 있습니다." in source
