from receipt_to_ledger.cord_eval import cord_ground_truth_to_canonical


def test_cord_mapping_handles_single_menu_object() -> None:
    raw = {
        "gt_parse": {
            "menu": {"nm": "PKT AYAM", "cnt": "1", "price": "33,000"},
            "sub_total": {"subtotal_price": "33,000", "tax_price": "3,300"},
            "total": {"total_price": "36,300"},
        }
    }
    result = cord_ground_truth_to_canonical(raw)
    assert result["amounts"] == {"subtotal": 33000.0, "tax": 3300.0, "total": 36300.0}
    assert result["lines"][0]["description"] == "PKT AYAM"
    assert result["lines"][0]["total"] == 33000.0


def test_cord_mapping_handles_menu_list() -> None:
    raw = {
        "gt_parse": {
            "menu": [
                {"nm": "Coffee", "cnt": "2", "unitprice": "10.000", "price": "20.000"},
                {"nm": "Cake", "price": "15,000"},
            ],
            "total": {"total_price": "35.000"},
        }
    }
    result = cord_ground_truth_to_canonical(raw)
    assert len(result["lines"]) == 2
    assert result["lines"][0]["quantity"] == 2.0
    assert result["amounts"]["total"] == 35000.0
