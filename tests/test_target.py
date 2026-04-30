from xvalidations.target import location_to_schema_overlay


def test_location_overlay_object_property() -> None:
    assert location_to_schema_overlay(("primary_tag",), {"enum": ["python"]}) == {
        "type": "object",
        "properties": {"primary_tag": {"enum": ["python"]}},
    }


def test_location_overlay_array_index_uses_prefix_items_and_min_items() -> None:
    assert location_to_schema_overlay((2,), {"const": "python"}) == {
        "type": "array",
        "minItems": 3,
        "prefixItems": [True, True, {"const": "python"}],
    }


def test_location_overlay_nested_array_object_path() -> None:
    assert location_to_schema_overlay(
        ("items", 1, "primary_tag"), {"enum": ["python"]}
    ) == {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": 2,
                "prefixItems": [
                    True,
                    {
                        "type": "object",
                        "properties": {"primary_tag": {"enum": ["python"]}},
                    },
                ],
            }
        },
    }
