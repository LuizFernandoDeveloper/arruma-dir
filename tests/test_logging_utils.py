from __future__ import annotations

import unittest
from pathlib import Path

from arruma_dir.logging_utils import format_log_event, format_log_fields, format_log_value


class LoggingFormatTests(unittest.TestCase):
    def test_format_log_event_keeps_simple_values_unquoted_and_ordered(self) -> None:
        message = format_log_event("scan_start", root=Path(r"F:\projetos"), external=True, workers=4)

        self.assertEqual(message, r"event=scan_start root=F:\projetos external=true workers=4")

    def test_format_log_event_quotes_spaces_and_escapes_paths_and_quotes(self) -> None:
        message = format_log_event(
            "duplicate",
            source=Path(r'F:\Projeto Mecanico\arquivo "x".pdf'),
            reason="linha 1\nlinha 2",
        )

        self.assertEqual(
            message,
            'event=duplicate source="F:\\\\Projeto Mecanico\\\\arquivo \\"x\\".pdf" reason="linha 1 linha 2"',
        )

    def test_format_log_event_keeps_unicode_readable(self) -> None:
        message = format_log_event("warning", message="Ação já está pronta")

        self.assertEqual(message, 'event=warning message="Ação já está pronta"')

    def test_format_log_event_formats_sequences_as_readable_single_field(self) -> None:
        message = format_log_event("external_candidate", reasons=["codigo Opcao", "extensao .pdf"], tags=[])

        self.assertEqual(message, 'event=external_candidate reasons="codigo Opcao; extensao .pdf" tags=-')

    def test_format_log_event_formats_mappings_with_stable_key_order(self) -> None:
        message = format_log_event("payload", data={"b": 2, "a": "x y"})

        self.assertEqual(message, 'event=payload data="{\\"a\\": \\"x y\\", \\"b\\": 2}"')

    def test_format_log_value_has_explicit_empty_and_none_representation(self) -> None:
        self.assertEqual(format_log_value(""), '""')
        self.assertEqual(format_log_value(None), "-")

    def test_format_log_fields_rejects_ambiguous_field_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "campo de log invalido"):
            format_log_fields(**{"bad key": "value"})

    def test_format_log_event_rejects_empty_event(self) -> None:
        with self.assertRaisesRegex(ValueError, "nao pode ser vazio"):
            format_log_event("")


if __name__ == "__main__":
    unittest.main()
