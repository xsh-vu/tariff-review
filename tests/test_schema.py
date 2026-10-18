from agent.schema import strict_response_format


def walk_objects(value: object) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            assert value.get("additionalProperties") is False
            assert set(value.get("required", [])) == set(value.get("properties", {}))
        for nested in value.values():
            walk_objects(nested)
    elif isinstance(value, list):
        for nested in value:
            walk_objects(nested)


def test_strict_schema_closes_every_object_and_requires_every_field() -> None:
    response_format = strict_response_format()
    assert response_format["strict"] is True
    walk_objects(response_format["schema"])
