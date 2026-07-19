from importlib import import_module

detect_sensitive_data = import_module("skills.sensitivedata-gov.src.detector").detect_sensitive_data


def test_external_sensitive_data_is_masked_or_approved_and_credentials_block():
    masked = detect_sensitive_data("联系人 13800138000", "external@example.com")
    assert masked["decision"] == "mask_and_allow"
    assert "13800138000" not in masked["sanitized_content"]
    assert masked["external_destination"]

    internal = detect_sensitive_data("内部人员名单", "service.xiongan.gov.cn", data_labels=["internal"])
    assert internal["decision"] == "allow_with_log"

    blocked = detect_sensitive_data("token=abcd1234", "external@example.com")
    assert blocked["decision"] == "block"
    assert blocked["risk_level"] == "critical"
    assert "abcd1234" not in blocked["sanitized_content"]
