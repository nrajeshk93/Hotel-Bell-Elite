"""Lock PO WhatsApp item layout (Item Name / Pack Size / Quantity)."""

from stores import (
    _po_default_message,
    _po_items_body,
    _po_whatsapp_template_params,
)


SAMPLE_LINES = [
    {"item_name": "Test", "pack_label": "250 gram", "quantity": 1},
    {"item_name": "Apple", "pack_label": "kg", "quantity": 1},
]


def test_po_items_body_matches_expected_layout():
    body = _po_items_body(SAMPLE_LINES, for_template=False)
    assert body == (
        "Items\n"
        "----------------------------------------------------\n"
        "1. Item Name : Test\n"
        "   Pack Size : 250 gram\n"
        "   Quantity  : 1\n"
        "\n"
        "2. Item Name : Apple\n"
        "   Pack Size : kg\n"
        "   Quantity  : 1\n"
        "----------------------------------------------------\n"
        "\n"
        "Total Items : 2"
    )
    assert "×" not in body
    assert "Test (250 gram)" not in body


def test_default_message_includes_items_block():
    msg = _po_default_message("Supplier", SAMPLE_LINES, "IND-1", "PO/1")
    assert "Item Name : Test" in msg
    assert "Pack Size : 250 gram" in msg
    assert "Quantity  : 1" in msg
    assert "Total Items : 2" in msg
    assert "×" not in msg


def test_template_params_use_same_labels():
    params = _po_whatsapp_template_params("Supplier", "PO/1", SAMPLE_LINES)
    assert len(params) == 3
    items = params[2]
    assert "Item Name : Test" in items
    assert "Pack Size : 250 gram" in items
    assert "Item Name : Apple" in items
    assert "Total Items : 2" in items
    assert "×" not in items
    assert "Test (250 gram)" not in items


def test_template_params_flat_fallback_keeps_labels():
    params = _po_whatsapp_template_params(
        "Supplier", "PO/1", SAMPLE_LINES, allow_newlines=False
    )
    items = params[2]
    assert "\n" not in items
    assert "Item Name : Test" in items
    assert "Pack Size : 250 gram" in items
    assert "Total Items : 2" in items
    assert "×" not in items
