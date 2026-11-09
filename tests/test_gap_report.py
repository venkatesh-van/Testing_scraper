"""gap_report.py: blank counts per column, split into withdrawn and other lots."""

from utils.gap_report import column_table, main


def test_column_table_splits_withdrawn_and_other():
    rows = [{"description": "", "lot_status": "withdrawn"}, {"description": "", "lot_status": "hidden"},
            {"description": "x", "lot_status": "hidden"}, {"description": " ", "lot_status": "sold"}]
    name, blank, withdrawn, other, fill = column_table(rows, ["description"])[0]
    assert (name, blank, withdrawn, other, round(fill)) == ("description", 3, 1, 2, 25)


def test_no_arguments_prints_help_instead_of_crashing(capsys):
    assert main([]) == 2 and "gap_report.py" in capsys.readouterr().out
