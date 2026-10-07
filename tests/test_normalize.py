import json

from biomed_mcp_receipts.models import RawResult
from biomed_mcp_receipts.normalize import literature_answer, normalise_status, trial_answer


def test_status_spellings_converge():
    assert normalise_status("Active, not recruiting") == "ACTIVE_NOT_RECRUITING"
    assert normalise_status("ACTIVE_NOT_RECRUITING") == "ACTIVE_NOT_RECRUITING"
    assert normalise_status("completed") == "COMPLETED"
    assert normalise_status("ok") is None
    assert normalise_status(3) is None


def test_trial_from_ctgov_shaped_structured_content():
    study = {
        "study": {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT04280705",
                    "briefTitle": "Adaptive COVID-19 Treatment Trial",
                },
                "statusModule": {
                    "overallStatus": "COMPLETED",
                    "lastUpdatePostDateStruct": {"date": "2024-05-01"},
                },
            }
        }
    }
    ans = trial_answer(RawResult(ok=True, structured=study), "Adaptive COVID-19 Treatment Trial (ACTT)")
    assert ans.nct_ids == ["NCT04280705"]
    assert ans.status == "COMPLETED"
    assert ans.last_update == "2024-05-01"
    assert ans.title_found is False  # the source title has "(ACTT)", which the server did not echo


def test_trial_from_json_inside_text():
    text = json.dumps({"nct_id": "NCT04368728", "overall_status": "Active, not recruiting"})
    ans = trial_answer(RawResult(ok=True, text=text))
    assert ans.status == "ACTIVE_NOT_RECRUITING"


def test_trial_from_labelled_prose():
    ans = trial_answer(RawResult(ok=True, text="NCT04368728\nOverall status: Active, not recruiting\n"), None)
    assert ans.status == "ACTIVE_NOT_RECRUITING"
    assert ans.nct_ids == ["NCT04368728"]


def test_unlabelled_prose_status_is_not_guessed():
    assert trial_answer(RawResult(ok=True, text="NCT04368728 is recruiting at 150 sites.")).status is None


def test_prose_takes_the_first_labelled_status_not_a_later_site_status():
    text = "Status: Completed\nSite 1 status: Recruiting"
    assert trial_answer(RawResult(ok=True, text=text)).status == "COMPLETED"


def test_prose_does_not_read_a_summary_word_as_the_status():
    text = "Status: Terminated\nSummary: the dose-finding phase completed early."
    assert trial_answer(RawResult(ok=True, text=text)).status == "TERMINATED"


def test_overall_status_beats_a_site_status_in_json():
    study = {
        "protocolSection": {
            "contactsLocationsModule": {"locations": [{"facility": "A", "status": "RECRUITING"}]},
            "statusModule": {"overallStatus": "ACTIVE_NOT_RECRUITING"},
        }
    }
    assert trial_answer(RawResult(ok=True, structured=study)).status == "ACTIVE_NOT_RECRUITING"


def test_non_ascii_title_in_structured_content_matches():
    raw = RawResult(ok=True, structured={"briefTitle": "Sjögren Syndrome in Adults ≥18 Years"})
    assert trial_answer(raw, "Sjögren Syndrome in Adults ≥18 Years").title_found


def test_unknown_status_word_alone_is_not_a_status():
    assert trial_answer(RawResult(ok=True, text="Status unknown for this query")).status is None


def test_title_match_ignores_case_and_punctuation():
    ans = trial_answer(
        RawResult(ok=True, text="adaptive covid 19 treatment trial actt"),
        "Adaptive COVID-19 Treatment Trial (ACTT)",
    )
    assert ans.title_found


def test_pmids_from_structured_records_keep_order_and_dedupe():
    raw = RawResult(ok=True, structured={"pmids": ["111111", "222222"], "records": [{"pmid": "111111"}]})
    assert literature_answer(raw).pmids == ["111111", "222222"]


def test_pmids_from_text_and_links():
    raw = RawResult(ok=True, text="PMID: 3456789 and https://pubmed.ncbi.nlm.nih.gov/9876543/")
    assert literature_answer(raw).pmids == ["3456789", "9876543"]


def test_no_pmids():
    assert literature_answer(RawResult(ok=True, text="0 results")).pmids == []
